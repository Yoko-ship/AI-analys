from __future__ import annotations



from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from functools import partial
from pydantic import BaseModel
from pydantic import Field
from typing import Any
import asyncio
import formulas
import news_store
import web_auth as identity
import reports_catalog as catalog_store
import securities_catalog as securities_store
import server.auth.access as auth_access
import server.http as http
import server.market.board as market_board
import server.market.history as market_history
import server.news.discovery as discovery


router = APIRouter()


class AdminNewsRequest(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


class AdminNewsImagesRequest(BaseModel):
    """url → preview-image URL, for image-only updates of already-stored items.

    ``replace`` is the upgrade pass: swapping a feed's thumbnail for the full-size original
    behind it, which is the one case where an image already on a row should be overwritten.
    """
    images: dict[str, str] = Field(default_factory=dict)
    replace: bool = False


class AdminNewsSnippetsRequest(BaseModel):
    """url → replacement snippet, for enriching already-stored filings in place."""
    snippets: dict[str, str] = Field(default_factory=dict)


class AdminNewsTranslationsRequest(BaseModel):
    """url → {"en": ..., "uz": ...}, for rows stored before those columns existed."""
    translations: dict[str, dict[str, str]] = Field(default_factory=dict)


class AdminNewsDetailsRequest(BaseModel):
    """url → {"ru": ..., "en": ..., "uz": ...} — the story page's long read.

    Our own multi-paragraph account of what the source published, written by the collector's
    detail pass from the article page. Never the source's own text.
    """
    details: dict[str, dict[str, str]] = Field(default_factory=dict)
    replace: bool = False


class AdminNewsKnownRequest(BaseModel):
    """Candidate URLs a collector is about to classify, for a dedup check against prod."""
    urls: list[str] = Field(default_factory=list, max_length=5000)


# TZ §3.11: every news signal is statistical/analytical, never a diagnosis or a
# claim of manipulation. Returned with every editorial-news response.
NEWS_DISCLAIMER = (
    "Тональность новостей и оценка влияния — статистический сигнал, а не рекомендация "
    "и не утверждение о манипуляции. Оценки сформированы моделью и могут быть неточными."
)


@router.get("/api/news")
async def api_news(limit: int = 60, days: int = 180) -> dict[str, Any]:
    """Public market-news feed (ТЗ §3.2, item 6). A single dated timeline of real
    market events — new report filings + listing / delisting — so the News section
    has genuine content. (Editorial news aggregation with AI sentiment is the
    separate §3.11 module and stays out of scope.) Items carry structured fields;
    the client composes the localized headline."""
    from datetime import datetime, timedelta

    loop = asyncio.get_running_loop()
    try:
        # Ordered by the date the ISSUER published the filing, not by when our sync
        # first saw it. `detected_at` is a fact about our schedule; it also carried
        # the literal string «now» on 195 of 199 rows (a DDL default that
        # pg_migrate mistranslated), which sorted above every real date and could
        # never age out — so the timeline was 195 undated items deep.
        filings, listings = await asyncio.gather(
            loop.run_in_executor(None, partial(catalog_store.get_recent_filings, max(1, days), max(1, limit))),
            loop.run_in_executor(None, catalog_store.get_all_listings),
        )
    except Exception as exc:
        http.logger.exception("news feed read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    items: list[dict[str, Any]] = []
    for r in filings or []:
        tk = r.get("ticker")
        items.append({
            "type": "report",
            "ticker": tk,
            "company": catalog_store._TICKER_TO_NAME.get(tk, tk),
            "report_form": r.get("report_form"),
            "period_type": r.get("period_type"),
            "year": r.get("year"),
            "quarter": r.get("quarter"),
            "title": r.get("title"),
            # The document itself, so a row in the timeline is a way INTO the
            # filing rather than only a note that it exists.
            "pdf_url": r.get("pdf_url"),
            "excel_url": r.get("excel_url"),
            "date": r.get("published_at"),
        })

    listing_map = listings or {}
    listed = sorted(
        ((tk, l) for tk, l in listing_map.items() if l.get("listing_date")),
        key=lambda kv: kv[1]["listing_date"], reverse=True,
    )[:20]
    # The RFB registry has no security-kind field, so every line in it reads
    # «ordinary» — including a bond's. IPYB2B6, admitted 04.08.2026, is «Ipak
    # Yo'li» AITB's 20% issue: calling it an ordinary share and printing the
    # placement's own size as a CAPITALISATION is the same defect that put it on
    # the equities board. The bond register is what knows, and it knows by ISIN.
    bond_isins = await loop.run_in_executor(None, market_board._registered_bond_isins)
    for tk, l in listed:
        is_bond = str(l.get("isin") or "").upper() in bond_isins
        item = {
            "type": "listing", "ticker": tk, "company": l.get("name") or tk,
            "share_type": "bond" if is_bond else l.get("share_type"),
            "date": l.get("listing_date"),
        }
        # An issue has no capitalisation. The field is omitted rather than
        # zeroed: absent means «we do not report this», zero would be a claim.
        if not is_bond:
            item["market_cap"] = l.get("market_cap")
        items.append(item)

    cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    delisted = sorted(
        ((tk, l) for tk, l in listing_map.items()
         if l.get("last_trade_date") and l["last_trade_date"] < cutoff),
        key=lambda kv: kv[1]["last_trade_date"], reverse=True,
    )[:12]
    for tk, l in delisted:
        items.append({
            "type": "delisting", "ticker": tk, "company": l.get("name") or tk,
            "date": l.get("last_trade_date"),
        })

    # Unified timeline, newest first. Mixed "YYYY-MM-DD[ HH:MM:SS]" formats sort
    # correctly lexically; dateless items fall to the end.
    items.sort(key=lambda i: (i.get("date") or ""), reverse=True)
    return http._json_safe({"ok": True, "count": len(items), "items": items[: max(1, limit)]})


@router.get("/api/news/feed")
async def api_news_feed(limit: int = 60, days: int = 30, type: str | None = None,
                        order: str = "rank", instrument: str | None = None) -> dict[str, Any]:
    """Editorial news feed (§3.11): classified, market-relevant items, ranked by impact.

    Distinct from /api/news (the market-events timeline). Each item carries a
    model-estimated tone / impact / direction — an analytical signal, not advice — plus the
    ``rank`` it was ordered by. ``order=recent`` returns plain newest-first instead.
    Low-relevance items are skipped and the same story from several outlets is merged.

    ``type`` takes one of the classifier's four classes, a comma-separated list, or
    one of the two reading groups the news section offers — ``economy`` (market +
    regulatory) and ``corporate`` (corporate_event + financial_report). The groups
    partition all four, so nothing is unreachable from both tabs.

    A corporate request is served from the **disclosure sources alone** (openinfo, the
    issuers' own filings — customer, 2026-08-11): a paper's write-up of a filing is a
    retelling, and the tab is the record. Only the corporate classes are narrowed, so
    ``type`` unset — the «Все» tab — is still the mixed feed it says it is.

    ``instrument`` (``stock`` / ``bond``) narrows the feed to the filings that name a
    security of that kind. The classifier files a coupon payment and a dividend under
    the same «corporate_event», so the split cannot come from it — it comes from the
    securities the item names, typed by the catalog here rather than guessed from the
    shape of a ticker.
    """
    loop = asyncio.get_running_loop()
    ticker_types = None
    notes: dict[str, Any] = {}
    if str(instrument or "").lower() in ("stock", "bond"):
        # TWO sources, because the traded universe is not the listed one.
        # `securities` is filled from the exchange feed, so it knows only what
        # trades — the eleven dormant listings (AGMK, TGBK, UZNG…) are absent
        # from it, and a filing about one of them would have fallen out of both
        # «Акции» and «Облигации» without a word. The registry carries them, and
        # its `share_type` is a SHARE class, so a row that has one is a share.
        # The feed's own `type` is layered on top and wins, which is how all
        # fifteen bonds stay bonds.
        listings, smap = await asyncio.gather(
            loop.run_in_executor(None, catalog_store.get_all_listings),
            loop.run_in_executor(None, securities_store.get_securities_map),
        )
        ticker_types = {}
        for tk, row in (listings or {}).items():
            klass = str((row or {}).get("share_type") or "").strip().lower()
            if klass in ("ordinary", "preferred"):
                ticker_types[str(tk).upper()] = "stock"
            elif klass == "bond":
                ticker_types[str(tk).upper()] = "bond"
        for tk, s in (smap or {}).items():
            kind = str((s or {}).get("type") or "").strip().lower()
            if kind in ("stock", "bond"):
                ticker_types[str(tk).upper()] = kind
    items = await loop.run_in_executor(
        None, partial(news_store.get_news_feed, limit=limit, days=days, news_type=type,
                      order="recent" if order == "recent" else "rank",
                      instrument=instrument, ticker_types=ticker_types, notes=notes))
    body: dict[str, Any] = {"ok": True, "count": len(items), "items": items,
                            "disclaimer": NEWS_DISCLAIMER}
    # Diagnostic, not rendered: the news page showed this and the customer had
    # it removed — a reader does not care that TNGB has no catalog type. It
    # stays on the response because it is the only place the gap is visible at
    # all, and the items themselves are still reachable under «Все бумаги».
    if notes.get("untyped_tickers"):
        body["untyped_tickers"] = notes["untyped_tickers"]
    return http._json_safe(body)


@router.get("/api/news/calendar/meetings")
async def api_news_calendar_meetings(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """One month of upcoming shareholder-meeting announcements (news «Календарь»).

    Served from ``catalog_meetings`` (see meetings.py) — openinfo's announcement
    calendar, the one disclosure feed that names a corporate event BEFORE it
    happens. The filings feed the rest of the news section reads shows a meeting
    only once its minutes are filed.
    """
    import meetings as meetings_store

    loop = asyncio.get_running_loop()
    try:
        payload = await loop.run_in_executor(
            None, partial(meetings_store.meetings_for, year, month))
        return http._json_safe(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        http.logger.exception("meetings calendar failed for %s-%s", year, month)
        return {"ok": False, "error": str(exc), "items": []}


@router.get("/api/news/calendar/announcements")
async def api_news_calendar_announcements(limit: int = 1000) -> dict[str, Any]:
    """The meeting-notice feed, newest publication first — the list shape of the
    same ``catalog_meetings`` window the month grid reads."""
    import meetings as meetings_store

    loop = asyncio.get_running_loop()
    try:
        payload = await loop.run_in_executor(
            None, partial(meetings_store.announcements, max(1, min(limit, 2000))))
        return http._json_safe(payload)
    except Exception as exc:
        http.logger.exception("announcements feed failed")
        return {"ok": False, "error": str(exc), "items": []}


@router.get("/api/news/calendar/announcements/{announcement_id}")
async def api_news_calendar_announcement(
    announcement_id: int,
    language: str = "ru",
) -> dict[str, Any]:
    """One openinfo notice, parsed into safe fields for our internal page."""
    import meetings as meetings_store

    if language not in {"ru", "uz", "en"}:
        raise HTTPException(status_code=422, detail="language must be ru, uz or en")
    loop = asyncio.get_running_loop()
    try:
        item = await loop.run_in_executor(
            None,
            partial(meetings_store.announcement_detail, announcement_id, language),
        )
        return http._json_safe({"ok": True, "item": item})
    except meetings_store.AnnouncementNotFound as exc:
        raise HTTPException(status_code=404, detail="announcement not found") from exc
    except meetings_store.AnnouncementSourceError as exc:
        http.logger.warning("openinfo announcement %s failed: %s", announcement_id, exc)
        raise HTTPException(status_code=502, detail="announcement source is unavailable") from exc


@router.get("/api/news/calendar/dividends")
async def api_news_calendar_dividends(limit: int = 300) -> dict[str, Any]:
    """The market-wide dividend calendar, one row per filing, newest first.

    The same ``catalog_dividends`` snapshot the company pages read, folded back
    from per-security copies to one row per filing so the market table does not
    list an issuer once per share class (see dividends.read_all).
    """
    import dividends as dividends_store

    loop = asyncio.get_running_loop()
    try:
        state = await loop.run_in_executor(None, dividends_store.snapshot_state)
        age = state.get("age_hours")
        if (not state.get("filings")) or age is None or age >= dividends_store.REFRESH_TTL_HOURS:
            dividends_store.refresh_in_background()
        items = await loop.run_in_executor(
            None, partial(dividends_store.read_all, max(1, min(limit, 1000))))
        return http._json_safe({"ok": True, "count": len(items), "items": items,
                           "as_of": state.get("updated_at")})
    except Exception as exc:
        http.logger.exception("dividend calendar read failed")
        return {"ok": False, "error": str(exc), "items": []}


@router.get("/api/news/item/{news_id}")
async def api_news_item(news_id: int, related: int = 6) -> dict[str, Any]:
    """One news item + its neighbours — the read path behind the /news/{id} page (§3.11).

    Pure database read of what the collector already stored (headline, our own summary, the
    classifier's tone / impact / direction, issuer links, source link), so opening an
    article never triggers a model call and costs nothing. The source's article body is
    not served here — it is never stored; the page links out for the full text.
    """
    loop = asyncio.get_running_loop()
    item = await loop.run_in_executor(None, partial(news_store.get_news_item, news_id))
    if item is None:
        raise HTTPException(status_code=404, detail="news item not found")
    neighbours: list[dict[str, Any]] = []
    if related > 0:
        neighbours = await loop.run_in_executor(
            None, partial(news_store.get_related_news, news_id, limit=min(related, 20)))
    return http._json_safe({"ok": True, "item": item, "related": neighbours,
                       "disclaimer": NEWS_DISCLAIMER})


@router.get("/api/news/item/{news_id}/reaction")
async def api_news_reaction(news_id: int, max_tickers: int = 3) -> dict[str, Any]:
    """What the tagged issuers' prices did around this story (§3.11).

    Its own endpoint rather than a field on /api/news/item: the first call for an
    issuer reaches openinfo for the full series, and an article page must not wait
    on that to render its text. Repeat calls are served from the same ten-minute
    memo the company card uses, so a reader moving between stories about one issuer
    pays for the history once.

    Nothing here claims the story MOVED the price — `formulas.price_reaction` returns
    two dated closes and the interface says so in as many words.
    """
    loop = asyncio.get_running_loop()
    item = await loop.run_in_executor(None, partial(news_store.get_news_item, news_id))
    if item is None:
        raise HTTPException(status_code=404, detail="news item not found")
    tickers = [t for t in (item.get("tickers") or [])][:max(1, min(max_tickers, 5))]
    published = item.get("published_at")
    out: list[dict[str, Any]] = []
    for ticker in tickers:
        try:
            isin = await market_history._resolve_isin(ticker)
            if not isin:
                out.append({"ticker": ticker, "status": "no_isin"})
                continue
            data = await market_history._full_history(isin)
            points = formulas.normalize_points(data.get("points") or [])
            out.append({"ticker": ticker, "isin": isin,
                        **formulas.price_reaction(points, published)})
        except Exception:  # noqa: BLE001 — one unreachable series is not a broken page
            http.logger.exception("news reaction failed for %s", ticker)
            out.append({"ticker": ticker, "status": "unavailable"})
    return http._json_safe({"ok": True, "id": item.get("id"), "published_at": published,
                       "items": out})


@router.get("/api/news/ticker/{ticker}")
async def api_news_ticker(
    ticker: str,
    limit: int = 30,
    days: int = 90,
    exclude_news_id: int | None = None,
) -> dict[str, Any]:
    """Per-issuer news + coverage-weighted background tone (the §3.4 info dimension)."""
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(
        None, partial(news_store.get_news_for_ticker, ticker, limit=limit, days=days,
                      exclude_news_id=exclude_news_id))
    sentiment = await loop.run_in_executor(
        None, partial(news_store.get_news_sentiment, ticker, days=days))
    return http._json_safe({"ok": True, "ticker": ticker.upper(), "count": len(items),
                       "items": items, "sentiment": sentiment, "disclaimer": NEWS_DISCLAIMER})


@router.post("/api/admin/news")
async def api_admin_news(
    payload: AdminNewsRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Ingest classified news items from the external news collector (§3.11).

    Mirrors /api/admin/facts: the collector runs where the sources are reachable
    and pushes here. Authenticated via ADMIN_API_SECRET in the X-Admin-Secret header.
    """
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(news_store.upsert_news, payload.items))
    except Exception as exc:
        http.logger.exception("admin news upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "upserted": n}


@router.post("/api/admin/news/images")
async def api_admin_news_images(
    payload: AdminNewsImagesRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Fill preview images (url → image_url) on already-stored news rows (§3.11).

    The collector's ``--backfill-images`` pass pushes here rather than to
    /api/admin/news: this only touches ``news.image_url``, so a stored item's classification
    (tone/impact/relevance) can never be overwritten. By default it only fills rows that
    have no image; ``replace: true`` is the upgrade pass, which swaps a feed thumbnail for
    the full-size original the collector has already verified.
    """
    images = payload.images or {}
    if len(images) > 2000:
        raise HTTPException(status_code=422, detail="too many images (max 2000 per call)")
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(
            None, partial(news_store.set_image_urls, images, replace=payload.replace))
    except Exception as exc:
        http.logger.exception("admin news image update failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "updated": n}


@router.post("/api/admin/news/snippets")
async def api_admin_news_snippets(
    payload: AdminNewsSnippetsRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Replace the snippet on already-stored news rows (§3.11).

    The openinfo enrichment pass pushes here rather than to /api/admin/news: a full upsert
    there would rewrite the item's classification from a snippet-only record and drop it out
    of the feed. Only ``news.snippet`` is touched, and only when the new text is longer, so a
    re-run can never shrink a row back to its bare "Существенный факт №21".
    """
    snippets = payload.snippets or {}
    if len(snippets) > 2000:
        raise HTTPException(status_code=422, detail="too many snippets (max 2000 per call)")
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(news_store.set_snippets, snippets))
    except Exception as exc:
        http.logger.exception("admin news snippet update failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "updated": n}


@router.post("/api/admin/news/translations")
async def api_admin_news_translations(
    payload: AdminNewsTranslationsRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Fill the English and Uzbek summaries on already-stored news rows (§3.11).

    The site is served in three languages but every summary used to be Russian, so an
    English or Uzbek reader got a Russian feed. New items now get all three from the same
    classification call; this is the backfill route for the rows that predate it.

    Pushes here rather than to /api/admin/news for the same reason as the image and snippet
    routes: a full upsert would rewrite the item's classification from a partial record and
    drop it out of the feed. Only the two summary columns are touched, and only where they
    are still empty, so this can never overwrite what the classifier itself wrote.
    """
    translations = payload.translations or {}
    if len(translations) > 2000:
        raise HTTPException(status_code=422, detail="too many translations (max 2000 per call)")
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(news_store.set_translations, translations))
    except Exception as exc:
        http.logger.exception("admin news translation update failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "updated": n}


@router.post("/api/admin/news/details")
async def api_admin_news_details(
    payload: AdminNewsDetailsRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Fill the story page's long read on already-stored news rows (§3.11).

    A feed teaser is one sentence; the article behind it is several paragraphs, and a reader
    who opened the story used to get the sentence. The collector's detail pass reads the
    source's article page once and writes OUR OWN 3-5 paragraph account of it in all three UI
    languages — the source's text is never stored, which is what keeps the legal invariant.

    Its own route rather than /api/admin/news for the same reason as the image, snippet and
    translation routes: a full upsert from a partial record would rewrite the classification.
    Normal runs fill only empty columns. ``replace`` is the explicit admin-only migration
    path used when one source's extraction quality materially improves.
    """
    details = payload.details or {}
    if len(details) > 500:
        raise HTTPException(status_code=422, detail="too many details (max 500 per call)")
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(
            None, partial(news_store.set_details, details, replace=payload.replace)
        )
    except Exception as exc:
        http.logger.exception("admin news detail update failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "updated": n}


@router.post("/api/admin/news/known")
async def api_admin_news_known(
    payload: AdminNewsKnownRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Which of these URLs prod already stores — the collector's dedup memory when it has no
    local history of its own.

    The collector normally remembers what it has classified in its own SQLite file. A
    scheduled run in a fresh container has no such file, so without this it would re-classify
    (and re-pay for) every item on every run; prod's UNIQUE(url) would keep the rows clean
    while the LLM bill quietly doubled. Read-only: nothing is written.
    """
    urls = [u for u in (payload.urls or []) if u]
    loop = asyncio.get_running_loop()
    known = await loop.run_in_executor(None, partial(news_store.existing_urls, urls))
    return {"ok": True, "checked": len(urls), "known": sorted(known)}


@router.post("/api/admin/news/purge-failed")
async def api_admin_news_purge_failed(
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Delete news items whose classification failed, so the collector retries them.

    Those rows sit at ``relevant = 0`` — invisible in the feed, yet their URLs make the
    collector's dedup skip them forever. Deleting them is the only retry. Rows carrying a
    real classifier verdict are never touched.
    """
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, news_store.delete_failed_classifications)
    except Exception as exc:
        http.logger.exception("admin news purge-failed failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, **result}


@router.post("/api/admin/news/rejudge")
async def api_admin_news_rejudge(
    payload: dict[str, Any],
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Delete one source's rejected rows so the collector classifies them again.

    A stored verdict is what stops us paying twice for the same item; it also means a gate
    that judged wrong keeps that judgement for the life of the row. When the gate changes,
    this is how the items it buried get a second reading. Only ``relevant = 0`` rows go —
    a card already on the feed is never withdrawn by this call.
    """
    source_id = str(payload.get("source_id") or "").strip()
    if not source_id:
        raise HTTPException(status_code=400, detail="source_id is required")
    days = int(payload.get("days") or 60)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, partial(news_store.delete_rejected_from_source, source_id, days=days))
    except Exception as exc:
        http.logger.exception("admin news rejudge failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, **result}


@router.get("/api/dividends/{ticker}")
async def api_dividends(ticker: str) -> dict[str, Any]:
    """Dividend history for one security, from the stored calendar snapshot.

    Served from ``catalog_dividends`` (see dividends.py), which maps openinfo's
    market-wide calendar onto our tickers by org id. The endpoint used to ask
    openinfo to resolve the *ticker* as a company name on every request — "UNVB"
    is not a company name, so the lookup failed and the page reported
    «Дивиденды не объявлялись» while openinfo held nine payouts for that bank.
    """
    import dividends as dividends_store

    ticker = ticker.upper()
    loop = asyncio.get_running_loop()
    try:
        payload = await loop.run_in_executor(None, partial(dividends_store.dividends_for, ticker))
        return http._json_safe(payload)
    except Exception as exc:
        http.logger.exception("dividends failed for %s", ticker)
        return {"ok": False, "ticker": ticker, "error": str(exc), "items": []}


@router.post("/api/admin/dividends/refresh")
async def api_admin_dividends_refresh(
    force: bool = False,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Re-read openinfo's dividend calendar and rewrite the snapshot.

    The read path refreshes itself once the snapshot goes stale; this is the
    handle for the collector and for a deploy that must not wait for the first
    visitor to warm the table.
    """
    import dividends as dividends_store

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, partial(dividends_store.refresh, force=force))
    return http._json_safe(result)


@router.post("/api/admin/meetings/refresh")
async def api_admin_meetings_refresh(
    force: bool = False,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Re-read openinfo's meeting-announcement window and rewrite the snapshot.

    The read path warms and refreshes itself; this is the collector's handle so
    the calendar is current before the first visitor of the day."""
    import meetings as meetings_store

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, partial(meetings_store.refresh, force=force))
    return http._json_safe(result)


@router.get("/api/admin/dividends/state")
async def api_admin_dividends_state(_: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    """How much of the calendar is stored and how old it is."""
    import dividends as dividends_store

    loop = asyncio.get_running_loop()
    return http._json_safe({"ok": True, **await loop.run_in_executor(None, dividends_store.snapshot_state)})


@router.get("/api/news/agent-search")
async def api_news_agent_search(
    q: str,
    days: int = 7,
    store: bool = True,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Admin-only news-agent search for the web UI (§3.11). Same engine as
    ``/api/admin/news/search`` (Grok finds → grok-4.3 classifies → upsert into the
    news tables), but authenticated by an admin web-user's Bearer token instead of
    the machine secret. Each call triggers billed Grok searches, hence admin-gated.
    """
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="q (search query) is required")
    if len(query) > 200:
        raise HTTPException(status_code=422, detail="q too long (max 200 chars)")
    days = max(1, min(days, 30))
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, partial(discovery._news_search_sync, query, days, store))
    except Exception as exc:
        http.logger.exception("news agent search failed for user %s", current_user.id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return http._json_safe({"ok": True, **result, "disclaimer": NEWS_DISCLAIMER})


@router.get("/api/admin/news/search")
async def api_admin_news_search(
    q: str,
    days: int = 7,
    store: bool = True,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """On-demand Layer-B news search (§3.11): the Grok agent actively finds news for
    a company/ticker/topic via server-side web + X search, classifies each hit, and
    (by default, store=true) stores it so it surfaces in /api/news/feed and the
    per-ticker endpoints. Admin-only — each call triggers billed searches.
    Authenticated via ADMIN_API_SECRET in the X-Admin-Secret header.
    """
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="q (search query) is required")
    if len(query) > 200:
        raise HTTPException(status_code=422, detail="q too long (max 200 chars)")
    days = max(1, min(days, 30))
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, partial(discovery._news_search_sync, query, days, store))
    except Exception as exc:
        http.logger.exception("admin news search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return http._json_safe({"ok": True, **result, "disclaimer": NEWS_DISCLAIMER})

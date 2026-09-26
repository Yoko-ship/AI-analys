"""News sources operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from datetime import datetime
from urllib.parse import parse_qsl
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
import collectors.news.http as collectors_news_http
import collectors.news.images as collectors_news_images
import collectors.news.settings as collectors_news_settings
import html
import json
import re
import requests
import time


def load_sources(only: str | None = None) -> list[dict[str, Any]]:
    """The sources a run collects from.

    ``paywall: true`` and ``hidden: true`` are skipped even when the source is still enabled:
    the read path hides those items (``news_store.hidden_source_ids``), so collecting them
    would spend a classifier call per item on cards nobody will ever be shown. Naming the
    source explicitly (``--source trend``) still works — that is how you check a source you
    are considering bringing back.
    """
    data = json.loads(collectors_news_settings.SOURCES_FILE.read_text(encoding="utf-8"))
    out = []
    for s in data.get("sources", []):
        if only and s.get("id") != only:
            continue
        if only:
            out.append(s)
        elif s.get("enabled") and not s.get("paywall") and not s.get("hidden"):
            out.append(s)
    return out


_TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|yclid|_openstat|from|ref)$", re.I)


def _canonical_url(url: str) -> str:
    """Drop tracking params and the trailing slash so dedup sees one article once.

    Kursiv's feed appends ``?utm_source=rss&utm_medium=rss&utm_campaign=<slug>``: if a
    campaign slug ever changes, exact-URL dedup treats the same article as new and we pay
    to classify it again. Fragments and default ports go too; nothing else is touched, so
    the link still resolves at the source.
    """
    url = (url or "").strip()
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = "&".join(f"{k}={v}" for k, v in parse_qsl(parts.query, keep_blank_values=True)
                     if not _TRACKING_PARAMS.match(k))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def _iso(struct_time: Any) -> str | None:
    if not struct_time:
        return None
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", struct_time)
    except (TypeError, ValueError):
        return None


_TAG_RE = re.compile(r"<[^>]+>")


_WS_RE = re.compile(r"\s+")


def _clean_text(value: Any) -> str:
    """Feed text → plain text: unescape entities, drop markup, collapse whitespace.

    Feeds are inconsistent: spot/gazeta double-escape (``&amp;nbsp;`` arrives as a
    literal ``&nbsp;``) and several embed an ``<img>`` in the description. Stored raw,
    that renders as visible entity/tag noise in the card and pollutes classifier input.
    """
    if not value:
        return ""
    text = _TAG_RE.sub(" ", html.unescape(html.unescape(str(value))))
    return _WS_RE.sub(" ", text.replace("\xa0", " ")).strip()


def _rss_image(entry: Any) -> str | None:
    """Best-effort thumbnail from a feed entry — media:content/thumbnail, an
    enclosure, or an <img> the source embedded in its own summary/content. This only
    ever uses the source's OWN published image (see ``_og_image`` for the fallback
    when a feed ships none)."""
    for attr in ("media_content", "media_thumbnail"):
        media = getattr(entry, attr, None)
        if isinstance(media, list):
            for m in media:
                u = (m.get("url") or "").strip()
                if u:
                    return u
    for enc in (getattr(entry, "enclosures", None) or []):
        u = (enc.get("href") or enc.get("url") or "").strip()
        typ = enc.get("type") or ""
        if u and (typ.startswith("image") or re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", u, re.I)):
            return u
    for lk in (getattr(entry, "links", None) or []):
        if lk.get("rel") == "enclosure":
            u = (lk.get("href") or "").strip()
            typ = lk.get("type") or ""
            if u and (typ.startswith("image") or re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", u, re.I)):
                return u
    for field in ("content", "summary"):
        val = getattr(entry, field, None)
        if isinstance(val, list) and val:
            val = (val[0] or {}).get("value")
        if isinstance(val, str):
            m = re.search(r'<img[^>]+src=["\']([^"\']+)', val)
            if m:
                return m.group(1).strip()
    return None


def _is_recent(published_at: Any, max_age_days: int) -> bool:
    """True if within the freshness window. Undated / unparseable items are KEPT
    (we skip on proven age, never on a missing date)."""
    if not published_at:
        return True
    s = str(published_at).replace("T", " ").strip()
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:19] if fmt.endswith("%S") else s[:10], fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return True
    return (datetime.now() - dt).days <= max_age_days


def fetch_rss(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    try:
        import feedparser  # lazy: not needed unless an RSS source is enabled
    except ImportError:
        collectors_news_settings.logger.error("feedparser is not installed — run: pip install feedparser")
        return []
    feed = feedparser.parse(source["url"], request_headers=collectors_news_http._source_headers(source))
    items: list[dict[str, Any]] = []
    for e in feed.entries[:limit]:
        url = (getattr(e, "link", "") or "").strip()
        if not url:
            continue
        items.append({
            "url": _canonical_url(url),
            # The feed's original link, so dedup can also match rows stored before URLs
            # were canonicalised (and we never re-pay for those).
            "raw_url": url,
            "title": _clean_text(getattr(e, "title", "")),
            # RSS 'summary' is the source's own short description — snippet, not body.
            "snippet": _clean_text(getattr(e, "summary", ""))[:1000],
            "published_at": _iso(getattr(e, "published_parsed", None))
            or _iso(getattr(e, "updated_parsed", None)),
            # "feed_image": false opts a source out entirely (its ToS bars media reuse).
            "image_url": _rss_image(e) if source.get("feed_image", True) else None,
            "lang": (source.get("lang") or ["ru"])[0],
        })
    return items


_RU_MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
              "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}


def _parse_list_date(text: str) -> str | None:
    """'17 июл 2026' / '25 мая 2026' / '17.07.2026' → 'YYYY-MM-DD', else None.

    A miss is safe: undated items pass the recency filter (``_is_recent``), so an
    unparseable date costs ranking precision, never the item itself.
    """
    raw = (text or "").strip().lower()
    if not raw:
        return None
    numeric = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", raw)
    if numeric:
        day, month, year = (int(g) for g in numeric.groups())
    else:
        named = re.match(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", raw)
        if not named:
            return None
        month = _RU_MONTHS.get(named.group(2)[:3], 0)
        if not month:
            return None
        day, year = int(named.group(1)), int(named.group(3))
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_html_list(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """A server-rendered listing page read as a feed (§3.11).

    For publishers whose RSS is a stub this is the only way to see their output: cbu.uz's
    feed carries a **single** entry, so a second press release published before the next
    run is lost for good, while its press-centre page lists the last ten. Selectors come
    from the source config (``list_selectors``), so covering another site is configuration,
    not code.

    One GET per run, and only what the listing itself renders — link, headline, date and
    the article's own thumbnail. No article page is opened and no body is stored, so the
    legal invariant (headline + our own summary + link) is untouched.
    """
    try:
        from bs4 import BeautifulSoup  # lazy: only html_list sources need it
    except ImportError:
        collectors_news_settings.logger.error("beautifulsoup4 is not installed — run: pip install beautifulsoup4")
        return []
    selectors = source.get("list_selectors") or {}
    if not selectors.get("item"):
        collectors_news_settings.logger.warning("source '%s' is html_list but has no list_selectors.item — skipped",
                       source["id"])
        return []
    try:
        resp = requests.get(source["url"], timeout=20, headers=collectors_news_http._source_headers(source))
        resp.raise_for_status()
    except requests.RequestException as exc:
        collectors_news_settings.logger.warning("listing fetch failed for %s: %s", source["id"], exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    pick = lambda node, key: (node.select_one(selectors[key])
                              if selectors.get(key) else None)  # noqa: E731
    items: list[dict[str, Any]] = []
    for node in soup.select(selectors["item"])[:limit]:
        link = node if node.has_attr("href") else node.select_one("a[href]")
        href = (link.get("href") if link else "") or ""
        title_node = pick(node, "title")
        title = _clean_text((title_node or node).get_text(" ", strip=True))
        if not href or not title:
            continue
        text_node = pick(node, "text")
        date_node = pick(node, "date")
        image = None
        # Same opt-out as the feeds: "feed_image": false when a ToS bars media reuse.
        if source.get("feed_image", True):
            img_node = pick(node, "image")
            src = (img_node.get("src") if img_node else "") or ""
            candidate = urljoin(source["url"], src) if src else ""
            if (candidate.lower().startswith(("http://", "https://"))
                    and not collectors_news_images._GENERIC_IMAGE_RE.search(urlparse(candidate).path)):
                image = candidate
        url = urljoin(source["url"], href)
        items.append({
            "url": _canonical_url(url),
            "raw_url": url,
            "title": title,
            # Listings publish a blurb only sometimes (cbu.uz renders an empty node), and
            # what is here is the publisher's own teaser — a snippet, never the body.
            "snippet": _clean_text(text_node.get_text(" ", strip=True))[:1000] if text_node else "",
            "published_at": _parse_list_date(date_node.get_text(" ", strip=True)) if date_node else None,
            "image_url": image,
            "lang": (source.get("lang") or ["ru"])[0],
        })
    return items


def _title_from_slug(url: str, strip_pattern: str | None = None) -> str:
    """'…/Moodys-Ratings-affirms-Zeda-Limiteds-Ba3-rating-outlook-stable--PR_514556'
    → 'Moodys Ratings affirms Zeda Limiteds Ba3 rating outlook stable'.

    Publishers that put the headline in the URL let us name an item without opening it.
    """
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if strip_pattern:
        slug = re.sub(strip_pattern, "", slug)
    return _clean_text(re.sub(r"[-_]+", " ", slug).strip())


_SLUG_ACRONYMS = {"jsc", "ojsc", "pjsc", "llc", "ltd", "plc", "idr", "idrs", "ifs", "esg",
                  "abs", "rmbs", "cmbs", "sme", "ipo", "gdp", "usd", "eur", "uk", "us", "uae"}


_RATING_GRADE = re.compile(r"(?:aaa|aa|a|bbb|bb|b|ccc|cc|c|d)[+-]?$")


_TITLE_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on",
                      "or", "the", "to", "vs", "with"}


def _recase_title(title: str, mode: str | None) -> str:
    """Give a slug-derived headline back the capitals the URL threw away.

    Fitch lower-cases every research slug, so its headline arrives as 'fitch affirms
    uzbekistan at bb outlook stable' and would sit in the feed next to properly cased ones
    looking broken. Only a source that declares ``title_case`` is touched, and only when the
    title is entirely lower case — Moody's slugs carry their own capitals and rewriting them
    could only do damage.
    """
    if mode != "title" or not title or title != title.lower():
        return title
    words = title.split()
    out: list[str] = []
    for i, word in enumerate(words):
        previous = words[i - 1] if i else ""
        if word in _SLUG_ACRONYMS or (previous in ("at", "to") and _RATING_GRADE.fullmatch(word)):
            out.append(word.upper())
        elif i and word in _TITLE_SMALL_WORDS:
            out.append(word)
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def fetch_sitemap(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """A publisher's XML sitemap read as a feed, filtered to our market before anything costs.

    For publishers with no usable feed that do expose a crawlable sitemap. Moody's
    ``ratingsnewsmap.xml`` is a rolling window of ~183 **global** rating actions with the
    headline in the URL slug — Uzbek issuers are a handful a year in that stream. So
    ``url_filter`` (a plain regex over the URL) runs **here**, ahead of the prefilter, the
    triage gate and any model call: the ~99% that names no issuer of ours costs exactly one
    shared HTTP request and nothing else.

    A **news sitemap** (the ``<news:>`` extension, which S&P Global publishes) carries the
    publisher's own headline and publication date per entry, and its ``<loc>`` is a numeric
    id with no slug in it. Those entries are filtered by ``title_filter`` over that headline
    instead — the same gate, applied to the only field that names anybody. A source must
    declare one filter or the other; a sitemap with neither would send a publisher's whole
    global output to the classifier.

    Nothing is opened: the headline comes from the sitemap itself — ``<news:title>``, or the
    slug where the publisher ships no title (``title_from: "slug"``) — so no article page is
    fetched and no body is stored. Entries without a date arrive undated, which ``_is_recent``
    keeps — correct for a rolling window that only ever lists current actions.

    Dates come from ``<news:publication_date>`` where there is one, then ``slug_date``, then
    ``<lastmod>``. ``slug_date`` exists because Fitch regenerates its research sitemap daily
    and stamps EVERY entry with the generation time, so a rating action published five days
    ago would be served to readers as today's news; its slug ends in the real date
    (``…-23-07-2026``).
    """
    try:
        resp = requests.get(source["url"], timeout=40, headers=collectors_news_http._source_headers(source))
        resp.raise_for_status()
    except requests.RequestException as exc:
        collectors_news_settings.logger.warning("sitemap fetch failed for %s: %s", source["id"], exc)
        return []

    strip_pattern = source.get("slug_strip")
    title_case = source.get("title_case")
    prefer_slug = source.get("title_from") == "slug"

    entries: list[dict[str, Any]] = []
    for block in re.finditer(r"<url>(.*?)</url>", resp.text, re.S):
        body = block.group(1)
        loc = re.search(r"<loc>\s*([^<]+?)\s*</loc>", body)
        if not loc:
            continue
        url = html.unescape(loc.group(1))
        lastmod = re.search(r"<lastmod>\s*([^<]+?)\s*</lastmod>", body)
        news_title = re.search(
            r"<news:title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</news:title>", body, re.S)
        news_date = re.search(
            r"<news:publication_date>\s*([^<]+?)\s*</news:publication_date>", body)
        published = html.unescape(news_date.group(1))[:10] if news_date else (
            lastmod.group(1)[:10] if lastmod else None)
        title = html.unescape(news_title.group(1)).strip() if news_title else ""
        if prefer_slug or not title:
            title = _recase_title(_title_from_slug(url, strip_pattern), title_case)
        entries.append({"url": url, "title": title, "published": published,
                        "dated_by_publisher": bool(news_date)})

    url_pattern = source.get("url_filter")
    title_pattern = source.get("title_filter")
    if url_pattern or title_pattern:
        url_matcher = re.compile(url_pattern, re.I) if url_pattern else None
        title_matcher = re.compile(title_pattern, re.I) if title_pattern else None
        kept = [e for e in entries
                if (url_matcher and url_matcher.search(e["url"]))
                or (title_matcher and title_matcher.search(e["title"] or ""))]
        collectors_news_settings.logger.info("  %s: %s filter kept %d of %d sitemap URL(s) — the rest cost nothing",
                    source["id"], "url" if url_matcher else "title", len(kept), len(entries))
        entries = kept
    elif entries:
        collectors_news_settings.logger.warning("source '%s' is a sitemap with no url_filter or title_filter — every "
                       "URL would be classified; refusing to fetch %d item(s)",
                       source["id"], len(entries))
        return []

    slug_date = source.get("slug_date") or {}
    date_pattern = slug_date.get("pattern")
    date_format = slug_date.get("format", "%d-%m-%Y")
    items: list[dict[str, Any]] = []
    for entry in entries[:limit]:
        url, title, published = entry["url"], entry["title"], entry["published"]
        if not title:
            continue
        # A date the publisher stated for THIS item is already the truth; slug_date exists
        # only to overrule a sitemap-wide build timestamp.
        if date_pattern and not entry["dated_by_publisher"]:
            match = re.search(date_pattern, url)
            if match:
                try:
                    published = datetime.strptime(match.group(1), date_format).strftime("%Y-%m-%d")
                except ValueError:
                    collectors_news_settings.logger.warning("  %s: unparseable slug date %r in %s",
                                   source["id"], match.group(1), url)
        items.append({
            "url": _canonical_url(url),
            "raw_url": url,
            "title": title,
            "snippet": "",
            "published_at": published,
            "image_url": None,
            "lang": (source.get("lang") or ["en"])[0],
        })
    return items

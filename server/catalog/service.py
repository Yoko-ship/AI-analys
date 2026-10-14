"""Catalogue analysis service: one verified-cache path for every issuer.

Before this, issuers in the ``finance`` sector took a separate path that
re-downloaded openinfo workbooks on every click, ran the company profile
through the industrial statement form and scored banks with factory formulas.
That path is where the 500s (banks and insurers have no revenue or cost of
sales), the non-JSON timeouts, the «D — Слабая компания» bank scores and the
quarter-for-year comparisons came from. Every analysis now reads the local
filing cache, resolves the organization kind first and picks its figures,
scoring and wording from that kind (:mod:`server.catalog.analysis`).

Everything here is synchronous and free of upstream I/O so the route can run
it in an executor under one deadline.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date
from typing import Any

from fastapi import HTTPException

import catalogue.filings as catalogue_filings
import catalogue.organization as catalogue_organization
import catalogue.ratios as catalogue_ratios
import catalogue.settings as catalogue_settings
import catalogue.storage as catalogue_storage
import server.catalog.analysis as catalog_analysis
from server.catalog.analysis import Subject, tr

SUPPORTED_TYPES = ("financial", "ratio", "dynamics", "quarter_compare", "annual_compare",
                   "swot", "recommendation", "multi_company")

# Peers whose balance sheets differ by more than this multiple are not offered
# for comparison. Checked against the listed universe: the 17 banks span 87×
# (1.2 to 104 trn UZS of assets) and the six insurers 22×, so every bank and
# insurer stays comparable with every other, while a 13 bn UZS retail fund and
# the 30 trn UZS national investment fund (1 880×) are not one peer group.
PEER_SCALE_LIMIT = 100.0
PEER_CACHE_SECONDS = 300.0


def _period_text(year: int, quarter: int, lang: str) -> str:
    return catalog_analysis.period_label(year, quarter, lang)


def _period_end(year: int, quarter: int) -> date:
    if not quarter:
        return date(year, 12, 31)
    month = quarter * 3
    return date(year, month, 30 if month in (6, 9) else 31)


def _not_found(lang: str, form: str, year: int, quarter: int, problem: dict | None = None) -> HTTPException:
    return HTTPException(status_code=404, detail=catalog_analysis._catalog_no_cached_data(
        lang, form, _period_text(year, quarter, lang), problem))


def company_name_for(ticker: str, approved: dict[str, Any]) -> str:
    return (catalogue_settings._TICKER_TO_NAME.get(ticker)
            or (approved.get(ticker) or {}).get("company_name") or ticker)


# ---------------------------------------------------------------------------
# Evidence beyond the statement
# ---------------------------------------------------------------------------

def _org_ids(tickers: list[str]) -> dict[str, str]:
    conn = catalogue_storage.get_catalog_conn()
    try:
        mapping = catalogue_ratios._ticker_org_map(conn)
    finally:
        conn.close()
    return {t: mapping[t] for t in tickers if t in mapping}


def _indicator(field: str, period: str) -> dict[str, float]:
    """org_id → one openinfo financial indicator for one period."""
    conn = catalogue_storage.get_catalog_conn()
    try:
        rows = conn.execute(
            "SELECT entity_id, value_num FROM facts WHERE dataset='financial_indicators' "
            "AND field=? AND period=? AND value_num IS NOT NULL", (field, period)).fetchall()
    except sqlite3.Error:
        catalogue_settings.logger.exception("catalog: indicator read failed")
        return {}
    finally:
        conn.close()
    return {str(r["entity_id"]): float(r["value_num"]) for r in rows}


def _published_risks(org_id: str | None, lang: str, form: str, period: str) -> list[dict[str, Any]]:
    """The company page's own risks, when it describes the same filing period."""
    if not org_id:
        return []
    try:
        from reporting import store as report_store
        report = report_store.latest_publication(org_id, lang, "ifrs" if form == "MSFO" else "nsbu")
    except Exception:  # noqa: BLE001 — the catalogue's own flags still stand
        catalogue_settings.logger.exception("catalog: published report read failed for %s", org_id)
        return []
    if not report or str(report.get("period") or "") != period:
        return []
    return [r for r in report.get("risks") or [] if isinstance(r, dict)]


def _market(ticker: str) -> dict[str, Any]:
    try:
        import catalogue.market_store as catalogue_market_store
        listing = catalogue_market_store.get_all_listings().get(ticker) or {}
    except Exception:  # noqa: BLE001 — no price is stated rather than a wrong one
        catalogue_settings.logger.exception("catalog: listing read failed for %s", ticker)
        return {}
    return {"price": listing.get("last_price"), "price_date": listing.get("last_trade_date"),
            "shares": listing.get("shares_outstanding")}


def _siblings(ticker: str) -> list[str]:
    conn = catalogue_storage.get_catalog_conn()
    try:
        return catalogue_filings._org_siblings(conn, ticker) or [ticker]
    finally:
        conn.close()


def freshness_notes(ticker: str, form: str, year: int, quarter: int, lang: str) -> list[str]:
    """Say when the other standard holds a newer statement than the one chosen.

    The analysis uses the filing the reader picked, and names its standard; if
    IFRS (or NSBU) is fresher, the reader is told which and that it can be
    chosen — or, when the newer filing has not been digitised yet, that the
    analysis is on the older statement for that reason.
    """
    other = "MSFO" if form == "NSBU" else "NSBU"
    chosen = _period_end(year, quarter)
    notes: list[str] = []
    latest = catalogue_ratios.latest_cached_catalog_period(ticker, other)
    if latest and _period_end(*latest) > chosen:
        notes.append(tr(lang,
                        f"Есть более свежая отчётность по {catalog_analysis.standard_label(other, lang)} — за {_period_text(*latest, lang)}; её можно выбрать в списке отчётов",
                        f"{catalog_analysis.standard_label(other, lang)} bo‘yicha yangiroq hisobot bor — {_period_text(*latest, lang)}; uni hisobotlar ro‘yxatidan tanlash mumkin",
                        f"A newer {catalog_analysis.standard_label(other, lang)} statement exists, for {_period_text(*latest, lang)}; it can be chosen in the report list"))
        return notes
    try:
        reports = catalogue_filings.get_company_reports(ticker) or []
    except Exception:  # noqa: BLE001
        return notes
    chosen_pub = max((str(r.get("published_at") or "") for r in reports
                      if r.get("report_form") == form and r.get("year") == year
                      and int(r.get("quarter") or 0) == quarter), default="")
    newer = sorted((str(r.get("published_at") or "")[:10] for r in reports
                    if r.get("report_form") == other and str(r.get("published_at") or "") > chosen_pub
                    and chosen_pub), reverse=True)
    if newer:
        notes.append(tr(lang,
                        f"{newer[0]} опубликован более свежий отчёт по {catalog_analysis.standard_label(other, lang)}, но его показатели ещё не оцифрованы, поэтому анализ выполнен по {catalog_analysis.standard_label(form, lang)}",
                        f"{newer[0]} {catalog_analysis.standard_label(other, lang)} bo‘yicha yangiroq hisobot e’lon qilingan, ammo uning ko‘rsatkichlari hali raqamlashtirilmagan, shuning uchun tahlil {catalog_analysis.standard_label(form, lang)} bo‘yicha bajarildi",
                        f"A newer {catalog_analysis.standard_label(other, lang)} report was published on {newer[0]}, but its figures are not digitised yet, so this analysis uses {catalog_analysis.standard_label(form, lang)}"))
    return notes


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------

_peer_cache: dict[tuple, tuple[float, list[dict[str, Any]]]] = {}
_peer_lock = threading.Lock()


def _universe(sectors: dict[str, Any]) -> list[dict[str, Any]]:
    companies = catalogue_filings.list_companies_with_stats()
    types = catalogue_organization.filing_org_types(
        member for company in companies for member in (company.get("tickers") or [company["ticker"]]))
    out = []
    for company in companies:
        ticker = str(company["ticker"]).upper()
        members = [str(m).upper() for m in (company.get("tickers") or [ticker])]
        org_type = types.get(ticker) or next((types[m] for m in members if m in types), None)
        name = catalogue_settings._TICKER_TO_NAME.get(ticker) or company.get("company_name") or ticker
        out.append({"ticker": ticker, "members": members, "company_name": name,
                    "sector": sectors.get(ticker),
                    "kind": catalogue_organization.resolve_kind(
                        org_type=org_type, name=name, sector=sectors.get(ticker))})
    return out


def peer_periods(kind: str, form: str, year: int, quarter: int,
                 sectors: dict[str, Any]) -> list[dict[str, Any]]:
    """Every issuer of one kind with a usable statement for one period."""
    key = (kind, form, year, quarter, tuple(sorted((k, str(v)) for k, v in sectors.items())))
    now = time.monotonic()
    with _peer_lock:
        hit = _peer_cache.get(key)
        if hit and now - hit[0] < PEER_CACHE_SECONDS:
            return hit[1]
    cost_of_risk = (_indicator("cost_of_risk", str(year))
                    if kind == catalogue_organization.BANK and not quarter else {})
    universe = [c for c in _universe(sectors) if c["kind"] == kind]
    orgs = _org_ids([c["ticker"] for c in universe])
    peers = []
    for company in universe:
        payload = catalogue_ratios.get_cached_catalog_period(company["ticker"], form, year, quarter)
        if not payload.get("has_data"):
            continue
        org = orgs.get(company["ticker"])
        metrics = catalog_analysis.kind_metrics(kind, payload, cost_of_risk.get(org) if org else None)
        peers.append({**company, "total_assets": (payload.get("all_values") or {}).get("total_assets"),
                      "metrics": metrics})
    with _peer_lock:
        if len(_peer_cache) > 64:
            _peer_cache.clear()
        _peer_cache[key] = (now, peers)
    return peers


def _scale_ratio(a: Any, b: Any) -> float | None:
    a, b = catalog_analysis._num(a), catalog_analysis._num(b)
    if not a or not b or a <= 0 or b <= 0:
        return None
    return max(a, b) / min(a, b)


def comparable_peers(ticker: str, kind: str, form: str, year: int, quarter: int,
                     own_assets: Any, sectors: dict[str, Any]) -> list[dict[str, Any]]:
    """Peers a comparison may be run against: same kind, same period, similar scale."""
    own = set(_siblings(ticker)) | {ticker}
    out = []
    for peer in peer_periods(kind, form, year, quarter, sectors):
        if own & set(peer["members"]):
            continue
        ratio = _scale_ratio(own_assets, peer.get("total_assets"))
        if ratio is not None and ratio > PEER_SCALE_LIMIT:
            continue
        out.append({"ticker": peer["ticker"], "company_name": peer["company_name"],
                    "total_assets": peer.get("total_assets")})
    return sorted(out, key=lambda p: p["company_name"])


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------

def build_subject(ticker: str, name: str, kind: str, sector: str | None, form: str,
                  year: int, quarter: int, lang: str, sectors: dict[str, Any], *,
                  with_peers: bool = True, with_notes: bool = True) -> Subject:
    current = catalogue_ratios.get_cached_catalog_period(ticker, form, year, quarter)
    if not current.get("has_data"):
        raise _not_found(lang, form, year, quarter, current.get("unavailable"))
    previous = catalogue_ratios.get_cached_catalog_period(ticker, form, year - 1, quarter)
    opening = catalogue_ratios.get_cached_catalog_period(ticker, form, year - 1, 0)
    period = f"{year}Q{quarter}" if quarter else str(year)
    org = _org_ids([ticker]).get(ticker)
    cor = prev_cor = None
    if kind == catalogue_organization.BANK and not quarter and org:
        cor = _indicator("cost_of_risk", str(year)).get(org)
        prev_cor = _indicator("cost_of_risk", str(year - 1)).get(org)
    from financial_analysis.sector_templates import CATALOG_SECTOR_TEMPLATES
    subject = Subject(
        ticker=ticker, name=name, kind=kind, form=form, year=year, quarter=quarter,
        current=current, previous=previous, opening=opening,
        sector_template=CATALOG_SECTOR_TEMPLATES.get(str(sector or "").lower()) if kind == catalogue_organization.INDUSTRY else None,
        cost_of_risk=cor, prev_cost_of_risk=prev_cor,
        published_risks=_published_risks(org, lang, form, period),
    )
    if kind == catalogue_organization.FUND and len(_siblings(ticker)) <= 1:
        subject.market = _market(ticker)
    if with_notes:
        subject.notes = freshness_notes(ticker, form, year, quarter, lang)
    if with_peers:
        # A bank's sector is «banks»; a factory's is its own catalogue sector —
        # cement is not measured against telecoms.
        own = set(_siblings(ticker)) | {ticker}
        others = [p["metrics"] for p in peer_periods(kind, form, year, quarter, sectors)
                  if not own & set(p["members"])
                  and (kind != catalogue_organization.INDUSTRY or p.get("sector") == sector)]
        subject.peer_avg = catalog_analysis.peer_average(others)
    return subject.evaluate(lang)


def _base(payload: Any, ticker: str, name: str, sector: str | None, kind: str) -> dict[str, Any]:
    return {"ok": True, "analysis_type": payload.analysis_type, "ticker": ticker, "company_name": name,
            "year": payload.year, "quarter": payload.quarter, "form": payload.form,
            "language": payload.language, "sector": sector, "org_kind": kind,
            "org_kind_label": catalog_analysis.kind_label(kind, payload.language),
            "data_source": "verified_cache"}


def _period_block(subject: Subject) -> dict[str, Any]:
    return {"year": subject.year, "quarter": subject.quarter, "form": subject.form,
            "metrics": subject.metrics, "source_values": (subject.current or {}).get("source_values") or {},
            "annualized": subject.annualized}


def _compare_periods(payload: Any, ticker: str, name: str, sector: str | None, kind: str,
                     sectors: dict[str, Any]) -> dict[str, Any]:
    lang, form = payload.language, payload.form
    notes: list[str] = []
    if payload.analysis_type == "annual_compare":
        # Annual against annual, whatever row the reader had selected: a
        # quarterly selection compares the last two completed years.
        cap_year = payload.year if not payload.quarter else payload.year - 1
        first = catalogue_ratios.latest_cached_catalog_period(ticker, form, annual_only=True,
                                                              not_after=(cap_year, 0))
        if not first:
            raise HTTPException(status_code=404, detail=tr(
                lang, "Годовых отчётов с подтверждёнными данными нет.", "Tasdiqlangan ma’lumotli yillik hisobotlar yo‘q.",
                "There are no annual filings with verified data."))
        if payload.quarter or first[0] != payload.year:
            notes.append(tr(lang, f"Сравниваются годовые отчёты: последний доступный — за {first[0]} год",
                            f"Yillik hisobotlar taqqoslanadi: oxirgi mavjud — {first[0]} yil",
                            f"Annual filings are compared: the latest available is FY{first[0]}"))
        if payload.compare_year and payload.compare_year != first[0]:
            second = (payload.compare_year, 0)
        else:
            second = catalogue_ratios.latest_cached_catalog_period(ticker, form, annual_only=True,
                                                                   not_after=(first[0] - 1, 0))
            if not second:
                raise HTTPException(status_code=404, detail=tr(
                    lang, f"Нет более раннего годового отчёта для сравнения с {first[0]} годом.",
                    f"{first[0]} yil bilan taqqoslash uchun oldingi yillik hisobot yo‘q.",
                    f"There is no earlier annual filing to compare with FY{first[0]}."))
            skipped = first[0] - 1
            if second[0] != skipped:
                problem = catalogue_ratios.get_cached_catalog_period(ticker, form, skipped, 0).get("unavailable")
                reason = catalog_analysis.unavailable_reason(problem, str(skipped), lang) or tr(
                    lang, "данных нет", "ma’lumot yo‘q", "no data")
                notes.append(tr(lang, f"{skipped} год пропущен: {reason}", f"{skipped} yil o‘tkazib yuborildi: {reason}",
                                f"FY{skipped} skipped: {reason}"))
        periods = [first, second]
    else:
        compare_quarter = payload.compare_quarter if payload.compare_quarter is not None else payload.quarter
        periods = [(payload.year, payload.quarter), (payload.compare_year or payload.year - 1, compare_quarter)]
    subjects = [build_subject(ticker, name, kind, sector, form, y, q, lang, sectors,
                              with_peers=False, with_notes=False) for y, q in periods]
    result = _base(payload, ticker, name, sector, kind)
    result.update({"period1": _period_block(subjects[0]), "period2": _period_block(subjects[1]),
                   "notes": notes,
                   "changes": {key: catalog_analysis.describe_change(
                       (subjects[0].current.get("source_values") or {}).get(key),
                       (subjects[1].current.get("source_values") or {}).get(key), lang)
                       for key in ("revenue", "net_income", "total_assets", "equity", "total_liabilities")}})
    result["year"], result["quarter"] = periods[0]
    return result


def analyze(payload: Any, approved: dict[str, Any], sectors: dict[str, Any]) -> dict[str, Any]:
    ticker = payload.ticker.upper()
    lang, form = payload.language, payload.form
    name = company_name_for(ticker, approved)
    sector = sectors.get(ticker)
    if payload.analysis_type not in SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail=tr(lang, "Неизвестный тип анализа.", "Noma’lum tahlil turi.",
                                                       "Unsupported analysis type."))
    kind = catalogue_organization.organization_kind(ticker, name=name, sector=sector)
    if form == "Audition":
        raise _not_found(lang, form, payload.year, payload.quarter)

    if payload.analysis_type == "dynamics":
        dynamics = catalogue_ratios.build_cached_catalog_dynamics(ticker, form)
        if not dynamics.get("years") and not dynamics.get("quarterly"):
            raise _not_found(lang, form, payload.year, payload.quarter)
        excluded = dynamics.get("excluded_periods") or []
        notes = [tr(lang, "Исключены периоды без пригодной отчётности: ", "Yaroqli hisobotsiz davrlar chiqarildi: ",
                    "Periods without a usable statement were left out: ")
                 + "; ".join(catalog_analysis.unavailable_reason(item, item["period"], lang) or item["period"]
                             for item in excluded)] if excluded else []
        return {**_base(payload, ticker, name, sector, kind), **dynamics, "notes": notes}

    if payload.analysis_type in ("quarter_compare", "annual_compare"):
        return _compare_periods(payload, ticker, name, sector, kind, sectors)

    subject = build_subject(ticker, name, kind, sector, form, payload.year, payload.quarter, lang, sectors)
    result = _base(payload, ticker, name, sector, kind)

    if payload.analysis_type == "ratio":
        result.update({
            "metrics": subject.metrics,
            "source_values": (subject.current or {}).get("source_values") or {},
            "prev_year": payload.year - 1,
            "prev_metrics": subject.prev_metrics,
            "sector_avg": subject.peer_avg,
            "annualized": subject.annualized,
            "period_months": (subject.current or {}).get("period_months"),
            "notes": subject.notes,
        })
        return result

    if payload.analysis_type == "multi_company":
        compare_ticker = str(payload.compare_ticker or "").strip().upper()
        if not compare_ticker:
            raise HTTPException(status_code=400, detail=tr(lang, "Выберите компанию для сравнения.",
                                                           "Taqqoslash uchun kompaniyani tanlang.",
                                                           "Choose a company to compare with."))
        other_name = company_name_for(compare_ticker, approved)
        other_kind = catalogue_organization.organization_kind(compare_ticker, name=other_name,
                                                              sector=sectors.get(compare_ticker))
        if other_kind != kind:
            raise HTTPException(status_code=400, detail=tr(
                lang, f"Сравнение возможно только с организацией того же типа: {name} — {catalog_analysis.kind_label(kind, lang)}, {other_name} — {catalog_analysis.kind_label(other_kind, lang)}.",
                f"Faqat bir xil turdagi tashkilot bilan taqqoslash mumkin: {name} — {catalog_analysis.kind_label(kind, lang)}, {other_name} — {catalog_analysis.kind_label(other_kind, lang)}.",
                f"Only organizations of the same kind can be compared: {name} is a {catalog_analysis.kind_label(kind, lang)}, {other_name} a {catalog_analysis.kind_label(other_kind, lang)}."))
        other_payload = catalogue_ratios.get_cached_catalog_period(compare_ticker, form, payload.year, payload.quarter)
        if not other_payload.get("has_data"):
            raise HTTPException(status_code=404, detail=tr(
                lang, f"У {other_name} нет подтверждённых данных по {catalog_analysis.standard_label(form, lang)} за {_period_text(payload.year, payload.quarter, lang)} — выберите компанию из списка сопоставимых.",
                f"{other_name} uchun {_period_text(payload.year, payload.quarter, lang)} bo‘yicha tasdiqlangan {catalog_analysis.standard_label(form, lang)} ma’lumotlari yo‘q — taqqoslanadigan ro‘yxatdan tanlang.",
                f"{other_name} has no verified {catalog_analysis.standard_label(form, lang)} data for {_period_text(payload.year, payload.quarter, lang)}; choose a company from the comparable list."))
        ratio = _scale_ratio((subject.current.get("all_values") or {}).get("total_assets"),
                             (other_payload.get("all_values") or {}).get("total_assets"))
        if ratio is not None and ratio > PEER_SCALE_LIMIT:
            raise HTTPException(status_code=400, detail=tr(
                lang, f"Масштаб {name} и {other_name} различается в {catalog_analysis.fmt_number(ratio, lang, 0)} раз (по активам) — их показатели несопоставимы.",
                f"{name} va {other_name} miqyosi {catalog_analysis.fmt_number(ratio, lang, 0)} barobar farq qiladi (aktivlar bo‘yicha) — ko‘rsatkichlar taqqoslanmaydi.",
                f"{name} and {other_name} differ {catalog_analysis.fmt_number(ratio, lang, 0)}-fold in assets; their metrics are not comparable."))
        other = build_subject(compare_ticker, other_name, kind, sectors.get(compare_ticker), form,
                              payload.year, payload.quarter, lang, sectors, with_peers=False, with_notes=False)
        result.update({
            "compare_ticker": compare_ticker, "compare_company_name": other_name,
            "sections": catalog_analysis.multi_company_sections(subject, other, lang),
            "comparison": {"rows": catalog_analysis.comparison_rows(subject, other),
                           "scores": {ticker: subject.score, compare_ticker: other.score}},
            "metrics": subject.metrics,
        })
        return result

    result.update({
        "sections": catalog_analysis.build_sections(payload.analysis_type, subject, lang),
        "metrics": subject.metrics,
        "score": subject.score,
        "flags": subject.flags,
        "notes": subject.notes,
    })
    return result


def peers(ticker: str, form: str, year: int, quarter: int, approved: dict[str, Any],
          sectors: dict[str, Any]) -> dict[str, Any]:
    ticker = ticker.upper()
    name = company_name_for(ticker, approved)
    kind = catalogue_organization.organization_kind(ticker, name=name, sector=sectors.get(ticker))
    current = catalogue_ratios.get_cached_catalog_period(ticker, form, year, quarter)
    own_assets = (current.get("all_values") or {}).get("total_assets") if current.get("has_data") else None
    return {"ok": True, "ticker": ticker, "org_kind": kind, "form": form, "year": year, "quarter": quarter,
            "scale_limit": PEER_SCALE_LIMIT,
            "peers": comparable_peers(ticker, kind, form, year, quarter, own_assets, sectors)}


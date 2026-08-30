"""Audited annual fund facts, kept separate from quarterly NSBU."""
import json
from datetime import date
from pathlib import Path

from sector_analysis import decimal, difference, number, ratio, tr, format_number


def audited_snapshot(issuer, period=None):
    records = json.loads((Path(__file__).parent / "config" / "verified_fund_reports.json").read_text(encoding="utf-8"))["reports"]
    eligible = [r for r in records if r["ticker"] == issuer["ticker"] and (period is None or r["period"] == period)]
    if not eligible:
        return None
    record = max(eligible, key=lambda r: r["period"])
    return {
        "standard": "ifrs", "template_basis": "IFRS_ANNUAL_PRIMARY", "organization_type": "investment_fund_ifrs_annual",
        "scope": "separate", "scope_verified": True, "audited": True, "period": record["period"],
        "period_start": record["period_start"], "period_basis": "annual_first_reporting_period",
        "previous_comparable_period": None, "current_values": {k: str(decimal(v) * 1000) for k, v in record["values"].items()},
        "previous_values": {}, "opening_values": {}, "rounding_unit": 1000, "display_divisor": 1000,
        "source": {"document_id": record["source_document_id"], "url": record["source_url"], "publication_date": record["publication_date"]},
        "quality": {"data_quality": []}, "fund_record": record,
    }


def enrich(report, snapshot, market=None):
    if report["status"] != "available":
        return report
    record, lang = snapshot["fund_record"], report["language"]
    raw = record["values"]
    nav = difference(raw["total_assets"], raw["total_liabilities"])
    report["nav"] = {"value_mln_uzs": number(nav), "per_exchange_share_uzs": None}
    report["portfolio"] = {
        "portfolio_to_assets_pct": number(ratio(raw["portfolio_fair_value"], raw["total_assets"], True)),
        "level_3_share_pct": number(ratio(raw["level3_investments"], raw["portfolio_fair_value"], True)),
        "top_1_pct": number(ratio(raw["largest_holding"], raw["portfolio_fair_value"], True)),
        "top_5_pct": number(ratio(raw["top5_holdings"], raw["portfolio_fair_value"], True)),
    }
    report["fund_ratios"] = {
        "unrealized_gain_to_profit_pct": number(ratio(raw["unrealized_fair_value_gain"], raw["net_income"], True)),
        "dividends_to_portfolio_pct": number(ratio(raw["dividend_income"], raw["portfolio_fair_value"], True)),
        "liabilities_to_nav_pct": number(ratio(raw["total_liabilities"], nav, True)),
        "management_expenses_to_nav_pct": number(ratio(raw["management_expenses"], nav, True)),
    }
    report["share_basis"] = record["share_basis"]
    report["valuation"] = {"price_to_nav": None, "premium_to_nav_pct": None, "blocked_reason": "SHARE_BASIS_NOT_RECONCILED"}
    report["subsequent_events"] = record["subsequent_events"]
    report["comparison_status"] = "not_available_first_reporting_period"
    report["report"]["period_start"] = record["period_start"]
    report["report"]["comparison_status"] = report["comparison_status"]
    report["market_as_of"] = (market or {}).get("date")
    all_facts = [*report["verified_facts"], *(f for group in report["replacement_blocks"].values() for f in group)]
    for fact in all_facts:
        key = fact.get("metric") or fact["metric_code"]
        if key in raw:
            fact.update(value_raw=raw[key], unit_raw="million UZS", source_line_id=record["source_lines"][key],
                        conversion_rule="million UZS * 1000 = thousand UZS")
    for risk in report["risks"]:
        risk["source_line_ids"] = [record["source_lines"].get(k, k) for k in
                                    ([risk["metric_code"], "net_income"] if risk["code"] == "profit_quality" else [risk["metric_code"]])]
    portfolio = report["portfolio"]
    paragraph = (f"NAV: {format_number(nav)} " + tr(lang, "млн сум", "mln so‘m", "million UZS") +
                 f"; Level 3: {format_number(portfolio['level_3_share_pct'])}%; Top-1: {format_number(portfolio['top_1_pct'])}%; Top-5: {format_number(portfolio['top_5_pct'])}%. " +
                 tr(lang, "Первый отчётный период 24.12.2024–31.12.2025; сопоставимого ряда нет. Цена/NAV скрыта до сверки количества и номинала акций.",
                    "Birinchi hisobot davri 24.12.2024–31.12.2025; taqqoslanadigan qator yo‘q. Aksiyalar soni va nominali tekshirilguncha narx/NAV yashirilgan.",
                    "First reporting period: 24 December 2024–31 December 2025; no comparable series exists. Price/NAV is withheld pending share-count and nominal reconciliation."))
    event = tr(lang, "После отчётной даты обмен портфеля имеет оценочный эффект", "Hisobotdan keyingi portfel almashinuvi baholangan ta’siri", "The post-reporting portfolio swap has an estimated effect")
    paragraph += f" {event}: −769 377 " + tr(lang, "млн сум; официальный NAV не изменён.", "mln so‘m; rasmiy NAV o‘zgartirilmagan.", "million UZS; reported NAV is unchanged.")
    report["paragraphs"].insert(-1, paragraph)
    report["text"] = "\n\n".join(report["paragraphs"])
    report["paragraph_count"] = len(report["paragraphs"])
    report["word_count"] = len(report["text"].split())
    report["sections"] = [{"id": f"section-{i}", "text": p} for i, p in enumerate(report["paragraphs"])]
    return report


def reconcile_share_basis(report, reconciliation, price, as_of=None):
    """Only an evidenced corporate-action reconciliation unlocks valuation."""
    if report.get("status") != "available" or not reconciliation:
        return
    evidence = reconciliation
    from bond_quality import day, freshness
    as_of = as_of or date.today()
    effective = day(evidence.get("effective_date"))
    issued = decimal(evidence.get("exchange_shares"))
    nominal = decimal(evidence.get("exchange_nominal_uzs"))
    basis = report.get("share_basis") or {}
    old_shares, old_nominal = decimal(basis.get("ifrs_issued_shares")), decimal(basis.get("ifrs_nominal_uzs"))
    if (evidence.get("verification_status") != "verified" or not evidence.get("source_url")
            or effective is None or effective > as_of or not issued or not nominal
            or issued <= 0 or nominal <= 0 or old_shares is None or old_nominal is None
            or issued * nominal != old_shares * old_nominal):
        return
    report["share_basis"] = {**basis, "exchange": evidence, "reconciliation_required": False,
                             "conversion_rule": "issued shares * nominal is unchanged"}
    nav_per_share = decimal(report["nav"]["value_mln_uzs"]) * 1000000 / issued
    report["nav"]["per_exchange_share_uzs"] = number(nav_per_share)
    market = freshness(report.get("market_as_of"), as_of)
    quote_day = day(report.get("market_as_of"))
    reason = ("NO_VERIFIED_TRADE" if decimal(price) is None or decimal(price) <= 0 or quote_day is None
              else "QUOTE_PRECEDES_SHARE_BASIS" if quote_day < effective
              else "STALE_OR_INVALID_QUOTE" if market["status"] != "fresh" else None)
    multiple = ratio(price, nav_per_share) if reason is None else None
    report["valuation"] = {"price_to_nav": number(multiple),
                           "premium_to_nav_pct": number((multiple - 1) * 100) if multiple is not None else None,
                           "blocked_reason": reason,
                           "financial_as_of": report["financial_as_of"], "market_as_of": report["market_as_of"]}

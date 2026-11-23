"""Lending figures from Openinfo's quarterly microfinance statement, in thousand UZS."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from numeric_parse import parse_decimal


def _amounts(rows, definitions):
    amounts = {}
    for code, label, column in definitions:
        matches = [row for row in rows if str(row.get("tnum")) == code]
        if len(matches) != 1 or label not in str(matches[0].get("title") or "").casefold():
            continue
        value = parse_decimal(matches[0].get(column), group_sep=",", strip_non_numeric=False)
        if value is not None:
            amounts[code] = value
    return amounts


def lending_facts(detail):
    """Reconcile independent sections so a bad reserve cannot hide an income line."""
    if detail.get("org_type") != "microfinance":
        return {}
    balance = _amounts(detail.get("quarter_balance_sheet_report") or [], (
        ("050", "кредиты", "value1"), ("051", "убытков по кредитам", "value1"), ("052", "кредиты, чистые", "value2"),
        ("060", "лизинг, брутто", "value1"), ("061", "убытков по лизингу", "value1"), ("062", "лизинг, чистые", "value2"),
    ))
    values, derived = {}, {}
    if (len(balance) == 6 and min(balance.values()) >= 0
            and abs(balance["050"] - balance["051"] - balance["052"]) <= 1
            and abs(balance["060"] - balance["061"] - balance["062"]) <= 1):
        values.update(gross_loans=balance["050"], gross_leasing=balance["060"],
                      loan_portfolio=balance["052"] + balance["062"], loan_reserves=balance["051"] + balance["061"])

        derived.update(loan_portfolio="052 + 062", loan_reserves="051 + 061")

    asset_labels = {"010": "денежные средства", "020": "размещенные в банках", "030": "проценты к получению",
                    "040": "факторинг", "052": "кредиты, чистые", "062": "лизинг, чистые", "072": "инвестиции, чистые",
                    "080": "основные средства", "090": "нематериальные активы", "102": "имущество, нетто",
                    "110": "другие активы", "120": "итого активы"}
    assets = _amounts(detail.get("quarter_balance_sheet_report") or [],
                      [(code, label, "value2") for code, label in asset_labels.items()])
    if (len(assets) == len(asset_labels) and assets["120"] > 0 and
            abs(sum(v for k, v in assets.items() if k != "120") - assets["120"]) <= 1):
        values.update(due_from_banks=assets["020"], fixed_assets=assets["080"])
    liability_labels = {"210": "кредиты и займы", "220": "обязательства по лизингу", "230": "выпущенные облигации",
                        "240": "проценты к уплате", "250": "налоги к уплате", "260": "доходы будущих периодов",
                        "270": "прочие обязательства", "280": "итого обязательства"}
    funding = _amounts(detail.get("quarter_balance_sheet_report") or [],
                       [(code, label, "value2") for code, label in liability_labels.items()])
    if (len(funding) == len(liability_labels) and min(funding.values()) >= 0 and
            abs(sum(v for k, v in funding.items() if k != "280") - funding["280"]) <= 1):
        values.update(borrowings=funding["210"] + funding["220"], debt_securities_issued=funding["230"])
        derived["borrowings"] = "210 + 220"

    labels = {"180": "всего процентных доходов", "270": "всего процентных расходов",
              "310": "чистые процентные доходы до", "320": "убытков по кредитам и лизингу",
              "330": "чистые процентные доходы после", "410": "поручительских операций", "420": "факторинговых услуг",
              "430": "посреднической деятельности", "440": "изменения валютного курса",
              "450": "дивиденды от инвестиций", "460": "прочие беспроцентные доходы", "470": "всего беспроцентных доходов",
              "550": "всего беспроцентных расходов", "600": "прибыль до операционных расходов",
              "780": "всего операционных расходов", "800": "убытков, не связанных",
              "900": "прибыль до налога", "1000": "оценка налога", "1100": "прибыль до корректировок",
              "1110": "корректировки к прибыли", "1200": "чистая прибыль"}
    flow = _amounts(detail.get("quarter_financial_results_report") or [],
                    [(code, label, "value") for code, label in labels.items()])
    if {"180", "270", "310"} <= flow.keys() and abs(flow["180"] - flow["270"] - flow["310"]) <= 1:
        values.update(interest_income=flow["180"], interest_expenses=flow["270"],
                      net_interest_income_before_provisions=flow["310"])
        if {"320", "330"} <= flow.keys() and abs(flow["310"] - flow["320"] - flow["330"]) <= 1:
            values.update(credit_loss_provisions=flow["320"], net_interest_income_after_provisions=flow["330"])

    noninterest = ("410", "420", "430", "440", "450", "460")
    if set(noninterest) <= flow.keys() and "470" in flow and abs(sum(flow[k] for k in noninterest) - flow["470"]) <= 1:
        values["other_noninterest_income"] = flow["460"]
    if {"330", "470", "550", "780", "800", "900"} <= flow.keys():
        before_expenses = flow["330"] + flow["470"] - flow["550"]
        after_expenses = flow["900"] + flow["780"] + flow["800"]
        subtotal = flow.get("600")
        if subtotal in (None, 0) and abs(before_expenses - after_expenses) <= 1 and before_expenses != 0:
            subtotal = before_expenses
            derived["net_revenue_before_operating_expenses"] = "330 + 470 - 550 (checked against 900 + 780 + 800)"
        if subtotal is not None and abs(subtotal - before_expenses) <= 1 and abs(subtotal - after_expenses) <= 1:
            values.update(net_revenue_before_operating_expenses=subtotal, operating_expenses=flow["780"],
                          noninterest_income=flow["470"], noninterest_expenses=flow["550"], profit_before_tax=flow["900"])
    if {"900", "1000", "1100", "1110", "1200"} <= flow.keys() and abs(flow["900"] - flow["1000"] - flow["1100"]) <= 1:
        if abs(flow["1100"] + flow["1110"] - flow["1200"]) <= 1:
            values["tax"] = flow["1000"]
    return {"values": values, "derived": derived} if values else {}


def selected_lending(issuer, period, document, values):
    """Match the stored form to the exact selected revision and its core figures."""
    from financial_ingestion import quarterly_comparative

    query = parse_qs(urlparse(document.get("excel_url") or "").query)
    report_id = (query.get("report_id") or [""])[0]
    if query.get("org_type") != ["microfinance"] or not report_id.isdigit():
        return {}
    saved = quarterly_comparative.read([issuer["ticker"]], structured=True).get(period) or {}
    source = saved.get("source") or {}
    url = f"https://openinfo.uz/reports/microfinance/quarter/{report_id}"
    if (source.get("org_id") != str(issuer["id"]) or source.get("source_period") != period
            or source.get("source_url") != url or not document.get("published_at")
            or source.get("pub_date") != document["published_at"]):
        return {}
    core = saved["values"]
    keys = ("revenue", "net_income", "total_assets", "total_liabilities", "total_equity")
    if any(core.get(key) is None or core[key] != values.get(key) for key in keys):
        return {}
    lending = saved.get("lending") or {}
    if not lending or any(values.get(k) is not None and values[k] != v for k, v in lending["values"].items()):
        return {}
    return {**lending, "url": url}

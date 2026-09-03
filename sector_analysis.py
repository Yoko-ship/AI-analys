"""Versioned, deterministic sector analysis. No network or language-model arithmetic.

The v2.2 specification is an internal calculation contract, not a source of
issuer observations. Only dated catalog filings / explicitly mapped source
lines enter this module. Missing values never become zero.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

VERSION = "sector-analysis-2.3"
CALCULATION_VERSION = "nsbu-core-2.1"
MAPPING_VERSION = "nsbu-lines-2.0"
FINANCIAL_TYPES = {"bank", "microfinance_bank", "microfinance", "insurance", "investment_fund_ifrs_annual", "spv"}
SPECIAL_TYPES = {
    "bank": "bank", "insurance": "insurance", "insurer": "insurance",
    "microfinance_bank": "microfinance_bank", "microbank": "microfinance_bank",
    "microfinance": "microfinance", "mfo": "microfinance", "pawnshop": "microfinance",
    "investment_fund": "investment_fund_ifrs_annual",
    "closed_end_investment_fund": "investment_fund_ifrs_annual",
    "commodity_exchange": "commodity_exchange", "spv": "spv",
    "investment_fund_ifrs_annual": "investment_fund_ifrs_annual",
}
# Prefixes are deliberately conservative. They are classifications, not risk rules.
OKED_MAP = {"511": "aviation", "512": "aviation", "61": "telecom", "6491": "leasing",
            "23": "cement", "24": "metallurgy", "05": "extractive", "06": "extractive",
            "07": "extractive", "08": "extractive", "46": "trade", "47": "trade",
            "49": "transport", "50": "transport", "52": "transport",
            **{str(n): "industry" for n in range(10, 34) if n not in (23, 24)}}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def decimal(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if not text or "#" in text or text in {"-", "—", "–"}:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    elif text.count(",") > 1:
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        number = Decimal(text)
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def number(value):
    value = decimal(value)
    return float(value) if value is not None else None


def total(*values):
    values = [decimal(v) for v in values]
    return sum(values, Decimal(0)) if values and all(v is not None for v in values) else None


def difference(current, previous):
    current, previous = decimal(current), decimal(previous)
    return current - previous if current is not None and previous is not None else None


def ratio(numerator, denominator, percent=False):
    numerator, denominator = decimal(numerator), decimal(denominator)
    if numerator is None or denominator is None or denominator <= 0:
        return None
    with localcontext() as context:
        context.prec = 38
        return numerator / denominator * (100 if percent else 1)


def change(current, previous):
    current, previous = decimal(current), decimal(previous)
    delta = difference(current, previous)
    pct = ratio(delta, abs(previous), True) if previous is not None else None
    sign_change = current is not None and previous is not None and current * previous < 0
    base_effect = previous is not None and current is not None and (previous == 0 or sign_change or (pct is not None and abs(pct) >= 500))
    return {"current": number(current), "previous": number(previous), "change_value": number(delta),
            "change_pct": number(pct), "base_effect": base_effect, "sign_change": sign_change}


def resolve_template(issuer, organization_type="non_financial", today=None):
    today = today or date.today()
    index, security = issuer.get("index") or {}, issuer.get("security") or {}
    explicit = issuer.get("special_legal_type") or index.get("special_legal_type") or security.get("special_legal_type")
    explicit = str(explicit or organization_type).lower()
    oked = str(issuer.get("oked_code") or index.get("oked_code") or index.get("oked") or security.get("oked_code") or "")
    oked = re.sub(r"\D", "", oked)
    override = issuer.get("template_override") or index.get("template_override") or {}
    valid_override = bool(override.get("approved_by") and override.get("evidence_source") and
                          override.get("valid_from", "0000") <= today.isoformat() <= override.get("valid_to", "9999"))
    special = SPECIAL_TYPES.get(explicit)
    prefix = next((p for p in sorted(OKED_MAP, key=len, reverse=True) if oked.startswith(p)), None)
    selected = special or (OKED_MAP[prefix] if prefix else "generic_nsbu")
    status = "special_override" if special else "matched_prefix" if prefix else "generic_fallback"
    if valid_override:
        selected, status = override.get("override_template", "generic_nsbu"), "manual_override"
    activity = issuer.get("verified_activity_template") or index.get("verified_activity_template")
    if activity and activity != selected and not valid_override:
        status = "classification_conflict"
    return {"selected_template": selected, "resolution_status": status, "input_oked": oked or None,
            "rule_version": VERSION, "evidence_source": override.get("evidence_source") if valid_override else index.get("source_url"),
            "reason_code": override.get("reason_code") if valid_override else ("special_legal_type" if special else "primary_oked" if prefix else "unknown_oked")}


FORM1 = {"c400": "total_assets", "c480": "total_equity", "c770": "total_liabilities",
         "c390": "current_assets", "c320": "cash", "c370": "short_term_investments",
         "c210": "receivables", "c140": "inventories", "c600": "current_liabilities",
         "c490": "long_term_liabilities", "c130": "non_current_assets", "c012": "fixed_assets", "c100": "construction_in_progress",
         "c030": "long_term_investments", "c410": "share_capital", "c420": "additional_capital",
         "c430": "reserve_capital", "c440": "treasury_shares", "c450": "retained_earnings",
         "c460": "target_receipts", "c470": "future_expense_reserves"}
FORM2 = {"c010": "revenue", "c020": "cost_of_sales", "c030": "gross_profit",
         "c040": "period_expenses", "c090": "other_operating_income", "c100": "operating_income",
         "c110": "financial_income", "c150": "fx_income", "c170": "financial_expenses",
         "c180": "interest_expenses", "c200": "fx_expenses", "c240": "profit_before_tax", "c270": "net_income"}
EXPENSE_LINES = {"c020", "c040", "c170", "c180", "c200"}


def statement_rows(sheet, form):
    rows = sheet.get("table_rows") or []
    start = next((i for i, row in enumerate(rows) if re.search(
        r"^чистая выручка от реализации|^доходы от оказания страховых услуг|^31\.\s*итого обязательств и собственного капитала",
        str(row.get("label") or ""), re.I)), None)
    if start is not None:
        bank_end = str(rows[start].get("label") or "").startswith("31.")
        boundary = start + 1 if bank_end else start
        rows = rows[boundary:] if form == "form2" else rows[:boundary]
    return [row for row in rows if not re.search(r"^(мфо|кфс|оконх|окпо|соато|период квартала|номер расчетного|присвоенные)", str(row.get("label") or ""), re.I)]


def source_line_pairs(workbook, form, known_codes=None):
    """Read explicit positions; never compress blanks or copy opening into end.

    In the parser's numeric_cells representation the original column indexes
    retain holes. The numeric_values fallback is accepted only for complete,
    unambiguous 3/5-cell exported layouts.
    """
    result = {}
    for sheet in (workbook or {}).get("sheets") or []:
        for row in statement_rows(sheet, form):
            cells = row.get("numeric_cells") or []
            raw = list(row.get("numeric_values") or [])
            if row.get("source_cells"):
                original = row["source_cells"]
                known_codes = known_codes or (set(FORM2) if form == "form2" else set(FORM1) | {"c570", "c580"})
                code_index = next((i for i, v in enumerate(original) if decimal(v) is not None), None)
                if code_index is not None:
                    candidate = decimal(original[code_index])
                    if candidate != int(candidate) or f"c{int(candidate):03d}" not in known_codes:
                        continue
                    count = 4 if form == "form2" else 2
                    raw = original[code_index:code_index + count + 1]
                    raw += [None] * (count + 1 - len(raw))
            elif cells:
                columns = [c.get("column_index", c.get("index")) for c in cells]
                if all(isinstance(c, int) for c in columns):
                    cell_map = dict(zip(columns, [c.get("value") for c in cells]))
                    raw = [cell_map.get(c) for c in range(min(columns), max(columns) + 1)]
            if len(raw) not in (3, 5):
                continue
            code_number = decimal(raw[0])
            if code_number is None or code_number != int(code_number) or not 0 < code_number < 2000:
                continue
            code = f"c{int(code_number):03d}"
            if len(raw) == 3:
                previous, current = decimal(raw[1]), decimal(raw[2])
            elif form == "form2":
                # Crossed-out cells are structurally inapplicable; a blank
                # amount cell remains missing. Only explicit X is a zero side.
                pair = lambda a, b: difference(0 if str(a).strip().lower() in {"x", "х"} else a,
                                                0 if str(b).strip().lower() in {"x", "х"} else b)
                previous, current = pair(raw[1], raw[2]), pair(raw[3], raw[4])
                if code in EXPENSE_LINES:
                    previous = abs(previous) if previous is not None else None
                    current = abs(current) if current is not None else None
            else:
                continue
            if code in result:
                # A duplicated code in another statement cannot overwrite one.
                if result[code]["current"] != number(current):
                    result[code]["conflict"] = True
                continue
            result[code] = {"current": number(current), "previous": number(previous),
                            "raw_current": str(current) if current is not None else None,
                            "raw_previous": str(previous) if previous is not None else None,
                            "source_line_id": f"{form}:{code}", "label": row.get("label"),
                            "source_url": workbook.get("source_url"),
                            "sheet": sheet.get("sheet", sheet.get("name")), "row": row.get("row", row.get("row_index"))}
    return result


METHODS = {
    "P1": (["form2:c270"], ["form1:c400"], True),
    "P2": (["form2:c240"], ["form1:c390"], True),
    "P3": (["form2:c240"], ["form1:c480", "form1:c570", "form1:c580"], True),
    "P4": (["form2:c240"], ["form1:c480"], True),
    "P5": (["form2:c030"], ["form2:c010"], True),
    "P6": (["form2:c030"], ["form2:c020"], True),
    "P7": (["form2:c240"], ["form2:c010"], True),
    "P8": (["form2:c240"], ["form1:c130"], True),
    "current_ratio": (["form1:c320", "form1:c370", "form1:c210", "form1:c140"], ["form1:c600"], False),
    "quick_ratio": (["form1:c320", "form1:c370", "form1:c210"], ["form1:c600"], False),
    "absolute_liquidity": (["form1:c320", "form1:c370"], ["form1:c600"], False),
}


def enterprise_ratios(lines, organization_type, standard, period, methods=None):
    if organization_type != "non_financial" or standard.lower() != "nsbu":
        return []
    results = []
    for code, (numerators, denominators, percent) in (METHODS if methods is None else methods).items():
        components = numerators + denominators
        values = {key: (lines.get(key) or {}).get("raw_current", (lines.get(key) or {}).get("current")) for key in components}
        numerator, denominator = total(*(values[k] for k in numerators)), total(*(values[k] for k in denominators))
        value = ratio(numerator, denominator, percent)
        # Balance opening values are comparable for liquidity, not for a
        # prior-year flow divided by this year's opening balance.
        opening = None
        if not percent:
            opening = ratio(total(*((lines.get(k) or {}).get("raw_previous", (lines.get(k) or {}).get("previous")) for k in numerators)),
                            total(*((lines.get(k) or {}).get("raw_previous", (lines.get(k) or {}).get("previous")) for k in denominators)))
        results.append({"metric": code, "metric_code": code,
                        "method_id": f"nsbu-enterprise-{'profitability' if percent else 'liquidity'}-1.0:{code}",
                        "accounting_standard": "NSBU", "period": period,
                        "numerator_value": number(numerator), "denominator_value": number(denominator),
                        "component_facts": components, "formula": f"({' + '.join(numerators)}) / ({' + '.join(denominators)})" + (" * 100" if percent else ""),
                        "raw_result": str(value) if value is not None else None,
                        "value": number(value), "display_result": str(value.quantize(Decimal("0.01"))) if value is not None else None,
                        "opening_value": number(opening), "change_value": number(difference(value, opening)),
                        "unit": "percent" if percent else "ratio", "benchmark_type": None if percent else "methodological_reference",
                        "benchmark_min": {"current_ratio": 1.5, "quick_ratio": 1, "absolute_liquidity": .2}.get(code),
                        "benchmark_max": {"current_ratio": 2, "absolute_liquidity": .5}.get(code),
                        "calculation_status": "verified" if value is not None else "missing_or_invalid_components",
                        "verification_status": "verified" if value is not None else "unavailable"})
    return results


def balance_gate(values, rounding_unit=1):
    assets, equity, liabilities = (decimal(values.get(k)) for k in ("total_assets", "total_equity", "total_liabilities"))
    if any(v is None for v in (assets, equity, liabilities)):
        return {"status": "not_checked", "code": "BALANCE_COMPONENTS_MISSING", "severity": "blocking"}
    difference_value = assets - equity - liabilities
    tolerance = min(decimal(rounding_unit) or Decimal(1), abs(assets) * Decimal("0.0005"))
    passed = abs(difference_value) <= tolerance and assets > 0
    return {"status": "passed" if passed else "failed", "code": "BALANCE_IDENTITY_FAILED",
            "severity": None if passed else "blocking", "difference": number(difference_value),
            "tolerance": number(tolerance), "formula": "assets = equity + liabilities"}


def capital_analysis(values, opening):
    result = {"method_id": "nsbu-capital-structure-1.0",
              "equity_open": number(opening.get("total_equity")), "equity_end": number(values.get("total_equity")),
              "equity_change": number(difference(values.get("total_equity"), opening.get("total_equity"))),
              "change_sources": []}
    for suffix, data in (("open", opening), ("end", values)):
        result[f"equity_to_assets_{suffix}"] = number(ratio(data.get("total_equity"), data.get("total_assets"), True))
        result[f"liabilities_to_equity_{suffix}"] = number(ratio(data.get("total_liabilities"), data.get("total_equity")))
    for key in ("share_capital", "additional_capital", "reserve_capital", "treasury_shares", "retained_earnings", "target_receipts", "future_expense_reserves"):
        delta = difference(values.get(key), opening.get(key))
        result["change_sources"].append({"metric_code": key, "change_value": number(-delta if delta is not None and key == "treasury_shares" else delta)})
    sum_changes = total(*(item["change_value"] for item in result["change_sources"]))
    result["reconciliation_difference"] = number(difference(result["equity_change"], sum_changes))
    result["reconciliation_status"] = "not_available" if result["reconciliation_difference"] is None else "passed" if abs(decimal(result["reconciliation_difference"])) <= 1 else "failed"
    return result


def profit_quality(values, previous):
    op = change(values.get("operating_income"), previous.get("operating_income"))
    profit = change(values.get("net_income"), previous.get("net_income"))
    fx, fx_prev = difference(values.get("fx_income"), values.get("fx_expenses")), difference(previous.get("fx_income"), previous.get("fx_expenses"))
    fx_delta = difference(fx, fx_prev)
    driver = "unknown"
    unrealized = decimal(values.get("unrealized_fair_value_gain"))
    if unrealized is not None and (decimal(values.get("net_income")) or 0) > 0 and unrealized > 0 and unrealized >= decimal(values["net_income"]) * Decimal("0.5"):
        driver = "unrealized_revaluation"
    elif fx_delta is not None and profit["change_value"] is not None and fx_delta > 0 and profit["change_value"] > 0 and fx_delta >= decimal(profit["change_value"]) * Decimal("0.5"):
        driver = "FX-driven"
    return {"method_id": "nsbu-profit-quality-1.0", "operating_profit_change": op,
            "net_profit_change": profit, "net_fx_result_current": number(fx), "net_fx_result_previous": number(fx_prev),
            "net_fx_result_change": number(fx_delta), "driver": driver, "cash_confirmation": "not_available"}


CORE_RESULT = ["revenue", "cost_of_sales", "gross_profit", "period_expenses", "operating_income", "profit_before_tax", "tax", "net_income"]
BANK_RESULT = ["interest_income", "interest_expenses", "noninterest_income", "noninterest_expenses", "operating_expenses", "profit_before_tax", "tax", "net_income"]
INSURANCE_RESULT = ["insurance_premiums", "insurance_claims", "revenue", "expenses", "operating_income", "profit_before_tax", "tax", "net_income"]
FUND_RESULT = ["unrealized_fair_value_gain", "dividend_income", "management_expenses", "tax", "net_income"]
BALANCE = ["cash", "receivables", "inventories", "current_liabilities", "total_assets", "total_liabilities", "total_equity"]
FINANCE_BALANCE = ["cash", "central_bank_balances", "loan_portfolio", "customer_funds", "borrowings", "loan_reserves", "total_assets", "total_liabilities", "total_equity"]
INSURANCE_BALANCE = ["cash", "receivables", "gross_insurance_reserves", "reinsurer_share_in_reserves", "net_insurance_reserves", "other_liabilities", "total_assets", "total_liabilities", "total_equity"]
FUND_BALANCE = ["cash", "dividends_receivable", "accounts_payable", "total_assets", "total_liabilities", "total_equity"]


def block_codes(template):
    financial = template in {"bank", "microfinance_bank", "microfinance"}
    result = BANK_RESULT if financial else INSURANCE_RESULT if template == "insurance" else FUND_RESULT if template == "investment_fund_ifrs_annual" else CORE_RESULT
    balance = FINANCE_BALANCE if financial else INSURANCE_BALANCE if template == "insurance" else FUND_BALANCE if template == "investment_fund_ifrs_annual" else BALANCE
    if template == "commodity_exchange":
        balance = ["own_cash", "client_cash", "settlement_liabilities", *BALANCE]
    return {"financial_result": result, "cash_and_working_capital": balance,
            "investment_base": ["portfolio_fair_value", "level3_investments", "largest_holding", "top5_holdings"] if template == "investment_fund_ifrs_annual" else ["fixed_assets", "construction_in_progress", "long_term_investments"],
            "sector_operating_facts": [], "market_facts": []}


LABELS = {
    "revenue": ("Выручка / раскрытые доходы", "Tushum / daromad", "Revenue / disclosed income"),
    "net_income": ("Чистая прибыль (убыток)", "Sof foyda (zarar)", "Net income (loss)"),
    "operating_income": ("Прибыль основной деятельности", "Asosiy faoliyat foydasi", "Operating result"),
    "total_assets": ("Активы", "Aktivlar", "Assets"), "total_equity": ("Капитал", "Kapital", "Equity"),
    "total_liabilities": ("Обязательства", "Majburiyatlar", "Liabilities"), "cash": ("Деньги", "Pul mablag‘lari", "Cash"),
    "cost_of_sales": ("Себестоимость", "Tannarx", "Cost of sales"), "gross_profit": ("Валовая прибыль", "Yalpi foyda", "Gross profit"),
    "period_expenses": ("Расходы периода", "Davr xarajatlari", "Period expenses"), "profit_before_tax": ("Прибыль до налога", "Soliqdan oldingi foyda", "Profit before tax"),
    "financial_income": ("Финансовые доходы", "Moliyaviy daromadlar", "Finance income"),
    "financial_expenses": ("Финансовые расходы", "Moliyaviy xarajatlar", "Finance expenses"),
    "receivables": ("Дебиторская задолженность", "Debitorlik qarzi", "Receivables"), "inventories": ("Запасы", "Zaxiralar", "Inventories"),
    "current_liabilities": ("Текущие обязательства", "Joriy majburiyatlar", "Current liabilities"),
    "fixed_assets": ("Основные средства", "Asosiy vositalar", "Fixed assets"), "construction_in_progress": ("Незавершённые вложения", "Tugallanmagan investitsiyalar", "Construction in progress"),
    "long_term_investments": ("Долгосрочные инвестиции", "Uzoq muddatli investitsiyalar", "Long-term investments"),
    "interest_income": ("Процентные доходы", "Foizli daromad", "Interest income"), "interest_expenses": ("Процентные расходы", "Foizli xarajat", "Interest expenses"),
    "noninterest_income": ("Непроцентные доходы", "Foizsiz daromad", "Noninterest income"), "noninterest_expenses": ("Непроцентные расходы", "Foizsiz xarajat", "Noninterest expenses"),
    "operating_expenses": ("Операционные расходы", "Operatsion xarajatlar", "Operating expenses"), "expenses": ("Расходы", "Xarajatlar", "Expenses"),
    "central_bank_balances": ("Средства в ЦБ", "Markaziy bankdagi mablag‘lar", "Central bank balances"),
    "loan_portfolio": ("Кредитный портфель", "Kredit portfeli", "Loan portfolio"), "customer_funds": ("Средства клиентов", "Mijozlar mablag‘lari", "Customer funds"),
    "borrowings": ("Заимствования", "Qarz mablag‘lari", "Borrowings"), "loan_reserves": ("Резервы по кредитам", "Kredit zaxiralari", "Loan reserves"),
    "insurance_premiums": ("Страховые премии", "Sug‘urta mukofotlari", "Insurance premiums"), "insurance_claims": ("Страховые выплаты", "Sug‘urta to‘lovlari", "Insurance claims"),
    "gross_insurance_reserves": ("Валовые страховые резервы", "Yalpi sug‘urta zaxiralari", "Gross insurance reserves"),
    "reinsurer_share_in_reserves": ("Доля перестраховщиков", "Qayta sug‘urtalovchilar ulushi", "Reinsurer share"),
    "net_insurance_reserves": ("Чистые страховые резервы", "Sof sug‘urta zaxiralari", "Net insurance reserves"),
    "other_liabilities": ("Прочие обязательства", "Boshqa majburiyatlar", "Other liabilities"),
    "own_cash": ("Собственные деньги", "O‘z pul mablag‘lari", "Own cash"), "client_cash": ("Деньги клиентов", "Mijozlar puli", "Client cash"),
    "settlement_liabilities": ("Расчётные обязательства", "Hisob-kitob majburiyatlari", "Settlement liabilities"),
    "unrealized_fair_value_gain": ("Нереализованная переоценка", "Realizatsiya qilinmagan qayta baholash", "Unrealized revaluation"),
    "dividend_income": ("Дивидендный доход", "Dividend daromadi", "Dividend income"), "management_expenses": ("Расходы управляющего", "Boshqaruvchi xarajatlari", "Management expenses"),
    "tax": ("Налог", "Soliq", "Tax"), "portfolio_fair_value": ("Стоимость портфеля", "Portfel qiymati", "Portfolio fair value"),
    "dividends_receivable": ("Дивиденды к получению", "Olinadigan dividendlar", "Dividends receivable"), "accounts_payable": ("Кредиторская задолженность", "Kreditorlik qarzi", "Accounts payable"),
    "level3_investments": ("Инвестиции Level 3", "Level 3 investitsiyalari", "Level 3 investments"), "largest_holding": ("Крупнейшая позиция", "Eng yirik pozitsiya", "Largest holding"), "top5_holdings": ("Пять крупнейших позиций", "Eng yirik beshta pozitsiya", "Top five holdings"),
}


def tr(lang, ru, uz, en):
    return (ru, uz, en)[{"ru": 0, "uz": 1, "en": 2}.get(lang, 0)]


def label(code, lang):
    return tr(lang, *LABELS.get(code, (code, code, code)))


def format_number(value):
    return "—" if value is None else f"{float(value):,.2f}".replace(",", " ")


def trend_state(points):
    """Describe only trends supported by comparable observations.

    Two observations are a comparison, not a trend.  Three comparable points
    can establish a direction; saying that a metric fell three times in a row
    requires four observations.  Context fields are part of comparability so a
    year, YTD and standalone quarter can never be joined into one sequence.
    """
    clean = []
    for point in points or []:
        value = decimal(point.get("value"))
        period = point.get("period")
        if value is None or not period:
            continue
        clean.append({**point, "value": number(value)})
    clean.sort(key=lambda item: str(item["period"]))
    if not clean:
        return {"status": "unavailable", "points": 0, "direction": None, "consecutive_moves": 0}
    contexts = {
        (item.get("period_basis"), item.get("accounting_standard"), item.get("consolidation_scope"))
        for item in clean
    }
    if len(contexts) > 1:
        return {"status": "not_comparable", "points": len(clean), "direction": None, "consecutive_moves": 0}
    if len(clean) == 1:
        return {"status": "single_point", "points": 1, "direction": None, "consecutive_moves": 0}
    moves = [clean[index]["value"] - clean[index - 1]["value"] for index in range(1, len(clean))]
    direction = "up" if all(move > 0 for move in moves) else "down" if all(move < 0 for move in moves) else "mixed"
    if len(clean) == 2:
        status = "comparison_only"
    elif direction == "down" and len(moves) >= 3:
        status = "three_consecutive_declines"
    elif direction in {"up", "down"}:
        status = "trend"
    else:
        status = "mixed"
    return {"status": status, "points": len(clean), "direction": direction,
            "consecutive_moves": len(moves) if direction in {"up", "down"} else 0,
            "periods": [item["period"] for item in clean]}


def prepare_inputs(snapshot, workbook=None):
    """Add exact form lines without changing the independent comparison API."""
    values = dict(snapshot.get("current_values") or {})
    previous = dict(snapshot.get("previous_values") or {})
    opening = dict(snapshot.get("opening_values") or {})
    lines = dict(snapshot.get("source_lines") or {})
    org = snapshot.get("organization_type")
    if workbook and org == "non_financial" and not snapshot.get("control_lines_prepared"):
        for form, table in (("form1", workbook.get("balance")), ("form2", workbook.get("income"))):
            lines.update({f"{form}:{key}": row for key, row in source_line_pairs(table, form).items()})
    for form, mapping in (("form1", FORM1), ("form2", FORM2)):
        for code, key in mapping.items():
            row = lines.get(f"{form}:{code}")
            if row is not None and org == "non_financial":
                values[key] = row.get("raw_current", row.get("current"))
                (opening if form == "form1" else previous)[key] = row.get("raw_previous", row.get("previous"))
    return values, previous, opening, lines


def make_report(snapshot, issuer, lang="ru", today=None, workbook=None, period_label=None):
    today = today or date.today()
    values, previous, opening, lines = prepare_inputs(snapshot, workbook)
    resolution = snapshot.get("template_resolution") or resolve_template(issuer, snapshot.get("organization_type"), today)
    template = resolution["selected_template"]
    org = snapshot.get("organization_type")
    standard, period = snapshot.get("standard", "nsbu"), snapshot.get("period")
    period_text = period_label or period or "—"
    source = snapshot.get("source") or {}
    source_url = source.get("url")
    data_quality = [dict(item) for item in (snapshot.get("quality") or {}).get("data_quality") or []
                    if item.get("code") not in {"BALANCE_COMPONENTS_MISSING", "BALANCE_IDENTITY_FAILED", "SECTOR_TEMPLATE_MISSING"}]
    codes = block_codes(template)
    # A bank's generic catalog "operating income" is often pre-tax income.
    # It cannot enter a bank verdict without a dedicated source mapping.
    if template in {"bank", "microfinance_bank", "microfinance"}:
        values.pop("operating_income", None)
        previous.pop("operating_income", None)
    balance = balance_gate(values, snapshot.get("rounding_unit", 1))
    if balance["status"] != "passed" and values:
        data_quality.append({**balance, "message": tr(lang, "Баланс не прошёл сверку: проверьте компоненты и единицы.", "Balans tekshiruvdan o‘tmadi: tarkib va birliklarni tekshiring.", "Balance validation failed: check components and units.")})
    if resolution["resolution_status"] == "classification_conflict":
        data_quality.append({"code": "CLASSIFICATION_CONFLICT", "severity": "blocking", "message": tr(lang, "Источники классификации противоречат друг другу.", "Tasnif manbalari bir-biriga zid.", "Classification sources conflict.")})
    if (template in FINANCIAL_TYPES or org in FINANCIAL_TYPES) and template != org:
        data_quality.append({"code": "TEMPLATE_FORM_MISMATCH", "severity": "blocking",
                             "message": tr(lang, "Отраслевой шаблон не соответствует типу исходной формы.", "Tarmoq shabloni asl shakl turiga mos emas.", "The sector template does not match the source form type.")})
    if snapshot.get("scope") == "consolidated" and not snapshot.get("scope_verified"):
        data_quality.append({"code": "SCOPE_NOT_VERIFIED", "severity": "blocking", "message": tr(lang, "Консолидированный периметр не подтверждён источником.", "Konsolidatsiya doirasi manbada tasdiqlanmagan.", "Consolidated scope is not verified by the source.")})
    for key, row in lines.items():
        if row.get("conflict"):
            data_quality.append({"code": "DUPLICATE_SOURCE_LINE", "severity": "blocking", "message": key})
        for field, expected in (("period", period), ("accounting_standard", standard.upper()), ("issuer_id", issuer["id"])):
            if row.get(field) is not None and str(row[field]).upper() != str(expected).upper():
                data_quality.append({"code": "FACT_CONTEXT_MISMATCH", "severity": "blocking", "message": f"{key}: {field}"})
    # A thousandfold form discrepancy cannot be silently repaired by scaling.
    scale = ratio(abs(decimal(values.get("net_income")) or 0), values.get("total_assets"))
    declared_units = snapshot.get("form_units") or {}
    if (scale is not None and scale > 100) or len(set(declared_units.values())) > 1:
        data_quality.append({"code": "blocked_unit_mismatch", "severity": "blocking", "message": tr(lang, "Масштаб Форм №1 и №2 не сопоставим; коэффициенты скрыты.", "1- va 2-shakl masshtablari mos emas; koeffitsiyentlar yashirilgan.", "Form 1 and Form 2 scales are incompatible; ratios are withheld.")})
    if template == "investment_fund_ifrs_annual" and (standard != "ifrs" or not snapshot.get("audited")):
        data_quality.append({"code": "AUDITED_IFRS_REQUIRED", "severity": "blocking", "message": tr(lang, "Нужна аудированная годовая МСФО фонда.", "Fondning auditdan o‘tgan yillik MHXS hisoboti kerak.", "The fund requires audited annual IFRS statements.")})
    if template == "spv":
        data_quality.append({"code": "SPV_ASSET_LINK_REQUIRED", "severity": "blocking", "message": tr(lang, "Не подтверждены обеспечивающие активы и денежные потоки SPV.", "SPV ta’minot aktivlari va pul oqimlari tasdiqlanmagan.", "SPV backing assets and cash flows have not been verified.")})
    if not source_url and values:
        data_quality.append({"code": "SOURCE_NOT_VERIFIED", "severity": "blocking", "message": tr(lang, "Нет ссылки на исходный документ.", "Asl hujjat havolasi yo‘q.", "The source document link is missing.")})
    capital = capital_analysis(values, opening)
    quality = profit_quality(values, previous)
    computed_ratios = enterprise_ratios(lines, org, standard, period, methods=snapshot.get("formula_methods"))
    for item in computed_ratios:
        disclosed = decimal((snapshot.get("reported_ratios") or {}).get(item["metric"]))
        if item["unit"] == "percent" and disclosed is not None and item["raw_result"] is not None and abs(disclosed - decimal(item["raw_result"])) > Decimal("0.1"):
            data_quality.append({"code": "PERCENTAGE_RECONCILIATION_FAILED", "severity": "blocking", "message": item["metric"]})
    if capital["reconciliation_status"] == "failed":
        data_quality.append({"code": "CAPITAL_COMPONENTS_MISMATCH", "severity": "blocking", "message": tr(lang, "Изменение капитала не сходится с его компонентами.", "Kapital o‘zgarishi uning tarkibiga mos emas.", "Equity movement does not reconcile to its components.")})
    if not period or not values:
        status = "no_source"
    elif any(q.get("severity") == "blocking" for q in data_quality):
        status = "mapping_failed" if any(q.get("code") == "SOURCE_MAPPING_FAILED" for q in data_quality) else "quality_blocked"
    else:
        status = "available"
    year = int(str(period)[:4]) if period and str(period)[:4].isdigit() else today.year
    quarter = int(str(period)[-1]) if period and re.fullmatch(r"\d{4}Q[1-4]", period) else 4
    end = date(year, quarter * 3, (31, 30, 30, 31)[quarter - 1])
    if status == "available" and (today - end).days > snapshot.get("max_age_days", 550 if standard == "ifrs" else 210):
        status = "stale"
    publishable = status == "available"
    ratios = computed_ratios if publishable else []
    if template == "commodity_exchange" and any(values.get(k) is None for k in ("own_cash", "client_cash", "settlement_liabilities")):
        ratios = [r for r in ratios if r["metric"].startswith("P")]
    facts, by_code = [], {}
    mapping = {key: f"form1:{code}" for code, key in FORM1.items()}
    mapping.update({key: f"form2:{code}" for code, key in FORM2.items()})
    allowed = set(sum(codes.values(), [])) | {"fx_income", "fx_expenses", "financial_income", "financial_expenses", "short_term_investments", "retained_earnings", "share_capital", "additional_capital"}
    for key in sorted(allowed):
        value = number(values.get(key))
        if value is None:
            continue
        line = (snapshot.get("field_sources", {}).get(key) or {}).get("source_line_id") or (mapping.get(key) if mapping.get(key) in lines else f"catalog:{key}")
        line_row = lines.get(line) or {}
        raw = line_row.get("raw_current", str(values[key]))
        fact_url = line_row.get("source_url") or source_url
        fact_doc_id = "filing:" + digest([issuer["id"], standard, period, fact_url])[:24] if fact_url else source.get("document_id")
        base = opening if key in FORM1.values() or key in codes["cash_and_working_capital"] else previous
        fact = {"id": digest([issuer["id"], standard, period, key, raw, fact_doc_id])[:24],
                "issuer_id": issuer["id"], "metric": key, "metric_code": key, "label": label(key, lang),
                "raw": raw, "value_raw": raw, "value": value, "value_normalized": str(decimal(raw)),
                "unit": "thousand UZS", "unit_raw": line_row.get("unit") or source.get("unit") or "thousand UZS",
                "unit_normalized": "thousand UZS", "currency": line_row.get("currency") or source.get("currency") or snapshot.get("currency") or "UZS",
                "multiplier": number(line_row.get("multiplier") or source.get("multiplier") or snapshot.get("multiplier") or 1),
                "period": period, "period_start": snapshot.get("period_start") or f"{year}-01-01", "period_end": end.isoformat(),
                "period_kind": snapshot.get("period_basis"), "accounting_standard": standard.upper(),
                "consolidation_scope": snapshot.get("scope"), "source": {**source, "url": fact_url, "document_id": fact_doc_id}, "source_url": fact_url,
                "source_document_id": fact_doc_id, "source_line_id": line,
                "source_document_hash": source.get("document_hash") or source.get("sha256") or source.get("hash"),
                "source_published_at": source.get("published_at") or source.get("publication_date"),
                "source_received_at": source.get("received_at") or source.get("retrieved_at"),
                "source_location": {k: v for k, v in {
                    "page": line_row.get("page") or source.get("page"), "sheet": line_row.get("sheet"),
                    "row": line_row.get("row"), "cell": line_row.get("cell") or line_row.get("cell_ref")
                }.items() if v is not None},
                "source_original_line": line_row.get("label") or line_row.get("original_line"),
                "mapping_rule_version": MAPPING_VERSION, "parser_version": snapshot.get("parser_version", "catalog"),
                "verification_status": "verified" if publishable else "blocked", "confidence": "high" if source_url else "low",
                **change(value, base.get(key))}
        facts.append(fact)
        by_code[key] = fact
    verified = facts if publishable else []
    calculation_inputs = []
    narrative_lines = {fact["source_line_id"] for fact in verified}
    for line in sorted({line for result in ratios for line in result["component_facts"]} - narrative_lines):
        row = lines.get(line) or {}
        raw = row.get("raw_current")
        if raw is None:
            continue
        fact_url = row.get("source_url") or source_url
        calculation_inputs.append({"id": digest([issuer["id"], standard, period, line, raw, fact_url])[:24],
                "metric_code": line, "label": row.get("label") or line, "value_raw": raw, "value": number(raw),
                "unit": "thousand UZS", "period": period, "period_end": end.isoformat(), "source_url": fact_url,
                "source_document_id": "filing:" + digest([issuer["id"], standard, period, fact_url])[:24], "source_line_id": line,
                "source_location": {k: row[k] for k in ("sheet", "row") if row.get(k) is not None},
                "parser_version": snapshot.get("parser_version", "catalog"), "mapping_rule_version": row.get("mapping_rule", MAPPING_VERSION),
                "verification_status": "verified" if publishable else "blocked"})
    blocks = {key: [{"metric_code": code, "label": label(code, lang), **(by_code.get(code) or {"value": None, "previous": None, "change_value": None, "change_pct": None})} for code in columns] if publishable else [] for key, columns in codes.items()}
    signals = []

    def signal(code, keys, direction, actual, prior=None, threshold=0, category="financial"):
        evidence = [by_code[k] for k in keys if k in by_code]
        if not publishable or len(evidence) != len(keys) or any(not f.get("source_url") for f in evidence):
            return
        signals.append({"id": digest([code, [f["id"] for f in evidence]])[:24], "code": code,
                        "issuer_id": issuer["id"], "sector_template_code": template, "metric_code": keys[0],
                        "signal_type": code, "direction": direction, "category": category,
                        "value_current": actual, "value_previous": prior, "change_value": number(difference(actual, prior)),
                        "threshold": threshold, "comparison_change_pct": change(actual, prior)["change_pct"],
                        "period_current": period, "period_previous": snapshot.get("previous_comparable_period"),
                        "materiality": "high" if code in {"net_loss", "net_income_decline", "profit_quality"} else "medium",
                        "evidence_fact_ids": [f["id"] for f in evidence], "source_url": source_url,
                        "verification_status": "verified"})

    for code in ("revenue", "net_income", "operating_income"):
        movement = change(values.get(code), previous.get(code))
        pct = movement["change_pct"]
        if pct is not None and pct > 3 and not movement["base_effect"]:
            signal(f"{code}_growth", [code], "positive", movement["current"], movement["previous"], 3)
        elif pct is not None and pct <= -20:
            signal(f"{code}_decline", [code], "negative", movement["current"], movement["previous"], -20)
        elif code == "operating_income" and pct is not None and pct < -3:
            signal("operating_income_decline", [code], "negative", movement["current"], movement["previous"], -3)
    if decimal(values.get("net_income")) is not None and decimal(values["net_income"]) < 0:
        signal("net_loss", ["net_income"], "negative", number(values["net_income"]), number(previous.get("net_income")))
    if decimal(values.get("operating_income")) is not None and decimal(values["operating_income"]) < 0:
        signal("negative_operating_result", ["operating_income"], "negative", number(values["operating_income"]), number(previous.get("operating_income")))
    if quality["driver"] != "unknown":
        keys = ["unrealized_fair_value_gain", "net_income"] if quality["driver"] == "unrealized_revaluation" else ["fx_income", "fx_expenses", "net_income"]
        signal("profit_quality", keys, "negative", number(values.get(keys[0])), threshold="share_of_profit_growth >= 50%")
    if template == "investment_fund_ifrs_annual" and (decimal(values.get("dividend_income")) or 0) > 0:
        signal("dividend_income_positive", ["dividend_income"], "positive", number(values["dividend_income"]))
    for asset in ("receivables", "inventories"):
        growth, sales = change(values.get(asset), opening.get(asset)), change(values.get("revenue"), previous.get("revenue"))
        if growth["change_pct"] is not None and sales["change_pct"] is not None and growth["change_pct"] > max(20, sales["change_pct"] + 10):
            signal(f"{asset}_outpace_revenue", [asset, "revenue"], "negative", growth["current"], growth["previous"], "growth exceeds revenue by 10pp")
    debt_growth = change(values.get("total_liabilities"), opening.get("total_liabilities"))
    equity_growth = change(values.get("total_equity"), opening.get("total_equity"))
    if debt_growth["change_pct"] is not None and equity_growth["change_pct"] is not None and debt_growth["change_pct"] > max(3, equity_growth["change_pct"] + 3):
        signal("liabilities_outpace_equity", ["total_liabilities", "total_equity"], "negative", debt_growth["current"], debt_growth["previous"], "growth exceeds equity by 3pp")
    if equity_growth["change_pct"] is not None and equity_growth["change_pct"] > 3:
        signal("equity_growth", ["total_equity"], "positive", equity_growth["current"], equity_growth["previous"], 3)
    claims, premiums = change(values.get("insurance_claims"), previous.get("insurance_claims")), change(values.get("insurance_premiums"), previous.get("insurance_premiums"))
    if claims["change_pct"] is not None and premiums["change_pct"] is not None and claims["change_pct"] > premiums["change_pct"] + 10:
        signal("claims_outpace_premiums", ["insurance_claims", "insurance_premiums"], "negative", claims["current"], claims["previous"], "growth exceeds premiums by 10pp")
    negatives = [s for s in signals if s["direction"] == "negative"]
    positives = [s for s in signals if s["direction"] == "positive"]
    verdict_status = "no_signal" if len(signals) < 2 or template == "generic_nsbu" else "mixed" if positives and negatives else "negative" if negatives else "positive"
    if quality["net_profit_change"]["base_effect"] and verdict_status == "positive":
        verdict_status = "mixed"
    verdict_label = {"positive": tr(lang, "Финансовая динамика положительная", "Moliyaviy dinamika ijobiy", "Financial trends are positive"),
                     "negative": tr(lang, "Финансовая динамика отрицательная", "Moliyaviy dinamika salbiy", "Financial trends are negative"),
                     "mixed": tr(lang, "Картина смешанная", "Natijalar aralash", "Financial trends are mixed"),
                     "no_signal": tr(lang, "Недостаточно сопоставимых данных для вердикта", "Xulosa uchun taqqoslanadigan ma’lumotlar yetarli emas", "Insufficient comparable data for a verdict")}[verdict_status]
    display_divisor = decimal(snapshot.get("display_divisor")) or Decimal(1)
    money_unit = tr(lang, "млн сум", "mln so‘m", "million UZS") if display_divisor == 1000 else tr(lang, "тыс. сум", "ming so‘m", "thousand UZS")
    display_money = lambda value: format_number(decimal(value) / display_divisor) if decimal(value) is not None else "—"

    def fact_sentence(key, comparison=True):
        fact = by_code.get(key)
        if not fact:
            return None
        text = f"{label(key, lang)}: {display_money(fact['value'])} {money_unit}"
        if comparison and fact["previous"] is not None:
            text = f"{label(key, lang)}: {display_money(fact['previous'])} → {display_money(fact['value'])} {money_unit}"
            if fact["change_pct"] is not None:
                text += f" ({format_number(fact['change_pct'])}%)"
        return text

    def bank_analysis_paragraphs():
        """Build an explanatory bank narrative from verified totals only.

        The sector report is deterministic: ratios are calculated here and the
        prose never attributes a movement to an undisclosed business line.
        """
        value = lambda key: decimal((by_code.get(key) or {}).get("value"))
        pct = lambda numerator, denominator: ratio(numerator, denominator, True)
        money = lambda key: f"{display_money(value(key))} {money_unit}" if value(key) is not None else None
        pct_text = lambda item: f"{format_number(item)}%" if item is not None else None

        interest_income = value("interest_income")
        noninterest_income = value("noninterest_income")
        interest_expenses = value("interest_expenses")
        noninterest_expenses = value("noninterest_expenses")
        operating_expenses = value("operating_expenses")
        profit_before_tax = value("profit_before_tax")
        net_income = value("net_income")
        disclosed_tax = value("tax")
        total_income = total(interest_income, noninterest_income)
        total_expenses = total(interest_expenses, noninterest_expenses, operating_expenses)
        tax_amount = disclosed_tax
        if tax_amount is None and profit_before_tax is not None and net_income is not None:
            tax_amount = profit_before_tax - net_income

        intro = f"{headline} " + tr(
            lang,
            "Ниже результат разобран по структуре доходов, стоимости фондирования, расходам и итоговой прибыли. Все доли рассчитаны только по раскрытым сопоставимым строкам отчёта; отсутствующая детализация не заменяется предположениями.",
            "Quyida natija daromadlar tarkibi, moliyalashtirish qiymati, xarajatlar va yakuniy foyda bo‘yicha tahlil qilinadi. Barcha ulushlar faqat hisobotdagi taqqoslanadigan satrlardan hisoblangan; yetishmagan tafsilotlar taxmin bilan almashtirilmagan.",
            "The result is analysed through income mix, funding cost, expenses and final profit. Every share uses only comparable disclosed lines; missing detail is not replaced with assumptions.",
        )

        if total_income is not None and total_income > 0 and interest_income >= 0 and noninterest_income >= 0:
            interest_share = pct(interest_income, total_income)
            noninterest_share = pct(noninterest_income, total_income)
            income_text = tr(
                lang,
                f"Совокупные раскрытые доходы банка за {period_text} составили {display_money(total_income)} {money_unit}: процентные доходы — {money('interest_income')} ({pct_text(interest_share)}), непроцентные — {money('noninterest_income')} ({pct_text(noninterest_share)}). Такая структура показывает, какая часть доходной базы зависит от кредитных и иных процентных инструментов, а какая формируется комиссиями, валютными и прочими операциями. Детализацию внутри этих двух групп отчёт не раскрывает, поэтому конкретный источник роста без примечаний определить нельзя.",
                f"Bankning {period_text} uchun jami oshkor qilingan daromadi {display_money(total_income)} {money_unit}: foizli daromad — {money('interest_income')} ({pct_text(interest_share)}), foizsiz daromad — {money('noninterest_income')} ({pct_text(noninterest_share)}). Tuzilma daromad bazasining foizli vositalar va boshqa operatsiyalarga bog‘liqligini ko‘rsatadi. Guruhlar ichidagi tafsilotlar oshkor qilinmagan bo‘lsa, o‘sishning aniq manbasini izohlarsiz aniqlab bo‘lmaydi.",
                f"The bank reported total disclosed income of {display_money(total_income)} {money_unit} for {period_text}: interest income was {money('interest_income')} ({pct_text(interest_share)}) and non-interest income was {money('noninterest_income')} ({pct_text(noninterest_share)}). This mix shows reliance on interest-bearing activity versus fees, FX and other operations. Without line-item notes, the precise growth driver cannot be identified.",
            )
        else:
            available_income = "; ".join(filter(None, (fact_sentence("interest_income"), fact_sentence("noninterest_income"))))
            income_text = tr(lang, "Структура доходов. ", "Daromadlar tarkibi. ", "Income mix. ") + (available_income or tr(lang, "Недостаточно данных для расчёта.", "Hisoblash uchun ma’lumot yetarli emas.", "Insufficient data to calculate it."))

        expense_parts = []
        funding_ratio = pct(interest_expenses, interest_income)
        if interest_expenses is not None:
            expense_parts.append(tr(lang, f"процентные расходы — {money('interest_expenses')}", f"foizli xarajatlar — {money('interest_expenses')}", f"interest expense was {money('interest_expenses')}"))
        if funding_ratio is not None:
            expense_parts.append(tr(
                lang,
                f"они равны {pct_text(funding_ratio)} процентных доходов: на каждый 1 сум процентного дохода приходится около {format_number(funding_ratio)} тийина процентных расходов",
                f"bu foizli daromadning {pct_text(funding_ratio)}iga teng: har 1 so‘m foizli daromadga taxminan {format_number(funding_ratio)} tiyin foizli xarajat to‘g‘ri keladi",
                f"that equals {pct_text(funding_ratio)} of interest income, or about {format_number(funding_ratio)} tiyin of interest expense per UZS 1 of interest income",
            ))
        if operating_expenses is not None:
            op_share = pct(operating_expenses, total_income)
            suffix = f" ({pct_text(op_share)} совокупных раскрытых доходов)" if lang == "ru" and op_share is not None else f" ({pct_text(op_share)} of total disclosed income)" if lang == "en" and op_share is not None else f" (jami oshkor qilingan daromadning {pct_text(op_share)})" if op_share is not None else ""
            expense_parts.append(tr(lang, f"операционные расходы — {money('operating_expenses')}{suffix}", f"operatsion xarajatlar — {money('operating_expenses')}{suffix}", f"operating expenses were {money('operating_expenses')}{suffix}"))
        if noninterest_expenses is not None:
            expense_parts.append(tr(lang, f"непроцентные расходы — {money('noninterest_expenses')}", f"foizsiz xarajatlar — {money('noninterest_expenses')}", f"non-interest expenses were {money('noninterest_expenses')}"))
        expense_text = tr(lang, "Расходы и стоимость ресурсов. ", "Xarajatlar va resurslar qiymati. ", "Expenses and funding cost. ") + ("; ".join(expense_parts) if expense_parts else tr(lang, "Недостаточно раскрытых данных для расчёта структуры расходов.", "Xarajatlar tarkibini hisoblash uchun ma’lumot yetarli emas.", "Insufficient disclosed data to calculate the expense mix.")) + "."

        profit_parts = []
        if net_income is not None:
            net_fact = by_code["net_income"]
            movement = net_fact.get("change_pct")
            profit_parts.append(tr(lang, f"Чистая прибыль составила {money('net_income')}", f"Sof foyda {money('net_income')}ni tashkil etdi", f"Net profit was {money('net_income')}"))
            if movement is not None:
                profit_parts.append(tr(lang, f"изменение к сопоставимому периоду — {format_number(movement)}%", f"taqqoslanadigan davrga nisbatan o‘zgarish — {format_number(movement)}%", f"the change from the comparable period was {format_number(movement)}%"))
        effective_tax = pct(tax_amount, profit_before_tax)
        if profit_before_tax is not None:
            profit_parts.append(tr(lang, f"прибыль до налога — {money('profit_before_tax')}", f"soliqdan oldingi foyda — {money('profit_before_tax')}", f"profit before tax was {money('profit_before_tax')}"))
        if tax_amount is not None:
            tax_source = tr(lang, "раскрытый налог", "oshkor qilingan soliq", "disclosed tax") if disclosed_tax is not None else tr(lang, "расчётная разница между прибылью до и после налога", "soliqdan oldingi va keyingi foyda o‘rtasidagi hisoblangan farq", "the calculated difference between pre- and post-tax profit")
            effective_tax_text = pct_text(effective_tax) or tr(lang, "не рассчитывается", "hisoblanmaydi", "not calculable")
            profit_parts.append(tr(lang, f"налоговый расход — {display_money(tax_amount)} {money_unit}, эффективная ставка — {effective_tax_text} ({tax_source})", f"soliq xarajati — {display_money(tax_amount)} {money_unit}, samarali stavka — {effective_tax_text} ({tax_source})", f"tax expense was {display_money(tax_amount)} {money_unit}, giving an effective rate of {effective_tax_text} ({tax_source})"))
        profit_text = tr(lang, "Прибыль и налог. ", "Foyda va soliq. ", "Profit and tax. ") + ("; ".join(profit_parts) if profit_parts else tr(lang, "Недостаточно данных.", "Ma’lumot yetarli emas.", "Insufficient data.")) + ". " + tr(
            lang,
            "Отклонение эффективной ставки от законодательной само по себе не доказывает наличие льгот: для вывода нужны налоговые примечания.",
            "Samarali stavkaning qonuniy stavkadan farqi imtiyoz mavjudligini o‘z-o‘zidan isbotlamaydi: xulosa uchun soliq izohlari kerak.",
            "A difference from the statutory rate does not by itself prove tax relief; tax notes are needed for that conclusion.",
        )

        balance_facts = [fact_sentence(key) for key in ("loan_portfolio", "customer_funds", "cash", "total_assets", "total_equity")]
        balance_facts = [item for item in balance_facts if item]
        watch = " ".join(
            f"{point['label']} — {display_money(point['current_baseline']['value'])} {money_unit}: {point['risk_signal']}; {point['required_disclosure']}."
            for point in monitoring_points
        )
        balance_text = tr(lang, "Баланс, устойчивость и следующий контроль. ", "Balans, barqarorlik va keyingi nazorat. ", "Balance, resilience and next checks. ") + ("; ".join(balance_facts[:4]) + ". " if balance_facts else "") + (watch or tr(lang, "Для следующего отчёта контрольные показатели не сформированы из-за недостатка данных.", "Keyingi hisobot uchun nazorat ko‘rsatkichlari ma’lumot yetishmasligi sababli shakllantirilmadi.", "No monitoring metrics were formed because the data is insufficient."))
        if total_expenses is None:
            balance_text += " " + tr(lang, "Полная сумма расходов не рассчитана, поскольку не все необходимые строки раскрыты.", "Barcha zarur satrlar oshkor qilinmagani uchun jami xarajatlar hisoblanmadi.", "Total expenses were not calculated because not all required lines were disclosed.")
        return [intro, income_text, expense_text, profit_text, balance_text]

    def general_analysis_paragraphs():
        """Detailed non-bank narrative using only traceable statement totals."""
        value = lambda key: decimal((by_code.get(key) or {}).get("value"))
        pct = lambda numerator, denominator: ratio(numerator, denominator, True)
        money = lambda key: f"{display_money(value(key))} {money_unit}" if value(key) is not None else None
        pct_text = lambda item: f"{format_number(item)}%" if item is not None else None

        revenue = value("revenue") or value("insurance_premiums") or value("operating_income")
        revenue_key = "revenue" if value("revenue") is not None else "insurance_premiums" if value("insurance_premiums") is not None else "operating_income"
        cost = value("cost_of_sales") or value("insurance_claims")
        gross = value("gross_profit")
        period_expenses = value("period_expenses") or value("expenses") or value("management_expenses")
        operating_income = value("operating_income")
        profit_before_tax = value("profit_before_tax")
        net_income = value("net_income")
        disclosed_tax = value("tax")
        tax_amount = disclosed_tax
        if tax_amount is None and profit_before_tax is not None and net_income is not None:
            tax_amount = profit_before_tax - net_income

        intro = f"{headline} " + tr(
            lang,
            "Ниже результат разобран по доходам, расходам, рентабельности и структуре баланса. Расчёты используют только проверенные строки отчётности; возможные причины изменения не выдаются за факт без примечаний эмитента.",
            "Quyida natija daromadlar, xarajatlar, rentabellik va balans tarkibi bo‘yicha tahlil qilinadi. Hisob-kitoblar faqat tekshirilgan hisobot satrlariga asoslanadi; emitent izohisiz ehtimoliy sabablar fakt sifatida berilmaydi.",
            "The result is analysed through income, expenses, profitability and balance-sheet structure. Calculations use only verified statement lines; possible causes are not presented as fact without issuer notes.",
        )

        income_parts = [fact_sentence(revenue_key)] if revenue_key in by_code else []
        if cost is not None:
            cost_key = "cost_of_sales" if value("cost_of_sales") is not None else "insurance_claims"
            cost_share = pct(cost, revenue)
            income_parts.append(f"{label(cost_key, lang)}: {money(cost_key)}" + (f" ({pct_text(cost_share)} {tr(lang, 'доходов', 'daromadga nisbatan', 'of income')})" if cost_share is not None else ""))
        if gross is not None:
            income_parts.append(f"{label('gross_profit', lang)}: {money('gross_profit')}" + (f" ({tr(lang, 'маржа', 'marja', 'margin')} {pct_text(pct(gross, revenue))})" if pct(gross, revenue) is not None else ""))
        income_text = tr(lang, "Доходы и прямые затраты. ", "Daromadlar va bevosita xarajatlar. ", "Income and direct costs. ") + ("; ".join(filter(None, income_parts)) if income_parts else tr(lang, "Недостаточно данных для расчёта структуры.", "Tarkibni hisoblash uchun ma’lumot yetarli emas.", "Insufficient data to calculate the structure.")) + ". " + tr(
            lang,
            "Соотношение показывает, какая часть дохода остаётся после прямых затрат; детализация драйверов требует примечаний к отчётности.",
            "Bu nisbat bevosita xarajatlardan keyin daromadning qancha qismi qolishini ko‘rsatadi; omillar tafsiloti hisobot izohlarini talab qiladi.",
            "The relationship shows how much income remains after direct costs; identifying the drivers requires statement notes.",
        )

        expense_parts = []
        if period_expenses is not None:
            expense_key = "period_expenses" if value("period_expenses") is not None else "expenses" if value("expenses") is not None else "management_expenses"
            expense_parts.append(f"{label(expense_key, lang)}: {money(expense_key)}" + (f" ({pct_text(pct(period_expenses, revenue))} {tr(lang, 'доходов', 'daromadga nisbatan', 'of income')})" if pct(period_expenses, revenue) is not None else ""))
        for key in ("financial_income", "financial_expenses", "interest_expenses"):
            if value(key) is not None:
                expense_parts.append(f"{label(key, lang)}: {money(key)}")
        if operating_income is not None:
            expense_parts.append(f"{label('operating_income', lang)}: {money('operating_income')}" + (f" ({tr(lang, 'операционная маржа', 'operatsion marja', 'operating margin')} {pct_text(pct(operating_income, revenue))})" if pct(operating_income, revenue) is not None else ""))
        expense_text = tr(lang, "Операционные и финансовые расходы. ", "Operatsion va moliyaviy xarajatlar. ", "Operating and finance costs. ") + ("; ".join(expense_parts) if expense_parts else tr(lang, "Недостаточно раскрытых данных.", "Oshkor qilingan ma’lumot yetarli emas.", "Insufficient disclosed data.")) + "."

        profit_parts = []
        if net_income is not None:
            profit_parts.append(f"{label('net_income', lang)}: {money('net_income')}" + (f" ({tr(lang, 'чистая маржа', 'sof marja', 'net margin')} {pct_text(pct(net_income, revenue))})" if pct(net_income, revenue) is not None else ""))
            movement = (by_code.get("net_income") or {}).get("change_pct")
            if movement is not None:
                profit_parts.append(tr(lang, f"изменение к сопоставимому периоду — {format_number(movement)}%", f"taqqoslanadigan davrga nisbatan o‘zgarish — {format_number(movement)}%", f"change from the comparable period — {format_number(movement)}%"))
        if profit_before_tax is not None:
            profit_parts.append(f"{label('profit_before_tax', lang)}: {money('profit_before_tax')}")
        effective_tax = pct(tax_amount, profit_before_tax)
        if tax_amount is not None:
            tax_basis = tr(lang, "раскрытая строка", "oshkor qilingan satr", "disclosed line") if disclosed_tax is not None else tr(lang, "расчётная разница до/после налога", "soliqdan oldingi/keyingi hisoblangan farq", "calculated pre/post-tax difference")
            profit_parts.append(tr(lang, f"налог — {display_money(tax_amount)} {money_unit}, эффективная ставка — {pct_text(effective_tax) or 'не рассчитывается'} ({tax_basis})", f"soliq — {display_money(tax_amount)} {money_unit}, samarali stavka — {pct_text(effective_tax) or 'hisoblanmaydi'} ({tax_basis})", f"tax — {display_money(tax_amount)} {money_unit}, effective rate — {pct_text(effective_tax) or 'not calculable'} ({tax_basis})"))
        profit_text = tr(lang, "Итоговая прибыль и налог. ", "Yakuniy foyda va soliq. ", "Final profit and tax. ") + ("; ".join(profit_parts) if profit_parts else tr(lang, "Недостаточно данных.", "Ma’lumot yetarli emas.", "Insufficient data.")) + "."

        asset_parts = [fact_sentence(key) for key in ("total_assets", "cash", "receivables", "inventories", "fixed_assets", "long_term_investments")]
        asset_parts = [item for item in asset_parts if item]
        asset_text = tr(lang, "Активы и оборотный капитал. ", "Aktivlar va aylanma kapital. ", "Assets and working capital. ") + ("; ".join(asset_parts[:5]) if asset_parts else tr(lang, "Недостаточно данных.", "Ma’lumot yetarli emas.", "Insufficient data.")) + ". " + tr(lang, "Рост доходов следует оценивать вместе с движением денег, дебиторской задолженности и запасов.", "Daromad o‘sishini pul, debitorlik va zaxiralar harakati bilan birga baholash kerak.", "Income growth should be assessed alongside cash, receivables and inventory movements.")

        funding_parts = [fact_sentence(key) for key in ("total_liabilities", "total_equity", "current_liabilities")]
        funding_parts = [item for item in funding_parts if item]
        debt_share = pct(value("total_liabilities"), value("total_assets"))
        if debt_share is not None:
            funding_parts.append(tr(lang, f"обязательства составляют {pct_text(debt_share)} активов", f"majburiyatlar aktivlarning {pct_text(debt_share)}ini tashkil etadi", f"liabilities equal {pct_text(debt_share)} of assets"))
        watch = " ".join(f"{point['label']} — {display_money(point['current_baseline']['value'])} {money_unit}; требуется следующая сопоставимая форма и объяснение изменения." for point in monitoring_points)
        funding_text = tr(lang, "Капитал, обязательства и следующий контроль. ", "Kapital, majburiyatlar va keyingi nazorat. ", "Capital, liabilities and next checks. ") + ("; ".join(funding_parts) if funding_parts else tr(lang, "Недостаточно данных о структуре финансирования.", "Moliyalashtirish tarkibi haqida ma’lumot yetarli emas.", "Insufficient funding-structure data.")) + ". " + watch
        return [intro, income_text, expense_text, profit_text, asset_text, funding_text]

    headline_facts = [fact_sentence("net_income"), fact_sentence("operating_income")]
    if quality["driver"] == "FX-driven":
        headline_facts.append(tr(lang, "Драйвер — курсовые разницы", "Asosiy omil — kurs farqlari", "Driven by foreign-exchange movements") + f": Δ {format_number(quality['net_fx_result_change'])} {money_unit}")
    elif quality["driver"] == "unrealized_revaluation":
        headline_facts.append(tr(lang, "Прибыль преимущественно от нереализованной переоценки", "Foyda asosan realizatsiya qilinmagan qayta baholashdan", "Profit is predominantly unrealized revaluation"))
    if quality["net_profit_change"]["base_effect"]:
        headline_facts.append(tr(lang, "Эффект низкой базы / смены знака", "Past baza / ishora o‘zgarishi ta’siri", "Low-base / sign-change effect"))
    headline = f"{issuer['ticker']} · {period_text}. {verdict_label}. " + "; ".join(f for f in headline_facts if f) + "."
    unavailable = {
        "no_source": tr(lang, "Анализ временно недоступен: подходящая отчётность НСБУ не найдена.", "Tahlil mavjud emas: mos hisobot topilmadi.", "Analysis unavailable: no suitable filing was found."),
        "quality_blocked": tr(lang, "Анализ временно недоступен: данные не прошли автоматическую сверку.", "Tahlil mavjud emas: ma’lumotlar tekshiruvdan o‘tmadi.", "Analysis unavailable: the data failed automated validation."),
        "mapping_failed": tr(lang, "Отчёт пока готовится.", "Hisobot hozir tayyorlanmoqda.", "The report is being prepared."),
        "stale": tr(lang, "Доступен только старый отчёт", "Faqat eski hisobot mavjud", "Only an old filing is available") + f": {period_text}.",
    }
    if not publishable:
        headline, verdict_status = unavailable.get(status, unavailable["quality_blocked"]), "no_signal"
    headline_words = headline.split()
    if len(headline_words) > 40:
        headline = " ".join(headline_words[:40]).rstrip(" ,;:") + "…"
    issues, risks = make_issues(negatives, by_code, quality, verdict_status, lang, period)
    watch_candidates = {
        "bank": ("net_income", "loan_portfolio", "customer_funds", "total_equity"),
        "microfinance_bank": ("net_income", "loan_portfolio", "customer_funds", "total_equity"),
        "microfinance": ("net_income", "loan_portfolio", "total_liabilities", "cash"),
        "insurance": ("operating_income", "net_income", "net_insurance_reserves", "insurance_claims"),
        "investment_fund_ifrs_annual": ("dividend_income", "unrealized_fair_value_gain", "cash", "management_expenses"),
        "commodity_exchange": ("operating_income", "own_cash", "client_cash", "settlement_liabilities"),
    }.get(template, ("operating_income", "net_income", "cash", "total_liabilities", "revenue"))
    monitoring_points = []
    for key in watch_candidates:
        fact = by_code.get(key)
        if not fact or len(monitoring_points) >= 2:
            continue
        comparison = fact.get("previous")
        monitoring_points.append({
            "id": digest([issuer["id"], period, "watch", key])[:24],
            "metric_code": key, "label": fact["label"], "period": period,
            "current_baseline": {"value": fact["value"], "unit": fact["unit"], "period": period},
            "comparison_baseline": ({"value": comparison, "unit": fact["unit"],
                                     "period": snapshot.get("previous_comparable_period")} if comparison is not None else None),
            "improvement_signal": tr(
                lang,
                "сопоставимая динамика улучшается без смены стандарта, состава и базы",
                "standart, tarkib va baza o‘zgarmasdan taqqoslanadigan dinamika yaxshilanadi",
                "the comparable movement improves without changing standard, scope or basis",
            ),
            "risk_signal": tr(
                lang,
                "сопоставимая динамика ухудшается, меняет знак или теряет проверяемую базу",
                "taqqoslanadigan dinamika yomonlashadi, ishorani o‘zgartiradi yoki tekshiriladigan bazani yo‘qotadi",
                "the comparable movement deteriorates, changes sign or loses its verifiable basis",
            ),
            "required_disclosure": tr(
                lang,
                "следующая сопоставимая форма и примечание о причинах изменения",
                "keyingi taqqoslanadigan shakl va o‘zgarish sababi haqidagi izoh",
                "the next comparable filing and a disclosure explaining the movement",
            ),
            "evidence_fact_ids": [fact["id"]], "source_url": fact.get("source_url"),
        })

    series = snapshot.get("comparable_series") or []
    if isinstance(series, dict):
        series = series.get("net_income") or series.get("revenue") or []
    if not series:
        trend_key = "net_income" if values.get("net_income") is not None else "revenue"
        series = []
        if previous.get(trend_key) is not None:
            series.append({"period": snapshot.get("previous_comparable_period") or "previous",
                           "value": number(previous[trend_key]), "period_basis": snapshot.get("period_basis"),
                           "accounting_standard": standard, "consolidation_scope": snapshot.get("scope")})
        if values.get(trend_key) is not None:
            series.append({"period": period, "value": number(values[trend_key]),
                           "period_basis": snapshot.get("period_basis"), "accounting_standard": standard,
                           "consolidation_scope": snapshot.get("scope")})
    trend = trend_state(series)

    key_metrics = ("revenue", "net_income", "total_assets", "total_liabilities", "total_equity", "cash")
    missing_metrics = [label(key, lang) for key in key_metrics if values.get(key) is None]
    checked = []
    if source_url:
        checked.append(tr(lang, "исходный документ и период", "asl hujjat va davr", "source document and period"))
    if balance.get("status") == "passed":
        checked.append(tr(lang, "равенство активов, капитала и обязательств", "aktivlar, kapital va majburiyatlar tengligi", "assets, equity and liabilities identity"))
    if previous:
        checked.append(tr(lang, "сопоставимая база изменения", "o‘zgarishning taqqoslanadigan bazasi", "comparable movement basis"))
    if ratios:
        checked.append(tr(lang, "формулы и входы применимых коэффициентов", "qo‘llanadigan koeffitsiyent formulalari va kirishlari", "formulas and inputs for applicable ratios"))
    cannot_assess = []
    if values.get("cfo") is None:
        cannot_assess.append(tr(
            lang,
            "качество прибыли и свободный денежный поток без данных об операционном денежном потоке и капитальных вложениях",
            "operatsion pul oqimi va kapital qo‘yilmalar ma’lumotlarisiz foyda sifati hamda erkin pul oqimi",
            "earnings quality and free cash flow without operating-cash-flow and capital-investment inputs",
        ))
    if template in {"bank", "microfinance_bank", "microfinance"}:
        cannot_assess.append(tr(lang, "регуляторные нормативы без раскрытых компонентов и методики", "oshkor qilingan qismlar va metodikasiz regulyativ me’yorlar", "regulatory ratios without disclosed components and methodology"))
    elif values.get("interest_expenses") is None:
        cannot_assess.append(tr(lang, "покрытие долга без графика платежей и процентных расходов", "to‘lov jadvali va foiz xarajatlarisiz qarz qoplamasi", "debt-service coverage without a payment schedule and interest expense"))
    verification_summary = {
        "checked": checked,
        "missing": missing_metrics,
        "cannot_assess": cannot_assess,
    }

    complete_content = publishable and len(verified) >= 7
    bank_without_income_comparison = template == "bank" and not any(
        previous.get(key) is not None for key in ("net_income", "profit_before_tax", "interest_income")
    )
    paragraphs = []
    if complete_content and template in {"bank", "microfinance_bank", "microfinance"}:
        paragraphs = bank_analysis_paragraphs()
    elif complete_content:
        paragraphs = general_analysis_paragraphs()
    elif publishable:
        paragraphs = [headline]
        for group in ("financial_result", "cash_and_working_capital", "investment_base"):
            sentences = [fact_sentence(key) for key in codes[group]]
            if any(sentences):
                paragraphs.append("; ".join(item for item in sentences if item) + ".")
        paragraphs.append(tr(lang, "Отчёт сокращён: подтверждённых фактов недостаточно; пропуски не заменены нулями или предположениями.", "Hisobot qisqartirilgan: tasdiqlangan faktlar yetarli emas; bo‘sh qiymatlar nol yoki taxmin bilan almashtirilmagan.", "The report is shortened because too few facts are verified; gaps were not replaced by zero or assumptions."))
    else:
        paragraphs = [headline]
    text = "\n\n".join(paragraphs)

    section_titles = {
        "ru": [
            ("methodology", "Общие сведения и методология"),
            ("financial_results", "Анализ финансовых результатов"),
            ("balance_sheet", "Горизонтальный и вертикальный анализ баланса"),
            ("risks", "Риски и ограничения"),
            ("conclusion", "Итоговая оценка"),
        ],
        "uz": [
            ("methodology", "Umumiy ma’lumot va metodologiya"),
            ("financial_results", "Moliyaviy natijalar tahlili"),
            ("balance_sheet", "Balansning gorizontal va vertikal tahlili"),
            ("risks", "Xavflar va cheklovlar"),
            ("conclusion", "Yakuniy baho"),
        ],
        "en": [
            ("methodology", "Issuer overview and methodology"),
            ("financial_results", "Financial results analysis"),
            ("balance_sheet", "Horizontal and vertical balance analysis"),
            ("risks", "Risks and limitations"),
            ("conclusion", "Final assessment"),
        ],
    }
    outline = section_titles.get(lang, section_titles["ru"])
    if publishable and complete_content and template in {"bank", "microfinance_bank", "microfinance"}:
        bank_section_titles = {
            "ru": [
                ("methodology", "Итог и методология"),
                ("income_structure", "Структура доходов"),
                ("expense_structure", "Расходы и стоимость ресурсов"),
                ("profit_and_tax", "Прибыль и налог"),
                ("balance_and_monitoring", "Баланс и следующий контроль"),
            ],
            "uz": [
                ("methodology", "Natija va metodologiya"),
                ("income_structure", "Daromadlar tarkibi"),
                ("expense_structure", "Xarajatlar va resurslar qiymati"),
                ("profit_and_tax", "Foyda va soliq"),
                ("balance_and_monitoring", "Balans va keyingi nazorat"),
            ],
            "en": [
                ("methodology", "Result and methodology"),
                ("income_structure", "Income mix"),
                ("expense_structure", "Expenses and funding cost"),
                ("profit_and_tax", "Profit and tax"),
                ("balance_and_monitoring", "Balance and next checks"),
            ],
        }
        outline = bank_section_titles.get(lang, bank_section_titles["ru"])
    elif publishable and complete_content:
        general_section_titles = {
            "ru": [
                ("methodology", "Итог и методология"),
                ("income_structure", "Доходы и прямые затраты"),
                ("expense_structure", "Операционные и финансовые расходы"),
                ("profit_and_tax", "Итоговая прибыль и налог"),
                ("assets_and_working_capital", "Активы и оборотный капитал"),
                ("capital_and_monitoring", "Капитал и следующий контроль"),
            ],
            "uz": [
                ("methodology", "Natija va metodologiya"),
                ("income_structure", "Daromadlar va bevosita xarajatlar"),
                ("expense_structure", "Operatsion va moliyaviy xarajatlar"),
                ("profit_and_tax", "Yakuniy foyda va soliq"),
                ("assets_and_working_capital", "Aktivlar va aylanma kapital"),
                ("capital_and_monitoring", "Kapital va keyingi nazorat"),
            ],
            "en": [
                ("methodology", "Result and methodology"),
                ("income_structure", "Income and direct costs"),
                ("expense_structure", "Operating and finance costs"),
                ("profit_and_tax", "Final profit and tax"),
                ("assets_and_working_capital", "Assets and working capital"),
                ("capital_and_monitoring", "Capital and next checks"),
            ],
        }
        outline = general_section_titles.get(lang, general_section_titles["ru"])
    report_sections = [
        {"id": section_id, "number": f"{index:02d}", "title": title, "text": paragraphs[index - 1]}
        for index, (section_id, title) in enumerate(outline, 1)
        if index <= len(paragraphs)
    ] if publishable else []

    card_text = None
    if publishable:
        brief_labels = {
            "revenue": tr(lang, "выручка", "tushum", "revenue"),
            "operating_income": tr(lang, "операционная прибыль", "operatsion foyda", "operating profit"),
            "net_income": tr(lang, "чистая прибыль", "sof foyda", "net profit"),
        }
        brief_facts = []
        brief_directions = []
        for code in ("revenue", "operating_income", "net_income"):
            fact = by_code.get(code)
            if not fact or fact.get("change_pct") is None:
                continue
            if lang == "ru":
                direction = "выросла" if fact["change_pct"] >= 0 else "снизилась"
            else:
                direction = tr(lang, "", "o‘sdi", "rose") if fact["change_pct"] >= 0 else tr(lang, "", "pasaydi", "fell")
            connector = "by " if lang == "en" else "на "
            brief_facts.append(f"{brief_labels[code]} {direction} {connector}{format_number(abs(fact['change_pct']))}%")
            brief_directions.append("positive" if fact["change_pct"] >= 0 else "negative")
            if len(brief_facts) == 2:
                break
        if "positive" in brief_directions and "negative" in brief_directions:
            card_verdict = tr(lang, "Картина смешанная", "Natijalar aralash", "The picture is mixed")
        elif brief_directions and all(item == "positive" for item in brief_directions):
            card_verdict = tr(lang, "Динамика положительная", "Dinamika ijobiy", "The trend is positive")
        elif brief_directions and all(item == "negative" for item in brief_directions):
            card_verdict = tr(lang, "Динамика отрицательная", "Dinamika salbiy", "The trend is negative")
        else:
            card_verdict = verdict_label
        card_text = f"{issuer['ticker']}: {', '.join(brief_facts)}. {card_verdict}." if brief_facts else f"{issuer['ticker']}: {card_verdict}."
    refs = [{**f, "raw": number(f["raw"])} for f in verified]
    report = {"ok": True, "issuer": {"id": issuer["id"], "ticker": issuer["ticker"], "name": issuer.get("name"), "organization_type": org, "sector": template},
              "report": {"standard": standard.upper(), "template_basis": snapshot.get("template_basis"), "period": period, "period_end": end.isoformat(), "status": status},
              "standard": standard, "scope": snapshot.get("scope"), "period": period, "period_label": period_text,
              "display_divisor": number(display_divisor),
              "period_basis": snapshot.get("period_basis"), "language": lang, "status": status,
              "content_status": "complete" if complete_content else "shortened",
              "shortened_reason": None if complete_content else "insufficient_traceable_metrics",
              "sector_template_code": template, "template_resolution": resolution, "template_version": VERSION,
              "calculation_version": CALCULATION_VERSION, "mapping_version": MAPPING_VERSION,
              "headline": headline, "short_summary": card_text, "card_text": card_text,
              "card_word_count": len(card_text.split()) if card_text else 0,
              "headline_tone": {"positive": "positive", "mixed": "warning", "negative": "danger", "no_signal": "neutral"}[verdict_status],
              "paragraphs": paragraphs, "text": text, "paragraph_count": len(paragraphs), "word_count": len(text.split()),
              "abstract": headline if publishable else None,
              "sections": report_sections,
              "verified_facts": refs, "number_references": refs, "calculation_inputs": calculation_inputs,
              "ratios": ratios, "public_ratios": [item for item in ratios if item.get("metric_code") not in {"current_ratio", "quick_ratio"}],
              "replacement_blocks": blocks,
              "capital_analysis": capital if publishable else {}, "profit_quality": quality if publishable else {},
              "analytical_signals": signals, "analytical_issues": issues, "risks": risks,
              "monitoring_points": monitoring_points if publishable else [], "trend": trend,
              "verification_summary": verification_summary,
              "verdict": {"status": verdict_status, "headline": headline if publishable else None, "evidence_signal_ids": [s["id"] for s in signals] if verdict_status != "no_signal" else [], "period_end": end.isoformat()},
              "data_quality": data_quality, "balance_check": balance, "financial_as_of": end.isoformat() if period else None,
              "market_as_of": None, "sources": [source] if source_url else [],
              "availability": {"reason_code": status, "last_source_period": period, "last_successful_period": None,
                               "next_action": tr(lang, "Мы проверим данные снова после обновления источника.", "Manba yangilangach ma’lumotlarni yana tekshiramiz.", "We will check the data again after the source is updated.") if not publishable else None},
              "source_snapshot_hash": digest([issuer["id"], standard, period, values, previous, opening, lines, source]),
              "generated_at": snapshot.get("generated_at")}
    report["control_rule_versions"] = snapshot.get("control_rule_versions", [])
    for result in report["ratios"]:
        if result["metric_code"] in snapshot.get("formula_rule_versions", {}):
            result["method_id"] = snapshot["formula_rule_versions"][result["metric_code"]]
    if report["control_rule_versions"]:
        report["calculation_version"] += ":" + digest(report["control_rule_versions"])[:16]
    report["version"] = digest([report["source_snapshot_hash"], resolution, VERSION, MAPPING_VERSION, CALCULATION_VERSION, lang, status, today.isoformat(), report["control_rule_versions"]])
    return report


def make_issues(signals, facts, quality, verdict, lang, period):
    if verdict in {"no_signal", "insufficient_data"}:
        return [], []
    catalog = {
        "profit_quality": ("Качество прибыли", "Foyda sifati", "Earnings quality", "separate_nonoperating_result", ["operating_income", "fx_income", "fx_expenses", "net_income"],
                           ("Оценивать основной результат отдельно от курсовых разниц и переоценки; рост чистой прибыли вторичен до подтверждения устойчивости.", "Asosiy natijani kurs farqlari va qayta baholashdan ajrating; barqarorlik tasdiqlanguncha sof foyda o‘sishi ikkilamchi.", "Assess operating results separately from FX and revaluation; treat net-profit growth as secondary until sustainability is confirmed.")),
        "receivables_outpace_revenue": ("Дебиторка опережает выручку", "Debitorlik tushumdan tezroq o‘sdi", "Receivables outpace revenue", "check_collections", ["receivables", "revenue", "cash"],
                                       ("Оценивать продажи с поправкой на собираемость дебиторки.", "Savdoni debitorlik undirilishini hisobga olib baholang.", "Assess sales growth alongside receivable collection.")),
        "inventories_outpace_revenue": ("Запасы опережают выручку", "Zaxiralar tushumdan tezroq o‘sdi", "Inventories outpace revenue", "check_inventory_conversion", ["inventories", "revenue", "cost_of_sales"],
                                      ("Ограничить положительную оценку оборотного капитала до подтверждения реализации запасов.", "Zaxiralar sotilishi tasdiqlanguncha aylanma kapitalga ijobiy bahoni cheklang.", "Limit positive working-capital conclusions until inventory sales are evidenced.")),
        "liabilities_outpace_equity": ("Обязательства опережают капитал", "Majburiyatlar kapitaldan tezroq o‘sdi", "Liabilities outpace equity", "check_debt_coverage", ["total_liabilities", "total_equity", "cash"],
                                      ("Сопоставить ближайшие погашения с собственными ликвидными активами и источниками капитала.", "Yaqin to‘lovlarni o‘z likvid aktivlari va kapital manbalari bilan solishtiring.", "Compare upcoming maturities with own liquid assets and equity sources.")),
        "claims_outpace_premiums": ("Выплаты опережают премии", "To‘lovlar mukofotlardan tezroq o‘sdi", "Claims outpace premiums", "check_claims_and_reserves", ["insurance_claims", "insurance_premiums", "net_insurance_reserves"],
                                   ("Ограничить положительный вывод до стабилизации выплат и резервов.", "To‘lovlar va zaxiralar barqarorlashguncha ijobiy xulosani cheklang.", "Limit positive conclusions until claims and reserve trends stabilize.")),
    }
    issues, risks, seen = [], [], set()
    for signal in sorted(signals, key=lambda s: s["materiality"] != "high"):
        key = signal["metric_code"]
        if key in seen:
            continue
        seen.add(key)
        entry = catalog.get(signal["code"])
        if entry:
            title, solution_code, metrics, solution = tr(lang, *entry[:3]), entry[3], entry[4], tr(lang, *entry[5])
        else:
            title = label(key, lang) + " — " + tr(lang, "ухудшение", "yomonlashish", "deterioration")
            solution_code, metrics = "check_next_comparable_result", [key, "net_income", "total_equity"]
            solution = tr(lang, "Не считать рост других статей достаточным улучшением; проверить результат следующего сопоставимого периода.", "Boshqa satrlar o‘sishini yetarli yaxshilanish deb hisoblamang; keyingi taqqoslanadigan davrni tekshiring.", "Do not treat improvements elsewhere as sufficient; check the next comparable result.")
        evidence = [f for f in facts.values() if f["id"] in signal["evidence_fact_ids"]]
        cause = "verified" if signal["code"] == "profit_quality" and quality["driver"] != "unknown" else "unknown"
        impact = tr(lang, "Снижает качество результата или запас финансовой устойчивости.", "Natija sifati yoki moliyaviy barqarorlik zaxirasini kamaytiradi.", "Reduces earnings quality or financial resilience.")
        cause_label = tr(lang, "Подтверждён нереализованный эффект переоценки.", "Realizatsiya qilinmagan qayta baholash ta’siri tasdiqlangan.", "An unrealized revaluation effect is confirmed.") if quality["driver"] == "unrealized_revaluation" else tr(lang, "Подтверждено влияние курсовых разниц.", "Kurs farqlari ta’siri tasdiqlangan.", "The foreign-exchange contribution is confirmed.")
        issue = {"issue_code": signal["code"], "title": title, "evidence_fact_ids": signal["evidence_fact_ids"],
                 "actual_value": signal["value_current"], "comparison_value": signal["value_previous"], "period": period,
                 "cause_status": cause, "cause_text": cause_label if cause == "verified" else tr(lang, "Причина не установлена по публичным данным.", "Sabab ochiq ma’lumotlarda aniqlanmagan.", "The cause is not established by public data."),
                 "verified_cause_fact_ids": signal["evidence_fact_ids"] if cause == "verified" else [],
                 "impact": impact, "verdict": verdict if verdict != "no_signal" else "insufficient_data",
                 "verdict_text": tr(lang, "Положительный вывод без проверки этого сигнала преждевременен", "Bu signal tekshirilmasdan ijobiy xulosa qilish erta", "A positive conclusion is premature without resolving this signal"),
                 "solution_code": solution_code, "solution_text": solution, "solution_priority": signal["materiality"],
                 "monitoring_metrics": metrics, "next_trigger": tr(lang, "Следующий сопоставимый отчёт", "Keyingi taqqoslanadigan hisobot", "Next comparable filing"),
                 "confidence": "high", "source_ids": sorted({f["source_document_id"] for f in evidence if f.get("source_document_id")}), "source_url": signal["source_url"]}
        issues.append(issue)
        risks.append({"code": signal["code"], "category": signal["category"], "title": title,
                      "severity": signal["materiality"], "direction": "negative", "metric_code": key,
                      "actual_value": signal["value_current"], "unit": "thousand UZS", "threshold": signal["threshold"],
                      "comparison_value": signal["value_previous"], "comparison_change_pct": signal["comparison_change_pct"],
                      "threshold_unit": "percent" if isinstance(signal["threshold"], (int, float)) and signal["threshold"] else "rule",
                      "threshold_type": "comparable_period_rule", "comparison_period": signal["period_previous"],
                      "evidence_source_id": evidence[0]["source_document_id"], "source_line_ids": [f["source_line_id"] for f in evidence],
                      "source_url": signal["source_url"], "consequence": impact, "monitoring_trigger": issue["next_trigger"], "confidence": "high"})
        if len(risks) == 5:
            break
    return issues, risks

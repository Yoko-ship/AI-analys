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

VERSION = "sector-analysis-2.2"
CALCULATION_VERSION = "nsbu-core-2.0"
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


CORE_RESULT = ["revenue", "cost_of_sales", "gross_profit", "period_expenses", "operating_income", "profit_before_tax", "net_income"]
BANK_RESULT = ["interest_income", "interest_expenses", "noninterest_income", "noninterest_expenses", "operating_expenses", "profit_before_tax", "net_income"]
INSURANCE_RESULT = ["insurance_premiums", "insurance_claims", "revenue", "expenses", "operating_income", "profit_before_tax", "net_income"]
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
        raw = (lines.get(line) or {}).get("raw_current", str(values[key]))
        fact_url = (lines.get(line) or {}).get("source_url") or source_url
        fact_doc_id = "filing:" + digest([issuer["id"], standard, period, fact_url])[:24] if fact_url else source.get("document_id")
        base = opening if key in FORM1.values() or key in codes["cash_and_working_capital"] else previous
        fact = {"id": digest([issuer["id"], standard, period, key, raw, fact_doc_id])[:24],
                "issuer_id": issuer["id"], "metric": key, "metric_code": key, "label": label(key, lang),
                "raw": raw, "value_raw": raw, "value": value, "value_normalized": str(decimal(raw)),
                "unit": "thousand UZS", "unit_raw": "thousand UZS", "unit_normalized": "thousand UZS",
                "period": period, "period_start": snapshot.get("period_start") or f"{year}-01-01", "period_end": end.isoformat(),
                "period_kind": snapshot.get("period_basis"), "accounting_standard": standard.upper(),
                "consolidation_scope": snapshot.get("scope"), "source": {**source, "url": fact_url, "document_id": fact_doc_id}, "source_url": fact_url,
                "source_document_id": fact_doc_id, "source_line_id": line,
                "source_location": {k: v for k, v in {"sheet": (lines.get(line) or {}).get("sheet"), "row": (lines.get(line) or {}).get("row")}.items() if v is not None},
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
        "mapping_failed": tr(lang, "Не удалось сопоставить строки отчётности.", "Hisobot satrlari moslashtirilmadi.", "Source rows could not be mapped."),
        "stale": tr(lang, "Доступен только старый отчёт", "Faqat eski hisobot mavjud", "Only an old filing is available") + f": {period_text}.",
    }
    if not publishable:
        headline, verdict_status = unavailable.get(status, unavailable["quality_blocked"]), "no_signal"
    issues, risks = make_issues(negatives, by_code, quality, verdict_status, lang, period)
    paragraphs = []
    if publishable:
        paragraphs.append(headline)
        for group in ("financial_result", "cash_and_working_capital", "investment_base"):
            sentences = [fact_sentence(key) for key in codes[group]]
            if any(sentences):
                paragraphs.append("; ".join(s for s in sentences if s) + ".")
        if capital["equity_open"] is not None:
            capital_text = tr(lang, "Капитал с начала года", "Yil boshidan kapital", "Equity since the start of the year") + f": {format_number(capital['equity_open'])} → {format_number(capital['equity_end'])} {money_unit}."
            retained = next(item["change_value"] for item in capital["change_sources"] if item["metric_code"] == "retained_earnings")
            if retained is not None:
                capital_text += " " + tr(lang, "Изменение нераспределённой прибыли", "Taqsimlanmagan foyda o‘zgarishi", "Retained-earnings movement") + f": {format_number(retained)} {money_unit}."
            if capital["equity_to_assets_open"] is not None:
                capital_text += " " + tr(lang, "Доля капитала в активах", "Aktivlarda kapital ulushi", "Equity / assets") + f": {format_number(capital['equity_to_assets_open'])}% → {format_number(capital['equity_to_assets_end'])}%."
            paragraphs.append(capital_text)
        if issues:
            paragraphs.append(" ".join(f"{issue['title']}: {display_money(issue['actual_value'])} {money_unit}. {issue['solution_text']} {issue['verdict_text']}." for issue in issues[:2]))
    else:
        paragraphs = [headline]
    text = "\n\n".join(paragraphs)
    refs = [{**f, "raw": number(f["raw"])} for f in verified]
    report = {"ok": True, "issuer": {"id": issuer["id"], "ticker": issuer["ticker"], "name": issuer.get("name"), "organization_type": org, "sector": template},
              "report": {"standard": standard.upper(), "template_basis": snapshot.get("template_basis"), "period": period, "period_end": end.isoformat(), "status": status},
              "standard": standard, "scope": snapshot.get("scope"), "period": period, "period_label": period_text,
              "display_divisor": number(display_divisor),
              "period_basis": snapshot.get("period_basis"), "language": lang, "status": status,
              "content_status": "complete" if publishable and len(verified) >= 7 else "shortened",
              "shortened_reason": None if publishable and len(verified) >= 7 else "insufficient_traceable_metrics",
              "sector_template_code": template, "template_resolution": resolution, "template_version": VERSION,
              "calculation_version": CALCULATION_VERSION, "mapping_version": MAPPING_VERSION,
              "headline": headline, "short_summary": headline if publishable else None,
              "headline_tone": {"positive": "positive", "mixed": "warning", "negative": "danger", "no_signal": "neutral"}[verdict_status],
              "paragraphs": paragraphs, "text": text, "paragraph_count": len(paragraphs), "word_count": len(text.split()),
              "sections": [{"id": f"section-{i}", "text": p} for i, p in enumerate(paragraphs)] if publishable else [],
              "verified_facts": refs, "number_references": refs, "calculation_inputs": calculation_inputs, "ratios": ratios, "replacement_blocks": blocks,
              "capital_analysis": capital if publishable else {}, "profit_quality": quality if publishable else {},
              "analytical_signals": signals, "analytical_issues": issues, "risks": risks,
              "verdict": {"status": verdict_status, "headline": headline if publishable else None, "evidence_signal_ids": [s["id"] for s in signals] if verdict_status != "no_signal" else [], "period_end": end.isoformat()},
              "data_quality": data_quality, "balance_check": balance, "financial_as_of": end.isoformat() if period else None,
              "market_as_of": None, "sources": [source] if source_url else [],
              "availability": {"reason_code": status, "last_source_period": period, "last_successful_period": None,
                               "next_action": tr(lang, "Автоматический повтор после обновления источника", "Manba yangilangach avtomatik takrorlash", "Automatically retry after the source updates") if not publishable else None},
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

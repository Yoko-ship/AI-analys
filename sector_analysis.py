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

VERSION = "sector-analysis-2.10"  # 2.10: bank/insurance formulation library (2026-09-24)
CALCULATION_VERSION = "nsbu-core-2.1"
MAPPING_VERSION = "nsbu-lines-2.2"
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

# The OKED code changes the analytical lens, not the underlying accounting
# facts. Each profile names the balance items and operating ratios that are
# economically material for that activity.
SECTOR_PROFILES = {
    "industry": {
        "name": ("производство", "ishlab chiqarish", "manufacturing"),
        "assets": ("construction_in_progress", "fixed_assets", "inventories", "receivables", "cash"),
        "result": ("Для производства ключевой вопрос — покрывает ли валовая маржа расходы периода и сохраняется ли операционная прибыль.", "Ishlab chiqarishda asosiy savol — yalpi marja davr xarajatlarini qoplayaptimi va operatsion foyda saqlanyaptimi.", "For manufacturing, the key question is whether gross margin covers period costs and preserves operating profit."),
        "risk": ("Отраслевой риск оценивается по себестоимости, запасам и загрузке основных средств.", "Tarmoq xavfi tannarx, zaxiralar va asosiy vositalar yuklamasi bo‘yicha baholanadi.", "Sector risk is assessed through production cost, inventory and fixed-asset utilisation."),
    },
    "cement": {
        "name": ("производство стройматериалов", "qurilish materiallari ishlab chiqarish", "building-materials production"),
        "assets": ("fixed_assets", "inventories", "cash", "receivables"),
        "result": ("Для капиталоёмкого производства цемента важны себестоимость, валовая маржа и способность операционной прибыли обслуживать вложения в мощности.", "Kapital talab qiladigan sement ishlab chiqarishda tannarx, yalpi marja va quvvatlarga investitsiyalarni operatsion foyda bilan qoplash muhim.", "For capital-intensive cement production, cost, gross margin and operating earnings available to support capacity are central."),
        "risk": ("Отраслевой риск — сжатие маржи при высокой доле основных средств и запасов.", "Tarmoq xavfi — asosiy vositalar va zaxiralar ulushi yuqori bo‘lganda marjaning qisqarishi.", "The sector risk is margin compression alongside a high fixed-asset and inventory burden."),
    },
    "metallurgy": {
        "name": ("металлургия", "metallurgiya", "metallurgy"),
        "assets": ("construction_in_progress", "inventories", "fixed_assets", "receivables", "cash"),
        "result": ("Для металлургии качество результата определяется валовой маржой: рост выручки без опережения себестоимости не усиливает прибыль.", "Metallurgiyada natija sifati yalpi marja bilan belgilanadi: tushum tannarxdan tezroq o‘smasa, foyda kuchaymaydi.", "In metallurgy, earnings quality is governed by gross margin: revenue growth does not strengthen profit unless it outpaces cost."),
        "risk": ("Отраслевой риск оценивается по запасам, капиталоёмкости и устойчивости операционной маржи.", "Tarmoq xavfi zaxiralar, kapital sig‘imi va operatsion marja barqarorligi bo‘yicha baholanadi.", "Sector risk is assessed through inventory, capital intensity and operating-margin resilience."),
    },
    "extractive": {
        "name": ("добывающая отрасль", "qazib olish sanoati", "extractive industry"),
        "assets": ("fixed_assets", "construction_in_progress", "inventories", "cash"),
        "result": ("Для добывающей компании сопоставляются операционная маржа и капиталоёмкость; объёмы добычи и цены нельзя определить без отраслевых примечаний.", "Qazib olish kompaniyasida operatsion marja va kapital sig‘imi solishtiriladi; qazib olish hajmi va narxlar izohlarsiz aniqlanmaydi.", "For an extractive company, operating margin is assessed against capital intensity; production volumes and prices require sector notes."),
        "risk": ("Отраслевой риск — слабая отдача от основных средств и незавершённых инвестиций.", "Tarmoq xavfi — asosiy vositalar va tugallanmagan investitsiyalarning past qaytimi.", "The sector risk is weak returns on fixed assets and construction in progress."),
    },
    "trade": {
        "name": ("торговля", "savdo", "trade"),
        "assets": ("inventories", "receivables", "cash", "current_liabilities"),
        "result": ("Для торговли рост выручки оценивается через валовую маржу и оборотный капитал: запасы и дебиторская задолженность не должны поглощать деньги.", "Savdoda tushum o‘sishi yalpi marja va aylanma kapital orqali baholanadi: zaxira va debitorlik pulni yutmasligi kerak.", "For trade, revenue growth is tested against gross margin and working capital: inventory and receivables should not absorb cash."),
        "risk": ("Отраслевой риск — накопление запасов и дебиторской задолженности при слабой ликвидности.", "Tarmoq xavfi — likvidlik zaiflashganda zaxira va debitorlikning to‘planishi.", "The sector risk is inventory and receivables accumulating while liquidity weakens."),
    },
    "transport": {
        "name": ("транспорт и логистика", "transport va logistika", "transport and logistics"),
        "assets": ("fixed_assets", "receivables", "cash", "current_liabilities"),
        "result": ("Для транспорта ключевые показатели — операционная маржа и отдача от основных средств; выручка сама по себе не показывает загрузку активов.", "Transportda operatsion marja va asosiy vositalar qaytimi muhim; tushumning o‘zi aktivlar yuklamasini ko‘rsatmaydi.", "For transport, operating margin and fixed-asset returns matter; revenue alone does not reveal asset utilisation."),
        "risk": ("Отраслевой риск — слабая операционная прибыль при высокой капиталоёмкости и долговой нагрузке.", "Tarmoq xavfi — kapital sig‘imi va qarz yuklamasi yuqori bo‘lganda operatsion foydaning zaifligi.", "The sector risk is weak operating profit alongside high capital intensity and leverage."),
    },
    "aviation": {
        "name": ("авиация", "aviatsiya", "aviation"),
        "assets": ("fixed_assets", "receivables", "cash", "current_liabilities"),
        "result": ("Для авиации результат оценивается по операционной марже, капиталоёмкости и запасу ликвидности; данные о загрузке и топливе требуют примечаний.", "Aviatsiyada natija operatsion marja, kapital sig‘imi va likvidlik zaxirasi bo‘yicha baholanadi; yuklama va yoqilg‘i ma’lumotlari izohlarni talab qiladi.", "For aviation, operating margin, capital intensity and liquidity headroom are central; load factors and fuel data require notes."),
        "risk": ("Отраслевой риск — недостаточная маржа для покрытия капитальных и финансовых расходов.", "Tarmoq xavfi — kapital va moliyaviy xarajatlarni qoplash uchun marjaning yetishmasligi.", "The sector risk is insufficient margin to cover capital and financing costs."),
    },
    "telecom": {
        "name": ("телекоммуникации", "telekommunikatsiyalar", "telecommunications"),
        "assets": ("fixed_assets", "construction_in_progress", "cash", "receivables"),
        "result": ("Для телекома важны операционная маржа и отдача от сети: рост выручки сопоставляется с основными средствами и незавершёнными инвестициями.", "Telekomda operatsion marja va tarmoq qaytimi muhim: tushum o‘sishi asosiy vositalar va tugallanmagan investitsiyalar bilan solishtiriladi.", "For telecoms, operating margin and network returns matter: revenue growth is assessed against fixed assets and construction in progress."),
        "risk": ("Отраслевой риск — рост инвестиций и долга без соответствующего усиления операционной прибыли.", "Tarmoq xavfi — operatsion foyda mos ravishda oshmasdan investitsiya va qarzning o‘sishi.", "The sector risk is investment and debt growth without a matching increase in operating profit."),
    },
    "leasing": {
        "name": ("лизинг", "lizing", "leasing"),
        "assets": ("receivables", "long_term_investments", "cash", "total_liabilities"),
        "result": ("Для лизинга прибыль сопоставляется с дебиторской задолженностью и стоимостью финансирования; качество портфеля без примечаний не оценивается.", "Lizingda foyda debitorlik va moliyalashtirish qiymati bilan solishtiriladi; portfel sifati izohlarsiz baholanmaydi.", "For leasing, profit is assessed against receivables and funding cost; portfolio quality cannot be judged without notes."),
        "risk": ("Отраслевой риск — рост портфеля и обязательств без достаточной прибыли и ликвидности.", "Tarmoq xavfi — yetarli foyda va likvidliksiz portfel va majburiyatlarning o‘sishi.", "The sector risk is portfolio and liability growth without sufficient earnings and liquidity."),
    },
}
CATALOG_SECTOR_TEMPLATES = {
    "manufacturing": "industry", "industry": "industry",
    "mining": "extractive", "extractive": "extractive",
    "transport": "transport", "telecom": "telecom", "trade": "trade",
    "aviation": "aviation", "leasing": "leasing",
}


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
    sector = str(issuer.get("sector") or index.get("sector") or security.get("sector") or "").strip().lower()
    sector_template = CATALOG_SECTOR_TEMPLATES.get(sector)
    selected = special or (OKED_MAP[prefix] if prefix else sector_template or "generic_nsbu")
    status = "special_override" if special else "matched_prefix" if prefix else "sector_catalog_fallback" if sector_template else "generic_fallback"
    if valid_override:
        selected, status = override.get("override_template", "generic_nsbu"), "manual_override"
    activity = issuer.get("verified_activity_template") or index.get("verified_activity_template")
    if activity and activity != selected and not valid_override:
        status = "classification_conflict"
    return {"selected_template": selected, "resolution_status": status, "input_oked": oked or None,
            "rule_version": VERSION, "evidence_source": override.get("evidence_source") if valid_override else index.get("source_url"),
            "reason_code": override.get("reason_code") if valid_override else ("special_legal_type" if special else "primary_oked" if prefix else "catalog_sector" if sector_template else "unknown_oked")}


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
BANK_RESULT = ["interest_income", "interest_expenses", "noninterest_income", "noninterest_expenses", "net_revenue_before_operating_expenses", "operating_expenses", "profit_before_tax", "tax", "net_income"]
INSURANCE_RESULT = ["insurance_premiums", "insurance_claims", "revenue", "expenses", "operating_income", "profit_before_tax", "tax", "net_income"]
FUND_RESULT = ["unrealized_fair_value_gain", "dividend_income", "management_expenses", "tax", "net_income"]
BALANCE = ["cash", "receivables", "inventories", "current_liabilities", "total_assets", "total_liabilities", "total_equity"]
FINANCE_BALANCE = ["cash", "central_bank_balances", "loan_portfolio", "customer_funds", "borrowings", "loan_reserves", "total_assets", "total_liabilities", "total_equity"]
INSURANCE_BALANCE = ["cash", "receivables", "gross_insurance_reserves", "reinsurer_share_in_reserves", "net_insurance_reserves", "other_liabilities", "total_assets", "total_liabilities", "total_equity"]
FUND_BALANCE = ["cash", "dividends_receivable", "accounts_payable", "total_assets", "total_liabilities", "total_equity"]


# Extra source lines behind the bank and insurance formulation library
# (customer glossary, 2026-09-24).  They are facts only when disclosed.
SECTOR_PHRASE_BALANCE_LINES = frozenset({"due_from_banks", "demand_deposits", "savings_deposits", "term_deposits"})
SECTOR_PHRASE_FLOW_LINES = frozenset({
    "net_interest_income_before_provisions", "credit_loss_provisions", "net_interest_income_after_provisions",
    "fee_income", "fee_expenses", "ceded_premiums", "insurance_service_cost", "insurance_service_result",
})


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
    "net_revenue_before_operating_expenses": ("Чистый доход до операционных расходов", "Operatsion xarajatlargacha sof daromad", "Net revenue before operating expenses"),
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
    "due_from_banks": ("Средства в других банках", "Boshqa banklardagi mablag‘lar", "Due from other banks"),
    "demand_deposits": ("Депозиты до востребования", "Talab qilinguncha depozitlar", "Demand deposits"),
    "savings_deposits": ("Сберегательные депозиты", "Jamg‘arma depozitlari", "Savings deposits"),
    "term_deposits": ("Срочные депозиты", "Muddatli depozitlar", "Term deposits"),
    "net_interest_income_before_provisions": ("Чистый процентный доход до оценки кредитных потерь", "Kredit yo‘qotishlarini baholashgacha sof foizli daromad", "Net interest income before the credit-loss estimate"),
    "credit_loss_provisions": ("Расходы на оценку кредитных потерь", "Kredit yo‘qotishlarini baholash xarajatlari", "Credit-loss estimate"),
    "net_interest_income_after_provisions": ("Чистый процентный доход после оценки кредитных потерь", "Kredit yo‘qotishlarini baholashdan keyingi sof foizli daromad", "Net interest income after the credit-loss estimate"),
    "fee_income": ("Комиссионные доходы", "Komission daromadlar", "Fee and commission income"),
    "fee_expenses": ("Комиссионные расходы", "Komission xarajatlar", "Fee and commission expense"),
    "fx_income": ("Доходы по валютным операциям", "Valyuta operatsiyalari daromadi", "Foreign-exchange gains"),
    "fx_expenses": ("Расходы по валютным операциям", "Valyuta operatsiyalari xarajati", "Foreign-exchange losses"),
    "ceded_premiums": ("Премии, переданные в перестрахование", "Qayta sug‘urtaga berilgan mukofotlar", "Premiums ceded to reinsurers"),
    "insurance_service_cost": ("Себестоимость страховых услуг", "Sug‘urta xizmatlari tannarxi", "Cost of insurance services"),
    "insurance_service_result": ("Результат от страховых услуг", "Sug‘urta xizmatlari natijasi", "Insurance-service result"),
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
    reviewed = {str(field) for field in snapshot.get("reviewed_correction_fields") or []}
    org = snapshot.get("organization_type")
    if workbook and org == "non_financial" and not snapshot.get("control_lines_prepared"):
        for form, table in (("form1", workbook.get("balance")), ("form2", workbook.get("income"))):
            lines.update({f"{form}:{key}": row for key, row in source_line_pairs(table, form).items()})
    for form, mapping in (("form1", FORM1), ("form2", FORM2)):
        for code, key in mapping.items():
            row = lines.get(f"{form}:{code}")
            if row is not None and org == "non_financial":
                # A confirmed catalogue correction is the authority over the
                # parsed workbook line.  Without this guard the analysis
                # recheck would see the original bad number and reject a
                # correction that the public financial data already uses.
                if key not in reviewed:
                    values[key] = row.get("raw_current", row.get("current"))
                if form == "form1" or key not in reviewed:
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
    # An issuer that has stopped filing is still analyzable from its last
    # traceable statement.  Keep the distinct ``stale`` status and date so it
    # can never be mistaken for current information, but do not turn a valid
    # historical report into an empty screen.
    publishable = status in {"available", "stale"}
    ratios = computed_ratios if publishable else []
    if template == "commodity_exchange" and any(values.get(k) is None for k in ("own_cash", "client_cash", "settlement_liabilities")):
        ratios = [r for r in ratios if r["metric"].startswith("P")]
    facts, by_code = [], {}
    mapping = {key: f"form1:{code}" for code, key in FORM1.items()}
    mapping.update({key: f"form2:{code}" for code, key in FORM2.items()})
    allowed = set(sum(codes.values(), [])) | {"fx_income", "fx_expenses", "financial_income", "financial_expenses", "short_term_investments", "retained_earnings", "share_capital", "additional_capital"} | SECTOR_PHRASE_BALANCE_LINES | SECTOR_PHRASE_FLOW_LINES
    def metric_label(key):
        if template == "insurance" and key == "revenue":
            return tr(lang, "Чистая выручка от страховых услуг", "Sug‘urta xizmatlaridan sof tushum", "Net insurance-service revenue")
        return label(key, lang)

    for key in sorted(allowed):
        value = number(values.get(key))
        if value is None:
            continue
        line = (snapshot.get("field_sources", {}).get(key) or {}).get("source_line_id") or (mapping.get(key) if mapping.get(key) in lines else f"catalog:{key}")
        line_row = lines.get(line) or {}
        raw = line_row.get("raw_current", str(values[key]))
        fact_url = line_row.get("source_url") or source_url
        fact_doc_id = "filing:" + digest([issuer["id"], standard, period, fact_url])[:24] if fact_url else source.get("document_id")
        base = opening if key in FORM1.values() or key in codes["cash_and_working_capital"] or key in SECTOR_PHRASE_BALANCE_LINES else previous
        fact = {"id": digest([issuer["id"], standard, period, key, raw, fact_doc_id])[:24],
                "issuer_id": issuer["id"], "metric": key, "metric_code": key, "label": metric_label(key),
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
        text = f"{metric_label(key)}: {display_money(fact['value'])} {money_unit}"
        if comparison and fact["previous"] is not None:
            text = f"{metric_label(key)}: {display_money(fact['previous'])} → {display_money(fact['value'])} {money_unit}"
            if fact["change_pct"] is not None:
                text += f" ({format_number(fact['change_pct'])}%)"
        return text

    # Structured prose blocks are rendered as separate analytical paragraphs
    # with a short bold lead.  The plain paragraph strings remain in the API
    # for backwards compatibility and exports.
    narrative_blocks = {"performance": [], "position": []}

    def vertical_narrative(asset_keys, heading, bank_funding=False, exchange_funding=False):
        """Explain the balance mix as a comparison, not a list of percentages.

        This follows the useful part of a Task-1 style commentary: lead with the
        dominant feature, compare both dates in percentage points, then explain
        the economic implication without inventing an undisclosed cause.
        """
        assets_fact = by_code.get("total_assets") or {}
        assets_now = decimal(assets_fact.get("value"))
        assets_before = decimal(assets_fact.get("previous"))
        if not assets_now or assets_now <= 0:
            return heading + tr(lang, "Недостаточно данных для расчёта структуры.", "Tarkibni hisoblash uchun ma’lumot yetarli emas.", "There is insufficient data to calculate the structure.")

        rows = []
        for key in dict.fromkeys(asset_keys):
            fact = by_code.get(key) or {}
            current = ratio(fact.get("value"), assets_now, True)
            previous_share = ratio(fact.get("previous"), assets_before, True)
            if current is None:
                continue
            rows.append({"key": key, "current": current, "previous": previous_share,
                         "shift": difference(current, previous_share)})
        if not rows:
            return heading + tr(lang, "Недостаточно данных для расчёта структуры.", "Tarkibni hisoblash uchun ma’lumot yetarli emas.", "There is insufficient data to calculate the structure.")

        dominant = max(rows, key=lambda item: item["current"])
        first = tr(
            lang,
            f"В структуре активов доминирует статья «{label(dominant['key'], lang)}» — {format_number(dominant['current'])}% итога баланса.",
            f"Aktivlar tarkibida «{label(dominant['key'], lang)}» ustun — balans jami aktivlarining {format_number(dominant['current'])}%i.",
            f"{label(dominant['key'], lang)} dominates the asset mix at {format_number(dominant['current'])}% of total assets.",
        )
        if dominant["previous"] is not None:
            first += " " + tr(
                lang,
                f"На начало периода доля составляла {format_number(dominant['previous'])}%, то есть изменилась на {format_number(dominant['shift'])} п.п.",
                f"Davr boshida ulush {format_number(dominant['previous'])}% edi, ya’ni {format_number(dominant['shift'])} foiz punktga o‘zgardi.",
                f"At the start of the period it was {format_number(dominant['previous'])}%, a change of {format_number(dominant['shift'])} percentage points.",
            )

        comparable = sorted((row for row in rows if row["shift"] is not None),
                            key=lambda item: abs(item["shift"]), reverse=True)
        movement = ""
        if comparable:
            parts = []
            for row in comparable[:2]:
                direction = tr(lang, "выросла", "oshdi", "rose") if row["shift"] >= 0 else tr(lang, "снизилась", "kamaydi", "fell")
                parts.append(tr(
                    lang,
                    f"доля «{label(row['key'], lang)}» {direction} с {format_number(row['previous'])}% до {format_number(row['current'])}% ({format_number(abs(row['shift']))} п.п.)",
                    f"«{label(row['key'], lang)}» ulushi {format_number(row['previous'])}%dan {format_number(row['current'])}%gacha {direction} ({format_number(abs(row['shift']))} foiz punkt)",
                    f"{label(row['key'], lang)} {direction} from {format_number(row['previous'])}% to {format_number(row['current'])}% ({format_number(abs(row['shift']))} pp)",
                ))
            movement = tr(lang, "Главные структурные изменения: ", "Asosiy tarkibiy o‘zgarishlar: ", "The main structural changes were: ") + "; ".join(parts) + "."

        if bank_funding:
            # Bank wording from the customer's formulation library: concentration
            # is described, never judged, and each share shift is stated plainly.
            if dominant["current"] >= 50:
                first = tr(
                    lang,
                    f"Основную часть активов составляет «{label(dominant['key'], lang)}» — {format_number(dominant['current'])}%. Такая структура указывает на значительную концентрацию баланса в этом направлении.",
                    f"Aktivlarning asosiy qismini «{label(dominant['key'], lang)}» tashkil etadi — {format_number(dominant['current'])}%. Bunday tuzilma balansning shu yo‘nalishda sezilarli darajada jamlanganini ko‘rsatadi.",
                    f"Most of the assets are «{label(dominant['key'], lang)}» — {format_number(dominant['current'])}%. This structure indicates a significant concentration of the balance sheet in this area.",
                )
            else:
                first = tr(
                    lang,
                    f"Крупнейшая раскрытая статья активов — «{label(dominant['key'], lang)}»: {format_number(dominant['current'])}%.",
                    f"Oshkor qilingan eng yirik aktiv moddasi — «{label(dominant['key'], lang)}»: {format_number(dominant['current'])}%.",
                    f"The largest disclosed asset item is «{label(dominant['key'], lang)}»: {format_number(dominant['current'])}%.",
                )
            shifts = []
            for row in comparable[:2]:
                if not row["shift"]:
                    continue
                up = row["shift"] > 0
                shifts.append(tr(
                    lang,
                    f"Доля «{label(row['key'], lang)}» в активах {'выросла' if up else 'снизилась'} с {format_number(row['previous'])}% до {format_number(row['current'])}%, что отражает изменение структуры активов.",
                    f"«{label(row['key'], lang)}»ning aktivlardagi ulushi {format_number(row['previous'])}%dan {format_number(row['current'])}%gacha {'oshdi' if up else 'kamaydi'}, bu aktivlar tuzilmasi o‘zgarganini aks ettiradi.",
                    f"The share of «{label(row['key'], lang)}» in assets {'rose' if up else 'fell'} from {format_number(row['previous'])}% to {format_number(row['current'])}%, reflecting a change in the asset structure.",
                ))
            movement = " ".join(shifts)

        rose = dominant["shift"] is None or dominant["shift"] >= 0
        implications = {
            "fixed_assets": tr(lang, "Высокая доля основных средств подтверждает капиталоёмкость бизнеса: значительная часть ресурсов связана в производственной базе.", "Asosiy vositalarning yuqori ulushi biznes kapital talabchanligini ko‘rsatadi: resurslarning katta qismi ishlab chiqarish bazasiga bog‘langan.", "The high fixed-asset share confirms a capital-intensive model, with substantial resources tied to the operating base."),
            "construction_in_progress": tr(lang, "Высокая доля незавершённых вложений показывает, что значительная часть активов ещё не введена в эксплуатацию; отдачу от этих инвестиций нужно проверять после запуска объектов.", "Tugallanmagan investitsiyalarning yuqori ulushi aktivlarning katta qismi hali ishga tushirilmaganini ko‘rsatadi; bu investitsiyalar qaytimi obyektlar ishga tushgach tekshirilishi kerak.", "A high construction-in-progress share means a substantial part of assets is not yet operational; returns should be assessed after the projects are commissioned."),
            "inventories": tr(lang, "Рост доли запасов означает, что больше средств связано в оборотном капитале; важно сопоставить это с динамикой выручки.", "Zaxiralar ulushining o‘sishi aylanma kapitalga ko‘proq mablag‘ bog‘langanini anglatadi; buni tushum dinamikasi bilan solishtirish kerak.", "A rising inventory share ties up more working capital and should be assessed against revenue growth.") if rose else tr(lang, "Снижение доли запасов высвобождает оборотный капитал, но без примечаний нельзя отличить ускорение оборачиваемости от сокращения деятельности.", "Zaxiralar ulushining pasayishi aylanma kapitalni bo‘shatadi, ammo izohlarsiz tezroq aylanishni faoliyat qisqarishidan ajratib bo‘lmaydi.", "A lower inventory share releases working capital, although the notes are needed to distinguish faster turnover from weaker activity."),
            "receivables": tr(lang, "Рост доли дебиторской задолженности усиливает зависимость ликвидности от своевременных расчётов покупателей.", "Debitorlik ulushining o‘sishi likvidlikni xaridorlarning o‘z vaqtida to‘lovlariga ko‘proq bog‘laydi.", "A rising receivables share makes liquidity more dependent on timely customer payments.") if rose else tr(lang, "Снижение доли дебиторской задолженности уменьшает объём средств, связанных в расчётах с покупателями, и потенциально поддерживает ликвидность.", "Debitorlik ulushining pasayishi xaridorlar bilan hisob-kitoblarga bog‘langan mablag‘larni kamaytirib, likvidlikni qo‘llab-quvvatlashi mumkin.", "A lower receivables share reduces funds tied up in customer settlements and may support liquidity."),
            "cash": tr(lang, "Рост доли денег усиливает немедленный запас ликвидности.", "Pul ulushining o‘sishi tezkor likvidlik zaxirasini kuchaytiradi.", "A rising cash share strengthens the immediate liquidity buffer.") if rose else tr(lang, "Снижение доли денег ослабляет немедленный запас ликвидности и требует сопоставления с краткосрочными обязательствами.", "Pul ulushining pasayishi tezkor likvidlik zaxirasini susaytiradi va joriy majburiyatlar bilan solishtirishni talab qiladi.", "A lower cash share weakens the immediate liquidity buffer and should be assessed against current liabilities."),
            "loan_portfolio": tr(lang, "Доминирование кредитного портфеля подтверждает кредитную специализацию банка и концентрацию активов на кредитном риске.", "Kredit portfelining ustunligi bankning kreditlashga ixtisoslashganini va aktivlar kredit riskida jamlanganini ko‘rsatadi.", "The dominant loan portfolio confirms the bank’s lending focus and concentration of assets in credit risk."),
        }
        meaning = implications.get(dominant["key"], tr(lang, "Такое соотношение показывает, где сосредоточена основная часть ресурсов компании.", "Bu nisbat kompaniya resurslarining asosiy qismi qayerda jamlanganini ko‘rsatadi.", "This mix shows where most of the company’s resources are concentrated."))
        if bank_funding:
            meaning = ""
        if exchange_funding and dominant["key"] in {"cash", "client_cash", "own_cash"}:
            meaning = tr(
                lang,
                "Высокая денежная доля характерна для расчётной инфраструктуры биржи, но её нельзя считать свободной ликвидностью без раздельного раскрытия собственных и клиентских средств.",
                "Pul ulushining yuqoriligi birjaning hisob-kitob infratuzilmasiga xos, ammo o‘z va mijoz mablag‘lari alohida oshkor qilinmasa, uni erkin likvidlik deb hisoblab bo‘lmaydi.",
                "A high cash share is consistent with an exchange settlement model, but it cannot be treated as freely available liquidity without a split between own and client funds.",
            )
        equity_share = ratio((by_code.get("total_equity") or {}).get("value"), assets_now, True)
        liability_share = ratio((by_code.get("total_liabilities") or {}).get("value"), assets_now, True)
        funding = ""
        if equity_share is not None and liability_share is not None:
            if bank_funding:
                funding = tr(
                    lang,
                    f"Капитал составляет {format_number(equity_share)}% активов, обязательства — {format_number(liability_share)}%. Для банка высокая доля обязательств является частью операционной модели, включая депозиты и заимствования, и сама по себе не означает чрезмерную зависимость от внешнего финансирования.",
                    f"Kapital aktivlarning {format_number(equity_share)}%ini, majburiyatlar esa {format_number(liability_share)}%ini tashkil etadi. Bankda majburiyatlarning yuqori ulushi depozitlar va qarzlarni o‘z ichiga olgan operatsion modelning bir qismi bo‘lib, o‘z-o‘zidan tashqi moliyalashtirishga ortiqcha qaramlikni anglatmaydi.",
                    f"Equity represents {format_number(equity_share)}% of assets and liabilities {format_number(liability_share)}%. For a bank, a high liability share is inherent to the operating model, including deposits and borrowings, and is not by itself evidence of excessive external-funding dependence.",
                )
            elif exchange_funding:
                funding = tr(
                    lang,
                    f"Капитал составляет {format_number(equity_share)}% активов, обязательства — {format_number(liability_share)}%. Для биржи обязательства могут включать клиентские расчёты и обеспечительные средства, поэтому эту долю нельзя автоматически трактовать как корпоративный долг.",
                    f"Kapital aktivlarning {format_number(equity_share)}%ini, majburiyatlar esa {format_number(liability_share)}%ini tashkil etadi. Birjada majburiyatlar mijozlar hisob-kitoblari va ta’minot mablag‘larini o‘z ichiga olishi mumkin, shuning uchun bu ulushni avtomatik ravishda korporativ qarz deb talqin qilib bo‘lmaydi.",
                    f"Equity represents {format_number(equity_share)}% of assets and liabilities {format_number(liability_share)}%. For an exchange, liabilities may include client settlements and collateral, so the ratio cannot automatically be interpreted as corporate debt.",
                )
            else:
                funding = tr(
                    lang,
                    f"Источники финансирования распределены так: собственный капитал покрывает {format_number(equity_share)}% активов, обязательства — {format_number(liability_share)}%; это прямо показывает уровень финансовой автономии и зависимость от внешнего фондирования.",
                    f"Moliyalashtirish manbalari quyidagicha: kapital aktivlarning {format_number(equity_share)}%ini, majburiyatlar esa {format_number(liability_share)}%ini qoplaydi; bu moliyaviy mustaqillik va tashqi mablag‘larga bog‘liqlik darajasini ko‘rsatadi.",
                    f"Funding is split between equity covering {format_number(equity_share)}% of assets and liabilities covering {format_number(liability_share)}%, directly indicating financial autonomy and reliance on external funding.",
                )
        return " ".join(part.strip() for part in (heading, first, movement, meaning, funding, tr(
            lang,
            "Точную операционную причину изменения можно подтвердить только примечаниями к отчётности.",
            "O‘zgarishning aniq operatsion sababini faqat hisobot izohlari tasdiqlashi mumkin.",
            "The exact operating cause can only be confirmed from the notes to the financial statements.",
        )) if part and part.strip())

    # ── Bank and insurance narratives: the customer's formulation library ──
    # Source: «Библиотека аналитических формулировок — банковский и страховой
    # секторы (НСБУ)», 2026-09-24.  Every statement runs metric → direction →
    # factor → caveat.  A change is never presented as its own cause, an
    # analytical ratio is never called a regulatory standard, and a phrase is
    # used only when every line it needs is disclosed.  In insurance, premiums,
    # insurance revenue, insurance result and net profit are kept apart.
    nsbu_name = tr(lang, "НСБУ", "BHMS", "NSBU")

    def moved(key):
        return (by_code.get(key) or {}).get("change_pct")

    def fact_now(key):
        return decimal((by_code.get(key) or {}).get("value"))

    def fact_before(key):
        return decimal((by_code.get(key) or {}).get("previous"))

    def amount_text(amount):
        return f"{display_money(amount)} {money_unit}"

    def pct_of(numerator, denominator):
        return ratio(numerator, denominator, True)

    def pct_str(item):
        return f"{format_number(item)}%"

    def sector_conclusion():
        """Close with the library's positive / mixed / negative wording."""
        insurance = template == "insurance"
        names = {
            "revenue": tr(lang, "чистая выручка от страховых услуг", "sug‘urta xizmatlaridan sof tushum", "net insurance-service revenue") if insurance else tr(lang, "раскрытые доходы", "oshkor qilingan daromadlar", "disclosed income"),
            "net_income": tr(lang, "чистая прибыль", "sof foyda", "net profit"),
            "operating_income": tr(lang, "операционный результат", "operatsion natija", "operating result"),
            "total_equity": tr(lang, "капитал", "kapital", "equity"),
            "total_liabilities": tr(lang, "соотношение обязательств и капитала", "majburiyatlar va kapital nisbati", "liabilities relative to equity"),
            "receivables": tr(lang, "дебиторская задолженность", "debitorlik qarzi", "receivables"),
            "inventories": tr(lang, "запасы", "zaxiralar", "inventories"),
            "insurance_claims": tr(lang, "страховые выплаты", "sug‘urta to‘lovlari", "insurance claims"),
            "profit_quality": tr(lang, "качество прибыли", "foyda sifati", "earnings quality"),
        }
        pressure = {
            "net_income": tr(lang, "прибыльность", "rentabellikka", "profitability"),
            "operating_income": tr(lang, "результат основной деятельности", "asosiy faoliyat natijasiga", "the core operating result"),
            "total_liabilities": tr(lang, "структуру баланса", "balans tuzilmasiga", "the balance-sheet structure"),
            "receivables": tr(lang, "структуру активов", "aktivlar tuzilmasiga", "the asset structure"),
            "inventories": tr(lang, "структуру активов", "aktivlar tuzilmasiga", "the asset structure"),
            "insurance_claims": tr(lang, "результат услуг", "xizmatlar natijasiga", "the service result"),
            "profit_quality": tr(lang, "прибыльность", "rentabellikka", "profitability"),
        }

        def subject(item):
            code = item["code"]
            if code == "profit_quality":
                return "profit_quality"
            return item["metric_code"]

        def seen(items):
            unique = []
            for item in items:
                key = subject(item)
                if key in names and key not in unique:
                    unique.append(key)
            return unique

        good, bad = seen(positives), seen(negatives)
        parts = []
        if verdict_status == "positive" and good:
            parts.append(tr(lang, f"За период компания увеличила показатель «{names[good[0]]}».", f"Davr mobaynida kompaniya «{names[good[0]]}» ko‘rsatkichini oshirdi.", f"Over the period the company increased «{names[good[0]]}»."))
            if len(good) > 1:
                parts.append(tr(lang, f"Одновременно показатель «{names[good[1]]}» изменился в благоприятном направлении.", f"Bir vaqtning o‘zida «{names[good[1]]}» ko‘rsatkichi ijobiy tomonga o‘zgardi.", f"At the same time «{names[good[1]]}» moved in a favourable direction."))
            parts.append(tr(lang, f"В целом динамика выглядит положительной в пределах доступных данных {nsbu_name}. Для подтверждения устойчивости тенденции необходимы данные за более длительный период.", f"Umuman olganda, dinamika mavjud {nsbu_name} ma’lumotlari doirasida ijobiy ko‘rinadi. Tendensiya barqarorligini tasdiqlash uchun uzoqroq davr ma’lumotlari kerak.", f"Overall, the trend looks positive within the available {nsbu_name} data. Data for a longer period are needed to confirm that the trend is sustainable."))
        elif verdict_status == "mixed" and good and bad:
            parts.append(tr(lang, f"Картина неоднородная: показатель «{names[good[0]]}» улучшился, тогда как показатель «{names[bad[0]]}» ухудшился.", f"Manzara bir xil emas: «{names[good[0]]}» ko‘rsatkichi yaxshilandi, «{names[bad[0]]}» ko‘rsatkichi esa yomonlashdi.", f"The picture is uneven: «{names[good[0]]}» improved, while «{names[bad[0]]}» worsened."))
            parts.append(tr(lang, f"Ключевой вопрос для дальнейшего наблюдения — дальнейшая динамика показателя «{names[bad[0]]}».", f"Keyingi kuzatuv uchun asosiy savol — «{names[bad[0]]}» ko‘rsatkichining keyingi dinamikasi.", f"The key question to monitor is the further movement of «{names[bad[0]]}»."))
        elif verdict_status == "negative" and bad:
            target = pressure.get(bad[0], tr(lang, "прибыльность", "rentabellikka", "profitability"))
            parts.append(tr(lang, f"За период ухудшился показатель «{names[bad[0]]}», что оказало давление на {target}.", f"Davr mobaynida «{names[bad[0]]}» ko‘rsatkichi yomonlashdi va bu {target} bosim o‘tkazdi.", f"Over the period «{names[bad[0]]}» worsened, which put pressure on {target}."))
            parts.append(tr(lang, "Наблюдаемая динамика требует внимания, но не позволяет самостоятельно заключить о нарушении нормативов или неплатёжеспособности.", "Kuzatilayotgan dinamika e’tibor talab qiladi, ammo undan mustaqil ravishda me’yorlar buzilgani yoki to‘lovga qobiliyatsizlik haqida xulosa chiqarib bo‘lmaydi.", "The observed trend requires attention, but on its own it does not support a conclusion of a breach of regulatory standards or insolvency."))
        else:
            comparable = snapshot.get("previous_comparable_period") or tr(lang, "прошлый год", "o‘tgan yil", "the previous year")
            parts.append(tr(lang, f"Сравнение ограничено отсутствием сопоставимых данных за {comparable}.", f"Taqqoslash {comparable} uchun taqqoslanadigan ma’lumotlar yo‘qligi bilan cheklangan.", f"The comparison is limited by the absence of comparable data for {comparable}."))
        parts.append(tr(lang, f"Вывод основан на доступных формах {nsbu_name} за {period_text} и не заменяет оценку по регуляторной отчётности.", f"Xulosa {period_text} uchun mavjud {nsbu_name} shakllariga asoslangan va regulyativ hisobot bo‘yicha baholashni almashtirmaydi.", f"The conclusion is based on the available {nsbu_name} forms for {period_text} and does not replace an assessment based on regulatory reporting."))
        return " ".join(parts)

    def bank_analysis_paragraphs():
        """Bank narrative in the library's wording, from verified lines only."""
        interest_income = fact_now("interest_income")
        noninterest_income = fact_now("noninterest_income")
        interest_expenses = fact_now("interest_expenses")
        noninterest_expenses = fact_now("noninterest_expenses")
        operating_expenses = fact_now("operating_expenses")
        net_revenue_before_opex = fact_now("net_revenue_before_operating_expenses")
        profit_before_tax = fact_now("profit_before_tax")
        net_income = fact_now("net_income")
        disclosed_tax = fact_now("tax")
        total_income = total(interest_income, noninterest_income)
        total_expenses = total(interest_expenses, noninterest_expenses, operating_expenses)
        net_interest_income = difference(interest_income, interest_expenses)
        interest_expense_share = pct_of(interest_expenses, interest_income)
        cost_to_income = pct_of(operating_expenses, net_revenue_before_opex)
        tax_amount = disclosed_tax
        if tax_amount is None and profit_before_tax is not None and net_income is not None:
            tax_amount = profit_before_tax - net_income

        net_change = moved("net_income")
        loan_change = moved("loan_portfolio")
        assets_change = moved("total_assets")
        bank_exec = []
        if net_change is not None:
            bank_exec.append(tr(lang, f"Чистая прибыль изменилась на {format_number(net_change)}%.", f"Sof foyda {format_number(net_change)}% ga o‘zgardi.", f"Net profit changed {format_number(net_change)}%."))
        if net_interest_income is not None:
            bank_exec.append(tr(lang, f"Чистый процентный доход составил {display_money(net_interest_income)} {money_unit}.", f"Sof foizli daromad {display_money(net_interest_income)} {money_unit}ni tashkil etdi.", f"Net interest income was {display_money(net_interest_income)} {money_unit}."))
        if cost_to_income is not None:
            bank_exec.append(tr(lang, f"Cost-to-Income составил {pct_str(cost_to_income)}.", f"Cost-to-Income {pct_str(cost_to_income)}ni tashkil etdi.", f"Cost-to-Income was {pct_str(cost_to_income)}."))
        intro = f"{headline} " + (" ".join(bank_exec) or tr(lang, "Главный вывод ограничен доступными раскрытиями.", "Asosiy xulosa mavjud ma’lumotlar bilan cheklangan.", "The key takeaway is limited by available disclosures."))

        # Assets and loan portfolio.
        asset_lines = []
        if assets_change is not None:
            grew = assets_change >= 0
            driver = ""
            loan_delta = difference(fact_now("loan_portfolio"), fact_before("loan_portfolio"))
            asset_delta = difference(fact_now("total_assets"), fact_before("total_assets"))
            if grew and loan_delta is not None and asset_delta is not None and asset_delta > 0 and loan_delta > 0 and loan_delta * 2 >= asset_delta:
                driver = tr(lang, ", главным образом за счёт роста кредитного портфеля", ", asosan kredit portfeli o‘sishi hisobiga", ", mainly due to growth in the loan portfolio")
            asset_lines.append(tr(
                lang,
                f"Активы банка за период {'увеличились' if grew else 'сократились'} на {format_number(abs(assets_change))}%{driver}.",
                f"Bank aktivlari davr mobaynida {format_number(abs(assets_change))}% ga {'oshdi' if grew else 'kamaydi'}{driver}.",
                f"The bank's assets {'increased' if grew else 'decreased'} by {format_number(abs(assets_change))}% over the period{driver}.",
            ))
        if loan_change is not None:
            if loan_change < 0:
                asset_lines.append(tr(lang, f"Кредитный портфель сократился на {format_number(abs(loan_change))}%. Для оценки причины важно сопоставить изменение с погашениями, выдачами и движением резервов — если эти данные раскрыты.", f"Kredit portfeli {format_number(abs(loan_change))}% ga qisqardi. Sababni baholash uchun o‘zgarishni so‘ndirishlar, berilgan kreditlar va zaxiralar harakati bilan solishtirish muhim — agar bu ma’lumotlar oshkor qilingan bo‘lsa.", f"The loan portfolio contracted by {format_number(abs(loan_change))}%. To assess the reason, the change should be compared with repayments, new lending and reserve movements — if these are disclosed."))
            elif assets_change is not None and loan_change > assets_change:
                asset_lines.append(tr(lang, f"Кредитный портфель рос быстрее активов: {pct_str(loan_change)} против {pct_str(assets_change)}. В структуре баланса усилилась роль кредитования.", f"Kredit portfeli aktivlardan tezroq o‘sdi: {pct_str(loan_change)} va {pct_str(assets_change)}. Balans tuzilmasida kreditlashning roli kuchaydi.", f"The loan portfolio grew faster than assets: {pct_str(loan_change)} versus {pct_str(assets_change)}. Lending now plays a larger role in the balance sheet."))
            else:
                asset_lines.append(tr(lang, f"Рост активов сопровождался расширением кредитного портфеля на {pct_str(loan_change)}. Это указывает на увеличение масштаба кредитных операций, но само по себе не характеризует их качество.", f"Aktivlar o‘sishi kredit portfelining {pct_str(loan_change)} ga kengayishi bilan birga kechdi. Bu kredit operatsiyalari ko‘lami oshganini ko‘rsatadi, ammo o‘z-o‘zidan ularning sifatini tavsiflamaydi.", f"Asset growth was accompanied by a {pct_str(loan_change)} expansion of the loan portfolio. This indicates larger lending operations but does not by itself describe their quality."))

        # Loan quality and reserves.  The statutory bank form reports the loan
        # line net of the reserve, so the gross book is net + reserve.
        reserve_lines = []
        reserves_now, reserves_open = fact_now("loan_reserves"), fact_before("loan_reserves")
        gross_book = template == "bank"
        loans_now = total(fact_now("loan_portfolio"), reserves_now) if gross_book else fact_now("loan_portfolio")
        loans_open = total(fact_before("loan_portfolio"), reserves_open) if gross_book else fact_before("loan_portfolio")
        reserve_change = change(reserves_now, reserves_open)["change_pct"]
        book_change = change(loans_now, loans_open)["change_pct"]
        book_name = tr(lang, "валовой кредитный портфель", "yalpi kredit portfeli", "the gross loan portfolio") if gross_book else tr(lang, "кредитный портфель", "kredit portfeli", "the loan portfolio")
        if reserve_change is not None and book_change is not None:
            reserve_up, book_up = reserve_change >= 0, book_change >= 0
            reserve_lines.append(tr(
                lang,
                f"Резервы под кредитные потери {'увеличились' if reserve_up else 'сократились'} на {format_number(abs(reserve_change))}%, тогда как {book_name} {'вырос' if book_up else 'сократился'} на {format_number(abs(book_change))}%.",
                f"Kredit yo‘qotishlari uchun zaxiralar {format_number(abs(reserve_change))}% ga {'oshdi' if reserve_up else 'kamaydi'}, {book_name} esa {format_number(abs(book_change))}% ga {'oshdi' if book_up else 'qisqardi'}.",
                f"Loan-loss reserves {'increased' if reserve_up else 'decreased'} by {format_number(abs(reserve_change))}%, while {book_name} {'grew' if book_up else 'contracted'} by {format_number(abs(book_change))}%.",
            ))
            if reserve_change > 0 and book_change >= 0 and reserve_change > book_change:
                reserve_lines.append(tr(lang, "Резервы росли быстрее кредитного портфеля. Это требует внимания, однако без данных о просрочке и классификации кредитов нельзя однозначно заключить, что качество портфеля ухудшилось.", "Zaxiralar kredit portfelidan tezroq o‘sdi. Bu e’tibor talab qiladi, ammo muddati o‘tgan kreditlar va kreditlar tasnifi haqida ma’lumotlarsiz portfel sifati yomonlashgan deb aniq xulosa chiqarib bo‘lmaydi.", "Reserves grew faster than the loan portfolio. This requires attention, but without data on overdue loans and loan classification it cannot be concluded that portfolio quality has deteriorated."))
            elif reserve_change > 0 and book_change < 0:
                reserve_lines.append(tr(lang, "Резервы увеличились при сокращении кредитного портфеля. Для объяснения динамики нужны данные о списаниях, восстановлении резервов и изменении качества кредитов.", "Kredit portfeli qisqargan holda zaxiralar oshdi. Dinamikani tushuntirish uchun hisobdan chiqarishlar, zaxiralarni tiklash va kreditlar sifati o‘zgarishi haqidagi ma’lumotlar kerak.", "Reserves increased while the loan portfolio contracted. Explaining this requires data on write-offs, reserve releases and changes in loan quality."))
        coverage_now, coverage_open = pct_of(reserves_now, loans_now), pct_of(reserves_open, loans_open)
        if coverage_now is not None:
            against = tr(lang, f" против {pct_str(coverage_open)}", f" ({pct_str(coverage_open)} o‘rniga)", f" versus {pct_str(coverage_open)}") if coverage_open is not None else ""
            reserve_lines.append(tr(
                lang,
                f"Отношение резервов к {'валовому кредитному портфелю' if gross_book else 'кредитному портфелю'} составило {pct_str(coverage_now)}{against}. Это аналитический коэффициент на основе отчётности, а не регуляторный норматив.",
                f"Zaxiralarning {'yalpi kredit portfeliga' if gross_book else 'kredit portfeliga'} nisbati {pct_str(coverage_now)}{against}ni tashkil etdi. Bu hisobotga asoslangan tahliliy koeffitsiyent, regulyativ me’yor emas.",
                f"The ratio of reserves to {'the gross loan portfolio' if gross_book else 'the loan portfolio'} was {pct_str(coverage_now)}{against}. This is an analytical ratio based on the financial statements, not a regulatory standard.",
            ))
        if reserves_now is not None:
            reserve_lines.append(tr(lang, "В доступной форме нет достаточной детализации по просроченным и обесцененным кредитам; поэтому уровень проблемной задолженности по ней оценить нельзя.", "Mavjud shaklda muddati o‘tgan va qadrsizlangan kreditlar bo‘yicha yetarli tafsilot yo‘q; shu sababli muammoli qarzdorlik darajasini u orqali baholab bo‘lmaydi.", "The available form does not provide enough detail on overdue and impaired loans, so the level of problem debt cannot be assessed from it."))
        if reserve_change is not None and reserve_change > 0:
            reserve_lines.append(tr(lang, "Рост резервов может отражать как увеличение кредитного риска, так и изменение оценки ожидаемых потерь. По одной балансовой динамике различить эти причины нельзя.", "Zaxiralarning o‘sishi kredit riskining oshishini ham, kutilayotgan yo‘qotishlar bahosining o‘zgarishini ham aks ettirishi mumkin. Faqat balans dinamikasi bo‘yicha bu sabablarni ajratib bo‘lmaydi.", "Reserve growth may reflect either higher credit risk or a change in the estimate of expected losses. Balance-sheet movements alone cannot distinguish between these causes."))

        # Deposits, funding and liquidity.
        funding_lines = []
        funds_change = moved("customer_funds")
        if funds_change is not None and assets_change is not None and funds_change > 0 and assets_change >= 0 and funds_change > assets_change:
            lead_pp = format_number(funds_change - assets_change)
            funding_lines.append(tr(lang, f"Средства клиентов увеличились на {pct_str(funds_change)}, опережая рост активов на {lead_pp} п.п. В отчётности это соответствует усилению клиентской ресурсной базы.", f"Mijozlar mablag‘lari {pct_str(funds_change)} ga oshib, aktivlar o‘sishidan {lead_pp} foiz punktga o‘zib ketdi. Hisobotda bu mijozlar resurs bazasining kuchayishiga mos keladi.", f"Customer funds increased by {pct_str(funds_change)}, outpacing asset growth by {lead_pp} pp. In the statements this corresponds to a stronger customer funding base."))
        if funds_change is not None and loan_change is not None:
            funding_lines.append(tr(lang, f"Депозиты {'выросли' if funds_change >= 0 else 'сократились'} на {format_number(abs(funds_change))}%, а кредитный портфель — на {pct_str(loan_change)}. Для дополнительной оценки можно рассмотреть их соотношение, но оно не заменяет полноценный анализ ликвидности.", f"Depozitlar {format_number(abs(funds_change))}% ga {'oshdi' if funds_change >= 0 else 'kamaydi'}, kredit portfeli esa {pct_str(loan_change)} ga o‘zgardi. Qo‘shimcha baholash uchun ularning nisbatini ko‘rib chiqish mumkin, ammo u to‘laqonli likvidlik tahlilini almashtirmaydi.", f"Deposits {'grew' if funds_change >= 0 else 'contracted'} by {format_number(abs(funds_change))}%, and the loan portfolio changed by {pct_str(loan_change)}. Their ratio can be considered as an additional check, but it does not replace a full liquidity analysis."))
        ldr = pct_of(fact_now("loan_portfolio"), fact_now("customer_funds"))
        if ldr is not None:
            funding_lines.append(tr(lang, f"Расчётное отношение кредитного портфеля к средствам клиентов (LDR) составляет {pct_str(ldr)}. Показатель описывает соотношение двух статей баланса и не является самостоятельной оценкой платёжеспособности банка.", f"Kredit portfelining mijozlar mablag‘lariga hisoblangan nisbati (LDR) {pct_str(ldr)}ni tashkil etadi. Ko‘rsatkich ikki balans moddasi nisbatini tavsiflaydi va bankning to‘lov qobiliyatini mustaqil baholash emas.", f"The calculated ratio of the loan portfolio to customer funds (LDR) is {pct_str(ldr)}. The ratio describes the relationship between two balance-sheet items and does not by itself assess the bank's solvency."))
        term_now, term_open = pct_of(fact_now("term_deposits"), fact_now("customer_funds")), pct_of(fact_before("term_deposits"), fact_before("customer_funds"))
        demand_now, demand_open = pct_of(fact_now("demand_deposits"), fact_now("customer_funds")), pct_of(fact_before("demand_deposits"), fact_before("customer_funds"))
        if term_now is not None and term_open is not None and term_now > term_open:
            funding_lines.append(tr(lang, f"Доля срочных вкладов в средствах клиентов увеличилась с {pct_str(term_open)} до {pct_str(term_now)}; структура клиентского фондирования сместилась в сторону срочных средств.", f"Mijozlar mablag‘laridagi muddatli omonatlar ulushi {pct_str(term_open)}dan {pct_str(term_now)}gacha oshdi; mijozlar hisobidan moliyalashtirish tuzilmasi muddatli mablag‘lar tomon siljidi.", f"The share of term deposits in customer funds rose from {pct_str(term_open)} to {pct_str(term_now)}; the customer funding mix shifted towards term funds."))
        if demand_now is not None and demand_open is not None and demand_now > demand_open:
            funding_lines.append(tr(lang, "Доля средств до востребования выросла. Это меняет структуру фондирования, но без данных о сроках активов и обязательств нельзя определить влияние на риск ликвидности.", "Talab qilinguncha mablag‘lar ulushi oshdi. Bu moliyalashtirish tuzilmasini o‘zgartiradi, ammo aktivlar va majburiyatlar muddatlari haqida ma’lumotlarsiz likvidlik riskiga ta’sirini aniqlab bo‘lmaydi.", "The share of demand funds increased. This changes the funding mix, but without data on the maturities of assets and liabilities its effect on liquidity risk cannot be determined."))
        liquid_keys = ("cash", "central_bank_balances", "due_from_banks")
        liquid_now = total(*(fact_now(key) for key in liquid_keys))
        liquid_open = total(*(fact_before(key) for key in liquid_keys))
        liquid_name = tr(lang, "Денежные средства и средства в центральном и других банках", "Pul mablag‘lari hamda markaziy va boshqa banklardagi mablag‘lar", "Cash and balances with the central bank and other banks")
        if liquid_now is None or liquid_open is None:
            liquid_now = total(fact_now("cash"), fact_now("central_bank_balances"))
            liquid_open = total(fact_before("cash"), fact_before("central_bank_balances"))
            liquid_name = tr(lang, "Денежные средства и средства в центральном банке", "Pul mablag‘lari va markaziy bankdagi mablag‘lar", "Cash and central bank balances")
        liquid_change = change(liquid_now, liquid_open)["change_pct"]
        if liquid_change is not None and liquid_change < 0:
            funding_lines.append(tr(lang, f"{liquid_name} сократились на {format_number(abs(liquid_change))}%. Для оценки ликвидности этого недостаточно: нужны данные о сроках, доступности и составе ликвидных активов.", f"{liquid_name} {format_number(abs(liquid_change))}% ga kamaydi. Likvidlikni baholash uchun bu yetarli emas: likvid aktivlarning muddatlari, mavjudligi va tarkibi haqida ma’lumotlar kerak.", f"{liquid_name} decreased by {format_number(abs(liquid_change))}%. This is not enough to assess liquidity: data on the maturities, availability and composition of liquid assets are needed."))
            if loan_change is not None and loan_change > 0:
                funding_lines.append(tr(lang, "Снижение отдельных денежных остатков сопровождается ростом кредитного портфеля. Это указывает на изменение размещения средств, но не позволяет само по себе сделать вывод о дефиците ликвидности.", "Ayrim pul qoldiqlarining kamayishi kredit portfelining o‘sishi bilan birga kechmoqda. Bu mablag‘larni joylashtirish o‘zgarganini ko‘rsatadi, ammo o‘z-o‘zidan likvidlik taqchilligi haqida xulosa chiqarishga imkon bermaydi.", "The decline in some cash balances is accompanied by growth in the loan portfolio. This indicates a reallocation of funds but does not by itself support a conclusion of a liquidity shortage."))
        elif liquid_change is not None:
            funding_lines.append(tr(lang, f"{liquid_name} увеличились на {pct_str(liquid_change)}; для оценки ликвидности нужны также данные о сроках, доступности и составе ликвидных активов.", f"{liquid_name} {pct_str(liquid_change)} ga oshdi; likvidlikni baholash uchun likvid aktivlarning muddatlari, mavjudligi va tarkibi haqida ham ma’lumotlar kerak.", f"{liquid_name} increased by {pct_str(liquid_change)}; assessing liquidity also requires data on the maturities, availability and composition of liquid assets."))

        balance_facts = [fact_sentence(key) for key in ("total_assets", "loan_portfolio", "loan_reserves", "cash", "customer_funds", "total_liabilities", "total_equity")]
        balance_facts = [item for item in balance_facts if item]
        horizontal_text = " ".join(filter(None, (
            tr(lang, "Горизонтальный анализ баланса. ", "Balansning gorizontal tahlili. ", "Horizontal balance-sheet analysis. ") + ("; ".join(balance_facts) if balance_facts else tr(lang, "Недостаточно сопоставимых строк.", "Taqqoslanadigan satrlar yetarli emas.", "Insufficient comparable lines.")) + ".",
            *asset_lines, *reserve_lines, *funding_lines,
        )))
        assets = fact_now("total_assets")
        vertical_text = vertical_narrative(
            ("loan_portfolio", "cash", "central_bank_balances", "due_from_banks"),
            tr(lang, "Вертикальный анализ показывает не только текущие доли, но и то, как изменилась модель размещения активов. ", "Vertikal tahlil nafaqat joriy ulushlarni, balki aktivlarni joylashtirish modeli qanday o‘zgarganini ham ko‘rsatadi. ", "Vertical analysis shows both current shares and how the asset-allocation model changed. "),
            bank_funding=True,
        )

        # Income and profitability.
        income_lines = []
        nii_before = fact_now("net_interest_income_before_provisions")
        if nii_before is None:
            nii_before = net_interest_income
        nii_after = fact_now("net_interest_income_after_provisions")
        provisions = fact_now("credit_loss_provisions")
        if nii_before is not None and nii_after is not None:
            income_lines.append(tr(lang, f"Чистый процентный доход до оценки кредитных потерь составил {amount_text(nii_before)}. После учёта расходов на оценку потерь он составил {amount_text(nii_after)}.", f"Kredit yo‘qotishlarini baholashgacha sof foizli daromad {amount_text(nii_before)}ni tashkil etdi. Yo‘qotishlarni baholash xarajatlari hisobga olingach, u {amount_text(nii_after)}ni tashkil etdi.", f"Net interest income before the credit-loss estimate was {amount_text(nii_before)}. After the credit-loss estimate it was {amount_text(nii_after)}."))
        elif nii_before is not None:
            income_lines.append(tr(lang, f"Чистый процентный доход до оценки кредитных потерь составил {amount_text(nii_before)}.", f"Kredit yo‘qotishlarini baholashgacha sof foizli daromad {amount_text(nii_before)}ni tashkil etdi.", f"Net interest income before the credit-loss estimate was {amount_text(nii_before)}."))
        provision_share = pct_of(provisions, nii_before) if provisions is not None and provisions > 0 else None
        if provision_share is not None:
            material = provision_share >= 20
            income_lines.append(tr(
                lang,
                f"Расходы на оценку кредитных потерь уменьшили чистый процентный результат на {pct_str(provision_share)}." + (" Их влияние существенно для итоговой оценки процентного бизнеса за период." if material else ""),
                f"Kredit yo‘qotishlarini baholash xarajatlari sof foizli natijani {pct_str(provision_share)} ga kamaytirdi." + (" Ularning ta’siri davr uchun foizli biznesning yakuniy bahosi uchun muhim." if material else ""),
                f"The credit-loss estimate reduced the net interest result by {pct_str(provision_share)}." + (" Its effect is material to the overall assessment of the interest business for the period." if material else ""),
            ))
        nii_prior = difference(fact_before("interest_income"), fact_before("interest_expenses"))
        nii_move = change(net_interest_income, nii_prior)["change_pct"] if nii_prior is not None and nii_prior > 0 else None
        if nii_move is not None:
            income_lines.append(tr(lang, f"Чистый процентный доход {'увеличился' if nii_move >= 0 else 'уменьшился'} на {format_number(abs(nii_move))}%. Для объяснения динамики следует отдельно рассмотреть процентные доходы и расходы.", f"Sof foizli daromad {format_number(abs(nii_move))}% ga {'oshdi' if nii_move >= 0 else 'kamaydi'}. Dinamikani tushuntirish uchun foizli daromad va xarajatlarni alohida ko‘rib chiqish kerak.", f"Net interest income {'increased' if nii_move >= 0 else 'decreased'} by {format_number(abs(nii_move))}%. Interest income and interest expense should be examined separately to explain the change."))
            income_move, expense_move = moved("interest_income"), moved("interest_expenses")
            if income_move is not None and expense_move is not None and max(income_move, expense_move) > 0:
                if income_move > expense_move:
                    income_lines.append(tr(lang, "Процентные доходы росли быстрее процентных расходов, что поддержало чистый процентный результат.", "Foizli daromadlar foizli xarajatlardan tezroq o‘sdi va bu sof foizli natijani qo‘llab-quvvatladi.", "Interest income grew faster than interest expense, which supported the net interest result."))
                elif expense_move > income_move:
                    income_lines.append(tr(lang, "Процентные расходы росли быстрее процентных доходов; это оказало давление на чистый процентный результат.", "Foizli xarajatlar foizli daromadlardan tezroq o‘sdi; bu sof foizli natijaga bosim o‘tkazdi.", "Interest expense grew faster than interest income, which put pressure on the net interest result."))
        fee_net = difference(fact_now("fee_income"), fact_now("fee_expenses"))
        fx_net = difference(fact_now("fx_income"), fact_now("fx_expenses"))
        if net_revenue_before_opex is not None and nii_after is not None and fee_net is not None and fx_net is not None:
            other = net_revenue_before_opex - nii_after - fee_net - fx_net
            sources = {
                "interest": (nii_after, tr(lang, "процентные", "foizli", "interest")),
                "fee": (fee_net, tr(lang, "комиссионные", "komission", "fee and commission")),
                "fx": (fx_net, tr(lang, "валютные", "valyuta", "foreign-exchange")),
                "other": (other, tr(lang, "прочие", "boshqa", "other")),
            }
            main = max(sources.values(), key=lambda item: item[0])
            if main[0] > 0:
                income_lines.append(tr(lang, f"Основной вклад в доходы до операционных расходов внесли {main[1]} операции.", f"Operatsion xarajatlargacha bo‘lgan daromadlarga asosiy hissani {main[1]} operatsiyalar qo‘shdi.", f"{main[1].capitalize()} operations made the main contribution to income before operating expenses."))
        if fx_net is not None and fx_net != 0:
            positive = fx_net > 0
            income_lines.append(tr(lang, f"Чистый результат по валютным операциям составил {amount_text(fx_net)} и оказал {'положительное' if positive else 'отрицательное'} влияние на прибыль периода.", f"Valyuta operatsiyalari bo‘yicha sof natija {amount_text(fx_net)}ni tashkil etdi va davr foydasiga {'ijobiy' if positive else 'salbiy'} ta’sir ko‘rsatdi.", f"The net result from foreign-exchange operations was {amount_text(fx_net)} and had a {'positive' if positive else 'negative'} effect on profit for the period."))

        if total_income is not None and total_income > 0 and interest_income >= 0 and noninterest_income >= 0:
            interest_share = pct_of(interest_income, total_income)
            noninterest_share = pct_of(noninterest_income, total_income)
            income_mix = tr(
                lang,
                f"Совокупные раскрытые доходы банка за {period_text} составили {display_money(total_income)} {money_unit}: процентные доходы — {amount_text(interest_income)} ({pct_str(interest_share)}), непроцентные — {amount_text(noninterest_income)} ({pct_str(noninterest_share)}).",
                f"Bankning {period_text} uchun jami oshkor qilingan daromadi {display_money(total_income)} {money_unit}: foizli daromad — {amount_text(interest_income)} ({pct_str(interest_share)}), foizsiz daromad — {amount_text(noninterest_income)} ({pct_str(noninterest_share)}).",
                f"The bank reported total disclosed income of {display_money(total_income)} {money_unit} for {period_text}: interest income was {amount_text(interest_income)} ({pct_str(interest_share)}) and non-interest income was {amount_text(noninterest_income)} ({pct_str(noninterest_share)}).",
            )
        else:
            available_income = "; ".join(filter(None, (fact_sentence("interest_income"), fact_sentence("noninterest_income"))))
            income_mix = available_income or tr(lang, "Недостаточно данных для расчёта структуры доходов.", "Daromadlar tarkibini hisoblash uchun ma’lumot yetarli emas.", "Insufficient data to calculate the income mix.")
        income_text = tr(lang, "Доходы и прибыльность. ", "Daromadlar va rentabellik. ", "Income and profitability. ") + " ".join([income_mix, *income_lines])

        expense_parts = []
        if interest_expenses is not None:
            expense_parts.append(tr(lang, f"процентные расходы — {amount_text(interest_expenses)}", f"foizli xarajatlar — {amount_text(interest_expenses)}", f"interest expense was {amount_text(interest_expenses)}"))
        if interest_expense_share is not None:
            expense_parts.append(tr(
                lang,
                f"они равны {pct_str(interest_expense_share)} процентных доходов: это доля расходов в доходах, а не стоимость фондирования, для которой нужны средние процентные обязательства и ставки",
                f"bu foizli daromadning {pct_str(interest_expense_share)}iga teng: bu daromaddagi xarajat ulushi, moliyalashtirish qiymati emas; buning uchun o‘rtacha foizli majburiyatlar va stavkalar kerak",
                f"that equals {pct_str(interest_expense_share)} of interest income; this is an expense-to-income share, not funding cost, which requires average interest-bearing liabilities and rates",
            ))
        if operating_expenses is not None:
            expense_parts.append(tr(lang, f"операционные расходы — {amount_text(operating_expenses)}", f"operatsion xarajatlar — {amount_text(operating_expenses)}", f"operating expenses were {amount_text(operating_expenses)}"))
        if noninterest_expenses is not None:
            expense_parts.append(tr(lang, f"непроцентные расходы — {amount_text(noninterest_expenses)}", f"foizsiz xarajatlar — {amount_text(noninterest_expenses)}", f"non-interest expenses were {amount_text(noninterest_expenses)}"))
        expense_body = "; ".join(expense_parts)
        expense_text = tr(lang, "Расходы и стоимость ресурсов. ", "Xarajatlar va resurslar qiymati. ", "Expenses and funding cost. ") + (expense_body[:1].upper() + expense_body[1:] if expense_parts else tr(lang, "Недостаточно раскрытых данных для расчёта структуры расходов.", "Xarajatlar tarkibini hisoblash uchun ma’lumot yetarli emas.", "Insufficient disclosed data to calculate the expense mix.")) + "."

        profit_parts = []
        if net_income is not None:
            profit_parts.append(tr(lang, f"Чистая прибыль составила {amount_text(net_income)}", f"Sof foyda {amount_text(net_income)}ni tashkil etdi", f"Net profit was {amount_text(net_income)}"))
            if net_change is not None:
                profit_parts.append(tr(lang, f"изменение к сопоставимому периоду — {format_number(net_change)}%", f"taqqoslanadigan davrga nisbatan o‘zgarish — {format_number(net_change)}%", f"the change from the comparable period was {format_number(net_change)}%"))
        effective_tax = pct_of(tax_amount, profit_before_tax)
        if profit_before_tax is not None:
            profit_parts.append(tr(lang, f"прибыль до налога — {amount_text(profit_before_tax)}", f"soliqdan oldingi foyda — {amount_text(profit_before_tax)}", f"profit before tax was {amount_text(profit_before_tax)}"))
        if tax_amount is not None:
            tax_source = tr(lang, "раскрытый налог", "oshkor qilingan soliq", "disclosed tax") if disclosed_tax is not None else tr(lang, "расчётная разница между прибылью до и после налога", "soliqdan oldingi va keyingi foyda o‘rtasidagi hisoblangan farq", "the calculated difference between pre- and post-tax profit")
            effective_tax_text = pct_str(effective_tax) if effective_tax is not None else tr(lang, "не рассчитывается", "hisoblanmaydi", "not calculable")
            profit_parts.append(tr(lang, f"налоговый расход — {amount_text(tax_amount)}, эффективная ставка — {effective_tax_text} ({tax_source})", f"soliq xarajati — {amount_text(tax_amount)}, samarali stavka — {effective_tax_text} ({tax_source})", f"tax expense was {amount_text(tax_amount)}, giving an effective rate of {effective_tax_text} ({tax_source})"))
        pbt_move = moved("profit_before_tax")
        tax_before = fact_before("tax")
        reconciles = all(
            item is not None for item in (profit_before_tax, disclosed_tax, net_income, fact_before("profit_before_tax"), tax_before, fact_before("net_income"))
        ) and profit_before_tax - disclosed_tax == net_income and fact_before("profit_before_tax") - tax_before == fact_before("net_income")
        pbt_sentence = ""
        if pbt_move is not None and net_change is not None and reconciles:
            pbt_sentence = " " + tr(lang, f"Прибыль до налогообложения {'увеличилась' if pbt_move >= 0 else 'снизилась'} на {format_number(abs(pbt_move))}%, а чистая прибыль — на {pct_str(net_change)}. Разница связана с изменением налоговых расходов.", f"Soliqqa tortishgacha foyda {format_number(abs(pbt_move))}% ga {'oshdi' if pbt_move >= 0 else 'kamaydi'}, sof foyda esa {pct_str(net_change)} ga o‘zgardi. Farq soliq xarajatlarining o‘zgarishi bilan bog‘liq.", f"Profit before tax {'increased' if pbt_move >= 0 else 'decreased'} by {format_number(abs(pbt_move))}%, and net profit changed by {pct_str(net_change)}. The difference reflects the change in tax expense.")
        profit_text = tr(lang, "Прибыль и налог. ", "Foyda va soliq. ", "Profit and tax. ") + ("; ".join(profit_parts) if profit_parts else tr(lang, "Недостаточно данных.", "Ma’lumot yetarli emas.", "Insufficient data.")) + "." + pbt_sentence + " " + tr(
            lang,
            "Отклонение эффективной ставки от законодательной само по себе не доказывает наличие льгот: для вывода нужны налоговые примечания.",
            "Samarali stavkaning qonuniy stavkadan farqi imtiyoz mavjudligini o‘z-o‘zidan isbotlamaydi: xulosa uchun soliq izohlari kerak.",
            "A difference from the statutory rate does not by itself prove tax relief; tax notes are needed for that conclusion.",
        )
        results_text = " ".join((income_text, expense_text, profit_text))

        # Ratios, operating efficiency and capital.
        ratio_parts = []
        if net_interest_income is not None:
            ratio_parts.append(tr(lang, f"NII = процентные доходы − процентные расходы = {amount_text(net_interest_income)}", f"NII = foizli daromad − foizli xarajat = {amount_text(net_interest_income)}", f"NII = interest income − interest expense = {amount_text(net_interest_income)}"))
        if interest_expense_share is not None:
            ratio_parts.append(tr(lang, f"Доля процентных расходов в процентных доходах = {pct_str(interest_expense_share)}", f"Foizli xarajatlarning foizli daromaddagi ulushi = {pct_str(interest_expense_share)}", f"Interest expense / interest income = {pct_str(interest_expense_share)}"))
        if ldr is not None:
            ratio_parts.append(f"LDR = {tr(lang, 'кредиты / средства клиентов', 'kreditlar / mijozlar mablag‘i', 'loans / customer funds')} = {pct_str(ldr)}")
        if cost_to_income is not None:
            ratio_parts.append(f"Cost-to-Income = {tr(lang, 'операционные расходы / чистый доход до операционных расходов', 'operatsion xarajatlar / operatsion xarajatlargacha sof daromad', 'operating expenses / net revenue before operating expenses')} = {pct_str(cost_to_income)}")
        if coverage_now is not None:
            ratio_parts.append(f"{tr(lang, 'Резервы / валовой кредитный портфель', 'Zaxiralar / yalpi kredit portfeli', 'Loan reserves / gross loan portfolio') if gross_book else tr(lang, 'Резервы / кредитный портфель', 'Zaxiralar / kredit portfeli', 'Loan reserves / loan portfolio')} = {pct_str(coverage_now)}")
        capital_share = pct_of(fact_now("total_equity"), assets)
        capital_share_open = pct_of(fact_before("total_equity"), fact_before("total_assets"))
        if capital_share is not None:
            ratio_parts.append(f"{tr(lang, 'Капитал / активы', 'Kapital / aktivlar', 'Equity / assets')} = {pct_str(capital_share)}")
        months = int(str(period)[-1]) * 3 if re.fullmatch(r"\d{4}Q[1-4]", str(period)) else 12
        assets_open = fact_before("total_assets")
        equity_now, equity_open = fact_now("total_equity"), fact_before("total_equity")
        average_basis = assets is not None and assets_open is not None and equity_now is not None and equity_open is not None
        asset_base = total(assets, assets_open) / 2 if assets is not None and assets_open is not None else assets
        equity_base = total(equity_now, equity_open) / 2 if equity_now is not None and equity_open is not None else equity_now
        annualized_profit = net_income * Decimal(12) / months if net_income is not None else None
        roa, roe = pct_of(annualized_profit, asset_base), pct_of(annualized_profit, equity_base)
        yearly = tr(lang, " в годовом выражении", " yillik hisobda", " on an annualised basis") if months < 12 else ""
        efficiency_lines = []
        if roa is not None:
            ratio_parts.append(f"{tr(lang, 'ROA (в годовом выражении)', 'ROA (yilliklashtirilgan)', 'ROA (annualized)')} = {pct_str(roa)}")
            efficiency_lines.append(tr(
                lang,
                f"Рентабельность активов (ROA), рассчитанная по доступным данным, составила {pct_str(roa)}{yearly}. Это аналитическая оценка за {period_text} с использованием {'средних' if average_basis else 'конечных'} активов.",
                f"Mavjud ma’lumotlar bo‘yicha hisoblangan aktivlar rentabelligi (ROA){yearly} {pct_str(roa)}ni tashkil etdi. Bu {period_text} uchun {'o‘rtacha' if average_basis else 'davr oxiridagi'} aktivlardan foydalangan holda tahliliy baho.",
                f"Return on assets (ROA), calculated from the available data, was {pct_str(roa)}{yearly}. This is an analytical estimate for {period_text} using {'average' if average_basis else 'closing'} assets.",
            ))
        if roe is not None:
            ratio_parts.append(f"{tr(lang, 'ROE (в годовом выражении)', 'ROE (yilliklashtirilgan)', 'ROE (annualized)')} = {pct_str(roe)}")
            efficiency_lines.append(tr(lang, f"Рентабельность капитала (ROE) составила {pct_str(roe)}{yearly}. При сравнении важно учитывать, что расчёт может быть чувствителен к использованию конечного или среднего капитала и к пересчёту неполного года.", f"Kapital rentabelligi (ROE){yearly} {pct_str(roe)}ni tashkil etdi. Taqqoslashda hisob davr oxiridagi yoki o‘rtacha kapitaldan foydalanishga va to‘liq bo‘lmagan yilni qayta hisoblashga sezgir bo‘lishi mumkinligini hisobga olish muhim.", f"Return on equity (ROE) was {pct_str(roe)}{yearly}. When comparing, note that the calculation can be sensitive to using closing or average equity and to annualising a partial year."))
        if cost_to_income is not None:
            efficiency_lines.append(tr(lang, f"Операционные расходы составили {pct_str(cost_to_income)} от выбранной базы операционных доходов (Cost-to-Income). В расчёте использована формула: операционные расходы / чистый доход до операционных расходов.", f"Operatsion xarajatlar tanlangan operatsion daromadlar bazasining {pct_str(cost_to_income)}ini tashkil etdi (Cost-to-Income). Hisobda formula qo‘llanildi: operatsion xarajatlar / operatsion xarajatlargacha sof daromad.", f"Operating expenses were {pct_str(cost_to_income)} of the selected operating-income base (Cost-to-Income). The formula used is: operating expenses / net revenue before operating expenses."))
            cir_before = pct_of(fact_before("operating_expenses"), fact_before("net_revenue_before_operating_expenses"))
            if cir_before is not None and cost_to_income < cir_before:
                efficiency_lines.append(tr(lang, f"Показатель Cost-to-Income снизился с {pct_str(cir_before)} до {pct_str(cost_to_income)}, что соответствует уменьшению доли расходов в рассчитанной базе доходов. Это не обязательно означает абсолютное сокращение расходов.", f"Cost-to-Income ko‘rsatkichi {pct_str(cir_before)}dan {pct_str(cost_to_income)}gacha pasaydi, bu hisoblangan daromad bazasidagi xarajatlar ulushining kamayishiga mos keladi. Bu xarajatlar mutlaq qisqarganini anglatishi shart emas.", f"Cost-to-Income fell from {pct_str(cir_before)} to {pct_str(cost_to_income)}, meaning expenses took a smaller share of the calculated income base. This does not necessarily mean expenses fell in absolute terms."))
            elif cir_before is not None and cost_to_income > cir_before:
                efficiency_lines.append(tr(lang, "Операционные расходы росли быстрее доходной базы, поэтому расчётный Cost-to-Income увеличился.", "Operatsion xarajatlar daromad bazasidan tezroq o‘sdi, shu sababli hisoblangan Cost-to-Income oshdi.", "Operating expenses grew faster than the income base, so the calculated Cost-to-Income rose."))
        equity_move = moved("total_equity")
        if equity_move is not None and assets_change is not None:
            equity_up, assets_up = equity_move >= 0, assets_change >= 0
            assets_clause = tr(lang, f"а активы — на {format_number(abs(assets_change))}%", f"aktivlar esa {format_number(abs(assets_change))}% ga", f"and assets by {format_number(abs(assets_change))}%") if equity_up == assets_up else tr(lang, f"а активы {'выросли' if assets_up else 'сократились'} на {format_number(abs(assets_change))}%", f"aktivlar esa {format_number(abs(assets_change))}% ga {'oshdi' if assets_up else 'kamaydi'}", f"while assets {'grew' if assets_up else 'contracted'} by {format_number(abs(assets_change))}%")
            shift = tr(lang, f" Балансовое соотношение капитала к активам изменилось с {pct_str(capital_share_open)} до {pct_str(capital_share)}.", f" Kapitalning aktivlarga balans nisbati {pct_str(capital_share_open)}dan {pct_str(capital_share)}gacha o‘zgardi.", f" The balance-sheet ratio of equity to assets moved from {pct_str(capital_share_open)} to {pct_str(capital_share)}.") if capital_share is not None and capital_share_open is not None else ""
            efficiency_lines.append(tr(lang, f"Капитал {'вырос' if equity_up else 'сократился'} на {format_number(abs(equity_move))}%, {assets_clause}.", f"Kapital {format_number(abs(equity_move))}% ga {'oshdi' if equity_up else 'kamaydi'}, {assets_clause}.", f"Equity {'grew' if equity_up else 'contracted'} by {format_number(abs(equity_move))}% {assets_clause}.") + shift)
        if capital_share is not None:
            efficiency_lines.append(tr(lang, "Соотношение капитала и активов рассчитано по бухгалтерскому балансу и не является нормативом достаточности капитала.", "Kapital va aktivlar nisbati buxgalteriya balansi bo‘yicha hisoblangan va kapital yetarliligi me’yori emas.", "The equity-to-assets ratio is calculated from the accounting balance sheet and is not a capital adequacy ratio."))
        efficiency_lines.append(tr(lang, f"По предоставленной форме {nsbu_name} нельзя подтвердить соблюдение банковских пруденциальных нормативов; для этого требуются регуляторная отчётность и соответствующие нормативные данные.", f"Taqdim etilgan {nsbu_name} shakli bo‘yicha bankning prudensial me’yorlariga rioya qilinishini tasdiqlab bo‘lmaydi; buning uchun regulyativ hisobot va tegishli me’yoriy ma’lumotlar kerak.", f"The {nsbu_name} form provided cannot confirm compliance with prudential banking ratios; that requires regulatory reporting and the relevant regulatory data."))
        ratio_text = tr(lang, "Коэффициентный анализ. ", "Koeffitsiyentlar tahlili. ", "Ratio analysis. ") + ("; ".join(ratio_parts) if ratio_parts else tr(lang, "Недостаточно компонентов для расчёта.", "Hisoblash komponentlari yetarli emas.", "Insufficient components for calculation.")) + ". " + " ".join(efficiency_lines)
        balance_text = tr(lang, "Сводная оценка. ", "Yakuniy baho. ", "Summary assessment. ") + sector_conclusion()
        if total_expenses is None:
            balance_text += " " + tr(lang, "Полная сумма расходов не рассчитана, поскольку не все необходимые строки раскрыты.", "Barcha zarur satrlar oshkor qilinmagani uchun jami xarajatlar hisoblanmadi.", "Total expenses were not calculated because not all required lines were disclosed.")
        narrative_blocks["performance"] = [
            {"lead": tr(lang, "Доходы и прибыльность", "Daromadlar va rentabellik", "Income and profitability"), "text": income_text},
            {"lead": tr(lang, "Расходы и стоимость ресурсов", "Xarajatlar va resurslar qiymati", "Expenses and resource cost"), "text": expense_text},
            {"lead": tr(lang, "Прибыль и налоги", "Foyda va soliqlar", "Profit and tax"), "text": profit_text},
            {"lead": tr(lang, "Операционная эффективность и капитал", "Operatsion samaradorlik va kapital", "Operating efficiency and capital"), "text": " ".join(efficiency_lines)},
        ]
        position_blocks = [
            (tr(lang, "Активы и кредитный портфель", "Aktivlar va kredit portfeli", "Assets and loan portfolio"), asset_lines),
            (tr(lang, "Качество кредитов и резервы", "Kreditlar sifati va zaxiralar", "Loan quality and reserves"), reserve_lines),
            (tr(lang, "Депозиты, финансирование и ликвидность", "Depozitlar, moliyalashtirish va likvidlik", "Deposits, funding and liquidity"), funding_lines),
        ]
        narrative_blocks["position"] = [
            {"lead": lead, "text": " ".join(lines)} for lead, lines in position_blocks if lines
        ] + [{"lead": tr(lang, "Структура активов и капитала", "Aktivlar va kapital tarkibi", "Asset and capital structure"), "text": vertical_text}]
        return [intro, horizontal_text, vertical_text, results_text, ratio_text, balance_text]

    def insurance_analysis_paragraphs():
        """Insurer narrative that keeps premiums, revenue, result and profit apart."""
        premiums = fact_now("insurance_premiums")
        premium_change = moved("insurance_premiums")
        ceded = fact_now("ceded_premiums")
        ceded_before = fact_before("ceded_premiums")
        revenue = fact_now("revenue")
        revenue_change = moved("revenue")
        service_cost = fact_now("insurance_service_cost")
        service_cost_change = moved("insurance_service_cost")
        service_result = fact_now("insurance_service_result")
        service_result_before = fact_before("insurance_service_result")
        if service_result is None:
            service_result = difference(revenue, service_cost)
            service_result_before = difference(fact_before("revenue"), fact_before("insurance_service_cost"))
        gross_reserves = fact_now("gross_insurance_reserves")
        reinsurer_reserves = fact_now("reinsurer_share_in_reserves")
        net_reserves = fact_now("net_insurance_reserves")
        operating_income = fact_now("operating_income")
        operating_change = moved("operating_income")
        net_income = fact_now("net_income")
        net_change = moved("net_income")
        claims = fact_now("insurance_claims")

        highlights = []
        if premium_change is not None:
            highlights.append(tr(lang, f"Страховые премии изменились на {format_number(premium_change)}%.", f"Sug‘urta mukofotlari {format_number(premium_change)}% ga o‘zgardi.", f"Insurance premiums changed {format_number(premium_change)}%."))
        operating_before = fact_before("operating_income")
        if operating_change is not None and net_change is not None and operating_income is not None and operating_income > 0 and operating_before is not None and operating_before > 0:
            highlights.append(tr(lang, f"Операционный результат изменился на {format_number(operating_change)}%, а чистая прибыль — на {format_number(net_change)}%.", f"Operatsion natija {format_number(operating_change)}%, sof foyda esa {format_number(net_change)}% ga o‘zgardi.", f"The operating result changed {format_number(operating_change)}% while net profit changed {format_number(net_change)}%."))
        highlights.append(tr(lang, "В страховании важно не смешивать начисленные премии, признанную выручку от страховых услуг, страховой результат и чистую прибыль: это разные показатели и этапы учёта.", "Sug‘urtada hisoblangan mukofotlar, tan olingan sug‘urta xizmatlari tushumi, sug‘urta natijasi va sof foydani aralashtirmaslik muhim: bular turli ko‘rsatkichlar va hisobning turli bosqichlaridir.", "In insurance, written premiums, recognised insurance-service revenue, the insurance result and net profit must not be mixed: they are different indicators and different accounting stages."))
        intro = f"{headline} " + " ".join(highlights)

        # Premiums and scale of business.
        premium_lines = []
        if premiums is not None:
            if premium_change is not None and premium_change >= 0:
                premium_lines.append(tr(lang, f"Объём страховых премий за период составил {amount_text(premiums)}, увеличившись на {pct_str(premium_change)} к сопоставимому периоду.", f"Davr uchun sug‘urta mukofotlari hajmi {amount_text(premiums)}ni tashkil etib, taqqoslanadigan davrga nisbatan {pct_str(premium_change)} ga oshdi.", f"Insurance premiums for the period were {amount_text(premiums)}, up {pct_str(premium_change)} on the comparable period."))
                premium_lines.append(tr(lang, "Рост премий указывает на расширение объёма привлечённого бизнеса, но сам по себе не подтверждает улучшение прибыльности или качества страхового портфеля.", "Mukofotlarning o‘sishi jalb qilingan biznes hajmi kengayganini ko‘rsatadi, ammo o‘z-o‘zidan rentabellik yoki sug‘urta portfeli sifati yaxshilanganini tasdiqlamaydi.", "Premium growth indicates a larger volume of business written, but does not by itself confirm better profitability or portfolio quality."))
            else:
                premium_lines.append(tr(lang, f"Объём страховых премий за период составил {amount_text(premiums)}.", f"Davr uchun sug‘urta mukofotlari hajmi {amount_text(premiums)}ni tashkil etdi.", f"Insurance premiums for the period were {amount_text(premiums)}."))
                if premium_change is not None:
                    premium_lines.append(tr(lang, f"Премии сократились на {format_number(abs(premium_change))}%. Для оценки устойчивости этой динамики нужны сопоставимые данные по видам страхования и каналам продаж.", f"Mukofotlar {format_number(abs(premium_change))}% ga qisqardi. Bu dinamikaning barqarorligini baholash uchun sug‘urta turlari va sotuv kanallari bo‘yicha taqqoslanadigan ma’lumotlar kerak.", f"Premiums fell by {format_number(abs(premium_change))}%. Comparable data by line of insurance and sales channel are needed to judge whether this is lasting."))
        if premium_change is not None and revenue_change is not None:
            premium_lines.append(tr(lang, f"Премии {'выросли' if premium_change >= 0 else 'снизились'} на {format_number(abs(premium_change))}%, тогда как чистая выручка от страховых услуг изменилась на {pct_str(revenue_change)}. Показатели отражают разные этапы учёта, поэтому их нельзя считать взаимозаменяемыми.", f"Mukofotlar {format_number(abs(premium_change))}% ga {'oshdi' if premium_change >= 0 else 'kamaydi'}, sug‘urta xizmatlaridan sof tushum esa {pct_str(revenue_change)} ga o‘zgardi. Ko‘rsatkichlar hisobning turli bosqichlarini aks ettiradi, shuning uchun ularni bir-birining o‘rnini bosuvchi deb hisoblab bo‘lmaydi.", f"Premiums {'rose' if premium_change >= 0 else 'fell'} by {format_number(abs(premium_change))}%, while net insurance-service revenue changed by {pct_str(revenue_change)}. The indicators reflect different accounting stages, so they cannot be treated as interchangeable."))

        # Reinsurance and risk retention (premium based, from ceded line c012).
        retention_lines = []
        ceded_share = pct_of(ceded, premiums)
        ceded_share_before = pct_of(ceded_before, fact_before("insurance_premiums"))
        if ceded_share is not None:
            versus = tr(lang, f" — против {pct_str(ceded_share_before)} в сопоставимом периоде", f" — taqqoslanadigan davrdagi {pct_str(ceded_share_before)}ga qarshi", f", versus {pct_str(ceded_share_before)} in the comparable period") if ceded_share_before is not None else ""
            retention_lines.append(tr(lang, f"Переданные перестраховщикам премии составили {pct_str(ceded_share)} от валовых премий{versus}.", f"Qayta sug‘urtalovchilarga berilgan mukofotlar yalpi mukofotlarning {pct_str(ceded_share)}ini tashkil etdi{versus}.", f"Premiums ceded to reinsurers were {pct_str(ceded_share)} of gross premiums{versus}."))
            if ceded_share_before is not None and ceded_share > ceded_share_before:
                retention_lines.append(tr(lang, "Доля переданных премий увеличилась. Это указывает на большую передачу премиального потока перестраховщикам, но не позволяет без дополнительных данных оценить снижение риска или экономическую эффективность перестрахования.", "Berilgan mukofotlar ulushi oshdi. Bu mukofotlar oqimining qayta sug‘urtalovchilarga ko‘proq o‘tkazilganini ko‘rsatadi, ammo qo‘shimcha ma’lumotlarsiz riskning kamayishini yoki qayta sug‘urtalashning iqtisodiy samaradorligini baholashga imkon bermaydi.", "The share of ceded premiums increased. This indicates that more of the premium flow is passed to reinsurers, but without further data it does not show whether risk fell or whether the reinsurance is economically efficient."))
            if ceded_share_before is not None and ceded_share != ceded_share_before:
                retention_lines.append(tr(lang, "Изменение переданных премий может быть связано с изменением структуры бизнеса или перестраховочной программы; одной отчётности недостаточно, чтобы установить причину.", "Berilgan mukofotlarning o‘zgarishi biznes tuzilmasi yoki qayta sug‘urtalash dasturining o‘zgarishi bilan bog‘liq bo‘lishi mumkin; sababni aniqlash uchun birgina hisobot yetarli emas.", "The change in ceded premiums may reflect a change in the business mix or the reinsurance programme; the statements alone are not enough to establish the cause."))
            retained = difference(premiums, ceded)
            retention_lines.append(tr(lang, f"Расчётные удержанные премии составили {amount_text(retained)}: валовые премии за вычетом переданных перестраховщикам премий.", f"Hisoblangan ushlab qolingan mukofotlar {amount_text(retained)}ni tashkil etdi: yalpi mukofotlardan qayta sug‘urtalovchilarga berilgan mukofotlar ayirilgan.", f"Calculated retained premiums were {amount_text(retained)}: gross premiums less premiums ceded to reinsurers."))
            retention_lines.append(tr(lang, f"Доля удержания премий составила {pct_str(pct_of(retained, premiums))}. Это расчёт по премиям и не тождественно доле удержания страховых убытков.", f"Mukofotlarni ushlab qolish ulushi {pct_str(pct_of(retained, premiums))}ni tashkil etdi. Bu mukofotlar bo‘yicha hisob bo‘lib, sug‘urta zararlarini ushlab qolish ulushiga teng emas.", f"The premium retention rate was {pct_str(pct_of(retained, premiums))}. This is a premium-based calculation and is not the same as the retention of insurance losses."))
        reserve_retention = pct_of(net_reserves, gross_reserves)
        if reserve_retention is not None:
            retention_lines.append(tr(lang, f"Отдельно от премий: после учёта доли перестраховщиков на компании остаётся {pct_str(reserve_retention)} валовых технических резервов (удержание резервов).", f"Mukofotlardan alohida: qayta sug‘urtalovchilar ulushi hisobga olingach, kompaniyada yalpi texnik zaxiralarning {pct_str(reserve_retention)}i qoladi (zaxiralarni ushlab qolish).", f"Separately from premiums, after the reinsurers' share the company retains {pct_str(reserve_retention)} of gross technical reserves (reserve retention)."))
        if ceded_share is not None or reserve_retention is not None:
            retention_lines.append(tr(lang, "Для оценки зависимости от перестрахования важно сопоставлять переданные премии с долей перестраховщиков в выплатах и технических резервах — если такие данные раскрыты.", "Qayta sug‘urtalashga bog‘liqlikni baholash uchun berilgan mukofotlarni qayta sug‘urtalovchilarning to‘lovlar va texnik zaxiralardagi ulushi bilan solishtirish muhim — agar bunday ma’lumotlar oshkor qilingan bo‘lsa.", "To assess dependence on reinsurance, ceded premiums should be compared with the reinsurers' share of claims and technical reserves — where these are disclosed."))

        # Insurance services, claims and result.
        service_lines = []
        if revenue is not None:
            service_lines.append(tr(lang, f"Доход от страховых услуг составил {amount_text(revenue)}. Показатель отражает признанный в отчётности доход за период, а не обязательно сумму начисленных премий.", f"Sug‘urta xizmatlaridan daromad {amount_text(revenue)}ni tashkil etdi. Ko‘rsatkich hisobotda tan olingan davr daromadini aks ettiradi va hisoblangan mukofotlar summasiga teng bo‘lishi shart emas.", f"Insurance-service revenue was {amount_text(revenue)}. It reflects the revenue recognised for the period, not necessarily the amount of premiums written."))
            service_lines.append(tr(lang, "Чистая выручка от страховых услуг включает премии за вычетом переданных в перестрахование, результат изменения страховых резервов и прочие доходы от страховых услуг (стр. 010–050 формы) и поэтому отличается от объёма премий.", "Sug‘urta xizmatlaridan sof tushum qayta sug‘urtaga berilganlari ayirilgan mukofotlar, sug‘urta zaxiralari o‘zgarishi natijasi va boshqa sug‘urta xizmatlari daromadlarini (shaklning 010–050-satrlari) o‘z ichiga oladi, shuning uchun mukofotlar hajmidan farq qiladi.", "Net insurance-service revenue includes premiums net of reinsurance ceded, the result of changes in insurance reserves and other insurance-service income (form lines 010–050), so it differs from premium volume."))
        if service_cost_change is not None and revenue_change is not None:
            if service_cost_change > 0 and service_cost_change > revenue_change:
                gap = format_number(service_cost_change - revenue_change) if revenue_change >= 0 else None
                service_lines.append(tr(
                    lang,
                    f"Расходы на страховые услуги увеличились на {pct_str(service_cost_change)}, опережая рост чистой выручки на {gap} п.п." if gap else f"Расходы на страховые услуги увеличились на {pct_str(service_cost_change)} при снижении чистой выручки на {format_number(abs(revenue_change))}%.",
                    f"Sug‘urta xizmatlari xarajatlari {pct_str(service_cost_change)} ga oshib, sof tushum o‘sishidan {gap} foiz punktga o‘zib ketdi." if gap else f"Sof tushum {format_number(abs(revenue_change))}% ga kamaygani holda sug‘urta xizmatlari xarajatlari {pct_str(service_cost_change)} ga oshdi.",
                    f"Insurance-service expenses rose by {pct_str(service_cost_change)}, outpacing net revenue growth by {gap} pp." if gap else f"Insurance-service expenses rose by {pct_str(service_cost_change)} while net revenue fell by {format_number(abs(revenue_change))}%.",
                ))
            elif service_cost_change < 0:
                service_lines.append(tr(lang, "Снижение расходов на страховые услуги поддержало результат периода, однако для оценки устойчивости эффекта нужно проверить, не связан ли он с изменением резервов или объёма бизнеса.", "Sug‘urta xizmatlari xarajatlarining kamayishi davr natijasini qo‘llab-quvvatladi, ammo ta’sir barqarorligini baholash uchun u zaxiralar yoki biznes hajmi o‘zgarishi bilan bog‘liq emasligini tekshirish kerak.", "Lower insurance-service expenses supported the result for the period, but to judge whether the effect will last it must be checked whether it stems from changes in reserves or business volume."))
            else:
                service_lines.append(tr(lang, f"Расходы на страховые услуги выросли на {pct_str(service_cost_change)} — медленнее чистой выручки ({pct_str(revenue_change)}).", f"Sug‘urta xizmatlari xarajatlari {pct_str(service_cost_change)} ga oshdi — sof tushumdan ({pct_str(revenue_change)}) sekinroq.", f"Insurance-service expenses rose by {pct_str(service_cost_change)}, more slowly than net revenue ({pct_str(revenue_change)})."))
        if service_result is not None and service_result_before is not None:
            comparable_period = str(snapshot.get("previous_comparable_period") or "")
            year_earlier = comparable_period[:4].isdigit() and str(period)[:4].isdigit() and int(comparable_period[:4]) == int(str(period)[:4]) - 1
            when = tr(lang, "годом ранее" if year_earlier else "в сопоставимом периоде", "bir yil oldin" if year_earlier else "taqqoslanadigan davrda", "a year earlier" if year_earlier else "in the comparable period")
            service_lines.append(tr(lang, f"Результат от страховых услуг составил {amount_text(service_result)} против {amount_text(service_result_before)} {when}; изменение обусловлено динамикой выручки и расходов на страховые услуги.", f"Sug‘urta xizmatlari natijasi {when} {amount_text(service_result_before)} bo‘lgan bo‘lsa, endi {amount_text(service_result)}ni tashkil etdi; o‘zgarish tushum va sug‘urta xizmatlari xarajatlari dinamikasi bilan bog‘liq.", f"The insurance-service result was {amount_text(service_result)} versus {amount_text(service_result_before)} {when}; the change reflects the movement in revenue and insurance-service expenses."))
            if service_result < service_result_before and premium_change is not None and premium_change > 0:
                service_lines.append(tr(lang, "Результат от страховых услуг снизился, несмотря на рост премий. Следовательно, рост объёма бизнеса не преобразовался в сопоставимое улучшение страхового результата.", "Mukofotlar o‘sganiga qaramay, sug‘urta xizmatlari natijasi pasaydi. Demak, biznes hajmining o‘sishi sug‘urta natijasining mos ravishda yaxshilanishiga aylanmadi.", "The insurance-service result fell despite premium growth, so the larger business volume did not translate into a comparable improvement in the insurance result."))
        if claims is not None:
            service_lines.append(tr(lang, "Рост выплат нельзя интерпретировать отдельно от заработанных премий, изменения резервов и доли перестраховщиков.", "To‘lovlar o‘sishini ishlab topilgan mukofotlar, zaxiralar o‘zgarishi va qayta sug‘urtalovchilar ulushidan alohida talqin qilib bo‘lmaydi.", "Claims growth cannot be interpreted apart from earned premiums, reserve changes and the reinsurers' share."))
        service_lines.append(tr(lang, "В отчётности нет достаточной разбивки страховых выплат и заработанных премий; поэтому коэффициент убыточности по доступным данным не рассчитывается.", "Hisobotda sug‘urta to‘lovlari va ishlab topilgan mukofotlar bo‘yicha yetarli tafsilot yo‘q; shu sababli zararlilik koeffitsiyenti mavjud ma’lumotlar bo‘yicha hisoblanmaydi.", "The statements do not break down claims paid and earned premiums in enough detail, so the loss ratio is not calculated from the available data."))
        service_lines.append(tr(lang, "Комбинированный коэффициент не рассчитывается: отсутствуют необходимые сопоставимые данные о выплатах, расходах на ведение дела и базе заработанных премий.", "Kombinatsiyalashgan koeffitsiyent hisoblanmaydi: to‘lovlar, ish yuritish xarajatlari va ishlab topilgan mukofotlar bazasi bo‘yicha zarur taqqoslanadigan ma’lumotlar yo‘q.", "The combined ratio is not calculated: the comparable data needed on claims, acquisition and administrative expenses and the earned-premium base are missing."))

        # Technical reserves and reinsurers.
        reserve_lines = []
        if gross_reserves is not None and reinsurer_reserves is not None and net_reserves is not None:
            reserve_lines.append(tr(lang, f"Валовые технические резервы составили {amount_text(gross_reserves)}, доля перестраховщиков — {amount_text(reinsurer_reserves)}, расчётные резервы за вычетом доли перестраховщиков — {amount_text(net_reserves)}.", f"Yalpi texnik zaxiralar {amount_text(gross_reserves)}, qayta sug‘urtalovchilar ulushi — {amount_text(reinsurer_reserves)}, qayta sug‘urtalovchilar ulushi ayirilgan hisoblangan zaxiralar — {amount_text(net_reserves)}ni tashkil etdi.", f"Gross technical reserves were {amount_text(gross_reserves)}, the reinsurers' share {amount_text(reinsurer_reserves)}, and calculated reserves net of the reinsurers' share {amount_text(net_reserves)}."))
        gross_move, reinsurer_move, net_move = moved("gross_insurance_reserves"), moved("reinsurer_share_in_reserves"), moved("net_insurance_reserves")
        if gross_move is not None and reinsurer_move is not None:
            reserve_lines.append(tr(lang, f"Валовые резервы {'выросли' if gross_move >= 0 else 'снизились'} на {format_number(abs(gross_move))}%, а доля перестраховщиков — на {format_number(abs(reinsurer_move)) if (reinsurer_move >= 0) == (gross_move >= 0) else format_number(reinsurer_move)}%. Изменение резервов следует рассматривать вместе с динамикой портфеля и перестрахования.", f"Yalpi zaxiralar {format_number(abs(gross_move))}% ga {'oshdi' if gross_move >= 0 else 'kamaydi'}, qayta sug‘urtalovchilar ulushi esa {format_number(reinsurer_move)}% ga o‘zgardi. Zaxiralar o‘zgarishini portfel va qayta sug‘urtalash dinamikasi bilan birga ko‘rib chiqish kerak.", f"Gross reserves {'rose' if gross_move >= 0 else 'fell'} by {format_number(abs(gross_move))}%, and the reinsurers' share changed by {format_number(reinsurer_move)}%. Reserve changes should be read together with portfolio and reinsurance movements."))
        if net_move is not None:
            reserve_lines.append(tr(lang, f"Расчётные чистые технические резервы {'увеличились' if net_move >= 0 else 'снизились'} на {format_number(abs(net_move))}%. Это изменение балансовой оценки обязательств и само по себе не является мерой прибыльности.", f"Hisoblangan sof texnik zaxiralar {format_number(abs(net_move))}% ga {'oshdi' if net_move >= 0 else 'kamaydi'}. Bu majburiyatlar balans bahosining o‘zgarishi bo‘lib, o‘z-o‘zidan rentabellik o‘lchovi emas.", f"Calculated net technical reserves {'increased' if net_move >= 0 else 'decreased'} by {format_number(abs(net_move))}%. This is a change in the balance-sheet measurement of liabilities and is not in itself a measure of profitability."))
        reinsurer_share = pct_of(reinsurer_reserves, gross_reserves)
        if reinsurer_share is not None:
            reserve_lines.append(tr(lang, f"Доля перестраховщиков в технических резервах составила {pct_str(reinsurer_share)}. Это показывает их участие в отражённых резервах, но не подтверждает фактическое получение возмещений.", f"Qayta sug‘urtalovchilarning texnik zaxiralardagi ulushi {pct_str(reinsurer_share)}ni tashkil etdi. Bu ularning aks ettirilgan zaxiralardagi ishtirokini ko‘rsatadi, ammo tovon puli haqiqatda olinishini tasdiqlamaydi.", f"The reinsurers' share of technical reserves was {pct_str(reinsurer_share)}. This shows their participation in the reported reserves but does not confirm that recoveries are actually received."))
        if gross_reserves is not None:
            reserve_lines.append(tr(lang, "По имеющейся форме нельзя определить достаточность резервов относительно будущих выплат без актуарной оценки и более детальной разбивки обязательств.", "Mavjud shakl bo‘yicha aktuar baholashsiz va majburiyatlarning batafsilroq taqsimotisiz zaxiralarning kelgusi to‘lovlarga nisbatan yetarliligini aniqlab bo‘lmaydi.", "The available form cannot establish whether reserves are adequate for future claims without an actuarial assessment and a more detailed breakdown of liabilities."))

        # Profitability and financial result.
        profit_lines = []
        if operating_income is not None:
            if operating_change is not None and not (by_code.get("operating_income") or {}).get("base_effect") and operating_income > 0:
                diverges = net_change is not None and (operating_change >= 0) != (net_change >= 0)
                profit_lines.append(tr(lang, f"Операционная прибыль составила {amount_text(operating_income)}, изменившись на {pct_str(operating_change)}." + (" Динамика отличается от динамики чистой прибыли." if diverges else ""), f"Operatsion foyda {amount_text(operating_income)}ni tashkil etib, {pct_str(operating_change)} ga o‘zgardi." + (" Uning dinamikasi sof foyda dinamikasidan farq qiladi." if diverges else ""), f"Operating profit was {amount_text(operating_income)}, a change of {pct_str(operating_change)}." + (" Its movement differs from that of net profit." if diverges else "")))
            else:
                before = fact_before("operating_income")
                versus = tr(lang, f" против {amount_text(before)}", f" ({amount_text(before)} o‘rniga)", f" versus {amount_text(before)}") if before is not None else ""
                profit_lines.append(tr(lang, f"Операционный результат составил {amount_text(operating_income)}{versus}.", f"Operatsion natija {amount_text(operating_income)}ni tashkil etdi{versus}.", f"The operating result was {amount_text(operating_income)}{versus}."))
        finance_now = difference(fact_now("financial_income"), fact_now("financial_expenses"))
        fx_now, fx_before = difference(fact_now("fx_income"), fact_now("fx_expenses")), difference(fact_before("fx_income"), fact_before("fx_expenses"))
        if net_change is not None and operating_change is not None and net_change > 0 and operating_change < 0:
            drivers = []
            if finance_now is not None and finance_now > 0:
                drivers.append(tr(lang, "финансовые доходы", "moliyaviy daromadlar", "finance income"))
            if fx_now is not None and fx_before is not None and fx_now > fx_before:
                drivers.append(tr(lang, "валютный результат", "valyuta natijasi", "the FX result"))
            if drivers:
                profit_lines.append(tr(lang, f"Чистая прибыль выросла, хотя операционная прибыль снизилась; на итог повлияли {', '.join(drivers)}.", f"Operatsion foyda kamaygan bo‘lsa-da, sof foyda oshdi; yakunga {', '.join(drivers)} ta’sir qildi.", f"Net profit rose although operating profit fell; the result was influenced by {', '.join(drivers)}."))
        if finance_now is not None and finance_now > 0 and net_income is not None and net_income > 0:
            support = tr(lang, f"Финансовый результат поддержал чистую прибыль на {amount_text(finance_now)}.", f"Moliyaviy natija sof foydani {amount_text(finance_now)}ga qo‘llab-quvvatladi.", f"The financial result supported net profit by {amount_text(finance_now)}.")
            if net_change is not None and net_change > 0:
                support += " " + tr(lang, "Поэтому рост чистой прибыли не следует полностью относить к улучшению страховой деятельности.", "Shu sababli sof foyda o‘sishini to‘liq sug‘urta faoliyatining yaxshilanishiga bog‘lamaslik kerak.", "Net-profit growth should therefore not be attributed entirely to better insurance operations.")
            profit_lines.append(support)
        if fx_now is not None and fx_before is not None and fx_now != fx_before:
            helped = fx_now > fx_before
            profit_lines.append(tr(lang, f"Чистый валютный результат составил {amount_text(fx_now)} против {amount_text(fx_before)}. Его изменение {'поддержало' if helped else 'снизило'} итоговую прибыль.", f"Sof valyuta natijasi {amount_text(fx_now)}ni tashkil etdi ({amount_text(fx_before)} o‘rniga). Uning o‘zgarishi yakuniy foydani {'qo‘llab-quvvatladi' if helped else 'kamaytirdi'}.", f"The net FX result was {amount_text(fx_now)} versus {amount_text(fx_before)}. The change {'supported' if helped else 'reduced'} the bottom line."))
        if net_change is not None and net_change > 0 and service_result is not None and service_result_before is not None and service_result < service_result_before:
            profit_lines.append(tr(lang, "Рост прибыли сопровождается снижением результата от страховых услуг. Это означает, что улучшение итогового результата обеспечено не только основной страховой деятельностью.", "Foyda o‘sishi sug‘urta xizmatlari natijasining pasayishi bilan birga kechmoqda. Bu yakuniy natijaning yaxshilanishi faqat asosiy sug‘urta faoliyati hisobiga bo‘lmaganini anglatadi.", "Profit growth is accompanied by a lower insurance-service result, meaning the better bottom line did not come from core insurance operations alone."))
        profit_lines.append(tr(lang, "Для оценки устойчивости прибыли важно разделять страховой результат, инвестиционный и прочий финансовый результат, а также влияние налога.", "Foyda barqarorligini baholash uchun sug‘urta natijasi, investitsiya va boshqa moliyaviy natija hamda soliq ta’sirini ajratish muhim.", "To judge how sustainable profit is, the insurance result, the investment and other financial result, and the tax effect must be separated."))

        balance_facts = [fact_sentence(key) for key in ("total_assets", "gross_insurance_reserves", "reinsurer_share_in_reserves", "net_insurance_reserves", "total_equity")]
        horizontal_text = " ".join(filter(None, (
            tr(lang, "Баланс и технические резервы. ", "Balans va texnik zaxiralar. ", "Balance sheet and technical reserves. ") + "; ".join(item for item in balance_facts if item) + ".",
            *reserve_lines,
        )))
        vertical_text = tr(lang, "Перестрахование и удержание риска. ", "Qayta sug‘urtalash va riskni ushlab qolish. ", "Reinsurance and risk retention. ") + (" ".join(retention_lines) or tr(lang, "Компонентов для расчёта удержания недостаточно.", "Ushlab qolishni hisoblash uchun komponentlar yetarli emas.", "There are insufficient components to calculate retention."))
        result_facts = [fact_sentence(key) for key in ("insurance_premiums", "revenue", "insurance_service_result", "operating_income", "profit_before_tax", "net_income")]
        results_text = " ".join(filter(None, (
            tr(lang, "Премии, страховые услуги и прибыльность. ", "Mukofotlar, sug‘urta xizmatlari va rentabellik. ", "Premiums, insurance services and profitability. ") + "; ".join(item for item in result_facts if item) + ".",
            *premium_lines, *service_lines, *profit_lines,
        )))

        ratio_parts = []
        if ceded_share is not None:
            ratio_parts.append(f"{tr(lang, 'Переданные премии / валовые премии', 'Berilgan mukofotlar / yalpi mukofotlar', 'Ceded premiums / gross premiums')} = {pct_str(ceded_share)}")
            ratio_parts.append(f"{tr(lang, 'Удержание премий', 'Mukofotlarni ushlab qolish', 'Premium retention')} = {pct_str(pct_of(difference(premiums, ceded), premiums))}")
        if reserve_retention is not None:
            ratio_parts.append(f"{tr(lang, 'Удержание резервов', 'Zaxiralarni ushlab qolish', 'Reserve retention')} = {pct_str(reserve_retention)}")
        if reinsurer_share is not None:
            ratio_parts.append(f"{tr(lang, 'Доля перестраховщиков в резервах', 'Zaxiralardagi qayta sug‘urtalovchilar ulushi', 'Reinsurer share of reserves')} = {pct_str(reinsurer_share)}")
        service_margin = pct_of(service_result, revenue) if revenue is not None and revenue > 0 else None
        if service_margin is not None:
            ratio_parts.append(f"{tr(lang, 'Результат от страховых услуг / чистая выручка от страховых услуг', 'Sug‘urta xizmatlari natijasi / sof tushum', 'Insurance-service result / net insurance-service revenue')} = {pct_str(service_margin)}")
        ratio_text = tr(lang, "Ключевые страховые коэффициенты. ", "Asosiy sug‘urta koeffitsiyentlari. ", "Key insurance ratios. ") + ("; ".join(ratio_parts) if ratio_parts else tr(lang, "Недостаточно компонентов для расчёта.", "Hisoblash uchun komponentlar yetarli emas.", "Insufficient components for calculation.")) + ". " + tr(lang, "Это аналитические коэффициенты на основе отчётности, а не нормативы, установленные регулятором; коэффициенты убыточности и комбинированный не рассчитываются без раскрытых выплат и заработанных премий.", "Bular hisobotga asoslangan tahliliy koeffitsiyentlar, regulyator belgilagan me’yorlar emas; zararlilik va kombinatsiyalashgan koeffitsiyentlar oshkor qilingan to‘lovlar va ishlab topilgan mukofotlarsiz hisoblanmaydi.", "These are analytical ratios based on the statements, not standards set by the regulator; the loss and combined ratios are not calculated without disclosed claims and earned premiums.")
        summary_text = tr(lang, "Сводная оценка. ", "Yakuniy baho. ", "Summary assessment. ") + sector_conclusion()
        narrative_blocks["performance"] = [
            {"lead": tr(lang, "Премии и масштаб бизнеса", "Mukofotlar va biznes ko‘lami", "Premiums and scale of business"), "text": " ".join(premium_lines) or results_text},
            {"lead": tr(lang, "Страховые услуги, выплаты и результат", "Sug‘urta xizmatlari, to‘lovlar va natija", "Insurance services, claims and result"), "text": " ".join(service_lines)},
            {"lead": tr(lang, "Прибыльность и финансовый результат", "Rentabellik va moliyaviy natija", "Profitability and financial result"), "text": " ".join(profit_lines)},
            {"lead": tr(lang, "Ключевые страховые коэффициенты", "Asosiy sug‘urta koeffitsiyentlari", "Key insurance ratios"), "text": ratio_text},
        ]
        narrative_blocks["position"] = [
            {"lead": tr(lang, "Технические резервы и перестраховщики", "Texnik zaxiralar va qayta sug‘urtalovchilar", "Technical reserves and reinsurers"), "text": horizontal_text},
            {"lead": tr(lang, "Перестрахование и удержание риска", "Qayta sug‘urtalash va riskni ushlab qolish", "Reinsurance and risk retention"), "text": vertical_text},
        ]
        return [intro, horizontal_text, vertical_text, results_text, ratio_text, summary_text]

    def fund_analysis_paragraphs():
        """Describe an audited investment fund through portfolio economics."""
        value = lambda key: decimal((by_code.get(key) or {}).get("value"))
        pct = lambda numerator, denominator: ratio(numerator, denominator, True)
        pct_text = lambda item: f"{format_number(item)}%" if item is not None else None
        portfolio = value("portfolio_fair_value")
        assets = value("total_assets")
        equity = value("total_equity")
        liabilities = value("total_liabilities")
        top5 = value("top5_holdings")
        largest = value("largest_holding")
        level3 = value("level3_investments")
        unrealized = value("unrealized_fair_value_gain")
        dividends = value("dividend_income")
        expenses = value("management_expenses")
        tax = value("tax")
        net_income = value("net_income")

        portfolio_share = pct(portfolio, assets)
        top5_share = pct(top5, portfolio)
        largest_share = pct(largest, portfolio)
        level3_share = pct(level3, portfolio)
        equity_share = pct(equity, assets)
        unrealized_to_profit = pct(unrealized, net_income)
        intro = f"{headline} " + tr(
            lang,
            f"Фонд оценивается по структуре и концентрации инвестиционного портфеля, качеству оценки и источникам прибыли; корпоративные показатели выручки и оборотного капитала к нему не применяются. Портфель составляет {pct_text(portfolio_share) or '—'} активов.",
            f"Fond investitsiya portfeli tarkibi va jamlanishi, baholash sifati hamda foyda manbalari bo‘yicha baholanadi; korporativ tushum va aylanma kapital ko‘rsatkichlari unga qo‘llanmaydi. Portfel aktivlarning {pct_text(portfolio_share) or '—'}ini tashkil etadi.",
            f"The fund is assessed through portfolio structure and concentration, valuation quality and profit sources; corporate revenue and working-capital measures do not apply. The portfolio represents {pct_text(portfolio_share) or '—'} of assets.",
        )

        position_facts = [fact_sentence(key, comparison=False) for key in ("total_assets", "portfolio_fair_value", "cash", "dividends_receivable", "accounts_payable", "total_equity", "total_liabilities")]
        horizontal_text = tr(lang, "Активы, портфель и капитал. ", "Aktivlar, portfel va kapital. ", "Assets, portfolio and capital. ") + "; ".join(item for item in position_facts if item) + "."
        concentration_parts = []
        if portfolio_share is not None:
            concentration_parts.append(tr(lang, f"инвестиционный портфель составляет {pct_text(portfolio_share)} активов", f"investitsiya portfeli aktivlarning {pct_text(portfolio_share)}ini tashkil etadi", f"the investment portfolio equals {pct_text(portfolio_share)} of assets"))
        if top5_share is not None:
            concentration_parts.append(tr(lang, f"пять крупнейших позиций — {pct_text(top5_share)} портфеля", f"beshta eng yirik pozitsiya portfelning {pct_text(top5_share)}ini tashkil etadi", f"the five largest holdings represent {pct_text(top5_share)} of the portfolio"))
        if largest_share is not None:
            concentration_parts.append(tr(lang, f"крупнейшая позиция — {pct_text(largest_share)} портфеля", f"eng yirik pozitsiya portfelning {pct_text(largest_share)}ini tashkil etadi", f"the largest holding represents {pct_text(largest_share)} of the portfolio"))
        if level3_share is not None:
            concentration_parts.append(tr(lang, f"инструменты Level 3 — {pct_text(level3_share)} портфеля", f"Level 3 vositalari portfelning {pct_text(level3_share)}ini tashkil etadi", f"Level 3 instruments represent {pct_text(level3_share)} of the portfolio"))
        if equity_share is not None:
            concentration_parts.append(tr(lang, f"капитал покрывает {pct_text(equity_share)} активов", f"kapital aktivlarning {pct_text(equity_share)}ini qoplaydi", f"equity covers {pct_text(equity_share)} of assets"))
        vertical_text = tr(lang, "Структура и концентрация портфеля. ", "Portfel tarkibi va jamlanishi. ", "Portfolio structure and concentration. ") + "; ".join(concentration_parts) + ". " + tr(
            lang,
            "Высокая доля Level 3 означает зависимость стоимости портфеля от моделей и непубличных исходных данных, а не автоматически низкое качество активов.",
            "Level 3 ulushining yuqoriligi portfel qiymati modellarga va ochiq bo‘lmagan ma’lumotlarga bog‘liqligini anglatadi, lekin aktivlar sifati avtomatik ravishda past degani emas.",
            "A high Level 3 share means portfolio value depends on models and unobservable inputs; it does not automatically imply poor asset quality.",
        )

        valuation_parts = [fact_sentence(key, comparison=False) for key in ("unrealized_fair_value_gain", "dividend_income")]
        valuation_text = tr(lang, "Источники инвестиционного результата. ", "Investitsiya natijasi manbalari. ", "Sources of investment return. ") + "; ".join(item for item in valuation_parts if item) + "."
        if unrealized_to_profit is not None:
            valuation_text += " " + tr(lang, f"Нереализованная переоценка равна {pct_text(unrealized_to_profit)} чистой прибыли, поэтому устойчивость результата зависит от будущего подтверждения оценочной стоимости.", f"Realizatsiya qilinmagan qayta baholash sof foydaning {pct_text(unrealized_to_profit)}iga teng, shuning uchun natija barqarorligi baholash qiymatining kelajakda tasdiqlanishiga bog‘liq.", f"Unrealized revaluation equals {pct_text(unrealized_to_profit)} of net profit, so result sustainability depends on future confirmation of the valuation.")
        cost_parts = [fact_sentence(key, comparison=False) for key in ("management_expenses", "tax", "net_income")]
        profit_text = tr(lang, "Расходы и итоговая прибыль. ", "Xarajatlar va yakuniy foyda. ", "Expenses and final profit. ") + "; ".join(item for item in cost_parts if item) + "."
        ratio_parts = []
        for title, result in (
            (tr(lang, "Портфель / активы", "Portfel / aktivlar", "Portfolio / assets"), portfolio_share),
            (tr(lang, "Топ-5 / портфель", "Top-5 / portfel", "Top five / portfolio"), top5_share),
            (tr(lang, "Крупнейшая позиция / портфель", "Eng yirik pozitsiya / portfel", "Largest holding / portfolio"), largest_share),
            (tr(lang, "Level 3 / портфель", "Level 3 / portfel", "Level 3 / portfolio"), level3_share),
            (tr(lang, "Капитал / активы", "Kapital / aktivlar", "Equity / assets"), equity_share),
        ):
            if result is not None:
                ratio_parts.append(f"{title} = {pct_text(result)}")
        ratio_text = tr(lang, "Ключевые показатели фонда. ", "Fondning asosiy ko‘rsatkichlari. ", "Key fund metrics. ") + "; ".join(ratio_parts) + "."
        summary_text = tr(
            lang,
            "Сводная оценка. Главные вопросы — концентрация портфеля, доля нереализованной переоценки и надёжность Level 3-оценок. Без сопоставимого прошлого периода нельзя делать вывод о тренде доходности.",
            "Yakuniy baho. Asosiy masalalar — portfel jamlanishi, realizatsiya qilinmagan qayta baholash ulushi va Level 3 baholarining ishonchliligi. Taqqoslanadigan oldingi davrsiz daromadlilik trendi haqida xulosa qilib bo‘lmaydi.",
            "Summary assessment. The central questions are portfolio concentration, the unrealized-revaluation share and reliability of Level 3 valuations. A return trend cannot be established without a comparable prior period.",
        )
        narrative_blocks["performance"] = [
            {"lead": tr(lang, "Переоценка портфеля", "Portfelni qayta baholash", "Portfolio revaluation"), "text": valuation_text},
            {"lead": tr(lang, "Расходы и чистая прибыль", "Xarajatlar va sof foyda", "Expenses and net profit"), "text": profit_text},
            {"lead": tr(lang, "Ключевые показатели фонда", "Fondning asosiy ko‘rsatkichlari", "Key fund metrics"), "text": ratio_text},
        ]
        narrative_blocks["position"] = [
            {"lead": tr(lang, "Активы, портфель и капитал", "Aktivlar, portfel va kapital", "Assets, portfolio and capital"), "text": horizontal_text},
            {"lead": tr(lang, "Концентрация и качество оценки", "Jamlanish va baholash sifati", "Concentration and valuation quality"), "text": vertical_text},
        ]
        return [intro, horizontal_text, vertical_text, f"{valuation_text} {profit_text}", ratio_text, summary_text]

    def general_analysis_paragraphs():
        """Detailed non-bank narrative using only traceable statement totals."""
        value = lambda key: decimal((by_code.get(key) or {}).get("value"))
        pct = lambda numerator, denominator: ratio(numerator, denominator, True)
        money = lambda key: f"{display_money(value(key))} {money_unit}" if value(key) is not None else None
        pct_text = lambda item: f"{format_number(item)}%" if item is not None else None
        profile = SECTOR_PROFILES.get(template)
        sector_name = tr(lang, *profile["name"]) if profile else tr(lang, "товарная биржа", "tovar birjasi", "commodity exchange") if template == "commodity_exchange" else tr(lang, "универсальный профиль", "umumiy profil", "general profile")
        oked_code = resolution.get("input_oked")

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

        revenue_change = (by_code.get(revenue_key) or {}).get("change_pct")
        operating_change = (by_code.get("operating_income") or {}).get("change_pct")
        net_change = (by_code.get("net_income") or {}).get("change_pct")
        cash_change = (by_code.get("cash") or {}).get("change_pct")
        liabilities_change = (by_code.get("total_liabilities") or {}).get("change_pct")
        operating_margin = pct(operating_income, revenue)
        financial_result = difference(value("financial_income"), value("financial_expenses"))
        previous_financial_result = difference(
            (by_code.get("financial_income") or {}).get("previous"),
            (by_code.get("financial_expenses") or {}).get("previous"),
        )
        financial_result_change = difference(financial_result, previous_financial_result)
        executive = []
        if revenue_change is not None and revenue_change > 0 and operating_change is not None and operating_change < 0:
            executive.append(tr(
                lang,
                f"Выручка выросла на {format_number(revenue_change)}%, однако операционная прибыль снизилась на {format_number(abs(operating_change))}%; операционная маржа составила {pct_text(operating_margin) or '—'}. Это означает, что рост масштаба не улучшил эффективность основной деятельности.",
                f"Tushum {format_number(revenue_change)}% ga oshdi, biroq operatsion foyda {format_number(abs(operating_change))}% ga kamaydi; operatsion marja {pct_text(operating_margin) or '—'} bo‘ldi. Demak, faoliyat ko‘lami o‘sishi asosiy faoliyat samaradorligini yaxshilamadi.",
                f"Revenue grew {format_number(revenue_change)}%, but operating profit fell {format_number(abs(operating_change))}%; operating margin was {pct_text(operating_margin) or '—'}. Greater scale therefore did not improve core operating efficiency.",
            ))
        elif revenue_change is not None and net_change is not None:
            executive.append(tr(
                lang,
                f"Доходы изменились на {format_number(revenue_change)}%, чистая прибыль — на {format_number(net_change)}%. Разница между темпами показывает, улучшается ли конверсия выручки в итоговый результат.",
                f"Daromad {format_number(revenue_change)}%, sof foyda esa {format_number(net_change)}% ga o‘zgardi. O‘sish sur’atlari farqi tushumning yakuniy natijaga aylanishi yaxshilanayotganini ko‘rsatadi.",
                f"Income changed {format_number(revenue_change)}% and net profit {format_number(net_change)}%. The gap shows whether revenue is converting into final earnings more effectively.",
            ))
        if operating_change is not None and operating_change < 0 and net_change is not None and net_change > 0 and financial_result_change is not None:
            executive.append(tr(
                lang,
                f"При этом чистая прибыль выросла не вслед за основной деятельностью: чистый финансовый результат улучшился на {display_money(financial_result_change)} {money_unit}. Курсовые разницы входят в этот финансовый результат и отдельно не суммируются.",
                f"Shu bilan birga sof foyda asosiy faoliyat ortidan oshmadi: sof moliyaviy natija {display_money(financial_result_change)} {money_unit}ga yaxshilandi. Kurs farqlari ushbu moliyaviy natija tarkibiga kiradi va alohida qo‘shilmaydi.",
                f"Net profit therefore did not rise with core operations: the net finance result improved by {display_money(financial_result_change)} {money_unit}. FX differences are included in that finance result and are not added again.",
            ))
        if cash_change is not None and liabilities_change is not None and cash_change < 0 < liabilities_change:
            executive.append(tr(
                lang,
                f"Одновременно деньги сократились на {format_number(abs(cash_change))}%, а обязательства выросли на {format_number(liabilities_change)}%, поэтому главный риск периода — ослабление ликвидной позиции.",
                f"Shu bilan birga pul {format_number(abs(cash_change))}% ga kamaydi, majburiyatlar {format_number(liabilities_change)}% ga oshdi; davrning asosiy xavfi — likvidlik holatining zaiflashishi.",
                f"At the same time, cash fell {format_number(abs(cash_change))}% while liabilities rose {format_number(liabilities_change)}%, making weaker liquidity the period’s main risk.",
            ))
        if not executive:
            executive.append(tr(lang, "Главный вывод формируется из динамики прибыли, маржи и баланса; неподтверждённые причины не используются.", "Asosiy xulosa foyda, marja va balans dinamikasidan tuziladi; tasdiqlanmagan sabablar ishlatilmaydi.", "The main conclusion is based on profit, margin and balance-sheet movements; unverified causes are excluded."))
        basis = tr(
            lang,
            f"Аналитический профиль: {sector_name}" + (f" (ОКЭД {oked_code})" if oked_code else "") + ".",
            f"Tahlil profili: {sector_name}" + (f" (IFUT {oked_code})" if oked_code else "") + ".",
            f"Analysis profile: {sector_name}" + (f" (OKED {oked_code})" if oked_code else "") + ".",
        )
        intro = f"{headline} {basis} " + " ".join(executive)

        income_parts = [fact_sentence(revenue_key)] if revenue_key in by_code else []
        if cost is not None:
            cost_key = "cost_of_sales" if value("cost_of_sales") is not None else "insurance_claims"
            cost_share = pct(cost, revenue)
            income_parts.append(f"{label(cost_key, lang)}: {money(cost_key)}" + (f" ({pct_text(cost_share)} {tr(lang, 'доходов', 'daromadga nisbatan', 'of income')})" if cost_share is not None else ""))
        if gross is not None:
            income_parts.append(f"{label('gross_profit', lang)}: {money('gross_profit')}" + (f" ({tr(lang, 'маржа', 'marja', 'margin')} {pct_text(pct(gross, revenue))})" if pct(gross, revenue) is not None else ""))
        income_text = tr(lang, "Доходы и прямые затраты. ", "Daromadlar va bevosita xarajatlar. ", "Income and direct costs. ") + ("; ".join(filter(None, income_parts)) if income_parts else tr(lang, "Недостаточно данных для расчёта структуры.", "Tarkibni hisoblash uchun ma’lumot yetarli emas.", "Insufficient data to calculate the structure.")) + "."
        if profile:
            income_text += " " + tr(lang, *profile["result"])

        expense_parts = []
        if period_expenses is not None:
            expense_key = "period_expenses" if value("period_expenses") is not None else "expenses" if value("expenses") is not None else "management_expenses"
            expense_parts.append(f"{label(expense_key, lang)}: {money(expense_key)}" + (f" ({pct_text(pct(period_expenses, revenue))} {tr(lang, 'доходов', 'daromadga nisbatan', 'of income')})" if pct(period_expenses, revenue) is not None else ""))
        for key in ("financial_income", "financial_expenses", "interest_expenses"):
            if value(key) is not None:
                expense_parts.append(f"{label(key, lang)}: {money(key)}")
        if operating_income is not None:
            expense_parts.append(f"{label('operating_income', lang)}: {money('operating_income')}" + (f" ({tr(lang, 'операционная маржа', 'operatsion marja', 'operating margin')} {pct_text(pct(operating_income, revenue))})" if pct(operating_income, revenue) is not None else ""))
        if financial_result is not None:
            financial_text = tr(lang, "чистый финансовый результат", "sof moliyaviy natija", "net finance result")
            if previous_financial_result is not None:
                expense_parts.append(f"{financial_text}: {display_money(previous_financial_result)} → {display_money(financial_result)} {money_unit}")
            else:
                expense_parts.append(f"{financial_text}: {display_money(financial_result)} {money_unit}")
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

        profile_assets = profile["assets"] if profile else ("own_cash", "client_cash", "cash", "short_term_investments", "receivables") if template == "commodity_exchange" else ("cash", "receivables", "inventories", "fixed_assets")
        asset_parts = [fact_sentence(key) for key in ("total_assets",) + tuple(profile_assets)]
        asset_parts = [item for item in asset_parts if item]
        asset_text = tr(lang, "Активы и оборотный капитал. ", "Aktivlar va aylanma kapital. ", "Assets and working capital. ") + ("; ".join(asset_parts[:5]) if asset_parts else tr(lang, "Недостаточно данных.", "Ma’lumot yetarli emas.", "Insufficient data.")) + ". " + tr(lang, "Рост доходов следует оценивать вместе с движением денег, дебиторской задолженности и запасов.", "Daromad o‘sishini pul, debitorlik va zaxiralar harakati bilan birga baholash kerak.", "Income growth should be assessed alongside cash, receivables and inventory movements.")

        funding_parts = [fact_sentence(key) for key in ("total_liabilities", "total_equity", "current_liabilities")]
        funding_parts = [item for item in funding_parts if item]
        debt_share = pct(value("total_liabilities"), value("total_assets"))
        if debt_share is not None:
            funding_parts.append(tr(lang, f"обязательства составляют {pct_text(debt_share)} активов", f"majburiyatlar aktivlarning {pct_text(debt_share)}ini tashkil etadi", f"liabilities equal {pct_text(debt_share)} of assets"))
        funding_text = tr(lang, "Капитал и обязательства. ", "Kapital va majburiyatlar. ", "Capital and liabilities. ") + ("; ".join(funding_parts) if funding_parts else tr(lang, "Недостаточно данных о структуре финансирования.", "Moliyalashtirish tarkibi haqida ma’lumot yetarli emas.", "Insufficient funding-structure data.")) + "."
        horizontal_text = asset_text + " " + funding_text
        assets = value("total_assets")
        vertical_keys = tuple(dict.fromkeys(tuple(profile_assets) + ("total_liabilities", "total_equity")))
        vertical_text = vertical_narrative(
            tuple(key for key in vertical_keys if key not in {"total_liabilities", "total_equity", "current_liabilities"}),
            tr(lang, f"Для профиля «{sector_name}» важно оценить не перечень долей сам по себе, а концентрацию ресурсов и её изменение за период. ", f"«{sector_name}» profili uchun ulushlar ro‘yxatining o‘zi emas, balki resurslar jamlanishi va uning davr ichidagi o‘zgarishi muhim. ", f"For the {sector_name} profile, the key question is not the list of percentages itself but where resources are concentrated and how that changed. "),
            exchange_funding=template == "commodity_exchange",
        )
        results_text = " ".join((income_text, expense_text, profit_text))
        ratio_parts = []
        for ratio_label, numerator in ((tr(lang, "Валовая маржа", "Yalpi marja", "Gross margin"), gross), (tr(lang, "Операционная маржа", "Operatsion marja", "Operating margin"), operating_income), (tr(lang, "Чистая маржа", "Sof marja", "Net margin"), net_income)):
            calculated = pct(numerator, revenue)
            if calculated is not None:
                ratio_parts.append(f"{ratio_label} = {pct_text(calculated)}")
        if debt_share is not None:
            ratio_parts.append(f"{tr(lang, 'Обязательства / активы', 'Majburiyatlar / aktivlar', 'Liabilities / assets')} = {pct_text(debt_share)}")
        if template in {"industry", "cement", "metallurgy", "extractive", "transport", "aviation", "telecom"}:
            fixed_asset_share = pct(value("fixed_assets"), assets)
            if fixed_asset_share is not None:
                ratio_parts.append(f"{tr(lang, 'Основные средства / активы', 'Asosiy vositalar / aktivlar', 'Fixed assets / assets')} = {pct_text(fixed_asset_share)}")
            construction_share = pct(value("construction_in_progress"), assets)
            if construction_share is not None:
                ratio_parts.append(f"{tr(lang, 'Незавершённые вложения / активы', 'Tugallanmagan investitsiyalar / aktivlar', 'Construction in progress / assets')} = {pct_text(construction_share)}")
        if template == "trade":
            working_capital_share = pct(total(value("inventories"), value("receivables")), assets)
            if working_capital_share is not None:
                ratio_parts.append(f"{tr(lang, 'Запасы и дебиторка / активы', 'Zaxira va debitorlik / aktivlar', 'Inventory and receivables / assets')} = {pct_text(working_capital_share)}")
        if template == "leasing":
            receivables_share = pct(value("receivables"), assets)
            if receivables_share is not None:
                ratio_parts.append(f"{tr(lang, 'Дебиторская задолженность / активы', 'Debitorlik / aktivlar', 'Receivables / assets')} = {pct_text(receivables_share)}")
        ratio_text = tr(lang, "Коэффициентный анализ. ", "Koeffitsiyentlar tahlili. ", "Ratio analysis. ") + ("; ".join(ratio_parts) if ratio_parts else tr(lang, "Недостаточно компонентов для расчёта.", "Hisoblash komponentlari yetarli emas.", "Insufficient components for calculation.")) + "."
        summary_parts = []
        if revenue_change is not None and operating_change is not None and revenue_change > 0 > operating_change:
            summary_parts.append(tr(lang, "Сильная сторона — рост выручки; основной риск — снижение операционной маржи.", "Kuchli tomon — tushum o‘sishi; asosiy xavf — operatsion marja pasayishi.", "The strength is revenue growth; the main risk is the lower operating margin."))
        if cash_change is not None and liabilities_change is not None and cash_change < 0 < liabilities_change:
            summary_parts.append(tr(lang, "Снижение денег при росте обязательств усиливает риск ликвидности.", "Majburiyatlar o‘sib, pul kamayishi likvidlik xavfini kuchaytiradi.", "Falling cash alongside rising liabilities increases liquidity risk."))
        if profile:
            summary_parts.append(tr(lang, *profile["risk"]))
        elif template == "commodity_exchange":
            summary_parts.append(tr(lang, "Для биржи ключевой вопрос — разделение собственных ресурсов и клиентских расчётов; без него высокая доля денег и обязательств не показывает ни ликвидность, ни долговую нагрузку компании сама по себе.", "Birja uchun asosiy masala — o‘z mablag‘lari va mijozlar hisob-kitoblarini ajratish; bunday ajratishsiz pul va majburiyatlarning yuqori ulushi kompaniyaning likvidligi yoki qarz yukini o‘z-o‘zidan ko‘rsatmaydi.", "For an exchange, the key issue is separating own resources from client settlements; without that split, high cash and liability shares do not by themselves establish corporate liquidity or leverage."))
        summary_text = tr(lang, "Сводная оценка. ", "Yakuniy baho. ", "Summary assessment. ") + (" ".join(summary_parts) or tr(lang, "Оценка ограничена раскрытыми показателями; ключевые изменения приведены выше.", "Baho oshkor qilingan ko‘rsatkichlar bilan cheklangan; asosiy o‘zgarishlar yuqorida keltirilgan.", "The assessment is limited to disclosed metrics; the key movements are shown above."))
        narrative_blocks["performance"] = [
            {"lead": tr(lang, "Выручка и прямые затраты", "Tushum va bevosita xarajatlar", "Revenue and direct costs"), "text": income_text},
            {"lead": tr(lang, "Операционный и финансовый результат", "Operatsion va moliyaviy natija", "Operating and finance result"), "text": expense_text},
            {"lead": tr(lang, "Чистая прибыль и налог", "Sof foyda va soliq", "Net profit and tax"), "text": profit_text},
            {"lead": tr(lang, "Маржинальность и финансовая нагрузка", "Marjinallik va moliyaviy yuk", "Margins and financial load"), "text": ratio_text},
        ]
        narrative_blocks["position"] = [
            {"lead": tr(lang, "Динамика активов и обязательств", "Aktivlar va majburiyatlar dinamikasi", "Asset and liability movement"), "text": horizontal_text},
            {"lead": tr(lang, "Концентрация активов и капитал", "Aktivlar jamlanishi va kapital", "Asset concentration and capital"), "text": vertical_text},
        ]
        return [intro, horizontal_text, vertical_text, results_text, ratio_text, summary_text]

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
                "в следующем отчёте показатель лучше текущего значения при сравнении одинаковых периодов",
                "bir xil davrlar taqqoslanganda, keyingi hisobotdagi ko‘rsatkich joriy qiymatdan yaxshiroq bo‘ladi",
                "in the next report, the metric is better than its current value when equivalent periods are compared",
            ),
            "risk_signal": tr(
                lang,
                "показатель хуже текущего значения либо отчёты составлены по-разному и сравнение ненадёжно",
                "ko‘rsatkich joriy qiymatdan yomonroq yoki hisobotlar turlicha tuzilganligi sababli taqqoslash ishonchsiz",
                "the metric is worse than its current value, or the reports were prepared differently and the comparison is unreliable",
            ),
            "required_disclosure": tr(
                lang,
                "значение в следующем отчёте и объяснение причин изменения",
                "keyingi hisobotdagi qiymat va o‘zgarish sabablari izohi",
                "the value in the next report and an explanation of what caused the change",
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
    elif complete_content and template == "insurance":
        paragraphs = insurance_analysis_paragraphs()
    elif complete_content and template == "investment_fund_ifrs_annual":
        paragraphs = fund_analysis_paragraphs()
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
    if bank_without_income_comparison and paragraphs:
        paragraphs[0] += " " + tr(
            lang,
            "Динамика баланса — относительно начала года; изменение прибыли и рентабельности не оценивается без сопоставимого периода.",
            "Balans dinamikasi yil boshiga nisbatan; taqqoslanadigan davrsiz foyda va rentabellik o‘zgarishi baholanmaydi.",
            "Balance-sheet movement is measured from the start of the year; profit and profitability changes are not assessed without a comparable period.",
        )

    # A short, evidence-linked layer enforces the analytical order: identify
    # the sector, select only the material movements, test their relationship,
    # and only then use them in the overview.  Consumers can render these as a
    # concise list without trying to extract priorities from long prose.
    key_changes = []

    def add_key_change(code, category, text_value, metric_codes):
        evidence = [by_code.get(key) for key in metric_codes]
        if len(key_changes) >= 5 or not text_value or any(not item or not item.get("source_url") for item in evidence):
            return
        key_changes.append({
            "id": digest([issuer["id"], period, "key-change", code, [item["id"] for item in evidence]])[:24],
            "code": code,
            "category": category,
            "text": text_value,
            "metric_codes": list(metric_codes),
            "evidence_fact_ids": [item["id"] for item in evidence],
            "verification_status": "verified",
        })

    fact_change = lambda key: (by_code.get(key) or {}).get("change_pct")
    fact_value = lambda key: decimal((by_code.get(key) or {}).get("value"))
    if publishable and template == "investment_fund_ifrs_annual":
        portfolio_share = ratio(fact_value("portfolio_fair_value"), fact_value("total_assets"), True)
        if portfolio_share is not None:
            add_key_change("fund_portfolio", "business", tr(lang, f"Инвестиционный портфель составляет {format_number(portfolio_share)}% активов фонда.", f"Investitsiya portfeli fond aktivlarining {format_number(portfolio_share)}%ini tashkil etadi.", f"The investment portfolio represents {format_number(portfolio_share)}% of fund assets."), ("portfolio_fair_value", "total_assets"))
        unrealized_share = ratio(fact_value("unrealized_fair_value_gain"), fact_value("net_income"), True)
        if unrealized_share is not None:
            add_key_change("fund_profit_quality", "profit_driver", tr(lang, f"Нереализованная переоценка равна {format_number(unrealized_share)}% чистой прибыли: итог существенно зависит от оценочного эффекта.", f"Realizatsiya qilinmagan qayta baholash sof foydaning {format_number(unrealized_share)}%iga teng: yakun baholash ta’siriga sezilarli darajada bog‘liq.", f"Unrealized revaluation equals {format_number(unrealized_share)}% of net profit, making the result materially dependent on valuation effects."), ("unrealized_fair_value_gain", "net_income"))
        top5_share = ratio(fact_value("top5_holdings"), fact_value("portfolio_fair_value"), True)
        if top5_share is not None:
            add_key_change("fund_concentration", "balance", tr(lang, f"Пять крупнейших позиций формируют {format_number(top5_share)}% портфеля.", f"Beshta eng yirik pozitsiya portfelning {format_number(top5_share)}%ini shakllantiradi.", f"The five largest holdings account for {format_number(top5_share)}% of the portfolio."), ("top5_holdings", "portfolio_fair_value"))
        level3_share = ratio(fact_value("level3_investments"), fact_value("portfolio_fair_value"), True)
        if level3_share is not None:
            add_key_change("fund_level3", "attention", tr(lang, f"Инструменты Level 3 составляют {format_number(level3_share)}% портфеля, поэтому качество моделей оценки требует особого внимания.", f"Level 3 vositalari portfelning {format_number(level3_share)}%ini tashkil etadi, shu sababli baholash modellari sifati alohida e’tibor talab qiladi.", f"Level 3 instruments represent {format_number(level3_share)}% of the portfolio, making valuation-model quality a key area of attention."), ("level3_investments", "portfolio_fair_value"))
    elif publishable and template in {"bank", "microfinance_bank", "microfinance"}:
        loan_change = fact_change("loan_portfolio")
        if loan_change is not None:
            loan_direction = tr(lang, "вырос", "oshdi", "grew") if loan_change >= 0 else tr(lang, "снизился", "kamaydi", "fell")
            add_key_change("loan_book", "business", tr(lang, f"Кредитный портфель {loan_direction} на {format_number(abs(loan_change))}% и составляет {display_money(fact_value('loan_portfolio'))} {money_unit}.", f"Kredit portfeli {format_number(abs(loan_change))}% ga {loan_direction} va {display_money(fact_value('loan_portfolio'))} {money_unit}ni tashkil etdi.", f"The loan portfolio {loan_direction} {format_number(abs(loan_change))}% to {display_money(fact_value('loan_portfolio'))} {money_unit}."), ("loan_portfolio",))
        ldr_value = ratio(fact_value("loan_portfolio"), fact_value("customer_funds"), True)
        if ldr_value is not None:
            add_key_change("deposit_funding", "balance", tr(lang, f"Средства клиентов составили {display_money(fact_value('customer_funds'))} {money_unit}, LDR — {format_number(ldr_value)}%.", f"Mijozlar mablag‘i {display_money(fact_value('customer_funds'))} {money_unit}ni tashkil etdi, LDR — {format_number(ldr_value)}%.", f"Customer funds were {display_money(fact_value('customer_funds'))} {money_unit} and LDR was {format_number(ldr_value)}%."), ("loan_portfolio", "customer_funds"))
        nii_value = difference(fact_value("interest_income"), fact_value("interest_expenses"))
        if nii_value is not None:
            add_key_change("net_interest_income", "profitability", tr(lang, f"Чистый процентный доход составил {display_money(nii_value)} {money_unit}; доля процентных расходов в процентных доходах — {format_number(ratio(fact_value('interest_expenses'), fact_value('interest_income'), True))}%.", f"Sof foizli daromad {display_money(nii_value)} {money_unit}; foizli xarajatlarning daromaddagi ulushi — {format_number(ratio(fact_value('interest_expenses'), fact_value('interest_income'), True))}%.", f"Net interest income was {display_money(nii_value)} {money_unit}; interest expense equalled {format_number(ratio(fact_value('interest_expenses'), fact_value('interest_income'), True))}% of interest income."), ("interest_income", "interest_expenses"))
        coi_value = ratio(fact_value("operating_expenses"), fact_value("net_revenue_before_operating_expenses"), True)
        if coi_value is not None:
            add_key_change("cost_to_income", "profitability", f"Cost-to-Income = {format_number(coi_value)}%.", ("operating_expenses", "net_revenue_before_operating_expenses"))
        if fact_value("net_income") is not None:
            change_text = f" ({format_number(fact_change('net_income'))}%)" if fact_change("net_income") is not None else ""
            add_key_change("bottom_line", "profitability", tr(lang, f"Чистая прибыль составила {display_money(fact_value('net_income'))} {money_unit}{change_text}.", f"Sof foyda {display_money(fact_value('net_income'))} {money_unit}{change_text}ni tashkil etdi.", f"Net profit was {display_money(fact_value('net_income'))} {money_unit}{change_text}."), ("net_income",))
    elif publishable and template == "insurance":
        if fact_change("insurance_premiums") is not None:
            premium_change = fact_change("insurance_premiums")
            premium_direction = tr(lang, "выросли", "oshdi", "grew") if premium_change >= 0 else tr(lang, "снизились", "kamaydi", "fell")
            add_key_change("premium_scale", "business", tr(lang, f"Страховые премии {premium_direction} на {format_number(abs(premium_change))}% до {display_money(fact_value('insurance_premiums'))} {money_unit}.", f"Sug‘urta mukofotlari {format_number(abs(premium_change))}% ga {premium_direction} va {display_money(fact_value('insurance_premiums'))} {money_unit}ga yetdi.", f"Insurance premiums {premium_direction} {format_number(abs(premium_change))}% to {display_money(fact_value('insurance_premiums'))} {money_unit}."), ("insurance_premiums",))
        retention_value = ratio(fact_value("net_insurance_reserves"), fact_value("gross_insurance_reserves"), True)
        if retention_value is not None:
            add_key_change("reserve_retention", "balance", tr(lang, f"Чистые резервы составляют {format_number(retention_value)}% валовых резервов после учёта доли перестраховщиков.", f"Qayta sug‘urtalovchilar ulushi hisobga olingach, sof zaxiralar yalpi zaxiralarning {format_number(retention_value)}%ini tashkil etadi.", f"Net reserves equal {format_number(retention_value)}% of gross reserves after the reinsurer share."), ("gross_insurance_reserves", "reinsurer_share_in_reserves", "net_insurance_reserves"))
        if fact_change("operating_income") is not None and fact_change("net_income") is not None:
            op_change, profit_change = fact_change("operating_income"), fact_change("net_income")
            op_direction = tr(lang, "вырос", "oshdi", "grew") if op_change >= 0 else tr(lang, "снизился", "kamaydi", "fell")
            profit_direction = tr(lang, "выросла", "oshdi", "grew") if profit_change >= 0 else tr(lang, "снизилась", "kamaydi", "fell")
            op_now, op_before = fact_value("operating_income"), decimal((by_code.get("operating_income") or {}).get("previous"))
            # A percentage change of a loss is not a readable movement; show the amounts.
            if op_now is not None and op_before is not None and op_now > 0 and op_before > 0:
                op_part = tr(lang, f"Операционный результат {op_direction} на {format_number(abs(op_change))}%", f"Operatsion natija {format_number(abs(op_change))}% ga {op_direction}", f"The operating result {op_direction} {format_number(abs(op_change))}%")
            else:
                op_part = tr(lang, f"Операционный результат: {display_money(op_before)} → {display_money(op_now)} {money_unit}", f"Operatsion natija: {display_money(op_before)} → {display_money(op_now)} {money_unit}", f"The operating result moved from {display_money(op_before)} to {display_money(op_now)} {money_unit}")
            # Only opposite movements mean the bottom line did not track operations.
            diverges = (op_change >= 0) != (profit_change >= 0)
            add_key_change("profit_divergence", "profit_driver", tr(
                lang,
                f"{op_part}, а чистая прибыль {profit_direction} на {format_number(abs(profit_change))}%" + (": итоговая прибыль не повторяет динамику основной деятельности." if diverges else "."),
                f"{op_part}, sof foyda esa {format_number(abs(profit_change))}% ga {profit_direction}" + (": yakuniy foyda asosiy faoliyat dinamikasini takrorlamadi." if diverges else "."),
                f"{op_part}, while net profit {profit_direction} {format_number(abs(profit_change))}%" + ("; the bottom line did not track core operations." if diverges else "."),
            ), ("operating_income", "net_income"))
        if fact_change("total_assets") is not None and fact_change("total_equity") is not None:
            add_key_change("insurance_balance", "balance", tr(lang, f"Активы изменились на {format_number(fact_change('total_assets'))}%, капитал — на {format_number(fact_change('total_equity'))}%.", f"Aktivlar {format_number(fact_change('total_assets'))}%, kapital {format_number(fact_change('total_equity'))}% ga o‘zgardi.", f"Assets changed {format_number(fact_change('total_assets'))}% and equity {format_number(fact_change('total_equity'))}%."), ("total_assets", "total_equity"))
    elif publishable and template == "commodity_exchange":
        revenue_change, op_change = fact_change("revenue"), fact_change("operating_income")
        if revenue_change is not None and op_change is not None:
            revenue_direction = tr(lang, "выросла", "oshdi", "grew") if revenue_change >= 0 else tr(lang, "снизилась", "kamaydi", "fell")
            op_direction = tr(lang, "выросла", "oshdi", "grew") if op_change >= 0 else tr(lang, "снизилась", "kamaydi", "fell")
            add_key_change("exchange_business", "business", tr(lang, f"Выручка {revenue_direction} на {format_number(abs(revenue_change))}%, операционная прибыль {op_direction} на {format_number(abs(op_change))}%.", f"Tushum {format_number(abs(revenue_change))}% ga {revenue_direction}, operatsion foyda {format_number(abs(op_change))}% ga {op_direction}.", f"Revenue {revenue_direction} {format_number(abs(revenue_change))}% and operating profit {op_direction} {format_number(abs(op_change))}%."), ("revenue", "operating_income"))
        if fact_change("net_income") is not None:
            profit_change = fact_change("net_income")
            profit_direction = tr(lang, "выросла", "oshdi", "grew") if profit_change >= 0 else tr(lang, "снизилась", "kamaydi", "fell")
            add_key_change("exchange_profit", "profitability", tr(lang, f"Чистая прибыль {profit_direction} на {format_number(abs(profit_change))}% до {display_money(fact_value('net_income'))} {money_unit}.", f"Sof foyda {format_number(abs(profit_change))}% ga {profit_direction} va {display_money(fact_value('net_income'))} {money_unit}ga yetdi.", f"Net profit {profit_direction} {format_number(abs(profit_change))}% to {display_money(fact_value('net_income'))} {money_unit}."), ("net_income",))
        cash_share = ratio(fact_value("cash"), fact_value("total_assets"), True)
        if cash_share is not None:
            add_key_change("exchange_cash", "balance", tr(lang, f"Деньги составляют {format_number(cash_share)}% активов; без разделения собственных и клиентских средств эта доля не является показателем свободной ликвидности биржи.", f"Pul aktivlarning {format_number(cash_share)}%ini tashkil etadi; o‘z va mijoz mablag‘lari ajratilmasa, bu ulush birjaning erkin likvidligini ko‘rsatmaydi.", f"Cash equals {format_number(cash_share)}% of assets; without separating own and client funds, this is not a measure of the exchange's freely available liquidity."), ("cash", "total_assets"))
        settlement_share = ratio(fact_value("current_liabilities"), fact_value("total_assets"), True)
        if settlement_share is not None:
            add_key_change("exchange_settlements", "attention", tr(lang, f"Текущие обязательства равны {format_number(settlement_share)}% активов, но могут включать клиентские расчёты и не трактуются автоматически как корпоративный долг.", f"Joriy majburiyatlar aktivlarning {format_number(settlement_share)}%iga teng, ammo mijozlar hisob-kitoblarini o‘z ichiga olishi mumkin va avtomatik ravishda korporativ qarz deb talqin qilinmaydi.", f"Current liabilities equal {format_number(settlement_share)}% of assets but may include client settlements and are not automatically treated as corporate debt."), ("current_liabilities", "total_assets"))
    elif publishable:
        if fact_change("revenue") is not None and fact_change("operating_income") is not None:
            revenue_change, op_change = fact_change("revenue"), fact_change("operating_income")
            revenue_direction = tr(lang, "выросла", "oshdi", "grew") if revenue_change >= 0 else tr(lang, "снизилась", "kamaydi", "fell")
            op_direction = tr(lang, "выросла", "oshdi", "grew") if op_change >= 0 else tr(lang, "снизилась", "kamaydi", "fell")
            add_key_change("core_business", "business", tr(lang, f"Выручка {revenue_direction} на {format_number(abs(revenue_change))}%, операционная прибыль {op_direction} на {format_number(abs(op_change))}%.", f"Tushum {format_number(abs(revenue_change))}% ga {revenue_direction}, operatsion foyda {format_number(abs(op_change))}% ga {op_direction}.", f"Revenue {revenue_direction} {format_number(abs(revenue_change))}% and operating profit {op_direction} {format_number(abs(op_change))}%."), ("revenue", "operating_income"))
        finance_now = difference(fact_value("financial_income"), fact_value("financial_expenses"))
        finance_before = difference((by_code.get("financial_income") or {}).get("previous"), (by_code.get("financial_expenses") or {}).get("previous"))
        finance_delta = difference(finance_now, finance_before)
        if finance_delta is not None and fact_change("net_income") is not None:
            profit_change = fact_change("net_income")
            profit_direction = tr(lang, "выросла", "oshdi", "grew") if profit_change >= 0 else tr(lang, "снизилась", "kamaydi", "fell")
            bridge_text = tr(lang, f"Чистая прибыль {profit_direction} на {format_number(abs(profit_change))}%, при этом чистый финансовый результат улучшился на {display_money(finance_delta)} {money_unit}.", f"Sof foyda {format_number(abs(profit_change))}% ga {profit_direction}, sof moliyaviy natija esa {display_money(finance_delta)} {money_unit}ga yaxshilandi.", f"Net profit {profit_direction} {format_number(abs(profit_change))}%, while the net finance result improved by {display_money(finance_delta)} {money_unit}.")
            bridge_metrics = ("financial_income", "financial_expenses", "net_income")
            if quality.get("driver") == "FX-driven" and all(key in by_code for key in ("fx_income", "fx_expenses")):
                bridge_text += " " + tr(lang, f"Внутри финансового результата чистый эффект курсовых разниц улучшился на {display_money(quality['net_fx_result_change'])} {money_unit}; он уже включён в финансовый результат и повторно не суммируется.", f"Moliyaviy natija tarkibida kurs farqlarining sof ta’siri {display_money(quality['net_fx_result_change'])} {money_unit}ga yaxshilandi; u moliyaviy natijaga allaqachon kiritilgan va qayta qo‘shilmaydi.", f"Within the finance result, the net FX effect improved by {display_money(quality['net_fx_result_change'])} {money_unit}; it is already included and is not added twice.")
                bridge_metrics += ("fx_income", "fx_expenses")
            add_key_change("profit_bridge", "profit_driver", bridge_text, bridge_metrics)
        asset_candidates = (SECTOR_PROFILES.get(template) or {}).get("assets", ("cash", "receivables", "inventories", "fixed_assets"))
        assets_total = fact_value("total_assets")
        available_assets = [(key, fact_value(key)) for key in asset_candidates if fact_value(key) is not None]
        if assets_total is not None and available_assets:
            dominant_key, dominant_value = max(available_assets, key=lambda item: item[1])
            add_key_change("asset_concentration", "balance", tr(lang, f"Крупнейшая раскрытая статья активов — «{label(dominant_key, lang)}»: {format_number(ratio(dominant_value, assets_total, True))}% активов.", f"Oshkor qilingan eng yirik aktiv moddasi — «{label(dominant_key, lang)}»: aktivlarning {format_number(ratio(dominant_value, assets_total, True))}%i.", f"The largest disclosed asset item is {label(dominant_key, lang)}, at {format_number(ratio(dominant_value, assets_total, True))}% of assets."), (dominant_key, "total_assets"))
        if fact_change("total_liabilities") is not None and fact_change("total_equity") is not None:
            add_key_change("capital_balance", "attention", tr(lang, f"Обязательства изменились на {format_number(fact_change('total_liabilities'))}%, капитал — на {format_number(fact_change('total_equity'))}%.", f"Majburiyatlar {format_number(fact_change('total_liabilities'))}%, kapital {format_number(fact_change('total_equity'))}% ga o‘zgardi.", f"Liabilities changed {format_number(fact_change('total_liabilities'))}% and equity {format_number(fact_change('total_equity'))}%."), ("total_liabilities", "total_equity"))

    text = "\n\n".join(paragraphs)

    # The company-page narrative follows the information architecture of
    # IELTS Writing Task 1: introduce the dataset, state the main pattern, and
    # then support it with two grouped detail paragraphs.  The underlying
    # verified facts, sector tables and calculation trace stay unchanged.
    task1_sections = []
    if publishable:
        scope_text = {
            "ru": {"separate": "отдельной отчётности", "consolidated": "консолидированной отчётности"},
            "uz": {"separate": "alohida hisobot", "consolidated": "konsolidatsiyalangan hisobot"},
            "en": {"separate": "separate reporting", "consolidated": "consolidated reporting"},
        }.get(lang, {}).get(snapshot.get("scope"), snapshot.get("scope") or "—")
        comparable_period = snapshot.get("previous_comparable_period")
        issuer_name = issuer.get("name") or issuer["ticker"]
        if comparable_period:
            comparison_text = tr(
                lang,
                f"Результаты сопоставляются с {comparable_period}, а балансовые показатели — с началом года.",
                f"Natijalar {comparable_period} bilan, balans ko‘rsatkichlari esa yil boshi bilan taqqoslanadi.",
                f"Performance is compared with {comparable_period}, while balance-sheet figures are compared with the start of the year.",
            )
        else:
            comparison_text = tr(
                lang,
                "Сопоставимый период для результатов не раскрыт; балансовые изменения показаны только при наличии начальных значений.",
                "Natijalar uchun taqqoslanadigan davr oshkor qilinmagan; balansdagi o‘zgarishlar faqat boshlang‘ich qiymatlar mavjud bo‘lsa ko‘rsatiladi.",
                "No comparable performance period is disclosed; balance-sheet movements are shown only where opening values are available.",
            )
        introduction = tr(
            lang,
            f"Анализ описывает финансовые результаты и положение {issuer_name} ({issuer['ticker']}) по {standard.upper()} за {period_text} на уровне {scope_text}. {comparison_text} Все суммы приведены в {money_unit} и взяты только из проверяемой отчётности.",
            f"Tahlil {issuer_name} ({issuer['ticker']}) kompaniyasining {period_text} davridagi {standard.upper()} standarti bo‘yicha moliyaviy natijalari va holatini {scope_text} doirasida tavsiflaydi. {comparison_text} Barcha summalar {money_unit}da berilgan va faqat tekshiriladigan hisobotdan olingan.",
            f"This analysis describes the financial performance and position of {issuer_name} ({issuer['ticker']}) under {standard.upper()} for {period_text} on a {scope_text} basis. {comparison_text} All amounts are in {money_unit} and come only from traceable filings.",
        )
        introduction_blocks = [{"text": introduction}]
        overview_blocks = []
        performance_blocks = []
        position_blocks = []

        if complete_content and len(paragraphs) >= 6:
            overview = " ".join(item["text"] for item in key_changes[:5]) or f"{headline} {paragraphs[5]}"
            performance_detail = " ".join(paragraphs[3:5])
            position_detail = " ".join(paragraphs[1:3])
            lead_catalog = {
                "ru": {
                    "loan_book": "Кредитный портфель", "deposit_funding": "Депозитная база",
                    "net_interest_income": "Процентный бизнес", "cost_to_income": "Операционная эффективность",
                    "bottom_line": "Чистая прибыль", "premium_scale": "Страховые премии",
                    "reserve_retention": "Перестрахование и резервы", "profit_divergence": "Прибыльность",
                    "insurance_balance": "Баланс", "core_business": "Основная деятельность",
                    "profit_bridge": "Почему изменилась чистая прибыль", "asset_concentration": "Структура активов",
                    "capital_balance": "Капитал и обязательства", "fund_portfolio": "Инвестиционный портфель",
                    "fund_profit_quality": "Качество прибыли", "fund_concentration": "Концентрация портфеля",
                    "fund_level3": "Качество оценки", "exchange_business": "Биржевой бизнес",
                    "exchange_profit": "Чистая прибыль", "exchange_cash": "Денежная позиция",
                    "exchange_settlements": "Клиентские расчёты",
                },
                "uz": {
                    "loan_book": "Kredit portfeli", "deposit_funding": "Depozit bazasi",
                    "net_interest_income": "Foizli biznes", "cost_to_income": "Operatsion samaradorlik",
                    "bottom_line": "Sof foyda", "premium_scale": "Sug‘urta mukofotlari",
                    "reserve_retention": "Qayta sug‘urtalash va zaxiralar", "profit_divergence": "Rentabellik",
                    "insurance_balance": "Balans", "core_business": "Asosiy faoliyat",
                    "profit_bridge": "Sof foyda nima uchun o‘zgardi", "asset_concentration": "Aktivlar tarkibi",
                    "capital_balance": "Kapital va majburiyatlar", "fund_portfolio": "Investitsiya portfeli",
                    "fund_profit_quality": "Foyda sifati", "fund_concentration": "Portfel jamlanishi",
                    "fund_level3": "Baholash sifati", "exchange_business": "Birja biznesi",
                    "exchange_profit": "Sof foyda", "exchange_cash": "Pul pozitsiyasi",
                    "exchange_settlements": "Mijozlar hisob-kitoblari",
                },
                "en": {
                    "loan_book": "Loan portfolio", "deposit_funding": "Deposit base",
                    "net_interest_income": "Interest business", "cost_to_income": "Operating efficiency",
                    "bottom_line": "Net profit", "premium_scale": "Insurance premiums",
                    "reserve_retention": "Reinsurance and reserves", "profit_divergence": "Profitability",
                    "insurance_balance": "Balance sheet", "core_business": "Core operations",
                    "profit_bridge": "Why net profit changed", "asset_concentration": "Asset structure",
                    "capital_balance": "Capital and liabilities", "fund_portfolio": "Investment portfolio",
                    "fund_profit_quality": "Earnings quality", "fund_concentration": "Portfolio concentration",
                    "fund_level3": "Valuation quality", "exchange_business": "Exchange business",
                    "exchange_profit": "Net profit", "exchange_cash": "Cash position",
                    "exchange_settlements": "Client settlements",
                },
            }
            fallback_leads = {
                "business": tr(lang, "Что изменилось в бизнесе", "Biznesda nima o‘zgardi", "What changed in the business"),
                "profitability": tr(lang, "Прибыльность", "Rentabellik", "Profitability"),
                "profit_driver": tr(lang, "Драйвер прибыли", "Foyda drayveri", "Profit driver"),
                "balance": tr(lang, "Баланс", "Balans", "Balance sheet"),
                "attention": tr(lang, "Что требует внимания", "Nimaga e’tibor kerak", "What needs attention"),
            }
            leads = lead_catalog.get(lang, lead_catalog["ru"])
            overview_blocks = [
                {"lead": leads.get(item["code"], fallback_leads.get(item["category"])), "text": item["text"],
                 "evidence_fact_ids": item["evidence_fact_ids"]}
                for item in key_changes[:5]
            ] or [{"text": overview}]
            performance_blocks = narrative_blocks["performance"] or [{"text": performance_detail}]
            position_blocks = narrative_blocks["position"] or [{"text": position_detail}]
        else:
            overview = f"{headline} " + tr(
                lang,
                "Общая картина ограничена раскрытыми показателями; пропуски не заменены нулями или предположениями.",
                "Umumiy manzara oshkor qilingan ko‘rsatkichlar bilan cheklangan; bo‘sh qiymatlar nol yoki taxmin bilan almashtirilmagan.",
                "The overall picture is limited to disclosed metrics; missing values were not replaced with zero or estimates.",
            )
            performance_facts = [fact_sentence(key) for key in ("revenue", "operating_income", "profit_before_tax", "net_income")]
            position_facts = [fact_sentence(key) for key in ("total_assets", "cash", "total_liabilities", "total_equity")]
            performance_detail = "; ".join(item for item in performance_facts if item) or tr(
                lang,
                "Подтверждённых данных о доходах и прибыли недостаточно для содержательного сравнения.",
                "Daromad va foydani mazmunli taqqoslash uchun tasdiqlangan ma’lumot yetarli emas.",
                "There is insufficient verified income and profit data for a meaningful comparison.",
            )
            position_detail = "; ".join(item for item in position_facts if item) or tr(
                lang,
                "Подтверждённых данных об активах, обязательствах и капитале недостаточно для содержательного сравнения.",
                "Aktivlar, majburiyatlar va kapitalni mazmunli taqqoslash uchun tasdiqlangan ma’lumot yetarli emas.",
                "There is insufficient verified asset, liability and equity data for a meaningful comparison.",
            )
            overview_blocks = [{"text": overview}]
            performance_blocks = [{"text": performance_detail}]
            position_blocks = [{"text": position_detail}]

        task1_titles = {
            "ru": ("Введение", "Общий обзор", "Детали I — финансовые результаты", "Детали II — финансовое положение"),
            "uz": ("Kirish", "Umumiy ko‘rinish", "I tafsilot — moliyaviy natijalar", "II tafsilot — moliyaviy holat"),
            "en": ("Introduction", "Overview", "Details I — Financial performance", "Details II — Financial position"),
        }.get(lang, ("Introduction", "Overview", "Details I — Financial performance", "Details II — Financial position"))
        task1_sections = [
            {"id": section_id, "number": f"{index:02d}", "title": title, "text": section_text, "blocks": blocks_value}
            for index, (section_id, title, section_text, blocks_value) in enumerate((
                ("introduction", task1_titles[0], introduction, introduction_blocks),
                ("overview", task1_titles[1], overview, overview_blocks),
                ("details_performance", task1_titles[2], performance_detail, performance_blocks),
                ("details_position", task1_titles[3], position_detail, position_blocks),
            ), 1)
        ]

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
                ("methodology", "Общие сведения и методология анализа"),
                ("horizontal_balance", "Горизонтальный анализ бухгалтерского баланса"),
                ("vertical_balance", "Вертикальный анализ бухгалтерского баланса"),
                ("financial_results", "Анализ отчёта о финансовых результатах"),
                ("ratios", "Коэффициентный анализ"),
                ("summary", "Вердикт"),
            ],
            "uz": [
                ("methodology", "Umumiy ma’lumot va tahlil metodologiyasi"),
                ("horizontal_balance", "Buxgalteriya balansining gorizontal tahlili"),
                ("vertical_balance", "Buxgalteriya balansining vertikal tahlili"),
                ("financial_results", "Moliyaviy natijalar hisobotining tahlili"),
                ("ratios", "Koeffitsiyentlar tahlili"),
                ("summary", "Xulosa"),
            ],
            "en": [
                ("methodology", "Issuer overview and analysis methodology"),
                ("horizontal_balance", "Horizontal balance-sheet analysis"),
                ("vertical_balance", "Vertical balance-sheet analysis"),
                ("financial_results", "Financial-results statement analysis"),
                ("ratios", "Ratio analysis"),
                ("summary", "Verdict"),
            ],
        }
        outline = bank_section_titles.get(lang, bank_section_titles["ru"])
    elif publishable and complete_content and template == "insurance":
        insurance_section_titles = {
            "ru": [
                ("methodology", "Общие сведения и методология анализа"),
                ("technical_reserves", "Технические резервы и перестраховщики"),
                ("reinsurance", "Перестрахование и удержание риска"),
                ("financial_results", "Премии, страховые услуги и прибыльность"),
                ("ratios", "Коэффициентный анализ"),
                ("summary", "Вердикт"),
            ],
            "uz": [
                ("methodology", "Umumiy ma’lumot va tahlil metodologiyasi"),
                ("technical_reserves", "Texnik zaxiralar va qayta sug‘urtalovchilar"),
                ("reinsurance", "Qayta sug‘urtalash va riskni ushlab qolish"),
                ("financial_results", "Mukofotlar, sug‘urta xizmatlari va rentabellik"),
                ("ratios", "Koeffitsiyentlar tahlili"),
                ("summary", "Xulosa"),
            ],
            "en": [
                ("methodology", "Issuer overview and analysis methodology"),
                ("technical_reserves", "Technical reserves and reinsurers"),
                ("reinsurance", "Reinsurance and risk retention"),
                ("financial_results", "Premiums, insurance services and profitability"),
                ("ratios", "Ratio analysis"),
                ("summary", "Verdict"),
            ],
        }
        outline = insurance_section_titles.get(lang, insurance_section_titles["ru"])
    elif publishable and complete_content:
        general_section_titles = {
            "ru": [
                ("methodology", "Общие сведения и методология анализа"),
                ("horizontal_balance", "Горизонтальный анализ бухгалтерского баланса"),
                ("vertical_balance", "Вертикальный анализ бухгалтерского баланса"),
                ("financial_results", "Анализ отчёта о финансовых результатах"),
                ("ratios", "Коэффициентный анализ"),
                ("summary", "Вердикт"),
            ],
            "uz": [
                ("methodology", "Umumiy ma’lumot va tahlil metodologiyasi"),
                ("horizontal_balance", "Buxgalteriya balansining gorizontal tahlili"),
                ("vertical_balance", "Buxgalteriya balansining vertikal tahlili"),
                ("financial_results", "Moliyaviy natijalar hisobotining tahlili"),
                ("ratios", "Koeffitsiyentlar tahlili"),
                ("summary", "Xulosa"),
            ],
            "en": [
                ("methodology", "Issuer overview and analysis methodology"),
                ("horizontal_balance", "Horizontal balance-sheet analysis"),
                ("vertical_balance", "Vertical balance-sheet analysis"),
                ("financial_results", "Financial-results statement analysis"),
                ("ratios", "Ratio analysis"),
                ("summary", "Verdict"),
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
              "sector_template_code": template, "template_resolution": resolution,
              "industry_analysis_basis": {"oked_code": resolution.get("input_oked"), "profile": template,
                                            "matched": template in SECTOR_PROFILES},
              "template_version": VERSION,
              "calculation_version": CALCULATION_VERSION, "mapping_version": MAPPING_VERSION,
              "headline": headline, "short_summary": card_text, "card_text": card_text,
              "card_word_count": len(card_text.split()) if card_text else 0,
              "headline_tone": {"positive": "positive", "mixed": "warning", "negative": "danger", "no_signal": "neutral"}[verdict_status],
              "narrative_structure": "ielts-task-1-v1", "task1_sections": task1_sections,
              "key_changes": key_changes,
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
              "availability": {"reason_code": status, "last_source_period": period, "last_successful_period": period if publishable else None,
                               "next_action": tr(lang, "Мы проверим данные снова после обновления источника.", "Manba yangilangach ma’lumotlarni yana tekshiramiz.", "We will check the data again after the source is updated.") if status == "stale" or not publishable else None},
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

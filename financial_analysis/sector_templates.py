"""Sector templates. Pure deterministic rules."""
from __future__ import annotations

from datetime import date
import re


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


OKED_MAP = {"511": "aviation", "512": "aviation", "61": "telecom", "6491": "leasing",
            "23": "cement", "24": "metallurgy", "05": "extractive", "06": "extractive",
            "07": "extractive", "08": "extractive", "46": "trade", "47": "trade",
            "49": "transport", "50": "transport", "52": "transport",
            **{str(n): "industry" for n in range(10, 34) if n not in (23, 24)}}


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


CORE_RESULT = ["revenue", "cost_of_sales", "gross_profit", "period_expenses", "operating_income", "profit_before_tax", "tax", "net_income"]


BANK_RESULT = ["interest_income", "interest_expenses", "noninterest_income", "noninterest_expenses", "net_revenue_before_operating_expenses", "operating_expenses", "profit_before_tax", "tax", "net_income"]


INSURANCE_RESULT = ["insurance_premiums", "insurance_claims", "revenue", "expenses", "operating_income", "profit_before_tax", "tax", "net_income"]


FUND_RESULT = ["unrealized_fair_value_gain", "dividend_income", "management_expenses", "tax", "net_income"]


BALANCE = ["cash", "receivables", "inventories", "current_liabilities", "total_assets", "total_liabilities", "total_equity"]


FINANCE_BALANCE = ["cash", "central_bank_balances", "loan_portfolio", "customer_funds", "borrowings", "loan_reserves", "total_assets", "total_liabilities", "total_equity"]


INSURANCE_BALANCE = ["cash", "receivables", "gross_insurance_reserves", "reinsurer_share_in_reserves", "net_insurance_reserves", "other_liabilities", "total_assets", "total_liabilities", "total_equity"]


FUND_BALANCE = ["cash", "dividends_receivable", "accounts_payable", "total_assets", "total_liabilities", "total_equity"]


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

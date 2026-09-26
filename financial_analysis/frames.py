"""Normalize annual and quarterly data frames into financial records."""
from __future__ import annotations

from collections import defaultdict
import pandas as pd
import re


KEEP_TITLES = {
    "Чистая выручка от реализации продукции (товаров, работ и услуг)":                                   "revenue",
    "Себестоимость реализованной продукции (товаров, работ и услуг)":                                    "cogs",
    "Валовая прибыль (убыток) от реализации продукции (товаров, работ и услуг) (стр.010-020)":           "gross_profit",
    "Расходы периода, всего (стр.050+060+070+080), в том числе:":                                        "operating_expenses",
    "Административные расходы":                                                                           "admin_expenses",
    "Прибыль (убыток) от основной деятельности (стр.0З0-040+090)":                                      "ebit",
    "Расходы по финансовой деятельности (стр.180+190+200+210), в том числе:":                            "finance_expenses",
    "Расходы в виде процентов":                                                                           "interest_expense",
    "Прибыль (убыток) до уплаты налога на доходы прибыль) (стр.220+/-230)":                             "ebt",
    "Налог на доходы (прибыль)":                                                                          "income_tax",
    "Чистая прибыль (убыток) отчетного периода (стр.240-250-260)":                                      "net_income",
    "ВСЕГО по активу баланса 130+390":                                                                    "total_assets",
    "ИТОГО ПО РАЗДЕЛУ I (012+022+030+090+100+110+120)":                                                  "non_current_assets",
    "ИТОГО ПО РАЗДЕЛУ II (стр. 140+190+200+210+320+370+380)":                                           "current_assets",
    "Товарно-материальные запасы, всего (стр.150+160+170+180), в том числе":                             "inventory",
    "Дебиторы, всего стр.220+240+250+260+270+280+290+300+310)":                                         "accounts_receivable",
    "Денежные средства, всего (стр.330+340+350+360), в том числе:":                                     "cash",
    "ИТОГО ПО РАЗДЕЛУ I 410+420+430+440+450+460+470":                                                   "equity",
    "Нераспределенная прибыль (непокрытый убыток) (8700)":                                              "retained_earnings",
    "Долгосрочные обязательства, всего (стр.500+520+530+540+550+560+570+580+590)":                      "long_term_debt",
    "Текущие обязательства, всего (стр.610+630+640+650+660+670+680+690+700+710+720+ +730+740+750+760)": "current_liabilities",
    "Задолженность поставщикам и подрядчикам (6000)":                                                    "accounts_payable",
}


BANK_TITLES = {
    # Income Statement (Form 2 for banks)
    "Процентные доходы":                                                    "revenue",
    "Процентные доходы, всего":                                             "revenue",
    "Итого процентных доходов":                                             "revenue",
    "Процентные расходы":                                                   "interest_expense",
    "Процентные расходы, всего":                                            "interest_expense",
    "Чистые процентные доходы":                                             "gross_profit",
    "Чистый процентный доход":                                              "gross_profit",
    "Комиссионные доходы":                                                  "commission_income",
    "Комиссионные расходы":                                                 "commission_expense",
    "Чистые комиссионные доходы":                                           "net_commission_income",
    "Операционные расходы":                                                 "operating_expenses",
    "Операционные расходы, всего":                                          "operating_expenses",
    "Административные и прочие операционные расходы":                       "admin_expenses",
    "Прибыль до налогообложения":                                           "ebt",
    "Прибыль (убыток) до налогообложения":                                  "ebt",
    "Налог на прибыль":                                                     "income_tax",
    "Расходы по налогу на прибыль":                                         "income_tax",
    "Чистая прибыль":                                                       "net_income",
    "Чистая прибыль (убыток)":                                              "net_income",
    "Чистая прибыль за период":                                             "net_income",
    "Итого совокупный доход за период":                                     "net_income",

    # Balance Sheet (Form 1 for banks)
    "Всего активов":                                                        "total_assets",
    "ИТОГО АКТИВОВ":                                                        "total_assets",
    "Итого активы":                                                         "total_assets",
    "Денежные средства и их эквиваленты":                                   "cash",
    "Денежные средства":                                                    "cash",
    "Средства в Центральном банке":                                         "central_bank_deposits",
    "Кредиты и авансы клиентам":                                            "loans_to_customers",
    "Кредиты клиентам":                                                     "loans_to_customers",
    "Чистые кредиты клиентам":                                              "loans_to_customers",
    "Средства клиентов":                                                    "customer_deposits",
    "Депозиты клиентов":                                                    "customer_deposits",
    "Вклады клиентов":                                                      "customer_deposits",
    "Средства других банков":                                               "interbank_deposits",
    "Всего обязательств":                                                   "total_liabilities",
    "ИТОГО ОБЯЗАТЕЛЬСТВ":                                                   "total_liabilities",
    "Итого обязательства":                                                  "total_liabilities",
    "Всего капитала":                                                       "equity",
    "ИТОГО КАПИТАЛ":                                                        "equity",
    "Итого капитал":                                                        "equity",
    "Итого собственный капитал":                                            "equity",
    "Собственный капитал":                                                  "equity",
    "Уставный капитал":                                                     "share_capital",
    "Нераспределенная прибыль":                                             "retained_earnings",
    "Резервный капитал":                                                    "reserves",
    "Резервы":                                                              "reserves",

    # Alternative field names that may appear
    "Доходы от процентов":                                                  "revenue",
    "Расходы по процентам":                                                 "interest_expense",
    "Прибыль от операционной деятельности":                                 "ebit",
    "Операционная прибыль":                                                 "ebit",

    # Real titles from the openinfo PnL/Balance Form2/Form1 banking template
    "ЧИСТАЯ ПРИБЫЛЬ (УБЫТКИ)":                                              "net_income",
    "Чистая прибыль (убытки)":                                              "net_income",
    "ЧИСТАЯ ПРИБЫЛЬ ДО УПЛАТЫ НАЛОГОВ И ДРУГИХ ПОПРАВОК":                   "ebt",
    "ДОХОД ДО ВВЕДЕНИЯ ПОПРАВОК":                                           "ebt",
    "ЧИСТЫЙ ДОХОД ДО ОПЕРАЦИОННЫХ РАСХОДОВ":                                "gross_profit",
    "ЧИСТЫЕ ПРОЦЕНТНЫЕ ДОХОДЫ ДО ОЦЕНКИ ВОЗМОЖНЫХ УБЫТКОВ ПО КРЕДИТАМ И ЛИЗИНГУ": "gross_profit",
    "ОПЕРАЦИОННЫЕ РАСХОДЫ":                                                 "operating_expenses",
    "Итого операционных расходов":                                          "operating_expenses",
    "Итого процентных расходов":                                            "interest_expense",
    "Итого процентных доходов":                                             "revenue",
    "Итого активов":                                                        "total_assets",
    "Итого обязательств":                                                   "total_liabilities",
    "Итого собственного капитала":                                          "equity",
    "Кредиты и лизинговые операции":                                        "loans_to_customers",
    "Кредиты и лизинговые операции, чистые":                                "loans_to_customers",
    "Кассовая наличность и другие платежные документы":                     "cash",
    "Срочные депозиты":                                                     "customer_deposits",
    "Депозиты до востребования":                                            "customer_deposits",
}


_TITLE_NUMBERING_RE = re.compile(r'^\s*(?:\d+|[a-zа-яёўқғҳ])\s*[.\)]\s*', re.IGNORECASE)


def _normalize_title(title) -> str:
    if not title:
        return ""
    text = str(title).strip()
    for _ in range(2):
        cleaned = _TITLE_NUMBERING_RE.sub('', text, count=1).strip()
        if cleaned == text:
            break
        text = cleaned
    return re.sub(r'\s+', ' ', text).lower()


_NORMALIZED_FIELD_MAP = {
    _normalize_title(key): value
    for source in (KEEP_TITLES, BANK_TITLES)
    for key, value in source.items()
    if _normalize_title(key)
}


ANNUAL_RATIOS = [
    "net_profit_margin", "return_on_equity", "return_on_assets",
    "debt_ratio", "debt_to_equity_ratio", "current_ratio",
    "quick_ratio", "total_asset_turnover", "gross_profit_margin", "ebit_margin",
]


def _get_field_mapping(title: str) -> str | None:
    """Get the field mapping from title, checking both standard and bank formats.

    Falls back to a normalized lookup so that titles arriving from openinfo as
    '14. Итого активов' / '      л. Итого процентных доходов' still match the
    plain-form keys we keep in KEEP_TITLES / BANK_TITLES.
    """
    if title in KEEP_TITLES:
        return KEEP_TITLES[title]
    if title in BANK_TITLES:
        return BANK_TITLES[title]
    normalized = _normalize_title(title)
    if normalized:
        mapped = _NORMALIZED_FIELD_MAP.get(normalized)
        if mapped:
            return mapped
    # Depreciation & amortization *expense* (a P&L / cash-flow flow) → used to
    # derive EBITDA. Require an expense context and exclude balance-sheet
    # accumulated depreciation ("накопленный износ", "остаточная стоимость"),
    # which is a stock, not the period charge.
    if isinstance(title, str):
        low = title.lower()
        if (("амортизац" in low) or ("износ" in low)) \
           and any(w in low for w in ("расход", "начисл", "деятельн", "себестоим")) \
           and not any(w in low for w in ("накопл", "остаточн", "первоначальн")):
            return "depreciation"
    return None


def df_to_annual(annual_df: pd.DataFrame) -> list:
    data = defaultdict(lambda: {"financials": {}, "ratios": {}})
    for _, row in annual_df.iterrows():
        year  = row.get("reporting_year")
        title = row.get("title")
        value = row.get("value")
        if pd.isna(year):
            continue
        year = int(year)
        field_name = _get_field_mapping(title)
        if field_name:
            # Don't overwrite if already set (prefer first match)
            if field_name not in data[year]["financials"]:
                data[year]["financials"][field_name] = value
        if not data[year]["ratios"]:
            for ratio in ANNUAL_RATIOS:
                if ratio in row.index and pd.notna(row[ratio]):
                    try:
                        data[year]["ratios"][ratio] = round(float(row[ratio]), 4)
                    except (ValueError, TypeError):
                        pass

    years = sorted(data.keys())
    result = []
    for i, year in enumerate(years):
        entry = {"year": year}
        entry.update(data[year]["financials"])
        entry.update(data[year]["ratios"])
        if i > 0:
            prev = data[years[i - 1]]["financials"]
            curr = data[year]["financials"]
            growth = {}
            for key in ["revenue", "gross_profit", "net_income", "equity", "total_assets"]:
                pv, cv = prev.get(key), curr.get(key)
                if pv and cv and pv != 0:
                    growth[f"{key}_growth_pct"] = round((cv - pv) / abs(pv) * 100, 2)
            if growth:
                entry["yoy_growth"] = growth
        result.append(entry)
    return result


def df_to_quarterly(quarter_df: pd.DataFrame) -> list:
    data = defaultdict(dict)
    for _, row in quarter_df.iterrows():
        year    = row.get("reporting_year")
        quarter = row.get("quarter")
        title   = row.get("title")
        value   = row.get("value")
        if pd.isna(year) or pd.isna(quarter):
            continue
        year, quarter = int(year), int(quarter)
        field_name = _get_field_mapping(title)
        if field_name:
            # Don't overwrite if already set
            if field_name not in data[(year, quarter)]:
                data[(year, quarter)][field_name] = value

    keys = sorted(data.keys())
    result = []
    for i, (year, quarter) in enumerate(keys):
        entry = {"year": year, "quarter": quarter, "period": f"{year}Q{quarter}"}
        entry.update(data[(year, quarter)])
        if i > 0:
            prev = data[keys[i - 1]]
            curr = data[(year, quarter)]
            growth = {}
            for key in ["revenue", "gross_profit", "net_income"]:
                pv, cv = prev.get(key), curr.get(key)
                if pv and cv and pv != 0:
                    growth[f"{key}_growth_pct"] = round((cv - pv) / abs(pv) * 100, 2)
            if growth:
                entry["qoq_growth"] = growth
        result.append(entry)
    return result


def slim_for_prompt(annual: list, quarterly: list) -> dict:
    keep_annual = {
        "year", "revenue", "gross_profit", "ebit", "net_income",
        "total_assets", "equity", "current_assets", "current_liabilities",
        "cash", "long_term_debt", "net_profit_margin", "return_on_equity",
        "return_on_assets", "debt_to_equity_ratio", "current_ratio",
        "gross_profit_margin", "ebit_margin", "yoy_growth",
        "inventory", "accounts_receivable", "accounts_payable",
        "interest_expense", "retained_earnings",
    }
    keep_quarterly = {
        "period", "revenue", "gross_profit", "ebit", "net_income",
        "total_assets", "equity", "current_assets", "current_liabilities",
        "cash", "qoq_growth",
    }
    annual_slim = [
        {k: v for k, v in row.items() if k in keep_annual}
        for row in annual[-5:]
    ]
    quarterly_slim = [
        {k: v for k, v in row.items() if k in keep_quarterly}
        for row in quarterly[-6:]
    ]

    # Если квартальных нет — строим приближение из годовых (делим на 4)
    if not quarterly_slim and annual_slim:
        print("   ⚠️ Квартальные данные отсутствуют — использую годовые как приближение")
        for row in annual_slim[-2:]:
            year = row.get("year", "?")
            for q in range(1, 5):
                approx = {"period": f"{year}Q{q}(approx)"}
                for k in ["revenue", "gross_profit", "ebit", "net_income",
                          "current_assets", "current_liabilities", "cash"]:
                    v = row.get(k)
                    if v:
                        approx[k] = round(v / 4, 0)
                quarterly_slim.append(approx)

    return {"currency": "UZS (млн)", "annual": annual_slim, "quarterly": quarterly_slim}

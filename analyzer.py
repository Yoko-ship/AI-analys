"""
Анализатор акций — профессиональная версия.

Методы анализа:
  • Fibonacci Retracement (уровни поддержки/сопротивления)
  • Piotroski F-Score (финансовая сила 0–9)
  • Graham Number (справедливая цена по Грэму)
  • Altman Z-Score (вероятность банкротства)
  • Buffett-критерии (ROE, долг, стабильность)
  • Peter Lynch PEG-подход (рост vs оценка)
  • Новости-катализаторы (компания + макро)
  • Скоринг 0–100
  • Упрощённый язык для не-финансистов
"""

import json
import math
import os
import re
import time
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
try:
    import anthropic
except ImportError:  # pragma: no cover - dependency is available in production
    anthropic = None
from main import get_data
from db import get_output_path

load_dotenv()

# ─────────────────────────────────────────────────────────
# КОНФИГ
# ─────────────────────────────────────────────────────────

API_KEY     = os.getenv("ANTHROPIC_API_KEY") or os.getenv("api_key")
OUTPUT_PATH = get_output_path()

MODEL_CHEAP = "claude-haiku-4-5-20251001"
MODEL_MAIN  = "claude-sonnet-4-6"

if not API_KEY:
    client = None
else:
    client = anthropic.Anthropic(api_key=API_KEY)


# ─────────────────────────────────────────────────────────
# RETRY
# ─────────────────────────────────────────────────────────

def api_call_with_retry(fn, max_retries=6):
    for attempt in range(max_retries):
        try:
            return fn()
        except anthropic.RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            wait = min(120, 15 * (2 ** attempt))
            try:
                resp = getattr(e, "response", None)
                if resp and hasattr(resp, "headers"):
                    ra = resp.headers.get("retry-after")
                    if ra:
                        wait = int(ra) + 2
            except Exception:
                pass
            print(f"   ⏳ Rate limit (попытка {attempt+1}/{max_retries}), жду {wait}с...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503) and attempt < max_retries - 1:
                wait = 20 * (attempt + 1)
                print(f"   ⏳ Сервер перегружен, жду {wait}с...")
                time.sleep(wait)
            else:
                raise


# ─────────────────────────────────────────────────────────
# МАППИНГ ПОЛЕЙ
# ─────────────────────────────────────────────────────────

# Standard industrial company field mappings
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

# Bank-specific field mappings (banks use different report format in Uzbekistan)
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
}

ANNUAL_RATIOS = [
    "net_profit_margin", "return_on_equity", "return_on_assets",
    "debt_ratio", "debt_to_equity_ratio", "current_ratio",
    "quick_ratio", "total_asset_turnover", "gross_profit_margin", "ebit_margin",
]


# ─────────────────────────────────────────────────────────
# DataFrame → структурированные списки
# ─────────────────────────────────────────────────────────

def _get_field_mapping(title: str) -> str | None:
    """Get the field mapping from title, checking both standard and bank formats."""
    if title in KEEP_TITLES:
        return KEEP_TITLES[title]
    if title in BANK_TITLES:
        return BANK_TITLES[title]
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


# ─────────────────────────────────────────────────────────
# РАСЧЁТ ЭКСПЕРТНЫХ МЕТРИК (чистый Python, бесплатно)
# ─────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────
# ОТРАСЛЕВЫЕ БЕНЧМАРКИ УЗБЕКИСТАНА
# Данные на основе публичной отчётности компаний за 2021–2024
# ─────────────────────────────────────────────────────────

INDUSTRY_BENCHMARKS = {
    "металлургия": {
        "name_ru":        "Металлургия и горнодобыча",
        "keywords":       ["металл","сталь","алюмин","медь","цинк","золото","серебро","уголь","руда","mining","met"],
        "net_margin":     {"weak": 3,  "ok": 8,   "good": 15},
        "roe":            {"weak": 6,  "ok": 12,  "good": 20},
        "roa":            {"weak": 2,  "ok": 6,   "good": 12},
        "debt_equity":    {"weak": 1.5,"ok": 0.8, "good": 0.3},  # слабо=выше, хорошо=ниже
        "current_ratio":  {"weak": 1.0,"ok": 1.5, "good": 2.5},
        "revenue_growth": {"weak": 3,  "ok": 10,  "good": 20},
        "capex_note":     "Капиталоёмкая отрасль — высокий долг норма",
        "wacc":           0.22,  # выше среднего из-за цикличности
    },
    "банки": {
        "name_ru":        "Банки и финансы",
        "keywords":       ["банк","bank","финанс","кредит","invest","capital","leasing","лизинг"],
        "net_margin":     {"weak": 10, "ok": 20,  "good": 30},
        "roe":            {"weak": 8,  "ok": 15,  "good": 25},
        "roa":            {"weak": 0.5,"ok": 1.5, "good": 3.0},
        "debt_equity":    {"weak": 8.0,"ok": 5.0, "good": 3.0},  # у банков высокое плечо норма
        "current_ratio":  {"weak": 1.0,"ok": 1.2, "good": 1.5},
        "revenue_growth": {"weak": 5,  "ok": 15,  "good": 30},
        "capex_note":     "Для банков ключевой показатель — NIM и NPL, не current ratio",
        "wacc":           0.18,
    },
    "химия": {
        "name_ru":        "Химическая промышленность и удобрения",
        "keywords":       ["хим","удобр","азот","карбамид","химик","нефтехим","пластик","chem","fertiliz"],
        "net_margin":     {"weak": 5,  "ok": 12,  "good": 20},
        "roe":            {"weak": 7,  "ok": 14,  "good": 22},
        "roa":            {"weak": 3,  "ok": 7,   "good": 13},
        "debt_equity":    {"weak": 1.5,"ok": 0.7, "good": 0.3},
        "current_ratio":  {"weak": 1.0,"ok": 1.5, "good": 2.5},
        "revenue_growth": {"weak": 4,  "ok": 12,  "good": 25},
        "capex_note":     "Зависит от мировых цен на газ и удобрения",
        "wacc":           0.21,
    },
    "энергетика": {
        "name_ru":        "Энергетика и коммунальные услуги",
        "keywords":       ["энерг","электр","газ","тепло","water","уголь","генераци","power","energy","utility"],
        "net_margin":     {"weak": 2,  "ok": 6,   "good": 12},
        "roe":            {"weak": 4,  "ok": 9,   "good": 16},
        "roa":            {"weak": 1,  "ok": 4,   "good": 8},
        "debt_equity":    {"weak": 2.0,"ok": 1.0, "good": 0.5},
        "current_ratio":  {"weak": 0.8,"ok": 1.2, "good": 2.0},
        "revenue_growth": {"weak": 2,  "ok": 8,   "good": 18},
        "capex_note":     "Регулируемые тарифы — стабильность выше роста",
        "wacc":           0.18,
    },
    "телеком": {
        "name_ru":        "Телекоммуникации и IT",
        "keywords":       ["телеком","связь","мобил","интернет","telecom","mobile","digital","it","tech","software"],
        "net_margin":     {"weak": 5,  "ok": 15,  "good": 25},
        "roe":            {"weak": 8,  "ok": 18,  "good": 30},
        "roa":            {"weak": 3,  "ok": 8,   "good": 15},
        "debt_equity":    {"weak": 1.5,"ok": 0.8, "good": 0.2},
        "current_ratio":  {"weak": 0.8,"ok": 1.2, "good": 2.0},
        "revenue_growth": {"weak": 5,  "ok": 15,  "good": 30},
        "capex_note":     "Высокие инвестиции в сеть — нормальны для роста",
        "wacc":           0.19,
    },
    "строительство": {
        "name_ru":        "Строительство и недвижимость",
        "keywords":       ["строи","недвижим","цемент","стекло","жилой","девелоп","construct","real estate"],
        "net_margin":     {"weak": 3,  "ok": 8,   "good": 15},
        "roe":            {"weak": 5,  "ok": 12,  "good": 20},
        "roa":            {"weak": 2,  "ok": 5,   "good": 10},
        "debt_equity":    {"weak": 2.5,"ok": 1.2, "good": 0.5},
        "current_ratio":  {"weak": 1.0,"ok": 1.5, "good": 2.5},
        "revenue_growth": {"weak": 5,  "ok": 15,  "good": 30},
        "capex_note":     "Цикличная отрасль — запас ликвидности критичен",
        "wacc":           0.22,
    },
    "торговля": {
        "name_ru":        "Торговля и ритейл",
        "keywords":       ["торгов","ритейл","магазин","дистриб","wholesale","retail","trade","фарм","аптек"],
        "net_margin":     {"weak": 1,  "ok": 4,   "good": 8},
        "roe":            {"weak": 5,  "ok": 15,  "good": 25},
        "roa":            {"weak": 2,  "ok": 6,   "good": 12},
        "debt_equity":    {"weak": 2.0,"ok": 1.0, "good": 0.4},
        "current_ratio":  {"weak": 1.0,"ok": 1.5, "good": 2.5},
        "revenue_growth": {"weak": 5,  "ok": 15,  "good": 30},
        "capex_note":     "Низкая маржа — нормально для торговли, важна оборачиваемость",
        "wacc":           0.20,
    },
    "агропром": {
        "name_ru":        "Агропромышленный комплекс",
        "keywords":       ["агро","сельхоз","продовол","мясо","молоко","зерно","хлопок","масло","food","agro","farm"],
        "net_margin":     {"weak": 2,  "ok": 6,   "good": 12},
        "roe":            {"weak": 4,  "ok": 10,  "good": 18},
        "roa":            {"weak": 2,  "ok": 5,   "good": 10},
        "debt_equity":    {"weak": 2.0,"ok": 1.0, "good": 0.4},
        "current_ratio":  {"weak": 1.0,"ok": 1.5, "good": 2.5},
        "revenue_growth": {"weak": 3,  "ok": 10,  "good": 20},
        "capex_note":     "Сезонность — ликвидность важна в межсезонье",
        "wacc":           0.21,
    },
    "нефтегаз": {
        "name_ru":        "Нефть, газ и горная добыча",
        "keywords":       ["нефт","газ","oil","gas","добыч","уголь","шахт","mining","геолог"],
        "net_margin":     {"weak": 5,  "ok": 15,  "good": 25},
        "roe":            {"weak": 7,  "ok": 15,  "good": 25},
        "roa":            {"weak": 3,  "ok": 8,   "good": 15},
        "debt_equity":    {"weak": 1.5,"ok": 0.7, "good": 0.3},
        "current_ratio":  {"weak": 1.0,"ok": 1.5, "good": 2.5},
        "revenue_growth": {"weak": 3,  "ok": 10,  "good": 20},
        "capex_note":     "Сильно зависит от мировых цен на сырьё",
        "wacc":           0.22,
    },
}

# Дефолтный бенчмарк если отрасль не определена
INDUSTRY_DEFAULT = {
    "name_ru":        "Диверсифицированная / прочие отрасли",
    "keywords":       [],
    "net_margin":     {"weak": 3,  "ok": 8,   "good": 15},
    "roe":            {"weak": 5,  "ok": 12,  "good": 20},
    "roa":            {"weak": 2,  "ok": 6,   "good": 12},
    "debt_equity":    {"weak": 2.0,"ok": 1.0, "good": 0.4},
    "current_ratio":  {"weak": 1.0,"ok": 1.5, "good": 2.5},
    "revenue_growth": {"weak": 5,  "ok": 15,  "good": 25},
    "capex_note":     "Используются общие нормы для рынка Узбекистана",
    "wacc":           0.20,
}


def detect_industry(company_name: str, web_research: str = "", profile: str = "") -> dict:
    """
    Определяет отрасль компании по ключевым словам из названия,
    веб-исследования и профиля. Возвращает словарь бенчмарков.
    """
    text = (company_name + " " + web_research[:500] + " " + profile[:500]).lower()
    scores = {}
    for sector, data in INDUSTRY_BENCHMARKS.items():
        score = sum(1 for kw in data["keywords"] if kw in text)
        if score > 0:
            scores[sector] = score
    if not scores:
        return {"sector": "прочие", **INDUSTRY_DEFAULT}
    best = max(scores, key=scores.get)
    return {"sector": best, **INDUSTRY_BENCHMARKS[best]}


def compare_to_industry(metrics: dict, industry: dict) -> dict:
    """
    Сравнивает ключевые метрики компании с отраслевыми бенчмарками.
    Возвращает dict с оценкой каждого показателя: weak / ok / good.
    """
    latest = {}
    # Из piotroski details берём roa approx через altman components
    roa  = 0.0
    if "altman_z_score" in metrics:
        roa = metrics["altman_z_score"]["components"].get("X3_прибыльность_активов", 0)

    # Из buffett_criteria берём roe и margin
    roe_str    = metrics.get("buffett_criteria", {}).get("checks", {}).get("ROE > 15%", {}).get("value", "0%")
    margin_str = metrics.get("buffett_criteria", {}).get("checks", {}).get("Чистая маржа > 10%", {}).get("value", "0%")
    de_str     = metrics.get("buffett_criteria", {}).get("checks", {}).get("Долг/капитал < 0.5", {}).get("value", "0")
    growth_str = metrics.get("buffett_criteria", {}).get("checks", {}).get("Рост выручки 5 лет > 30%", {}).get("value", "0%")

    def parse_pct(s):
        try:
            return float(str(s).replace("%","").replace(",",".").strip())
        except:
            return 0.0

    roe    = parse_pct(roe_str)
    margin = parse_pct(margin_str)
    de     = parse_pct(de_str)
    growth = parse_pct(growth_str)

    def rate(val, bench, higher_is_better=True):
        """Оцениваем показатель относительно бенчмарков."""
        if higher_is_better:
            if val >= bench["good"]: return "good"
            if val >= bench["ok"]:   return "ok"
            return "weak"
        else:  # для долга — чем меньше, тем лучше
            if val <= bench["good"]: return "good"
            if val <= bench["ok"]:   return "ok"
            return "weak"

    ratings = {
        "net_margin":     {"value": round(margin,1), "rating": rate(margin, industry["net_margin"])},
        "roe":            {"value": round(roe,1),    "rating": rate(roe,    industry["roe"])},
        "roa":            {"value": round(roa*100,1),"rating": rate(roa*100, industry["roa"])},
        "debt_equity":    {"value": round(de,2),     "rating": rate(de,    industry["debt_equity"], higher_is_better=False)},
        "revenue_growth": {"value": round(growth,1), "rating": rate(growth, industry["revenue_growth"])},
    }

    # Сводная оценка по отрасли
    good_count = sum(1 for r in ratings.values() if r["rating"] == "good")
    ok_count   = sum(1 for r in ratings.values() if r["rating"] == "ok")
    weak_count = sum(1 for r in ratings.values() if r["rating"] == "weak")

    if good_count >= 3:
        industry_verdict = f"Выше среднего по отрасли «{industry['name_ru']}»"
        industry_grade   = "outperform"
    elif weak_count >= 3:
        industry_verdict = f"Ниже среднего по отрасли «{industry['name_ru']}»"
        industry_grade   = "underperform"
    else:
        industry_verdict = f"На уровне среднего по отрасли «{industry['name_ru']}»"
        industry_grade   = "inperform"

    return {
        "sector":          industry.get("sector", "прочие"),
        "sector_name":     industry["name_ru"],
        "ratings":         ratings,
        "good_count":      good_count,
        "ok_count":        ok_count,
        "weak_count":      weak_count,
        "verdict":         industry_verdict,
        "grade":           industry_grade,
        "capex_note":      industry.get("capex_note",""),
        "wacc_used":       industry.get("wacc", 0.20),
    }


def compute_metrics(annual_data: list, quarterly_data: list = None) -> dict:
    """
    Вычисляет профессиональные метрики по финансовым данным.
    Все расчёты — чистый Python, без API.
    quarterly_data используется для momentum-анализа (3/6/12 месяцев).
    """
    if not annual_data:
        return {}
    quarterly_data = quarterly_data or []

    latest = annual_data[-1]
    prev   = annual_data[-2] if len(annual_data) >= 2 else {}

    def get(d, key, default=None):
        v = d.get(key, default)
        return v if v and not (isinstance(v, float) and math.isnan(v)) else default

    # ── Базовые значения ─────────────────────────────────
    revenue         = get(latest, "revenue", 0)
    net_income      = get(latest, "net_income", 0)
    equity          = get(latest, "equity", 0)
    total_assets    = get(latest, "total_assets", 0)
    current_assets  = get(latest, "current_assets", 0)
    current_liab    = get(latest, "current_liabilities", 0)
    long_term_debt  = get(latest, "long_term_debt", 0)
    cash            = get(latest, "cash", 0)
    inventory       = get(latest, "inventory", 0)
    accounts_rec    = get(latest, "accounts_receivable", 0)
    ebit            = get(latest, "ebit", 0)
    interest_exp    = get(latest, "interest_expense", 0)
    gross_profit    = get(latest, "gross_profit", 0)
    ret_earnings    = get(latest, "retained_earnings", 0)

    prev_revenue    = get(prev, "revenue", 0)
    prev_net_income = get(prev, "net_income", 0)
    prev_assets     = get(prev, "total_assets", 0)
    prev_equity     = get(prev, "equity", 0)
    prev_curr_liab  = get(prev, "current_liabilities", 0)
    prev_long_debt  = get(prev, "long_term_debt", 0)

    metrics = {}

    # ── FIBONACCI RETRACEMENT ────────────────────────────
    # Используем выручку как прокси для ценового движения
    revenues = [get(y, "revenue", 0) for y in annual_data if get(y, "revenue")]
    revenues = [r for r in revenues if r and r > 0]

    if len(revenues) >= 2:
        high = max(revenues)
        low  = min(revenues)
        diff = high - low
        fib_levels = {
            "high":   round(high, 0),
            "low":    round(low, 0),
            "0.236":  round(high - 0.236 * diff, 0),
            "0.382":  round(high - 0.382 * diff, 0),
            "0.500":  round(high - 0.500 * diff, 0),
            "0.618":  round(high - 0.618 * diff, 0),  # золотое сечение
            "0.786":  round(high - 0.786 * diff, 0),
        }
        current_rev = revenues[-1]
        # Определяем зону Фибоначчи для текущей выручки
        if current_rev >= fib_levels["0.236"]:
            fib_zone = "выше 23.6% — сильный восходящий тренд"
        elif current_rev >= fib_levels["0.382"]:
            fib_zone = "зона 23.6–38.2% — здоровая коррекция"
        elif current_rev >= fib_levels["0.500"]:
            fib_zone = "зона 38.2–50% — умеренная коррекция"
        elif current_rev >= fib_levels["0.618"]:
            fib_zone = "зона 50–61.8% — глубокая коррекция (золотое сечение)"
        else:
            fib_zone = "ниже 61.8% — сильный нисходящий тренд"

        metrics["fibonacci"] = {
            "levels_by_revenue": fib_levels,
            "current_revenue": round(current_rev, 0),
            "current_zone": fib_zone,
            "interpretation": (
                "Уровни Фибоначчи показывают ключевые зоны поддержки и сопротивления "
                "на основе исторических максимумов и минимумов выручки компании."
            ),
        }

    # ── PIOTROSKI F-SCORE (0–9) ──────────────────────────
    # Метод Джозефа Пиотроски для оценки финансовой силы
    f_score = 0
    f_details = {}

    # Прибыльность (0–4 балла)
    f1 = 1 if net_income > 0 else 0
    f_details["ROA > 0 (прибыльность)"] = f1
    f_score += f1

    roa = net_income / total_assets if total_assets else 0
    prev_roa = prev_net_income / prev_assets if prev_assets else 0
    f2 = 1 if roa > prev_roa else 0
    f_details["ROA растёт (улучшение)"] = f2
    f_score += f2

    op_cf = ebit  # упрощение: используем EBIT как прокси операционного CF
    f3 = 1 if op_cf > 0 else 0
    f_details["Операционный поток > 0"] = f3
    f_score += f3

    f4 = 1 if (op_cf > net_income) else 0
    f_details["CF > чистой прибыли (качество прибыли)"] = f4
    f_score += f4

    # Leverage/Liquidity (0–3 балла)
    curr_ratio = current_assets / current_liab if current_liab else 0
    prev_curr_ratio = (get(prev, "current_assets", 0) / prev_curr_liab) if prev_curr_liab else 0
    f5 = 1 if curr_ratio > prev_curr_ratio else 0
    f_details["Ликвидность улучшилась"] = f5
    f_score += f5

    leverage = long_term_debt / total_assets if total_assets else 0
    prev_leverage = prev_long_debt / prev_assets if prev_assets else 0
    f6 = 1 if leverage < prev_leverage else 0
    f_details["Долговая нагрузка снизилась"] = f6
    f_score += f6

    # Упрощение: нет доп. эмиссии акций (считаем как рост equity без долгов)
    f7 = 1 if equity > prev_equity else 0
    f_details["Капитал не размывался"] = f7
    f_score += f7

    # Эффективность (0–2 балла)
    gp_margin = gross_profit / revenue if revenue else 0
    prev_gp   = get(prev, "gross_profit", 0)
    prev_rev  = get(prev, "revenue", 0)
    prev_gp_margin = prev_gp / prev_rev if prev_rev else 0
    f8 = 1 if gp_margin > prev_gp_margin else 0
    f_details["Валовая маржа растёт"] = f8
    f_score += f8

    asset_turn = revenue / total_assets if total_assets else 0
    prev_asset_turn = prev_revenue / prev_assets if prev_assets else 0
    f9 = 1 if asset_turn > prev_asset_turn else 0
    f_details["Оборачиваемость активов растёт"] = f9
    f_score += f9

    if f_score >= 7:
        f_verdict = "Сильная компания — высокая вероятность роста"
    elif f_score >= 4:
        f_verdict = "Средняя компания — нейтральные перспективы"
    else:
        f_verdict = "Слабая компания — высокий риск"

    metrics["piotroski_f_score"] = {
        "score": f_score,
        "max": 9,
        "verdict": f_verdict,
        "details": f_details,
    }

    # ── GRAHAM NUMBER ────────────────────────────────────
    # Бен Грэм: справедливая цена = √(22.5 × EPS × BVPS)
    # Используем прокси: EPS ~ net_income/equity, BVPS ~ equity
    # (без данных о кол-ве акций используем относительный показатель)
    if net_income > 0 and equity > 0:
        # Упрощённый Graham: справедливая стоимость компании
        # GV = √(22.5 × NI × BV) — масштаб компании, не цена акции
        graham_value = math.sqrt(22.5 * abs(net_income) * abs(equity))
        graham_ratio = graham_value / total_assets if total_assets else 0
        metrics["graham_number"] = {
            "estimated_fair_value_proxy": round(graham_value, 0),
            "vs_total_assets": round(graham_ratio, 2),
            "interpretation": (
                "Число Грэма — оценка справедливой стоимости бизнеса. "
                f"Если рыночная капитализация ниже {round(graham_value/1e9, 1)} млрд UZS — "
                "акция потенциально недооценена."
            ),
        }

    # ── ALTMAN Z-SCORE ───────────────────────────────────
    # Предсказывает вероятность банкротства
    # Z = 1.2×X1 + 1.4×X2 + 3.3×X3 + 0.6×X4 + 1.0×X5
    if total_assets > 0:
        x1 = (current_assets - current_liab) / total_assets
        x2 = ret_earnings / total_assets if ret_earnings else 0
        x3 = ebit / total_assets
        total_liab = total_assets - equity
        x4 = equity / total_liab if total_liab > 0 else 0
        x5 = revenue / total_assets

        z = 1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5

        if z > 2.99:
            z_zone = "Безопасная зона — банкротство маловероятно"
        elif z > 1.81:
            z_zone = "Серая зона — есть риски, нужен мониторинг"
        else:
            z_zone = "Опасная зона — высокий риск финансовых проблем"

        metrics["altman_z_score"] = {
            "score": round(z, 2),
            "zone": z_zone,
            "components": {
                "X1_ликвидность": round(x1, 3),
                "X2_накопленная_прибыль": round(x2, 3),
                "X3_прибыльность_активов": round(x3, 3),
                "X4_капитал_vs_долг": round(x4, 3),
                "X5_эффективность": round(x5, 3),
            },
        }

    # ── BUFFETT-КРИТЕРИИ ─────────────────────────────────
    roe = net_income / equity if equity else 0
    debt_to_equity = (long_term_debt) / equity if equity else 0
    net_margin = net_income / revenue if revenue else 0

    # Стабильность прибыли — кол-во лет с положительной прибылью
    profitable_years = sum(
        1 for y in annual_data if (get(y, "net_income") or 0) > 0
    )

    # Рост выручки за 5 лет
    rev_first = get(annual_data[0], "revenue", 0) if annual_data else 0
    rev_last  = get(annual_data[-1], "revenue", 0) if annual_data else 0
    rev_growth_5y = ((rev_last / rev_first) - 1) * 100 if rev_first and rev_first > 0 else 0

    buffett_checks = {
        "ROE > 15%": {"pass": roe > 0.15, "value": f"{roe*100:.1f}%"},
        "Долг/капитал < 0.5": {"pass": debt_to_equity < 0.5, "value": f"{debt_to_equity:.2f}"},
        "Чистая маржа > 10%": {"pass": net_margin > 0.10, "value": f"{net_margin*100:.1f}%"},
        f"Прибыльность {profitable_years}/{len(annual_data)} лет": {
            "pass": profitable_years >= len(annual_data) * 0.8,
            "value": f"{profitable_years} из {len(annual_data)}"
        },
        "Рост выручки 5 лет > 30%": {"pass": rev_growth_5y > 30, "value": f"{rev_growth_5y:.1f}%"},
    }
    buffett_passed = sum(1 for v in buffett_checks.values() if v["pass"])
    metrics["buffett_criteria"] = {
        "passed": buffett_passed,
        "total": len(buffett_checks),
        "checks": buffett_checks,
        "verdict": (
            "Компания соответствует критериям Баффетта" if buffett_passed >= 4
            else "Компания частично соответствует" if buffett_passed >= 2
            else "Компания не соответствует критериям Баффетта"
        ),
    }

    # ── INTEREST COVERAGE RATIO ──────────────────────────
    if interest_exp and interest_exp > 0:
        icr = ebit / interest_exp
        metrics["interest_coverage"] = {
            "ratio": round(icr, 2),
            "verdict": (
                "Отлично — легко платит по долгам" if icr > 5
                else "Нормально — платит по долгам" if icr > 2
                else "Риск — могут быть проблемы с долгами"
            ),
        }

    # ── EFFICIENCY METRICS (NEW) ─────────────────────────
    # Оборачиваемость и эффективность использования активов
    cogs = get(latest, "cogs", 0) or 0
    accounts_pay = get(latest, "accounts_payable", 0) or 0
    prev_inventory = get(prev, "inventory", 0) or 0
    prev_accounts_rec = get(prev, "accounts_receivable", 0) or 0
    prev_accounts_pay = get(prev, "accounts_payable", 0) or 0

    efficiency = {}

    # Inventory Turnover (оборачиваемость запасов)
    avg_inventory = (inventory + prev_inventory) / 2 if prev_inventory else inventory
    if avg_inventory and cogs:
        inv_turnover = cogs / avg_inventory
        inv_days = 365 / inv_turnover if inv_turnover > 0 else 0
        efficiency["inventory_turnover"] = {
            "ratio": round(inv_turnover, 2),
            "days": round(inv_days, 0),
            "verdict": (
                "Отлично — быстрая оборачиваемость" if inv_days < 60
                else "Нормально" if inv_days < 120
                else "Медленно — деньги заморожены в запасах"
            ),
        }

    # Receivable Days (дни дебиторской задолженности)
    avg_receivables = (accounts_rec + prev_accounts_rec) / 2 if prev_accounts_rec else accounts_rec
    if avg_receivables and revenue:
        rec_turnover = revenue / avg_receivables
        rec_days = 365 / rec_turnover if rec_turnover > 0 else 0
        efficiency["receivable_days"] = {
            "ratio": round(rec_turnover, 2),
            "days": round(rec_days, 0),
            "verdict": (
                "Отлично — быстро собирают деньги" if rec_days < 30
                else "Нормально" if rec_days < 60
                else "Медленно — деньги застряли у клиентов"
            ),
        }

    # Payable Days (дни кредиторской задолженности)
    avg_payables = (accounts_pay + prev_accounts_pay) / 2 if prev_accounts_pay else accounts_pay
    if avg_payables and cogs:
        pay_turnover = cogs / avg_payables
        pay_days = 365 / pay_turnover if pay_turnover > 0 else 0
        efficiency["payable_days"] = {
            "ratio": round(pay_turnover, 2),
            "days": round(pay_days, 0),
            "verdict": (
                "Хорошо — используют деньги поставщиков" if pay_days > 45
                else "Нормально" if pay_days > 20
                else "Платят слишком быстро"
            ),
        }

    # Cash Conversion Cycle (цикл конвертации денег)
    inv_days_val = efficiency.get("inventory_turnover", {}).get("days", 0) or 0
    rec_days_val = efficiency.get("receivable_days", {}).get("days", 0) or 0
    pay_days_val = efficiency.get("payable_days", {}).get("days", 0) or 0
    if inv_days_val or rec_days_val:
        ccc = inv_days_val + rec_days_val - pay_days_val
        efficiency["cash_conversion_cycle"] = {
            "days": round(ccc, 0),
            "verdict": (
                "Отрицательный CCC — бизнес генерирует кеш" if ccc < 0
                else "Отлично" if ccc < 30
                else "Нормально" if ccc < 60
                else "Долгий цикл — много денег заморожено"
            ),
            "interpretation": (
                f"От покупки товара до получения денег: {round(ccc, 0)} дней"
            ),
        }

    if efficiency:
        metrics["efficiency"] = efficiency

    # ── DUPONT ANALYSIS (ROE Decomposition) ──────────────
    # ROE = Net Margin × Asset Turnover × Equity Multiplier
    if revenue and total_assets and equity and equity > 0:
        net_margin_pct = (net_income / revenue) * 100 if revenue else 0
        asset_turnover = revenue / total_assets
        equity_multiplier = total_assets / equity
        roe_dupont = (net_income / revenue) * (revenue / total_assets) * (total_assets / equity) * 100

        # Определяем драйверы ROE
        drivers = []
        if net_margin_pct > 10:
            drivers.append("высокая маржа")
        elif net_margin_pct < 3:
            drivers.append("низкая маржа тянет вниз")

        if asset_turnover > 1.5:
            drivers.append("эффективное использование активов")
        elif asset_turnover < 0.5:
            drivers.append("активы работают неэффективно")

        if equity_multiplier > 3:
            drivers.append("высокий leverage (риск)")
        elif equity_multiplier < 1.5:
            drivers.append("консервативная структура капитала")

        metrics["dupont_analysis"] = {
            "roe_pct": round(roe_dupont, 2),
            "components": {
                "net_margin_pct": round(net_margin_pct, 2),
                "asset_turnover": round(asset_turnover, 3),
                "equity_multiplier": round(equity_multiplier, 2),
            },
            "drivers": drivers if drivers else ["сбалансированный профиль"],
            "interpretation": (
                f"ROE {round(roe_dupont, 1)}% = "
                f"маржа {round(net_margin_pct, 1)}% × "
                f"оборачиваемость {round(asset_turnover, 2)}x × "
                f"leverage {round(equity_multiplier, 1)}x"
            ),
        }

    # ── WORKING CAPITAL ANALYSIS ─────────────────────────
    working_capital = current_assets - current_liab
    prev_working_cap = get(prev, "current_assets", 0) - get(prev, "current_liabilities", 0)

    wc_change = working_capital - prev_working_cap if prev_working_cap else 0
    wc_to_revenue = (working_capital / revenue * 100) if revenue else 0

    # Quick Ratio (без запасов)
    quick_assets = current_assets - inventory
    quick_ratio = quick_assets / current_liab if current_liab else 0

    # Cash Ratio (только деньги)
    cash_ratio = cash / current_liab if current_liab else 0

    metrics["working_capital"] = {
        "amount": round(working_capital, 0),
        "change_yoy": round(wc_change, 0),
        "pct_of_revenue": round(wc_to_revenue, 1),
        "current_ratio": round(curr_ratio, 2),
        "quick_ratio": round(quick_ratio, 2),
        "cash_ratio": round(cash_ratio, 2),
        "verdict": (
            "Отлично — избыток ликвидности" if curr_ratio > 2.5 and quick_ratio > 1.5
            else "Хорошо — здоровая ликвидность" if curr_ratio > 1.5 and quick_ratio > 1.0
            else "Нормально — достаточная ликвидность" if curr_ratio > 1.0
            else "Риск — может не хватить на текущие платежи"
        ),
        "change_verdict": (
            "Рабочий капитал растёт" if wc_change > 0
            else "Рабочий капитал снижается" if wc_change < 0
            else "Без изменений"
        ),
    }

    # ── HORIZONTAL ANALYSIS (Горизонтальный анализ) ──────
    # Сравнение показателей текущего года с предыдущим (YoY изменения)
    horizontal = {}

    def yoy_change(current, previous):
        if current and previous and previous != 0:
            change = current - previous
            pct = (change / abs(previous)) * 100
            return {"current": round(current, 0), "previous": round(previous, 0),
                    "change": round(change, 0), "pct": round(pct, 1)}
        return None

    # Ключевые статьи для горизонтального анализа
    h_items = [
        ("revenue", "Выручка"),
        ("gross_profit", "Валовая прибыль"),
        ("net_income", "Чистая прибыль"),
        ("total_assets", "Всего активов"),
        ("equity", "Собственный капитал"),
        ("current_assets", "Оборотные активы"),
        ("current_liabilities", "Краткосрочные обязательства"),
        ("long_term_debt", "Долгосрочный долг"),
        ("cash", "Денежные средства"),
        ("inventory", "Запасы"),
    ]

    for key, label in h_items:
        curr_val = get(latest, key, 0)
        prev_val = get(prev, key, 0)
        change = yoy_change(curr_val, prev_val)
        if change:
            horizontal[key] = {"label": label, **change}

    if horizontal:
        # Определяем общий тренд горизонтального анализа
        growing = sum(1 for v in horizontal.values() if v.get("pct", 0) > 5)
        declining = sum(1 for v in horizontal.values() if v.get("pct", 0) < -5)

        metrics["horizontal_analysis"] = {
            "items": horizontal,
            "summary": {
                "growing_count": growing,
                "declining_count": declining,
                "stable_count": len(horizontal) - growing - declining,
            },
            "verdict": (
                "Позитивная динамика — большинство показателей растут" if growing > declining + 2
                else "Негативная динамика — большинство показателей падают" if declining > growing + 2
                else "Смешанная динамика — нет явного тренда"
            ),
        }

    # ── VERTICAL ANALYSIS (Вертикальный анализ) ───────────
    # Структура баланса: каждая статья как % от общих активов
    # Структура доходов: каждая статья как % от выручки
    vertical = {}

    # Баланс: % от total_assets
    if total_assets > 0:
        balance_structure = {}
        balance_items = [
            ("cash", "Денежные средства"),
            ("accounts_receivable", "Дебиторская задолженность"),
            ("inventory", "Запасы"),
            ("current_assets", "Оборотные активы"),
            ("long_term_debt", "Долгосрочный долг"),
            ("equity", "Собственный капитал"),
        ]
        for key, label in balance_items:
            val = get(latest, key, 0) or 0
            if val:
                balance_structure[key] = {
                    "label": label,
                    "value": round(val, 0),
                    "pct_of_assets": round((val / total_assets) * 100, 1),
                }

        # Добавляем обязательства (total_assets - equity)
        total_liab = total_assets - equity
        if total_liab > 0:
            balance_structure["total_liabilities"] = {
                "label": "Всего обязательств",
                "value": round(total_liab, 0),
                "pct_of_assets": round((total_liab / total_assets) * 100, 1),
            }

        vertical["balance_sheet"] = {
            "base": "total_assets",
            "base_value": round(total_assets, 0),
            "items": balance_structure,
            "equity_ratio": round((equity / total_assets) * 100, 1) if equity else 0,
            "debt_ratio": round((total_liab / total_assets) * 100, 1) if total_liab else 0,
        }

    # Отчет о прибылях: % от выручки
    if revenue > 0:
        income_structure = {}
        income_items = [
            ("gross_profit", "Валовая прибыль"),
            ("ebit", "Операционная прибыль (EBIT)"),
            ("net_income", "Чистая прибыль"),
            ("interest_expense", "Процентные расходы"),
        ]
        for key, label in income_items:
            val = get(latest, key, 0) or 0
            if val:
                income_structure[key] = {
                    "label": label,
                    "value": round(val, 0),
                    "pct_of_revenue": round((val / revenue) * 100, 1),
                }

        # Расчет COGS если есть валовая прибыль
        if gross_profit:
            cogs_calc = revenue - gross_profit
            income_structure["cogs"] = {
                "label": "Себестоимость",
                "value": round(cogs_calc, 0),
                "pct_of_revenue": round((cogs_calc / revenue) * 100, 1),
            }

        vertical["income_statement"] = {
            "base": "revenue",
            "base_value": round(revenue, 0),
            "items": income_structure,
            "gross_margin_pct": round((gross_profit / revenue) * 100, 1) if gross_profit else 0,
            "operating_margin_pct": round((ebit / revenue) * 100, 1) if ebit else 0,
            "net_margin_pct": round((net_income / revenue) * 100, 1),
        }

    if vertical:
        metrics["vertical_analysis"] = vertical

    # ── PROFITABILITY RATIOS (Коэффициенты рентабельности) ─
    profitability = {}

    if revenue > 0:
        profitability["gross_margin"] = {
            "value": round((gross_profit / revenue) * 100, 2) if gross_profit else 0,
            "benchmark": "15-40%",
            "verdict": (
                "Отлично" if gross_profit and (gross_profit / revenue) > 0.35
                else "Хорошо" if gross_profit and (gross_profit / revenue) > 0.20
                else "Низкая маржа"
            ),
        }
        profitability["operating_margin"] = {
            "value": round((ebit / revenue) * 100, 2) if ebit else 0,
            "benchmark": "10-25%",
            "verdict": (
                "Отлично" if ebit and (ebit / revenue) > 0.20
                else "Хорошо" if ebit and (ebit / revenue) > 0.10
                else "Низкая операционная маржа"
            ),
        }
        profitability["net_margin"] = {
            "value": round((net_income / revenue) * 100, 2),
            "benchmark": "5-15%",
            "verdict": (
                "Отлично" if (net_income / revenue) > 0.15
                else "Хорошо" if (net_income / revenue) > 0.08
                else "Нормально" if (net_income / revenue) > 0.03
                else "Низкая чистая маржа"
            ),
        }

    if total_assets > 0:
        profitability["roa"] = {
            "value": round((net_income / total_assets) * 100, 2),
            "benchmark": "5-10%",
            "verdict": (
                "Отлично" if (net_income / total_assets) > 0.10
                else "Хорошо" if (net_income / total_assets) > 0.05
                else "Низкая доходность активов"
            ),
        }

    if equity > 0:
        profitability["roe"] = {
            "value": round((net_income / equity) * 100, 2),
            "benchmark": "15-25%",
            "verdict": (
                "Отлично" if (net_income / equity) > 0.20
                else "Хорошо" if (net_income / equity) > 0.12
                else "Низкая доходность капитала"
            ),
        }

    if profitability:
        metrics["profitability_ratios"] = profitability

    # ── SOLVENCY RATIOS (Коэффициенты платежеспособности) ─
    solvency = {}
    total_liab = total_assets - equity if total_assets and equity else 0

    if total_assets > 0:
        solvency["debt_ratio"] = {
            "value": round((total_liab / total_assets) * 100, 1),
            "benchmark": "<50%",
            "verdict": (
                "Отлично — низкий долг" if (total_liab / total_assets) < 0.40
                else "Нормально" if (total_liab / total_assets) < 0.60
                else "Высокий долг — риск"
            ),
        }

    if equity > 0 and total_liab > 0:
        dte = total_liab / equity
        solvency["debt_to_equity"] = {
            "value": round(dte, 2),
            "benchmark": "<1.0",
            "verdict": (
                "Отлично — капитал превышает долг" if dte < 0.5
                else "Нормально" if dte < 1.5
                else "Высокий финансовый рычаг"
            ),
        }

    if equity > 0:
        solvency["equity_ratio"] = {
            "value": round((equity / total_assets) * 100, 1) if total_assets else 0,
            "benchmark": ">40%",
            "verdict": (
                "Отлично — сильный капитал" if total_assets and (equity / total_assets) > 0.50
                else "Нормально" if total_assets and (equity / total_assets) > 0.30
                else "Слабая капитализация"
            ),
        }

    if solvency:
        metrics["solvency_ratios"] = solvency

    # ── CASH FLOW ANALYSIS (Анализ денежных потоков) ──────
    # Используем доступные данные для оценки денежных потоков
    cash_flow = {}

    # Операционный денежный поток (прокси через EBIT + амортизация)
    # Упрощение: OCF ≈ EBIT × (1 - tax) + depreciation (если нет прямых данных)
    op_cash_flow = get(latest, "operating_cash_flow", 0)
    if not op_cash_flow and ebit > 0:
        # Грубая оценка: EBIT после налога как прокси OCF
        op_cash_flow = ebit * 0.85  # ~15% налог

    if op_cash_flow and revenue > 0:
        ocf_to_sales = (op_cash_flow / revenue) * 100
        cash_flow["ocf_to_sales"] = {
            "value": round(ocf_to_sales, 1),
            "interpretation": (
                "Отлично — сильная генерация кеша" if ocf_to_sales > 15
                else "Хорошо — здоровый денежный поток" if ocf_to_sales > 8
                else "Нормально" if ocf_to_sales > 3
                else "Слабый денежный поток"
            ),
        }

    # Коэффициент денежного покрытия
    if op_cash_flow and current_liab > 0:
        cash_coverage = op_cash_flow / current_liab
        cash_flow["cash_coverage_ratio"] = {
            "value": round(cash_coverage, 2),
            "interpretation": (
                "Отлично — OCF покрывает обязательства" if cash_coverage > 1.5
                else "Нормально" if cash_coverage > 0.8
                else "Риск — недостаточный денежный поток"
            ),
        }

    # Free Cash Flow (если есть CAPEX или оцениваем)
    capex = get(latest, "capital_expenditures", 0) or get(latest, "capex", 0)
    if op_cash_flow:
        # Если нет CAPEX, оцениваем как % от выручки (средне 5-10%)
        if not capex and revenue > 0:
            capex = revenue * 0.06  # консервативная оценка

        fcf = op_cash_flow - capex if capex else op_cash_flow
        cash_flow["free_cash_flow"] = {
            "value": round(fcf, 0),
            "as_pct_of_revenue": round((fcf / revenue) * 100, 1) if revenue else 0,
            "verdict": (
                "Позитивный FCF — компания генерирует свободный кеш" if fcf > 0
                else "Отрицательный FCF — компания потребляет кеш"
            ),
        }

        if op_cash_flow > 0:
            fcf_ratio = fcf / op_cash_flow
            cash_flow["fcf_to_ocf_ratio"] = {
                "value": round(fcf_ratio * 100, 1),
                "interpretation": (
                    f"{round(fcf_ratio * 100, 0)}% OCF остается после капзатрат"
                ),
            }

    if cash_flow:
        metrics["cash_flow_analysis"] = cash_flow

    # ── TREND ANALYSIS: SLOPE / ACCELERATION / CONSISTENCY ─
    # Все три метода считаются из временного ряда без внешних библиотек.

    def linear_slope(values: list) -> float:
        """
        Наклон линии тренда методом наименьших квадратов (OLS).
        Нормализован: slope / mean → относительный прирост за период.
        Положительный = рост, отрицательный = падение.
        """
        n = len(values)
        if n < 2:
            return 0.0
        xs = list(range(n))
        mx = sum(xs) / n
        my = sum(values) / n
        num   = sum((x - mx) * (y - my) for x, y in zip(xs, values))
        denom = sum((x - mx) ** 2 for x in xs)
        if denom == 0 or my == 0:
            return 0.0
        return round(num / denom / abs(my) * 100, 2)  # % за период

    def acceleration(values: list) -> float:
        """
        Ускорение роста: сравниваем среднегодовой рост первой
        и второй половины периода.
        > 0 — рост ускоряется, < 0 — замедляется.
        """
        n = len(values)
        if n < 4:
            return 0.0
        mid = n // 2
        first_half  = values[:mid]
        second_half = values[mid:]

        def avg_growth(seq):
            rates = []
            for i in range(1, len(seq)):
                if seq[i-1] and seq[i-1] != 0:
                    rates.append((seq[i] - seq[i-1]) / abs(seq[i-1]) * 100)
            return sum(rates) / len(rates) if rates else 0

        return round(avg_growth(second_half) - avg_growth(first_half), 2)

    def consistency(values: list) -> float:
        """
        Стабильность роста: 100 - коэффициент вариации темпов роста.
        100 = идеально стабильный рост, 0 = хаотичный.
        """
        n = len(values)
        if n < 3:
            return 50.0
        rates = []
        for i in range(1, n):
            if values[i-1] and values[i-1] != 0:
                rates.append((values[i] - values[i-1]) / abs(values[i-1]) * 100)
        if not rates:
            return 50.0
        mean = sum(rates) / len(rates)
        if mean == 0:
            return 50.0
        std  = (sum((r - mean) ** 2 for r in rates) / len(rates)) ** 0.5
        cv   = std / abs(mean) * 100  # коэффициент вариации
        return round(max(0, min(100, 100 - cv)), 1)

    def trend_label(slope: float, accel: float, consist: float) -> str:
        """Человекочитаемое описание тренда."""
        if slope > 10:
            direction = "Сильный рост"
        elif slope > 3:
            direction = "Умеренный рост"
        elif slope > -3:
            direction = "Стагнация"
        elif slope > -10:
            direction = "Умеренное падение"
        else:
            direction = "Сильное падение"

        if accel > 5:
            momentum = "ускоряется"
        elif accel > -5:
            momentum = "стабильный темп"
        else:
            momentum = "замедляется"

        if consist >= 70:
            stability = "стабильно"
        elif consist >= 40:
            stability = "умеренно предсказуемо"
        else:
            stability = "нестабильно/скачки"

        return f"{direction} ({momentum}, {stability})"

    # Временные ряды для анализа
    rev_series    = [get(y, "revenue", 0) or 0 for y in annual_data]
    ni_series     = [get(y, "net_income", 0) or 0 for y in annual_data]
    margin_series = [
        round((get(y, "net_income", 0) or 0) / (get(y, "revenue", 1) or 1) * 100, 2)
        for y in annual_data
    ]
    equity_series = [get(y, "equity", 0) or 0 for y in annual_data]
    debt_series   = [get(y, "long_term_debt", 0) or 0 for y in annual_data]

    trend_revenue = {
        "slope":       linear_slope(rev_series),
        "acceleration": acceleration(rev_series),
        "consistency":  consistency(rev_series),
        "label":        trend_label(
                            linear_slope(rev_series),
                            acceleration(rev_series),
                            consistency(rev_series)
                        ),
        "values_by_year": {
            str(annual_data[i].get("year", i)): round(rev_series[i] / 1e6, 1)
            for i in range(len(annual_data)) if rev_series[i]
        },
    }
    trend_profit = {
        "slope":        linear_slope(ni_series),
        "acceleration": acceleration(ni_series),
        "consistency":  consistency(ni_series),
        "label":        trend_label(
                            linear_slope(ni_series),
                            acceleration(ni_series),
                            consistency(ni_series)
                        ),
        "profitable_years": sum(1 for v in ni_series if v > 0),
        "total_years":      len(ni_series),
    }
    trend_margin = {
        "slope":        linear_slope(margin_series),
        "acceleration": acceleration(margin_series),
        "consistency":  consistency(margin_series),
        "label":        trend_label(
                            linear_slope(margin_series),
                            acceleration(margin_series),
                            consistency(margin_series)
                        ),
        "current_pct":  round(margin_series[-1], 2) if margin_series else 0,
    }
    trend_debt = {
        "slope":        linear_slope(debt_series),
        "direction":    "снижается" if linear_slope(debt_series) < -2 else
                        "растёт"    if linear_slope(debt_series) > 2  else "стабильно",
        "acceleration": acceleration(debt_series),
    }

    # Сводный тренд-скоринг (влияет на итоговый скоринг)
    trend_score = 0
    if trend_revenue["slope"] > 10:  trend_score += 3
    elif trend_revenue["slope"] > 3: trend_score += 1
    if trend_revenue["acceleration"] > 3: trend_score += 2
    if trend_revenue["consistency"] > 70: trend_score += 2
    if trend_profit["slope"] > 5:    trend_score += 2
    if trend_margin["slope"] > 0:    trend_score += 1
    if trend_debt["slope"] < -2:     trend_score += 2  # долг снижается — хорошо
    trend_score = min(12, trend_score)

    metrics["trends"] = {
        "revenue":  trend_revenue,
        "profit":   trend_profit,
        "margin":   trend_margin,
        "debt":     trend_debt,
        "overall_score": trend_score,
        "overall_label": (
            "Позитивный" if trend_score >= 8
            else "Нейтральный" if trend_score >= 4
            else "Негативный"
        ),
    }

    # ── MOMENTUM-АНАЛИЗ (квартальные данные) ────────────
    # Три горизонта: 3 мес (последний квартал), 6 мес (2 квартала), 12 мес (4 квартала).
    # Считаем изменение выручки, прибыли и тренд ускорения между горизонтами.
    # Сигналы: BULLISH / NEUTRAL / BEARISH для каждого горизонта.

    def safe_get_q(d, key):
        v = d.get(key)
        return float(v) if v and str(v) not in ("None", "nan", "0") else None

    def pct_change(new_val, old_val):
        if old_val and old_val != 0 and new_val is not None:
            return round((new_val - old_val) / abs(old_val) * 100, 2)
        return None

    def momentum_signal(pct):
        """Сигнал по одному показателю."""
        if pct is None:    return "нет данных"
        if pct > 15:       return "STRONG_UP"
        if pct > 5:        return "UP"
        if pct > -5:       return "FLAT"
        if pct > -15:      return "DOWN"
        return "STRONG_DOWN"

    mom = {}

    if len(quarterly_data) >= 2:
        # Берём последние 8 кварталов (2 года максимум)
        q = quarterly_data[-8:]
        n = len(q)

        # Текущий квартал и предыдущие
        q_now  = q[-1]    if n >= 1 else {}
        q_1ago = q[-2]    if n >= 2 else {}
        q_3ago = q[-4]    if n >= 4 else {}
        q_5ago = q[-5]    if n >= 5 else {}  # ~12 мес назад (5 кварталов = 15 мес ≈ год)

        # ── 3-месячный (последний квартал vs предыдущий) ──
        rev_3m  = pct_change(safe_get_q(q_now, "revenue"), safe_get_q(q_1ago, "revenue"))
        ni_3m   = pct_change(safe_get_q(q_now, "net_income"), safe_get_q(q_1ago, "net_income"))
        mom["3m"] = {
            "revenue_pct":    rev_3m,
            "net_income_pct": ni_3m,
            "signal":         momentum_signal(rev_3m),
            "period":         f"{q_1ago.get('period','?')} → {q_now.get('period','?')}",
        }

        # ── 6-месячный (2 квартала назад vs 2 квартала до) ──
        if n >= 4:
            q_2ago = q[-3] if n >= 3 else {}
            q_4ago = q[-5] if n >= 5 else {}
            rev_6m  = pct_change(
                safe_get_q(q_now, "revenue"),
                safe_get_q(q_3ago, "revenue")
            )
            ni_6m   = pct_change(
                safe_get_q(q_now, "net_income"),
                safe_get_q(q_3ago, "net_income")
            )
            mom["6m"] = {
                "revenue_pct":    rev_6m,
                "net_income_pct": ni_6m,
                "signal":         momentum_signal(rev_6m),
                "period":         f"{q_3ago.get('period','?')} → {q_now.get('period','?')}",
            }

        # ── 12-месячный (год назад vs сейчас) ──
        if n >= 5:
            rev_12m = pct_change(
                safe_get_q(q_now, "revenue"),
                safe_get_q(q_5ago, "revenue")
            )
            ni_12m  = pct_change(
                safe_get_q(q_now, "net_income"),
                safe_get_q(q_5ago, "net_income")
            )
            mom["12m"] = {
                "revenue_pct":    rev_12m,
                "net_income_pct": ni_12m,
                "signal":         momentum_signal(rev_12m),
                "period":         f"{q_5ago.get('period','?')} → {q_now.get('period','?')}",
            }

        # ── Acceleration: ускоряется ли рост? ──
        # Сравниваем 3m-рост с 6m-ростом
        accel_signal = "нет данных"
        accel_desc   = ""
        if rev_3m is not None and "6m" in mom and mom["6m"]["revenue_pct"] is not None:
            half_6m = mom["6m"]["revenue_pct"] / 2  # нормируем к одному кварталу
            if rev_3m > half_6m + 3:
                accel_signal = "УСКОРЕНИЕ"
                accel_desc   = f"Последний квартал (+{rev_3m:.1f}%) быстрее среднего за полгода (+{half_6m:.1f}%)"
            elif rev_3m < half_6m - 3:
                accel_signal = "ЗАМЕДЛЕНИЕ"
                accel_desc   = f"Последний квартал (+{rev_3m:.1f}%) медленнее среднего за полгода (+{half_6m:.1f}%)"
            else:
                accel_signal = "СТАБИЛЬНО"
                accel_desc   = f"Темп роста стабилен: {rev_3m:.1f}% (кв) vs {half_6m:.1f}% (норм. полгода)"

        # ── Consecutive growth streaks ──
        # Сколько кварталов подряд растёт выручка?
        growth_streak = 0
        decline_streak = 0
        for i in range(len(q)-1, 0, -1):
            curr_rev = safe_get_q(q[i],   "revenue")
            prev_rev = safe_get_q(q[i-1], "revenue")
            if curr_rev and prev_rev:
                if curr_rev > prev_rev:
                    if decline_streak == 0:
                        growth_streak += 1
                    else:
                        break
                else:
                    if growth_streak == 0:
                        decline_streak += 1
                    else:
                        break
            else:
                break

        # ── Общий momentum-сигнал ──
        signals = [v.get("signal","") for v in mom.values()]
        bullish  = sum(1 for s in signals if "UP" in s)
        bearish  = sum(1 for s in signals if "DOWN" in s)
        if bullish >= 2:
            overall_momentum = "БЫЧИЙ — рост на нескольких горизонтах"
            mom_css = "bullish"
        elif bearish >= 2:
            overall_momentum = "МЕДВЕЖИЙ — падение на нескольких горизонтах"
            mom_css = "bearish"
        else:
            overall_momentum = "НЕЙТРАЛЬНЫЙ — смешанные сигналы"
            mom_css = "neutral"

        metrics["momentum"] = {
            "horizons":        mom,
            "acceleration":    accel_signal,
            "accel_desc":      accel_desc,
            "growth_streak":   growth_streak,
            "decline_streak":  decline_streak,
            "overall":         overall_momentum,
            "css":             mom_css,
            "quarters_used":   n,
            "summary": (
                f"Рост выручки за последний квартал: "
                f"{rev_3m:+.1f}%" if rev_3m is not None else "нет данных"
            ),
        }
    else:
        metrics["momentum"] = {
            "overall": "НЕЙТРАЛЬНЫЙ — недостаточно квартальных данных",
            "css": "neutral",
            "horizons": {},
        }

    # ── DCF — ОЦЕНКА СПРАВЕДЛИВОЙ СТОИМОСТИ ─────────────
    # Упрощённая двухэтапная модель DCF (без данных о кол-ве акций).
    # Считает справедливую стоимость всего бизнеса в UZS.
    #
    # Этап 1 (5 лет): FCF = EBIT × (1 - налог) — прокси свободного денежного потока.
    # Этап 2 (терминальная стоимость): TV = FCF₅ × (1 + g) / (WACC - g).
    # Discount rate откалиброван под UZ: WACC = 20% (инфляция ~13% + риск-премия).
    # Рост g выводится из исторического тренда выручки, но не более 8%.

    try:
        # Параметры (откалиброваны под frontier market Узбекистана)
        WACC      = 0.20   # ставка дисконтирования: инфляция UZS + премия за риск
        TAX_RATE  = 0.15   # ставка налога на прибыль в Узбекистане
        MAX_G     = 0.08   # максимальный вечный рост (conservative)
        MIN_G     = 0.02   # минимальный вечный рост
        N_YEARS   = 5      # горизонт прогноза

        # Базовый FCF = EBIT × (1 - tax)
        base_fcf = ebit * (1 - TAX_RATE) if ebit > 0 else net_income

        # Темп роста выручки — из тренда, ограничиваем
        raw_slope = trend_revenue.get("slope", 0) / 100  # slope уже в % за период
        # Переводим в годовой % (slope считался как % от среднего за весь период)
        n_years_data = len(annual_data)
        if n_years_data > 1 and rev_first and rev_first > 0:
            cagr = (rev_last / rev_first) ** (1 / (n_years_data - 1)) - 1
        else:
            cagr = 0.05  # дефолтный рост 5%

        # Консервативный прогноз: берём меньшее из CAGR и разумного максимума
        growth_rate = min(max(cagr * 0.7, MIN_G), 0.25)  # не более 25% в год
        terminal_g  = min(max(cagr * 0.3, MIN_G), MAX_G)  # вечный рост скромнее

        if base_fcf > 0:
            # Этап 1: дисконтируем FCF на 5 лет
            pv_fcf = 0.0
            fcf_t  = base_fcf
            fcf_by_year = {}
            for t_year in range(1, N_YEARS + 1):
                fcf_t *= (1 + growth_rate)
                pv_t   = fcf_t / (1 + WACC) ** t_year
                pv_fcf += pv_t
                fcf_by_year[f"год_{t_year}"] = round(fcf_t, 0)

            # Этап 2: терминальная стоимость
            fcf_terminal = fcf_t * (1 + terminal_g)
            tv = fcf_terminal / (WACC - terminal_g)
            pv_tv = tv / (1 + WACC) ** N_YEARS

            # Итоговая справедливая стоимость бизнеса
            intrinsic_value = pv_fcf + pv_tv

            # Сравниваем с балансовой стоимостью активов
            vs_assets = intrinsic_value / total_assets if total_assets else 0

            # Интерпретация
            if vs_assets > 1.5:
                dcf_verdict = "Потенциально сильно недооценён — DCF выше активов в 1.5x+"
                dcf_signal  = "bullish"
            elif vs_assets > 1.0:
                dcf_verdict = "Потенциально недооценён — DCF выше балансовой стоимости"
                dcf_signal  = "bullish"
            elif vs_assets > 0.7:
                dcf_verdict = "Оценён справедливо — DCF близок к балансовой стоимости"
                dcf_signal  = "neutral"
            else:
                dcf_verdict = "Потенциально переоценён или бизнес стагнирует"
                dcf_signal  = "bearish"

            metrics["dcf"] = {
                "intrinsic_value":   round(intrinsic_value, 0),
                "intrinsic_value_bn": round(intrinsic_value / 1e9, 2),
                "pv_fcf_5yr":        round(pv_fcf, 0),
                "terminal_value":    round(pv_tv, 0),
                "assumed_growth_pct": round(growth_rate * 100, 1),
                "terminal_growth_pct": round(terminal_g * 100, 1),
                "wacc_pct":          round(WACC * 100, 1),
                "vs_total_assets":   round(vs_assets, 2),
                "verdict":           dcf_verdict,
                "signal":            dcf_signal,
                "fcf_projection":    fcf_by_year,
                "note": (
                    f"Прогнозный рост {round(growth_rate*100,1)}%/год × 5 лет, "
                    f"затем вечный рост {round(terminal_g*100,1)}%/год. "
                    f"Ставка дисконтирования {round(WACC*100,0):.0f}% (UZ frontier market)."
                ),
            }
        else:
            metrics["dcf"] = {
                "intrinsic_value": 0,
                "verdict": "DCF не применим — компания убыточна (FCF отрицательный)",
                "signal": "bearish",
                "note": "DCF требует положительного операционного потока.",
            }
    except Exception as dcf_err:
        metrics["dcf"] = {
            "verdict": f"Ошибка расчёта DCF: {dcf_err}",
            "signal": "neutral",
        }

    # ── СВОДНЫЙ СКОРИНГ 0–100 ────────────────────────────
    score = 0

    # Piotroski (0–27 баллов)
    score += f_score * 3

    # Altman Z (0–20 баллов)
    if "altman_z_score" in metrics:
        z = metrics["altman_z_score"]["score"]
        if z > 2.99:   score += 20
        elif z > 1.81: score += 10

    # Buffett (0–20 баллов)
    score += buffett_passed * 4

    # Тренды (0–12 баллов) ← новый блок
    score += trend_score

    # Рост выручки за 5 лет (0–12 баллов)
    if rev_growth_5y > 100: score += 12
    elif rev_growth_5y > 50: score += 8
    elif rev_growth_5y > 20: score += 4

    # Momentum (0–8 баллов)
    if "momentum" in metrics:
        mom_css = metrics["momentum"].get("css", "neutral")
        streak  = metrics["momentum"].get("growth_streak", 0)
        if mom_css == "bullish":   score += 5
        elif mom_css == "neutral": score += 2
        if streak >= 3:  score += 3
        elif streak >= 2: score += 1

    # DCF сигнал (0–9 баллов)
    if "dcf" in metrics:
        dcf_sig = metrics["dcf"].get("signal", "neutral")
        if dcf_sig == "bullish":   score += 9
        elif dcf_sig == "neutral": score += 4

    # Маржа (0–9 баллов)
    if net_margin > 0.20: score += 9
    elif net_margin > 0.10: score += 6
    elif net_margin > 0.05: score += 3

    # Отраслевое сравнение (0–6 баллов)
    # добавляется после detect_industry, пока пропускаем (нет industry в scope)
    # industry_grade добавляется в run_analysis после вызова compute_metrics

    score = min(100, score)

    metrics["total_score"] = {
        "score": score,
        "grade": (
            "A — Отличная компания" if score >= 80
            else "B — Хорошая компания" if score >= 60
            else "C — Средняя компания" if score >= 40
            else "D — Слабая компания"
        ),
    }

    return metrics


def compute_technical_indicators(price_history: list) -> dict:
    """
    Вычисляет технические индикаторы из истории цен.
    Использует реальные рыночные данные из OpenInfo.

    Args:
        price_history: список dict с ключами date, open, high, low, close, trading_volume

    Returns:
        dict с RSI, MACD, уровнями Фибоначчи, объёмным анализом
    """
    if not price_history or len(price_history) < 5:
        return {"status": "insufficient_data", "message": "Нужно минимум 5 точек данных"}

    def safe_float(v):
        if v is None:
            return None
        try:
            val = float(v)
            return val if not math.isnan(val) else None
        except (TypeError, ValueError):
            return None

    # Очищаем данные
    points = []
    for p in price_history:
        close = safe_float(p.get("close"))
        if close is not None and close > 0:
            points.append({
                "date": p.get("date"),
                "open": safe_float(p.get("open")),
                "high": safe_float(p.get("high")),
                "low": safe_float(p.get("low")),
                "close": close,
                "volume": safe_float(p.get("trading_volume")) or 0,
            })

    if len(points) < 5:
        return {"status": "insufficient_data", "message": "Недостаточно валидных данных"}

    # Сортируем по дате
    points = sorted(points, key=lambda x: str(x.get("date") or ""))
    closes = [p["close"] for p in points]
    volumes = [p["volume"] for p in points]

    indicators = {"status": "ok", "data_points": len(points)}

    # ── RSI (Relative Strength Index) ────────────────────
    # RSI = 100 - (100 / (1 + RS))
    # RS = Average Gain / Average Loss за период (обычно 14 дней)
    period = min(14, len(closes) - 1)
    if period >= 5:
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        # Используем последние N периодов
        recent_gains = gains[-period:]
        recent_losses = losses[-period:]

        avg_gain = sum(recent_gains) / len(recent_gains) if recent_gains else 0
        avg_loss = sum(recent_losses) / len(recent_losses) if recent_losses else 0

        if avg_loss == 0:
            rsi = 100 if avg_gain > 0 else 50
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        if rsi >= 70:
            rsi_signal = "ПЕРЕКУПЛЕННОСТЬ — возможна коррекция вниз"
            rsi_css = "bearish"
        elif rsi <= 30:
            rsi_signal = "ПЕРЕПРОДАННОСТЬ — возможен отскок вверх"
            rsi_css = "bullish"
        elif rsi >= 60:
            rsi_signal = "Бычий тренд, но приближается к перекупленности"
            rsi_css = "neutral"
        elif rsi <= 40:
            rsi_signal = "Медвежий тренд, но приближается к перепроданности"
            rsi_css = "neutral"
        else:
            rsi_signal = "Нейтральная зона"
            rsi_css = "neutral"

        indicators["rsi"] = {
            "value": round(rsi, 1),
            "period": period,
            "signal": rsi_signal,
            "css": rsi_css,
        }

    # ── PRICE FIBONACCI LEVELS (на основе реальных цен) ──
    highs = [p["high"] for p in points if p["high"]]
    lows = [p["low"] for p in points if p["low"]]

    if highs and lows:
        swing_high = max(highs)
        swing_low = min(lows)
        price_range = swing_high - swing_low

        if price_range > 0:
            current_price = closes[-1]

            fib_levels = {
                "0.0": round(swing_high, 2),
                "23.6": round(swing_high - price_range * 0.236, 2),
                "38.2": round(swing_high - price_range * 0.382, 2),
                "50.0": round(swing_high - price_range * 0.5, 2),
                "61.8": round(swing_high - price_range * 0.618, 2),
                "78.6": round(swing_high - price_range * 0.786, 2),
                "100.0": round(swing_low, 2),
            }

            # Определяем текущую зону
            if current_price >= fib_levels["23.6"]:
                zone = "выше 23.6% — сильный бычий тренд"
                zone_css = "bullish"
            elif current_price >= fib_levels["38.2"]:
                zone = "23.6–38.2% — здоровая коррекция"
                zone_css = "neutral"
            elif current_price >= fib_levels["50.0"]:
                zone = "38.2–50% — умеренная коррекция"
                zone_css = "neutral"
            elif current_price >= fib_levels["61.8"]:
                zone = "50–61.8% — глубокая коррекция (золотое сечение)"
                zone_css = "bearish"
            else:
                zone = "ниже 61.8% — сильный медвежий тренд"
                zone_css = "bearish"

            # Ближайшие уровни
            support_levels = [
                (level, price) for level, price in fib_levels.items()
                if price < current_price
            ]
            resistance_levels = [
                (level, price) for level, price in fib_levels.items()
                if price > current_price
            ]

            nearest_support = max(support_levels, key=lambda x: x[1]) if support_levels else None
            nearest_resistance = min(resistance_levels, key=lambda x: x[1]) if resistance_levels else None

            indicators["fibonacci_price"] = {
                "swing_high": round(swing_high, 2),
                "swing_low": round(swing_low, 2),
                "current_price": round(current_price, 2),
                "levels": fib_levels,
                "current_zone": zone,
                "css": zone_css,
                "nearest_support": {
                    "level": nearest_support[0],
                    "price": nearest_support[1],
                } if nearest_support else None,
                "nearest_resistance": {
                    "level": nearest_resistance[0],
                    "price": nearest_resistance[1],
                } if nearest_resistance else None,
            }

    # ── PRICE MOMENTUM ───────────────────────────────────
    # Изменение цены за разные периоды
    if len(closes) >= 2:
        price_changes = {}

        # 1 день
        price_changes["1d"] = round((closes[-1] / closes[-2] - 1) * 100, 2)

        # 1 неделя (5 торговых дней)
        if len(closes) >= 6:
            price_changes["1w"] = round((closes[-1] / closes[-6] - 1) * 100, 2)

        # 1 месяц (20 торговых дней)
        if len(closes) >= 21:
            price_changes["1m"] = round((closes[-1] / closes[-21] - 1) * 100, 2)

        # За весь период
        price_changes["total"] = round((closes[-1] / closes[0] - 1) * 100, 2)

        # Определяем тренд
        total_change = price_changes["total"]
        if total_change > 15:
            trend = "Сильный рост"
            trend_css = "bullish"
        elif total_change > 5:
            trend = "Умеренный рост"
            trend_css = "bullish"
        elif total_change > -5:
            trend = "Боковик"
            trend_css = "neutral"
        elif total_change > -15:
            trend = "Умеренное падение"
            trend_css = "bearish"
        else:
            trend = "Сильное падение"
            trend_css = "bearish"

        indicators["price_momentum"] = {
            "changes": price_changes,
            "trend": trend,
            "css": trend_css,
            "start_price": round(closes[0], 2),
            "end_price": round(closes[-1], 2),
        }

    # ── VOLUME ANALYSIS ──────────────────────────────────
    valid_volumes = [v for v in volumes if v and v > 0]
    if len(valid_volumes) >= 5:
        avg_volume = sum(valid_volumes) / len(valid_volumes)
        recent_avg = sum(valid_volumes[-5:]) / min(5, len(valid_volumes))
        latest_volume = valid_volumes[-1] if valid_volumes else 0

        # Volume trend
        if recent_avg > avg_volume * 1.5:
            vol_signal = "Объёмы растут — повышенный интерес"
            vol_css = "bullish"
        elif recent_avg < avg_volume * 0.5:
            vol_signal = "Объёмы падают — снижение интереса"
            vol_css = "bearish"
        else:
            vol_signal = "Объёмы стабильны"
            vol_css = "neutral"

        # Volume-price divergence
        price_up = closes[-1] > closes[0] if len(closes) >= 2 else False
        vol_up = recent_avg > avg_volume

        if price_up and not vol_up:
            divergence = "Цена растёт на низких объёмах — слабый рост"
        elif not price_up and vol_up:
            divergence = "Цена падает на высоких объёмах — сильное давление продавцов"
        elif price_up and vol_up:
            divergence = "Цена и объёмы растут — здоровый бычий тренд"
        else:
            divergence = "Цена и объёмы падают — истощение продавцов"

        indicators["volume_analysis"] = {
            "avg_volume": round(avg_volume, 0),
            "recent_avg": round(recent_avg, 0),
            "latest": round(latest_volume, 0),
            "signal": vol_signal,
            "css": vol_css,
            "divergence": divergence,
        }

    # ── VOLATILITY ───────────────────────────────────────
    if len(closes) >= 10:
        # Standard deviation of daily returns
        returns = [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes))]
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        daily_volatility = variance ** 0.5
        annual_volatility = daily_volatility * (252 ** 0.5)  # annualized

        if annual_volatility > 0.5:
            vol_level = "Очень высокая волатильность"
            vol_css = "bearish"
        elif annual_volatility > 0.3:
            vol_level = "Высокая волатильность"
            vol_css = "neutral"
        elif annual_volatility > 0.15:
            vol_level = "Умеренная волатильность"
            vol_css = "neutral"
        else:
            vol_level = "Низкая волатильность"
            vol_css = "bullish"

        indicators["volatility"] = {
            "daily_pct": round(daily_volatility * 100, 2),
            "annual_pct": round(annual_volatility * 100, 1),
            "level": vol_level,
            "css": vol_css,
        }

    # ── SUMMARY SIGNAL ───────────────────────────────────
    bullish_signals = 0
    bearish_signals = 0
    neutral_signals = 0

    for key in ["rsi", "fibonacci_price", "price_momentum", "volume_analysis", "volatility"]:
        if key in indicators:
            css = indicators[key].get("css", "neutral")
            if css == "bullish":
                bullish_signals += 1
            elif css == "bearish":
                bearish_signals += 1
            else:
                neutral_signals += 1

    if bullish_signals >= 3:
        overall = "БЫЧИЙ — большинство индикаторов указывают на рост"
        overall_css = "bullish"
    elif bearish_signals >= 3:
        overall = "МЕДВЕЖИЙ — большинство индикаторов указывают на падение"
        overall_css = "bearish"
    else:
        overall = "НЕЙТРАЛЬНЫЙ — смешанные сигналы"
        overall_css = "neutral"

    indicators["summary"] = {
        "bullish_count": bullish_signals,
        "bearish_count": bearish_signals,
        "neutral_count": neutral_signals,
        "overall": overall,
        "css": overall_css,
    }

    return indicators


# ─────────────────────────────────────────────────────────
# ШАГ A — Haiku + web_search (улучшенный промпт)
# ─────────────────────────────────────────────────────────

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}

WEB_RESEARCH_PROMPT = """Ты — финансовый разведчик. Собери информацию о компании «{company}» (Узбекистан).

Найди:
1. Чем занимается, основные продукты/услуги, доля рынка
2. Последние новости за 6–12 месяцев — что важного произошло
3. НОВОСТИ-КАТАЛИЗАТОРЫ — события которые уже повлияли или могут повлиять на стоимость акции:
   - Смена руководства, M&A сделки, новые контракты
   - Санкции, регуляторные изменения в Узбекистане
   - Изменения цен на сырьё которое использует компания
   - Конкурентная ситуация — кто наступает на пятки
4. МАКРО-ФАКТОРЫ которые влияют на эту отрасль:
   - Курс USD/UZS и его влияние
   - Ставки ЦБ Узбекистана
   - Мировые цены на металл/нефть/газ (зависит от отрасли)
   - Реформы правительства Узбекистана в секторе
5. Цена акции сейчас и за последний год (если торгуется)
6. Планы компании: инвестиции, расширение, дивиденды

Ищи на русском и узбекском. Пиши конкретно — с датами, цифрами, источниками."""


def research_company_online(company_name: str) -> str:
    messages = [{"role": "user", "content": WEB_RESEARCH_PROMPT.format(company=company_name)}]
    print(f"🔍 Ищу «{company_name}» в интернете + новости-катализаторы (Haiku)...")

    for iteration in range(10):
        def _call(msgs=messages):
            return client.messages.create(
                model=MODEL_CHEAP,
                max_tokens=2500,
                temperature=0.1,
                tools=[WEB_SEARCH_TOOL],
                messages=msgs,
            )
        response = api_call_with_retry(_call)

        tool_uses  = [b for b in response.content if b.type == "tool_use"]
        text_parts = [b.text for b in response.content if b.type == "text"]

        if response.stop_reason == "end_turn" or not tool_uses:
            print(f"   ✅ Веб-исследование готово ({iteration+1} итераций)")
            return "\n".join(text_parts).strip()

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tu in tool_uses:
            print(f"   🌐 {tu.input.get('query', '...')}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": "Результаты поиска получены.",
            })
        messages.append({"role": "user", "content": tool_results})
        time.sleep(0.5)

    print("   ⚠️ Лимит итераций веб-поиска")
    return "Веб-данные не получены."


# ─────────────────────────────────────────────────────────
# ШАГ B — Haiku → профиль компании
# ─────────────────────────────────────────────────────────

PROFILE_PROMPT = """Составь профиль компании «{company}» (300–400 слов).

ВЕБ-ДАННЫЕ:
{web_research}

ФИНАНСЫ (UZS):
{financials_json}

Включи: деятельность, масштаб, динамика, маржинальность, долги, рентабельность.
Обязательно упомяни ключевые новости и внешние факторы которые влияют на компанию.
Пиши просто — как объясняешь другу который ничего не знает о финансах. С цифрами."""


def build_company_profile(company_name: str, annual_data: list,
                           quarterly_data: list, web_research: str,
                           liquidity_data: dict | None = None) -> str:
    slim = slim_for_prompt(annual_data, quarterly_data)
    fin_short = {
        "annual": [
            {k: v for k, v in r.items() if k in
             {"year","revenue","net_income","total_assets","equity","net_profit_margin","yoy_growth"}}
            for r in slim["annual"]
        ],
        "latest_q": slim["quarterly"][-1] if slim["quarterly"] else {},
        "liquidity": liquidity_data or {},
    }
    prompt = PROFILE_PROMPT.format(
        company=company_name,
        web_research=web_research[:2500],
        financials_json=json.dumps(fin_short, ensure_ascii=False),
    )
    print("📋 Генерирую профиль (Haiku)...")

    def _call():
        return client.messages.create(
            model=MODEL_CHEAP,
            max_tokens=1500,   # увеличено: профиль иногда обрезался
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
    msg = api_call_with_retry(_call)
    profile = msg.content[0].text.strip()
    if msg.stop_reason == "max_tokens":
        print("   ⚠️ Профиль обрезан — увеличь max_tokens профиля")
    print(f"   ✅ Профиль готов ({msg.usage.output_tokens} токенов, stop={msg.stop_reason})")
    return profile


def slim_metrics_for_prompt(metrics: dict) -> dict:
    if not metrics:
        return {}

    keep = {}

    score = metrics.get("total_score", {})
    if score:
        keep["total_score"] = {
            "score": score.get("score"),
            "grade": score.get("grade"),
            "summary": score.get("summary"),
        }

    piotroski = metrics.get("piotroski_f_score", {})
    if piotroski:
        keep["piotroski_f_score"] = {
            "score": piotroski.get("score"),
            "max": piotroski.get("max"),
            "verdict": piotroski.get("verdict"),
        }

    altman = metrics.get("altman_z_score", {})
    if altman:
        keep["altman_z_score"] = {
            "score": altman.get("score"),
            "verdict": altman.get("verdict"),
        }

    buffett = metrics.get("buffett_criteria", {})
    if buffett:
        keep["buffett_criteria"] = {
            "passed": buffett.get("passed"),
            "total": buffett.get("total"),
            "verdict": buffett.get("verdict"),
        }

    graham = metrics.get("graham_number", {})
    if graham:
        keep["graham_number"] = {
            "value": graham.get("graham_number"),
            "price": graham.get("current_price"),
            "upside_pct": graham.get("upside_pct"),
            "verdict": graham.get("verdict"),
        }

    dcf = metrics.get("dcf", {})
    if dcf:
        keep["dcf"] = {
            "intrinsic_value_bn": dcf.get("intrinsic_value_bn"),
            "signal": dcf.get("signal"),
            "verdict": dcf.get("verdict"),
        }

    trends = metrics.get("trends", {})
    if trends:
        keep["trends"] = {
            "overall_score": trends.get("overall_score"),
            "overall_label": trends.get("overall_label"),
            "revenue": trends.get("revenue"),
            "profit": trends.get("profit"),
            "margin": trends.get("margin"),
            "debt": trends.get("debt"),
        }

    industry = metrics.get("industry", {})
    if industry:
        keep["industry"] = {
            "sector_name": industry.get("sector_name"),
            "verdict": industry.get("verdict"),
            "good_count": industry.get("good_count"),
            "weak_count": industry.get("weak_count"),
            "capex_note": industry.get("capex_note"),
        }

    liquidity = metrics.get("market_liquidity", {})
    if liquidity:
        keep["market_liquidity"] = liquidity

    momentum = metrics.get("momentum", {})
    if momentum:
        keep["momentum"] = momentum

    # NEW: Efficiency metrics
    efficiency = metrics.get("efficiency", {})
    if efficiency:
        keep["efficiency"] = {
            "inventory_turnover": efficiency.get("inventory_turnover"),
            "receivable_days": efficiency.get("receivable_days"),
            "payable_days": efficiency.get("payable_days"),
            "cash_conversion_cycle": efficiency.get("cash_conversion_cycle"),
        }

    # NEW: DuPont Analysis
    dupont = metrics.get("dupont_analysis", {})
    if dupont:
        keep["dupont_analysis"] = {
            "roe_pct": dupont.get("roe_pct"),
            "components": dupont.get("components"),
            "drivers": dupont.get("drivers"),
            "interpretation": dupont.get("interpretation"),
        }

    # NEW: Working Capital
    working_cap = metrics.get("working_capital", {})
    if working_cap:
        keep["working_capital"] = {
            "amount": working_cap.get("amount"),
            "change_yoy": working_cap.get("change_yoy"),
            "current_ratio": working_cap.get("current_ratio"),
            "quick_ratio": working_cap.get("quick_ratio"),
            "cash_ratio": working_cap.get("cash_ratio"),
            "verdict": working_cap.get("verdict"),
        }

    # NEW: Technical Indicators
    technical = metrics.get("technical_indicators", {})
    if technical and technical.get("status") == "ok":
        keep["technical_indicators"] = {
            "rsi": technical.get("rsi"),
            "fibonacci_price": technical.get("fibonacci_price"),
            "price_momentum": technical.get("price_momentum"),
            "volume_analysis": technical.get("volume_analysis"),
            "volatility": technical.get("volatility"),
            "summary": technical.get("summary"),
        }

    # NEW: Horizontal Analysis (YoY changes)
    horizontal = metrics.get("horizontal_analysis", {})
    if horizontal:
        keep["horizontal_analysis"] = {
            "items": horizontal.get("items"),
            "summary": horizontal.get("summary"),
            "verdict": horizontal.get("verdict"),
        }

    # NEW: Vertical Analysis (structure %)
    vertical = metrics.get("vertical_analysis", {})
    if vertical:
        keep["vertical_analysis"] = {
            "balance_sheet": vertical.get("balance_sheet"),
            "income_statement": vertical.get("income_statement"),
        }

    # NEW: Profitability Ratios
    profitability = metrics.get("profitability_ratios", {})
    if profitability:
        keep["profitability_ratios"] = profitability

    # NEW: Solvency Ratios
    solvency = metrics.get("solvency_ratios", {})
    if solvency:
        keep["solvency_ratios"] = solvency

    # NEW: Cash Flow Analysis
    cash_flow = metrics.get("cash_flow_analysis", {})
    if cash_flow:
        keep["cash_flow_analysis"] = cash_flow

    return keep


# ─────────────────────────────────────────────────────────
# ШАГ C — Sonnet → полный анализ (обновлённый промпт)
# ─────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────
# КОНТЕКСТ РЫНКА УЗБЕКИСТАНА (используется в промпте)
# ─────────────────────────────────────────────────────────

# Реальные бенчмарки для Узбекистана (frontier market, данные 2022–2024)
UZ_BENCHMARKS = """
ВАЖНО — ТЫ АНАЛИЗИРУЕШЬ КОМПАНИЮ НА РЫНКЕ УЗБЕКИСТАНА (FRONTIER MARKET).
Не сравнивай с западными стандартами. Используй эти бенчмарки:

НОРМЫ UZ-РЫНКА (слабо / норма / отлично):
Чистая маржа: <3% / 3–12% / >12%
ROE: <5% / 5–15% / >15%
ROA: <2% / 2–8% / >8%
Долг/капитал: >2.0 / 0.5–2.0 / <0.5
Ликвидность: <1.0 / 1.0–2.5 / >2.5
Рост выручки: <5% / 5–25% / >25%
Piotroski: 0–3 / 4–6 / 7–9
Altman Z: <1.5 / 1.5–2.5 / >2.5

КОНТЕКСТ РЫНКА:
- Рынок акций Узбекистана — молодой (биржа с 1994, активен с 2020-х)
- Ликвидность низкая → премия за риск 3–5% к развитым рынкам
- Инфляция UZS исторически 10–15%/год → реальная доходность важнее номинальной
- Государство — часто мажоритарный акционер → защита от банкротства, но риск дивидендной политики
- Прозрачность отчётности ниже мировых стандартов → консервативные оценки
- Курс USD/UZS волатилен → экспортёры выигрывают при ослаблении сума

КАЛИБРОВКА ВЕРДИКТА:
Для ПОКУПАТЬ достаточно 3+ из 5: [маржа выше нормы UZ] [рост выручки > 10%] 
[Piotroski ≥ 5] [долг в норме] [положительный тренд 2+ лет]
Для ВОЗДЕРЖАТЬСЯ нужно 3+ красных флага с цифрами — НЕ просто «рынок нестабилен»

ОТРАСЛЕВОЙ КОНТЕКСТ (авто-определён):
{industry_context}
"""

ANALYSIS_PROMPT = """Ты — инвестиционный аналитик специализирующийся на рынках СНГ и Центральной Азии.
Анализируешь «{company}» для обычного человека — НЕ финансиста.

{uz_benchmarks}

ПРАВИЛА ЯЗЫКА:
— Пиши как умный друг, а не как учебник
— Никаких сложных терминов без объяснения в скобках
— Каждый вывод — конкретная цифра + что она значит на языке UZ-рынка
— Хороший пример: «Компания зарабатывает 8 сум с каждых 100 сум выручки — для Узбекистана это нормально»
— Плохой пример: «Чистая маржа 8% ниже глобального среднего» — НЕ ТАК, глобальный средний нерелевантен

ДАННЫЕ:
Валюта: {currency}

ПРОФИЛЬ:
{company_profile}

ВЕБ-ИССЛЕДОВАНИЕ (новости и катализаторы):
{web_brief}

ЭКСПЕРТНЫЕ МЕТРИКИ (посчитаны автоматически по данным компании):
{metrics_json}

МЕТОДОЛОГИЯ АНАЛИЗА (используй эти подходы):
1. ГОРИЗОНТАЛЬНЫЙ АНАЛИЗ — сравни показатели текущего года с прошлым (YoY изменения в %)
2. ВЕРТИКАЛЬНЫЙ АНАЛИЗ — оцени структуру: какой % активов = долг, какой % выручки = прибыль
3. КОЭФФИЦИЕНТНЫЙ АНАЛИЗ — используй рассчитанные метрики выше
4. АНАЛИЗ ДЕНЕЖНЫХ ПОТОКОВ — способность генерировать кеш (OCF/Sales, FCF)
5. ТРЕНД-АНАЛИЗ — направление и ускорение роста/падения за 3-5 лет

БИРЖЕВАЯ ЛИКВИДНОСТЬ АКЦИИ ЗА ПОСЛЕДНИЕ 30 ДНЕЙ:
{liquidity_json}
Учитывай ликвидность в вердикте: даже хорошая компания может быть неудобной для входа и выхода, если сделок мало.

ГОДОВЫЕ ДАННЫЕ ({annual_period}):
{annual_json}

КВАРТАЛЫ ({quarterly_period}):
{quarterly_json}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КРИТИЧЕСКИ ВАЖНО — ФОРМАТ ОТВЕТА:
1. Начни ответ СРАЗУ с [СКОРИНГ] — без вступлений и markdown
2. Каждая секция ОБЯЗАТЕЛЬНО должна быть в ответе
3. НЕ используй ## заголовки — только метки [СЕКЦИЯ]
4. НЕ пропускай секции — лучше написать "Данных нет" чем пропустить
5. Используй UZ-бенчмарки, не западные стандарты

ШАБЛОН (копируй метки ТОЧНО как написано):

[СКОРИНГ]
Оценка: XX/100
Класс: A/B/C/D
Расшифровка: 2–3 предложения простыми словами — что этот балл означает для инвестора на рынке Узбекистана.

[ДОСЬЕ]
3 предложения — суть бизнеса на языке простого человека.
Пример: «Компания делает X и продаёт Y. Грубо говоря это как [аналогия]. Зарабатывают на Z.»

[ЧТО_С_ДЕНЬГАМИ]
Простое объяснение финансового состояния без терминов (5–7 предложений).
Сравнивай с нормами Узбекистана, не глобальными. Используй аналогии с обычной жизнью.
Объясни: зарабатывает ли компания, растёт ли, есть ли долги, хватает ли денег на работу.

[СТРУКТУРА_ФИНАНСОВ]
Вертикальный анализ — структура баланса и доходов:
Структура активов: ... (какой % = деньги, какой % = запасы, какой % = дебиторка)
Структура капитала: ...% собственный капитал vs ...% заёмный — это значит ...
Структура доходов: валовая маржа ...%, операционная маржа ...%, чистая маржа ...%
Вывод о структуре: ЗДОРОВАЯ / РИСКОВАННАЯ / ЕСТЬ ВОПРОСЫ — 1 предложение почему

[РЕНТАБЕЛЬНОСТЬ]
Коэффициенты рентабельности простым языком:
ROE (доходность капитала): ...% — на каждые 100 сум капитала зарабатывают ... сум прибыли
ROA (доходность активов): ...% — насколько эффективно используют имущество
Чистая маржа: ...% — сколько из каждых 100 сум выручки остается прибылью
Оценка по меркам UZ: ОТЛИЧНО / ХОРОШО / НОРМАЛЬНО / СЛАБО — почему

[ЛИКВИДНОСТЬ_И_ДОЛГ]
Способность платить по счетам:
Текущая ликвидность: ... (хватает ли оборотных активов на краткосрочные долги)
Быстрая ликвидность: ... (хватает ли без учета запасов)
Долговая нагрузка: ...% активов = долг — это НИЗКО / СРЕДНЕ / ВЫСОКО для UZ
Покрытие процентов: ... — насколько легко обслуживать долги
Вывод: компания УСТОЙЧИВА / ЕСТЬ РИСКИ / КРИТИЧНЫЙ ДОЛГ

[ДЕНЕЖНЫЕ_ПОТОКИ]
Анализ движения денег:
Генерация кеша: компания генерирует ...% от выручки в виде денежного потока — это ... для UZ
Свободный денежный поток: ... млрд UZS — денег после капзатрат ... (ХВАТАЕТ / НЕ ХВАТАЕТ)
Покрытие обязательств: операционный поток покрывает текущие долги в ... раз
Вывод: у компании ЗДОРОВЫЙ / СЛАБЫЙ / ПРОБЛЕМНЫЙ денежный поток

[ДИНАМИКА_ПОКАЗАТЕЛЕЙ]
Горизонтальный анализ — изменения год к году:
Выручка: ... → ... (+...%) — РОСТ / ПАДЕНИЕ
Прибыль: ... → ... (+...%) — РОСТ / ПАДЕНИЕ
Активы: ... → ... (+...%) — компания РАСТЕТ / СЖИМАЕТСЯ
Капитал: ... → ... (+...%) — капитализация УКРЕПЛЯЕТСЯ / РАЗМЫВАЕТСЯ
Общая динамика: ПОЗИТИВНАЯ / НЕГАТИВНАЯ / СМЕШАННАЯ — объяснение

[ТРЕНД]
Анализ направления движения компании за последние 3–5 лет:
Выручка: РАСТЁТ / ПАДАЕТ / СТАГНИРУЕТ — темп роста и ускоряется или замедляется
Прибыль: РАСТЁТ / ПАДАЕТ / СТАГНИРУЕТ — стабильна ли или скачет
Долги: СНИЖАЮТСЯ / РАСТУТ / СТАБИЛЬНО — куда движется долговая нагрузка
Momentum (из квартальных данных): ... — рост за последние 3/6/12 месяцев с сигналом БЫЧИЙ/НЕЙТРАЛЬНЫЙ/МЕДВЕЖИЙ
Ускорение роста: УСКОРЕНИЕ / СТАБИЛЬНО / ЗАМЕДЛЕНИЕ — объясни что это значит для инвестора
Итог тренда: ПОЗИТИВНЫЙ / НЕЙТРАЛЬНЫЙ / НЕГАТИВНЫЙ — 1–2 предложения почему

[ФИБОНАЧЧИ]
Объясни уровни Фибоначчи простым языком:
Текущая зона: ...
Что это значит: ... (объясни как будто человек никогда не слышал об этом)
Ключевые уровни поддержки: ...
Ключевые уровни сопротивления: ...
Вывод для инвестора: ...

[ОЦЕНКА_ЦЕНЫ]
Дорого или дёшево сейчас покупать? (относительно норм UZ-рынка)
DCF-оценка: справедливая стоимость бизнеса = ... млрд UZS (объясни простыми словами что это значит для покупки акции)
Метод Грэма: ... (справедливая стоимость по формуле — выше или ниже DCF?)
Метод Баффетта: ... (X из 5 критериев выполнено — объясни какие именно)
Altman Z-Score: ... баллов — компания далека от банкротства или есть риски?
Piotroski F-Score: .../9 — компания сильная/средняя/слабая по меркам UZ
Итоговый вывод по цене: ДЁШЕВО / СПРАВЕДЛИВО / ДОРОГО — 1–2 предложения почему

[КАТАЛИЗАТОРЫ]
События которые могут ПОДНЯТЬ цену акции:
• Событие: ... | Когда: ... | Вероятный эффект: ...
• Событие: ... | Когда: ... | Вероятный эффект: ...

События которые могут ОПУСТИТЬ цену акции:
• Риск: ... | Вероятность: ВЫСОКАЯ/СРЕДНЯЯ/НИЗКАЯ | Возможный эффект: ...
• Риск: ... | Вероятность: ВЫСОКАЯ/СРЕДНЯЯ/НИЗКАЯ | Возможный эффект: ...

Макро-факторы (Узбекистан + мир):
• Фактор: ... | Как влияет на эту компанию: ...
• Фактор: ... | Как влияет на эту компанию: ...

[СИЛЬНЫЕ_СТОРОНЫ]
• Факт: ... | Цифра: ... | Значимость: ...
• Факт: ... | Цифра: ... | Значимость: ...
• Факт: ... | Цифра: ... | Значимость: ...

[СЛАБЫЕ_СТОРОНЫ]
• Факт: ... | Цифра: ... | Значимость: ...
• Факт: ... | Цифра: ... | Значимость: ...
• Факт: ... | Цифра: ... | Значимость: ...

[ПРОГНОЗ]
ВАЖНО: каждая строка начинается ТОЧНО с этих слов, затем двоеточие, затем значение, затем длинное тире —, затем объяснение одним предложением.
Рост прибыли: ВЫСОКАЯ — выручка растёт 3 года подряд, новые контракты подписаны
Долговая нагрузка: УЛУЧШЕНИЕ — компания гасит долги быстрее чем берёт новые
Ликвидность: СТАБИЛЬНО — достаточно денег чтобы платить по счетам без проблем

[ВЕРДИКТ]
ПРАВИЛО: используй 5-уровневую шкалу. ПОКУПАТЬ нужно смелее давать если показатели в норме для UZ-рынка.
ЗАПРЕЩЕНО ставить ВОЗДЕРЖАТЬСЯ без минимум 3 конкретных красных флагов с цифрами.

МЕТКА: выбери ОДИН из вариантов:
🟢 ПОКУПАТЬ — показатели хорошие по меркам UZ, тренд позитивный, риски умеренные
🟢 ДЕРЖАТЬ — если уже есть позиция, продолжать держать; новым — можно рассматривать
🟡 НАБЛЮДАТЬ — интересная компания но нужно подождать квартал-два для подтверждения
🟠 ОСТОРОЖНО — есть реальные риски, покупать только небольшую долю и с стоп-лоссом
🔴 ВОЗДЕРЖАТЬСЯ — серьёзные проблемы: убытки ИЛИ падение выручки 2+ лет ИЛИ критический долг

Обоснование: 3–4 предложения простым языком без терминов. Объясни решение через аналогию.

[СОВЕТЫ]
Доля портфеля: ...% (для 🟢 обычно 5–15%, для 🟡 3–8%, для 🟠 1–3%)
Горизонт: краткосрочно (до 1 года) / среднесрочно (1–3 года) / долгосрочно (3+ лет)
Точка входа: ... (при каком условии/цене покупать — если ПОКУПАТЬ/ДЕРЖАТЬ/НАБЛЮДАТЬ)
Следить за:
1. Показатель: ... | Почему важен для этой компании: ...
2. Показатель: ... | Почему важен для этой компании: ...
3. Показатель: ... | Почему важен для этой компании: ...

[ИТОГ]
Напиши 4–6 предложений простым языком для человека который никогда не инвестировал.
Используй аналогию из обычной жизни (магазин, машина, квартира).
Без цифр, без терминов — только суть: стоит ли вкладывать деньги и почему."""


def run_analysis(company_name: str, company_profile: str, web_research: str,
                 annual_data: list, quarterly_data: list,
                 liquidity_data: dict | None = None) -> tuple:
    slim = slim_for_prompt(annual_data, quarterly_data)

    annual_period = (
        f"{slim['annual'][0]['year']}–{slim['annual'][-1]['year']}"
        if slim["annual"] else "нет данных"
    )
    quarterly_period = (
        f"{slim['quarterly'][0]['period']}–{slim['quarterly'][-1]['period']}"
        if slim["quarterly"] else "квартальные данные недоступны"
    )

    # Вычисляем экспертные метрики (бесплатно, чистый Python)
    metrics = compute_metrics(annual_data, quarterly_data)
    if liquidity_data:
        metrics["market_liquidity"] = liquidity_data

    # Определяем отрасль и сравниваем с бенчмарками
    industry    = detect_industry(company_name, web_research, company_profile)
    ind_compare = compare_to_industry(metrics, industry)
    metrics["industry"] = ind_compare
    # Обновляем WACC в DCF под отраслевой если он уже посчитан
    if "dcf" in metrics and industry.get("wacc"):
        metrics["dcf"]["wacc_used_sector"] = round(industry["wacc"] * 100, 1)

    mom_str = metrics.get('momentum',{}).get('css','?')
    print(f"   📐 Метрики: Piotroski={metrics.get('piotroski_f_score',{}).get('score','?')}/9, "
          f"Altman={metrics.get('altman_z_score',{}).get('score','?')}, "
          f"Momentum={mom_str}, "
          f"Отрасль={ind_compare.get('sector_name','?')}, "
          f"Score={metrics.get('total_score',{}).get('score','?')}/100")

    web_brief = web_research[:1400] + ("..." if len(web_research) > 1400 else "")
    prompt_metrics = slim_metrics_for_prompt(metrics)

    # Строим отраслевой контекст для промпта
    ind = metrics.get("industry", {})
    industry_context_str = (
        f"Отрасль: {ind.get('sector_name', 'не определена')}\n"
        f"Результат vs бенчмарк: {ind.get('verdict','')}\n"
        f"Хороших показателей: {ind.get('good_count',0)}/5, "
        f"Слабых: {ind.get('weak_count',0)}/5\n"
        f"Примечание: {ind.get('capex_note','')}"
    ) if ind else "Отрасль не определена — используй общие нормы UZ"

    prompt = ANALYSIS_PROMPT.format(
        uz_benchmarks=UZ_BENCHMARKS.format(industry_context=industry_context_str),
        currency=slim["currency"],
        company=company_name,
        company_profile=company_profile,
        web_brief=web_brief,
        metrics_json=json.dumps(prompt_metrics, ensure_ascii=False, indent=1),
        liquidity_json=json.dumps(liquidity_data or {"status": "нет данных"}, ensure_ascii=False, indent=1),
        annual_period=annual_period,
        annual_json=json.dumps(slim["annual"], ensure_ascii=False),
        quarterly_period=quarterly_period,
        quarterly_json=json.dumps(slim["quarterly"], ensure_ascii=False),
    )

    approx_tokens = len(prompt) // 4
    print(f"📤 Анализ (Sonnet) — ~{approx_tokens} токенов входа...")

    def _call():
        return client.messages.create(
            model=MODEL_MAIN,
            max_tokens=8000,
            temperature=0.2,
            system=(
                "Ты строго следуешь формату ответа. "
                "КАЖДАЯ секция ОБЯЗАТЕЛЬНО начинается с метки в квадратных скобках: [СКОРИНГ], [ДОСЬЕ] и т.д. "
                "НЕ используй markdown заголовки (##). "
                "НЕ пропускай ни одну секцию. "
                "Если данных недостаточно — напиши 'Недостаточно данных' внутри секции, но секцию не пропускай."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
    msg = api_call_with_retry(_call)
    raw = msg.content[0].text.strip()

    # Проверяем не обрезан ли ответ
    if msg.stop_reason == "max_tokens":
        print("   ⚠️  ВНИМАНИЕ: ответ обрезан по max_tokens! Некоторые секции могут быть пустыми.")
        # Дописываем минимальный вердикт если его нет
        if "[ВЕРДИКТ]" not in raw:
            raw += (
                "\n\n[ВЕРДИКТ]\n"
                "МЕТКА: 🟡 НАБЛЮДАТЬ\n"
                "Обоснование: Анализ был прерван из-за ограничения токенов. "
                "Доступные данные не позволяют дать полный вердикт.\n\n"
                "[ИТОГ]\nАнализ был прерван из-за технического ограничения. "
                "Смотри профиль компании и метрики выше для оценки."
            )

    cost = (msg.usage.input_tokens / 1_000_000 * 3.0 +
            msg.usage.output_tokens / 1_000_000 * 15.0)
    print(f"   ✅ in={msg.usage.input_tokens} out={msg.usage.output_tokens} | stop={msg.stop_reason} | ~${cost:.4f}")

    return raw, annual_period, quarterly_period, cost, metrics


# ─────────────────────────────────────────────────────────
# ПАРСЕР
# ─────────────────────────────────────────────────────────

def parse_bullet(line: str) -> dict:
    result = {}
    line = line.lstrip("•–- ").strip()
    for part in line.split("|"):
        if ":" in part:
            key, _, val = part.partition(":")
            result[key.strip()] = val.strip()
    return result


# Карта нормализации меток — claude иногда пишет по-другому
_SECTION_ALIASES = {
    # Русские варианты
    "СКОРИНГ": ["СКОРИНГ", "SCORING", "ОЦЕНКА", "SCORE"],
    "ДОСЬЕ": ["ДОСЬЕ", "DOSSIER", "КРАТКОЕ_ДОСЬЕ", "КРАТКОЕ ДОСЬЕ"],
    "ЧТО_С_ДЕНЬГАМИ": ["ЧТО_С_ДЕНЬГАМИ", "ЧТО С ДЕНЬГАМИ", "ФИНАНСЫ", "ДЕНЬГИ", "ФИНАНСОВОЕ_СОСТОЯНИЕ"],
    "ТРЕНД": ["ТРЕНД", "TREND", "ТРЕНДЫ", "НАПРАВЛЕНИЕ"],
    "ЭФФЕКТИВНОСТЬ": ["ЭФФЕКТИВНОСТЬ", "EFFICIENCY", "ОБОРАЧИВАЕМОСТЬ"],
    "ТЕХНИЧЕСКИЙ_АНАЛИЗ": ["ТЕХНИЧЕСКИЙ_АНАЛИЗ", "ТЕХНИЧЕСКИЙ АНАЛИЗ", "TECHNICAL_ANALYSIS", "TECHNICAL ANALYSIS", "RSI", "ТЕХАНАЛИЗ"],
    "ФИБОНАЧЧИ": ["ФИБОНАЧЧИ", "FIBONACCI", "ФИБ", "FIB", "ФИБО"],
    "ОЦЕНКА_ЦЕНЫ": ["ОЦЕНКА_ЦЕНЫ", "ОЦЕНКА ЦЕНЫ", "ОЦЕНКА", "ЦЕНА", "СТОИМОСТЬ", "ДОРОГО_ИЛИ_ДЕШЕВО"],
    "КАТАЛИЗАТОРЫ": ["КАТАЛИЗАТОРЫ", "CATALYSTS", "ДВИЖУЩИЕ_СИЛЫ", "ФАКТОРЫ", "НОВОСТИ"],
    "СИЛЬНЫЕ_СТОРОНЫ": ["СИЛЬНЫЕ_СТОРОНЫ", "СИЛЬНЫЕ СТОРОНЫ", "ПЛЮСЫ", "STRENGTHS"],
    "СЛАБЫЕ_СТОРОНЫ": ["СЛАБЫЕ_СТОРОНЫ", "СЛАБЫЕ СТОРОНЫ", "МИНУСЫ", "WEAKNESSES"],
    "ВОЗМОЖНОСТИ": ["ВОЗМОЖНОСТИ", "OPPORTUNITIES"],
    "УГРОЗЫ": ["УГРОЗЫ", "THREATS", "РИСКИ"],
    "ПРОГНОЗ": ["ПРОГНОЗ", "FORECAST", "ПРОГНОЗЫ"],
    "ВЕРДИКТ": ["ВЕРДИКТ", "VERDICT", "РЕШЕНИЕ", "ИТОГОВЫЙ_ВЕРДИКТ"],
    "СОВЕТЫ": ["СОВЕТЫ", "РЕКОМЕНДАЦИИ", "ADVICE", "РЕКОМЕНДАЦИЯ"],
    "ИТОГ": ["ИТОГ", "ИТОГО", "CONCLUSION", "ВЫВОД", "ЗАКЛЮЧЕНИЕ"],
    "РЫНОЧНЫЕ_ДАННЫЕ": ["РЫНОЧНЫЕ_ДАННЫЕ", "РЫНОЧНЫЕ ДАННЫЕ", "MARKET_DATA", "MARKET DATA"],
    "ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА": ["ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА", "ОГРАНИЧЕНИЯ ПУБЛИЧНОГО КОНТУРА", "ОГРАНИЧЕНИЯ", "LIMITATIONS"],
    "ЗЕЛЕНЫЕ_ФЛАГИ": ["ЗЕЛЕНЫЕ_ФЛАГИ", "ЗЕЛЁНЫЕ_ФЛАГИ", "GREEN_FLAGS"],
    "КРАСНЫЕ_ФЛАГИ": ["КРАСНЫЕ_ФЛАГИ", "RED_FLAGS"],
}

# Обратная карта: alias → canonical
_ALIAS_MAP = {}
for canonical, aliases in _SECTION_ALIASES.items():
    for alias in aliases:
        _ALIAS_MAP[alias.upper().replace(" ","_")] = canonical


def parse_response(text: str) -> dict:
    """
    Парсит ответ Claude в словарь секций.
    Устойчив к: mixed case, пробелам в метках, markdown заголовкам,
    альтернативным названиям секций.
    """
    sections = {}
    current_key = None
    current_lines = []

    for line in text.splitlines():
        stripped = line.strip()

        # Вариант 1: стандартная метка [СЕКЦИЯ] или [СЕКЦИЯ С ПРОБЕЛОМ]
        m = re.match(r"^\[([A-ZА-ЯЁa-zа-яё_\s]+)\]\s*$", stripped)
        if not m:
            # Вариант 2: метка с текстом после [СЕКЦИЯ] текст
            m = re.match(r"^\[([A-ZА-ЯЁa-zа-яё_\s]+)\]", stripped)

        if m:
            raw_key = m.group(1).strip().upper().replace(" ", "_")
            # Нормализуем через alias map
            canonical = _ALIAS_MAP.get(raw_key, raw_key)

            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = canonical
            # Если после метки есть текст — добавляем как первую строку
            rest = stripped[m.end():].strip()
            current_lines = [rest] if rest else []
            continue

        current_lines.append(line)

    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


# ─────────────────────────────────────────────────────────
# HTML ШАБЛОН
# ─────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Анализ финансовой отчётности — {company}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,300;0,8..60,400;0,8..60,600;1,8..60,300;1,8..60,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink: #1a1612;
    --ink-mid: #3d3530;
    --ink-light: #6b5e55;
    --rule: #c9b99a;
    --rule-light: #e8ddd0;
    --accent: #8b1a1a;
    --accent-soft: #c0392b;
    --gold: #9a7b3a;
    --bg: #faf7f2;
    --bg-warm: #f3ede3;
    --bg-table: #fdf9f4;
    --green: #1a5c2e;
    --red: #8b1a1a;
    --amber: #7a5200;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--ink); font-family: 'Source Serif 4', Georgia, serif; font-size: 17px; line-height: 1.8; }}

  .masthead {{ border-top: 3px solid var(--ink); border-bottom: 1px solid var(--rule); padding: 12px 0 8px; text-align: center; background: var(--bg); margin-bottom: 0; }}
  .masthead-journal {{ font-family: 'Playfair Display', serif; font-size: 11px; letter-spacing: 0.3em; text-transform: uppercase; color: var(--ink-light); }}
  .masthead-title {{ font-family: 'Playfair Display', serif; font-size: 28px; font-weight: 700; letter-spacing: 0.01em; color: var(--ink); margin: 6px 0 4px; }}
  .masthead-sub {{ font-size: 13px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--gold); }}
  .masthead-rule {{ display: flex; align-items: center; gap: 12px; margin: 10px auto 0; max-width: 400px; justify-content: center; }}
  .masthead-rule span {{ height: 1px; flex: 1; background: var(--rule); }}
  .masthead-rule em {{ font-size: 11px; color: var(--ink-light); letter-spacing: 0.2em; font-style: normal; }}

  .page {{ max-width: 900px; margin: 0 auto; padding: 0 40px 80px; }}
  .meta-bar {{ border-bottom: 2px solid var(--ink); padding: 14px 0; display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; margin-bottom: 40px; }}
  .meta-item {{ padding: 0 16px; border-right: 1px solid var(--rule); }}
  .meta-item:first-child {{ padding-left: 0; }}
  .meta-item:last-child {{ border-right: none; }}
  .meta-label {{ font-size: 9px; letter-spacing: 0.3em; text-transform: uppercase; color: var(--ink-light); margin-bottom: 2px; }}
  .meta-value {{ font-family: 'Playfair Display', serif; font-size: 13px; color: var(--ink); }}

  .abstract {{ border-left: 3px solid var(--accent); padding: 20px 24px; background: var(--bg-warm); margin-bottom: 44px; position: relative; }}
  .abstract::before {{ content: 'АННОТАЦИЯ'; font-size: 9px; letter-spacing: 0.35em; color: var(--accent); display: block; margin-bottom: 10px; }}
  .abstract p {{ font-size: 15px; line-height: 1.75; color: var(--ink-mid); font-style: italic; }}

  .section {{ margin-bottom: 52px; }}
  .section-number {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--gold); letter-spacing: 0.1em; display: block; margin-bottom: 4px; }}
  h2 {{ font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 700; color: var(--ink); border-bottom: 2px solid var(--ink); padding-bottom: 8px; margin-bottom: 22px; line-height: 1.3; }}
  h3 {{ font-family: 'Playfair Display', serif; font-size: 16px; font-weight: 600; font-style: italic; color: var(--accent); margin: 28px 0 12px; }}
  p {{ margin-bottom: 16px; text-align: justify; hyphens: auto; }}
  p:last-child {{ margin-bottom: 0; }}
  .dropcap::first-letter {{ font-family: 'Playfair Display', serif; font-size: 68px; font-weight: 700; float: left; line-height: 0.8; margin: 6px 8px -4px 0; color: var(--accent); }}
  .prose {{ font-size: 15px; line-height: 1.85; white-space: pre-wrap; }}

  .table-wrap {{ margin: 28px 0 32px; overflow-x: auto; }}
  .table-caption {{ font-size: 11px; letter-spacing: 0.15em; text-transform: uppercase; color: var(--ink-light); margin-bottom: 8px; padding-left: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; background: var(--bg-table); }}
  thead tr {{ background: var(--ink); color: #f5ede0; }}
  thead th {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; padding: 10px 12px; text-align: right; font-weight: 500; }}
  thead th:first-child {{ text-align: left; }}
  tbody tr {{ border-bottom: 1px solid var(--rule-light); }}
  tbody tr:hover {{ background: #f0e9de; }}
  tbody tr.subtotal {{ background: #ede4d6; font-weight: 600; }}
  tbody tr.total {{ background: var(--bg-warm); border-top: 2px solid var(--rule); border-bottom: 2px solid var(--rule); font-weight: 700; }}
  tbody tr.section-head {{ background: #f7f1e8; }}
  tbody td {{ padding: 8px 12px; color: var(--ink-mid); vertical-align: middle; }}
  tbody td:first-child {{ color: var(--ink); }}
  tbody td.num {{ text-align: right; font-family: 'JetBrains Mono', monospace; font-size: 13px; }}
  .pos {{ color: var(--green); font-weight: 600; }}
  .neg {{ color: var(--red); font-weight: 600; }}
  .warn {{ color: var(--amber); font-weight: 600; }}
  .indent {{ padding-left: 28px !important; font-size: 13.5px; color: var(--ink-light); }}

  .callout-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 24px 0 32px; }}
  .callout {{ border: 1px solid var(--rule); padding: 16px 20px; background: var(--bg-warm); }}
  .callout.good {{ border-left: 4px solid var(--green); }}
  .callout.bad {{ border-left: 4px solid var(--red); }}
  .callout.neutral {{ border-left: 4px solid var(--gold); }}
  .callout-label {{ font-size: 9px; letter-spacing: 0.3em; text-transform: uppercase; color: var(--ink-light); margin-bottom: 6px; }}
  .callout-value {{ font-family: 'Playfair Display', serif; font-size: 26px; font-weight: 700; color: var(--ink); }}
  .callout-desc {{ font-size: 12.5px; color: var(--ink-light); margin-top: 4px; line-height: 1.5; }}

  .kpi-row {{ display: flex; gap: 0; border: 1px solid var(--rule); margin: 24px 0 32px; }}
  .kpi-item {{ flex: 1; padding: 16px 18px; border-right: 1px solid var(--rule); text-align: center; }}
  .kpi-item:last-child {{ border-right: none; }}
  .kpi-label {{ font-size: 10px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--ink-light); margin-bottom: 6px; }}
  .kpi-val {{ font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 700; color: var(--accent); }}
  .kpi-sub {{ font-size: 11px; color: var(--ink-light); margin-top: 2px; }}

  .formula-box {{ border: 1px solid var(--rule); border-left: 3px solid var(--gold); background: #faf5ec; padding: 12px 18px; font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--ink-mid); margin: 12px 0 20px; }}

  .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 20px 0; }}
  .metric-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 16px; }}
  .metric-label {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.15em; color: var(--ink-light); margin-bottom: 8px; }}
  .metric-val {{ font-family: 'Playfair Display', serif; font-size: 24px; margin-bottom: 4px; }}
  .metric-sub {{ font-size: 12px; color: var(--ink-light); line-height: 1.4; }}
  .val-green {{ color: var(--green); }} .val-red {{ color: var(--red); }} .val-yellow {{ color: var(--amber); }}

  .swot-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 20px 0; }}
  @media (max-width: 600px) {{ .swot-grid {{ grid-template-columns: 1fr; }} }}
  .swot-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 18px; }}
  .swot-card h3 {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 0.15em; margin-bottom: 12px; border: none; padding: 0; }}
  .swot-card.strengths h3 {{ color: var(--green); }} .swot-card.weaknesses h3 {{ color: var(--red); }}
  .swot-item {{ margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--rule-light); }}
  .swot-item:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: none; }}
  .swot-fact {{ font-size: 14px; font-weight: 500; }} .swot-num {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--accent); }} .swot-sig {{ font-size: 12px; color: var(--ink-light); margin-top: 2px; }}

  .catalyst-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 20px 0; }}
  @media (max-width: 600px) {{ .catalyst-grid {{ grid-template-columns: 1fr; }} }}
  .catalyst-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 14px; }}
  .catalyst-card.up {{ border-left: 4px solid var(--green); }}
  .catalyst-card.down {{ border-left: 4px solid var(--red); }}
  .catalyst-card.macro {{ border-left: 4px solid var(--amber); }}
  .catalyst-label {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }}
  .catalyst-label.up {{ color: var(--green); }} .catalyst-label.down {{ color: var(--red); }} .catalyst-label.macro {{ color: var(--amber); }}
  .catalyst-item {{ font-size: 13px; color: var(--ink); margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid var(--rule-light); }}
  .catalyst-item:last-child {{ border-bottom: none; margin-bottom: 0; padding-bottom: 0; }}

  .forecast-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 20px 0; }}
  @media (max-width: 600px) {{ .forecast-grid {{ grid-template-columns: 1fr; }} }}
  .forecast-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 18px; text-align: center; }}
  .forecast-label {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.15em; color: var(--ink-light); margin-bottom: 8px; }}
  .forecast-val {{ font-family: 'Playfair Display', serif; font-size: 18px; margin-bottom: 6px; }}
  .forecast-note {{ font-size: 12px; color: var(--ink-light); line-height: 1.4; }}
  .trend-up {{ color: var(--green); }} .trend-down {{ color: var(--red); }} .trend-flat {{ color: var(--amber); }}

  .tips-card {{ background: var(--bg-warm); border: 1px solid var(--rule); padding: 22px; margin: 20px 0; }}
  .tips-row {{ display: flex; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; }}
  .tips-badge {{ background: rgba(154, 123, 58, 0.1); border: 1px solid rgba(154, 123, 58, 0.3); color: var(--gold); font-family: 'JetBrains Mono', monospace; font-size: 12px; padding: 5px 12px; }}
  .watch-item {{ display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--rule-light); }}
  .watch-item:last-child {{ border-bottom: none; }}
  .watch-num {{ width: 22px; height: 22px; background: var(--gold); color: var(--bg); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 500; flex-shrink: 0; margin-top: 2px; }}
  .watch-name {{ font-size: 14px; font-weight: 500; }} .watch-why {{ font-size: 12px; color: var(--ink-light); }}

  .trend-row {{ display: flex; flex-direction: column; gap: 8px; margin: 20px 0; }}
  .trend-item {{ display: flex; align-items: center; gap: 10px; background: var(--bg-warm); border: 1px solid var(--rule); padding: 10px 14px; }}
  .trend-name {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--ink-light); width: 90px; flex-shrink: 0; }}
  .trend-bar-wrap {{ flex: 1; height: 4px; background: var(--rule-light); overflow: hidden; }}
  .trend-bar {{ height: 4px; }}
  .trend-bar.pos {{ background: var(--green); }} .trend-bar.neg {{ background: var(--red); }} .trend-bar.neu {{ background: var(--amber); }}
  .trend-val {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--gold); width: 55px; text-align: right; flex-shrink: 0; }}
  .trend-lbl {{ font-size: 12px; color: var(--ink-light); margin-left: 4px; flex-shrink: 0; }}

  .verdict {{ background: var(--ink); color: #f5ede0; padding: 32px 36px; margin: 40px 0 0; }}
  .verdict-label {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.3em; color: var(--gold); margin-bottom: 14px; }}
  .verdict h3 {{ color: #f5ede0; font-family: 'Playfair Display', serif; font-size: 20px; margin: 0 0 16px; font-style: normal; border: none; padding: 0; }}
  .verdict p {{ color: #d4c5b0; font-size: 15px; margin-bottom: 12px; text-align: left; }}
  .verdict ul {{ list-style: none; padding: 0; margin-top: 8px; }}
  .verdict ul li {{ font-size: 14.5px; color: #d4c5b0; padding: 5px 0 5px 18px; position: relative; border-bottom: 1px solid #3d352a; }}
  .verdict ul li::before {{ content: '›'; position: absolute; left: 0; color: var(--gold); font-size: 18px; line-height: 1.4; }}

  .web-toggle {{ background: none; border: 1px solid var(--rule); color: var(--ink-light); font-family: 'JetBrains Mono', monospace; font-size: 11px; padding: 6px 14px; cursor: pointer; text-transform: uppercase; letter-spacing: 0.1em; margin: 10px 0; }}
  .web-toggle:hover {{ border-color: var(--gold); color: var(--gold); }}
  .web-text {{ font-size: 13px; color: var(--ink-light); background: var(--bg-warm); border: 1px solid var(--rule); border-left: 3px solid var(--gold); padding: 16px 20px; line-height: 1.75; white-space: pre-wrap; max-height: 240px; overflow-y: auto; display: none; margin-top: 10px; }}

  .footer {{ border-top: 2px solid var(--ink); padding: 20px 0 0; margin-top: 60px; display: grid; grid-template-columns: 1fr 1fr; gap: 24px; font-size: 12px; color: var(--ink-light); }}
  .footer strong {{ display: block; color: var(--ink); margin-bottom: 4px; font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; }}

  @media (max-width: 700px) {{
    .page {{ padding: 0 20px 60px; }}
    .meta-bar {{ grid-template-columns: 1fr 1fr; }}
    .callout-grid {{ grid-template-columns: 1fr; }}
    .kpi-row {{ flex-wrap: wrap; }}
    .footer {{ grid-template-columns: 1fr; }}
    .masthead-title {{ font-size: 20px; }}
  }}

  @media print {{
    body {{ font-size: 12pt; }}
    .page {{ max-width: 100%; padding: 0; }}
    h2 {{ page-break-after: avoid; }}
    .section {{ page-break-inside: avoid; }}
    table {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>

<div class="masthead">
  <div class="masthead-journal">Финансовый анализ / Financial Analysis Report</div>
  <div class="masthead-title">{company}</div>
  <div class="masthead-sub">Анализ финансовой отчётности — {annual_period}</div>
  <div class="masthead-rule"><span></span><em>{analyzed_at}</em><span></span></div>
</div>

<div class="page">

  <div class="meta-bar">
    <div class="meta-item">
      <div class="meta-label">Эмитент</div>
      <div class="meta-value">{company}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Период</div>
      <div class="meta-value">{annual_period}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Кварталы</div>
      <div class="meta-value">{quarterly_period}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Скоринг</div>
      <div class="meta-value">{score}/100 · {score_grade}</div>
    </div>
  </div>

  <div class="abstract">
    <p>{company_profile}</p>
  </div>

  <!-- РАЗДЕЛ 1: ПРОФИЛЬ И МЕТОДОЛОГИЯ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 1</span>
    <h2>Профиль компании и методология анализа</h2>
    <p class="dropcap">{score_desc}</p>
    <p>Настоящий анализ строится на трёх классических методах финансового анализа: <strong>горизонтальный анализ</strong> (оценка динамики абсолютных и относительных изменений), <strong>вертикальный анализ</strong> (структурный анализ — удельный вес каждой статьи) и <strong>коэффициентный анализ</strong> (расчёт показателей по группам: ликвидность, рентабельность, качество активов, достаточность капитала, эффективность).</p>
  </div>

  <!-- РАЗДЕЛ 2: ФИНАНСОВЫЙ АНАЛИЗ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 2</span>
    <h2>Анализ финансовых показателей</h2>
    <div class="prose">{what_money}</div>
    {trends_html}
    <div class="prose" style="margin-top:20px">{trend_text}</div>
  </div>

  <!-- РАЗДЕЛ 3: ЭКСПЕРТНЫЕ МЕТРИКИ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 3</span>
    <h2>Экспертные метрики и индикаторы</h2>
    <p>Ключевые метрики рассчитаны по методологиям Piotroski F-Score, Altman Z-Score, критериям Баффетта и другим признанным подходам.</p>
    <div class="metrics-grid">{metrics_html}</div>
    <h3>Ликвидность акции на рынке</h3>
    {liquidity_html}
  </div>

  <!-- РАЗДЕЛ 4: ТЕХНИЧЕСКИЙ АНАЛИЗ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 4</span>
    <h2>Технический анализ и уровни Фибоначчи</h2>
    <div class="prose">{fibonacci_text}</div>
    <h3>Оценка стоимости акции</h3>
    <div class="prose">{price_valuation}</div>
  </div>

  <!-- РАЗДЕЛ 5: КАТАЛИЗАТОРЫ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 5</span>
    <h2>Факторы, влияющие на стоимость</h2>
    {catalysts_html}
  </div>

  <!-- РАЗДЕЛ 6: СИЛЬНЫЕ И СЛАБЫЕ СТОРОНЫ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 6</span>
    <h2>Сильные и слабые стороны компании</h2>
    <div class="swot-grid">
      <div class="swot-card strengths"><h3>Сильные стороны</h3>{strengths_html}</div>
      <div class="swot-card weaknesses"><h3>Риски и слабости</h3>{weaknesses_html}</div>
    </div>
  </div>

  <!-- РАЗДЕЛ 7: ВЕРДИКТ И РЕКОМЕНДАЦИИ -->
  <div class="section">
    <span class="section-number">РАЗДЕЛ 7</span>
    <h2>Инвестиционный вердикт</h2>

    <h3>Прогноз</h3>
    <div class="forecast-grid">{forecast_html}</div>

    <h3>Рекомендации</h3>
    <div class="tips-card">
      <div class="tips-row">{tips_badges_html}</div>
      <div>{watch_html}</div>
    </div>

    <div class="verdict">
      <div class="verdict-label">{verdict_emoji} ЗАКЛЮЧЕНИЕ</div>
      <h3>{verdict_label}</h3>
      <p>{verdict_text}</p>
      <p>{itog}</p>
    </div>
  </div>

  <!-- ВЕБ-ИССЛЕДОВАНИЕ -->
  <div class="section">
    <span class="section-number">ПРИЛОЖЕНИЕ</span>
    <h2>Источники и веб-исследование</h2>
    <button class="web-toggle" onclick="var d=this.nextElementSibling;d.style.display=d.style.display==='block'?'none':'block'">Показать источники</button>
    <div class="web-text">{web_research}</div>
  </div>

  <div class="footer">
    <div>
      <strong>Методология</strong>
      Fibonacci · Piotroski · Graham · Altman
    </div>
    <div>
      <strong>Дисклеймер</strong>
      Данный отчёт не является инвестиционной рекомендацией
    </div>
  </div>

</div>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────
# HTML-ХЕЛПЕРЫ
# ─────────────────────────────────────────────────────────

def build_metrics_html(metrics: dict) -> str:
    html = ""

    # Piotroski
    if "piotroski_f_score" in metrics:
        p = metrics["piotroski_f_score"]
        score = p["score"]
        css = "val-green" if score >= 7 else "val-yellow" if score >= 4 else "val-red"
        html += f'''<div class="metric-card">
            <div class="metric-label">Piotroski F-Score</div>
            <div class="metric-val {css}">{score}/9</div>
            <div class="metric-sub">{p["verdict"]}</div>
        </div>'''

    # Altman Z
    if "altman_z_score" in metrics:
        a = metrics["altman_z_score"]
        z = a["score"]
        css = "val-green" if z > 2.99 else "val-yellow" if z > 1.81 else "val-red"
        html += f'''<div class="metric-card">
            <div class="metric-label">Altman Z-Score</div>
            <div class="metric-val {css}">{z}</div>
            <div class="metric-sub">{a["zone"]}</div>
        </div>'''

    # Buffett
    if "buffett_criteria" in metrics:
        b = metrics["buffett_criteria"]
        passed = b["passed"]
        total  = b["total"]
        css = "val-green" if passed >= 4 else "val-yellow" if passed >= 2 else "val-red"
        html += f'''<div class="metric-card">
            <div class="metric-label">Критерии Баффетта</div>
            <div class="metric-val {css}">{passed}/{total}</div>
            <div class="metric-sub">{b["verdict"]}</div>
        </div>'''

    # Momentum
    if "momentum" in metrics:
        mo = metrics["momentum"]
        css_map = {"bullish": "val-green", "bearish": "val-red", "neutral": "val-yellow"}
        css = css_map.get(mo.get("css","neutral"), "val-yellow")
        streak = mo.get("growth_streak", 0)
        streak_txt = f"{streak} кв. роста подряд" if streak > 0 else (
            f"{mo.get('decline_streak',0)} кв. падения" if mo.get('decline_streak',0) > 0 else "")
        h3m = mo.get("horizons",{}).get("3m",{})
        val_str = f"{h3m.get('revenue_pct',0):+.1f}%" if h3m.get("revenue_pct") is not None else "—"
        html += f'''<div class="metric-card">
            <div class="metric-label">Momentum (3м выручка)</div>
            <div class="metric-val {css}">{val_str}</div>
            <div class="metric-sub">{mo.get("overall","")[:60]}<br>{streak_txt}</div>
        </div>'''

    # Industry comparison
    if "industry" in metrics:
        ind = metrics["industry"]
        grade = ind.get("grade","inperform")
        css_map = {"outperform":"val-green","inperform":"val-yellow","underperform":"val-red"}
        css = css_map.get(grade, "val-yellow")
        label_map = {"outperform":"Выше рынка","inperform":"На уровне рынка","underperform":"Ниже рынка"}
        label = label_map.get(grade, grade)
        good = ind.get("good_count",0); ok = ind.get("ok_count",0); weak = ind.get("weak_count",0)
        sector = ind.get("sector_name","")[:25]
        html += f'''<div class="metric-card">
            <div class="metric-label">Отраслевой бенчмарк</div>
            <div class="metric-val {css}">{label}</div>
            <div class="metric-sub">{sector}<br>✅{good} / 🟡{ok} / ❌{weak} показателей</div>
        </div>'''

    # DCF
    if "dcf" in metrics:
        d = metrics["dcf"]
        val_bn = d.get("intrinsic_value_bn")
        sig = d.get("signal", "neutral")
        css = "val-green" if sig == "bullish" else "val-red" if sig == "bearish" else "val-yellow"
        val_str = f"{val_bn} млрд" if val_bn else "н/д"
        html += f'''<div class="metric-card">
            <div class="metric-label">DCF — справедливая стоимость</div>
            <div class="metric-val {css}">{val_str}</div>
            <div class="metric-sub">{d.get("verdict", "")[:80]}</div>
        </div>'''

    # Total score
    if "total_score" in metrics:
        t = metrics["total_score"]
        s = t["score"]
        css = "val-green" if s >= 70 else "val-yellow" if s >= 45 else "val-red"
        html += f'''<div class="metric-card">
            <div class="metric-label">Итоговый скоринг</div>
            <div class="metric-val {css}">{s}/100</div>
            <div class="metric-sub">{t["grade"]}</div>
        </div>'''

    return html or "<div class='metric-sub'>Метрики не рассчитаны</div>"


def build_liquidity_html(metrics: dict) -> str:
    liquidity = (metrics or {}).get("market_liquidity")
    if not liquidity:
        return "<div class='prose-plain'>Нет данных по биржевой ликвидности за последние 30 дней.</div>"

    label = str(liquidity.get("liquidity_label", "")).lower()
    label_map = {
        "high": ("Высокая", "val-green"),
        "medium": ("Средняя", "val-yellow"),
        "low": ("Низкая", "val-red"),
    }
    label_text, label_css = label_map.get(label, ("Нет данных", "val-yellow"))

    trade_days = liquidity.get("trade_days", "—")
    trade_count = liquidity.get("trade_count", "—")
    avg_trade_value = liquidity.get("avg_trade_value", "—")
    total_volume = liquidity.get("total_volume", "—")
    active_days_share = liquidity.get("active_days_share")

    if isinstance(active_days_share, (int, float)):
        active_days_share_text = f"{active_days_share * 100:.0f}%"
    else:
        active_days_share_text = "—"

    if label == "high":
        comment = "Бумага торгуется регулярно. Вход и выход из позиции обычно проще, чем у большинства акций на рынке UZSE."
    elif label == "medium":
        comment = "Ликвидность рабочая, но не идеальная. Крупную позицию лучше набирать постепенно и не рассчитывать на мгновенный выход."
    else:
        comment = "Ликвидность слабая. Даже при хороших финансах акция может быть неудобной для покупки и особенно для продажи."

    def fmt_money(value):
        if isinstance(value, (int, float)):
            return f"{value:,.0f} UZS"
        return "—"

    cards = f"""
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-label">Режим ликвидности</div>
        <div class="metric-val {label_css}">{label_text}</div>
        <div class="metric-sub">Оценка по активности торгов за 30 дней</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Торговых дней</div>
        <div class="metric-val">{trade_days}</div>
        <div class="metric-sub">Из 30 календарных дней</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Сделок</div>
        <div class="metric-val">{trade_count}</div>
        <div class="metric-sub">Количество сделок за период</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Средняя сделка</div>
        <div class="metric-val">{fmt_money(avg_trade_value)}</div>
        <div class="metric-sub">Средний денежный объём одной сделки</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Оборот</div>
        <div class="metric-val">{fmt_money(total_volume)}</div>
        <div class="metric-sub">Суммарный объём торгов за месяц</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Активность</div>
        <div class="metric-val">{active_days_share_text}</div>
        <div class="metric-sub">Доля дней, когда бумага реально торговалась</div>
      </div>
    </div>
    <div class="prose">{comment}</div>
    """
    return cards


def build_trends_html(metrics: dict) -> str:
    """Строит визуальные карточки трендов из metrics["trends"]."""
    if "trends" not in metrics:
        return ""

    t = metrics["trends"]
    html = '<div class="trend-row">'

    def trend_card(name: str, slope: float, label: str, consistency: float = None, acceleration: float = None):
        # Нормализуем slope в ширину бара (0–100%)
        bar_pct = min(100, abs(slope) * 3)
        css = "pos" if slope > 2 else "neg" if slope < -2 else "neu"
        arrow = "↑" if slope > 2 else "↓" if slope < -2 else "→"
        slope_str = f"{arrow} {abs(slope):.1f}%"

        extras = ""
        if acceleration is not None:
            accel_icon = "⚡" if acceleration > 3 else "🐌" if acceleration < -3 else ""
            if accel_icon:
                extras += f' {accel_icon}'
        if consistency is not None:
            cons_str = f"стаб. {consistency:.0f}%"
            extras += f' · {cons_str}'

        return (
            f'<div class="trend-item">'
            f'<span class="trend-name">{name}</span>'
            f'<div class="trend-bar-wrap"><div class="trend-bar {css}" style="width:{bar_pct}%"></div></div>'
            f'<span class="trend-val">{slope_str}</span>'
            f'<span class="trend-lbl">{extras}</span>'
            f'</div>'
        )

    # Выручка
    rv = t.get("revenue", {})
    if rv:
        html += trend_card(
            "Выручка", rv.get("slope", 0), rv.get("label", ""),
            rv.get("consistency"), rv.get("acceleration")
        )

    # Прибыль
    pr = t.get("profit", {})
    if pr:
        html += trend_card(
            "Прибыль", pr.get("slope", 0), pr.get("label", ""),
            pr.get("consistency"), pr.get("acceleration")
        )

    # Маржа
    mg = t.get("margin", {})
    if mg:
        html += trend_card(
            "Маржа", mg.get("slope", 0), mg.get("label", ""),
            mg.get("consistency")
        )

    # Долг (инвертируем — снижение долга это хорошо)
    db = t.get("debt", {})
    if db:
        slope = db.get("slope", 0)
        html += trend_card("Долг", slope, db.get("direction", ""))

    # Общий итог
    overall = t.get("overall_label", "")
    overall_score = t.get("overall_score", 0)
    css_overall = "pos" if overall == "Позитивный" else "neg" if overall == "Негативный" else "neu"
    html += (
        f'<div class="trend-item" style="margin-top:4px;border-color:var(--accent)">'
        f'<span class="trend-name" style="color:var(--accent)">Итог тренда</span>'
        f'<div class="trend-bar-wrap"><div class="trend-bar {css_overall}" style="width:{overall_score/12*100:.0f}%"></div></div>'
        f'<span class="trend-val">{overall_score}/12</span>'
        f'<span class="trend-lbl" style="color:var(--text)">{overall}</span>'
        f'</div>'
    )

    html += '</div>'
    return html


def swot_items_html(text: str) -> str:
    html = ""
    for line in text.splitlines():
        if not line.strip().startswith("•"):
            continue
        p = parse_bullet(line)
        fact = p.get("Факт", p.get("факт", ""))
        num  = p.get("Цифра", p.get("цифра", ""))
        sig  = p.get("Значимость", p.get("значимость", ""))
        html += f'<div class="swot-item"><div class="swot-fact">{fact}</div><div class="swot-num">{num}</div><div class="swot-sig">{sig}</div></div>'
    return html or "<div class='swot-sig'>Нет данных</div>"


def build_catalysts_html(text: str) -> str:
    up_items, down_items, macro_items = [], [], []
    current = None
    for line in text.splitlines():
        ls = line.strip()
        low = ls.lower()
        if "поднять" in low or "вверх" in low or "рост" in low and "событи" in low:
            current = "up"
        elif "опустить" in low or "вниз" in low or "риск" in low:
            current = "down"
        elif "макро" in low:
            current = "macro"
        elif ls.startswith("•") and current:
            item = ls.lstrip("• ").strip()
            if current == "up":   up_items.append(item)
            elif current == "down": down_items.append(item)
            elif current == "macro": macro_items.append(item)

    def make_card(items, cls, label):
        if not items:
            return ""
        items_html = "".join(f'<div class="catalyst-item">{i}</div>' for i in items[:3])
        return f'<div class="catalyst-card {cls}"><div class="catalyst-label {cls}">{label}</div>{items_html}</div>'

    cards = (
        make_card(up_items,    "up",    "📈 Могут поднять цену") +
        make_card(down_items,  "down",  "📉 Могут опустить цену") +
        make_card(macro_items, "macro", "🌍 Макро-факторы")
    )
    return f'<div class="catalyst-grid">{cards}</div>' if cards else '<div class="prose-plain">Катализаторы не определены</div>'


def build_forecast_html(text: str) -> str:
    """Парсит [ПРОГНОЗ]. Устойчив к любым тире: —, –, -, и переносам строк."""
    import re as _re

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    labels_map = {
        "рост прибыли":      ("Рост прибыли",     ["высокая", "высок"], ["низкая", "низк"]),
        "долговая нагрузка": ("Долговая нагрузка", ["улучшение"],        ["ухудшение"]),
        "ликвидность":       ("Ликвидность",       ["улучшение"],        ["ухудшение"]),
    }

    # Собираем строки по ключам (Claude иногда переносит пояснение)
    merged = {}
    current_key = None
    for line in lines:
        low = line.lower()
        matched = False
        for key in labels_map:
            if low.startswith(key):
                merged[key] = line
                current_key = key
                matched = True
                break
        if not matched and current_key:
            merged[current_key] = merged.get(current_key, "") + " " + line

    cards = []
    for key, (label, good_kw, bad_kw) in labels_map.items():
        if key not in merged:
            continue
        raw = merged[key]
        after_colon = raw.partition(":")[2].strip() if ":" in raw else raw
        # Разбиваем по любому тире
        parts = _re.split(r"\s*[—–\-]\s*", after_colon, maxsplit=1)
        val  = parts[0].strip() if parts else after_colon
        note = parts[1].strip() if len(parts) > 1 else ""
        css = "trend-flat"
        if any(k in val.lower() for k in good_kw):  css = "trend-up"
        elif any(k in val.lower() for k in bad_kw): css = "trend-down"
        cards.append(
            f'<div class="forecast-card">' +
            f'<div class="forecast-label">{label}</div>' +
            f'<div class="forecast-val {css}">{val}</div>' +
            f'<div class="forecast-note">{note}</div>' +
            f'</div>'
        )

    return "\n".join(cards) if cards else "<div class='forecast-card'><div class='forecast-note'>Нет данных</div></div>"


def build_tips_html(text: str):
    badges, watches, watch_n = "", "", 0
    for line in text.splitlines():
        ls = line.strip()
        if ls.lower().startswith("доля"):
            badges += f'<span class="tips-badge">📊 Доля: {ls.partition(":")[2].strip()}</span>'
        elif ls.lower().startswith("горизонт"):
            badges += f'<span class="tips-badge">⏱ {ls.partition(":")[2].strip()}</span>'
        elif re.match(r"^\d+\.", ls):
            watch_n += 1
            rest = re.sub(r"^\d+\.\s*", "", ls)
            p = parse_bullet("• " + rest.replace("Показатель:", "").strip())
            name = p.get("Показатель", p.get("показатель", rest.split("|")[0].strip()))
            why  = p.get("Почему", p.get("почему", ""))
            watches += f'<div class="watch-item"><div class="watch-num">{watch_n}</div><div><div class="watch-name">{name}</div><div class="watch-why">{why}</div></div></div>'
    return badges, watches


def verdict_parts(text: str):
    """Парсит вердикт. Поддерживает 5 уровней: ПОКУПАТЬ/ДЕРЖАТЬ/НАБЛЮДАТЬ/ОСТОРОЖНО/ВОЗДЕРЖАТЬСЯ."""
    label, body, emoji, css = "Анализ завершён", "", "📋", "yellow"
    for line in text.splitlines():
        ls = line.strip()
        if ls.lower().startswith("метка:"):
            raw = ls.partition(":")[2].strip()
            label = raw
            # 5-уровневая шкала
            if "ПОКУПАТЬ" in raw.upper():
                emoji, css = "🟢", "green"
            elif "ДЕРЖАТЬ" in raw.upper():
                emoji, css = "🟢", "green"
            elif "НАБЛЮДАТЬ" in raw.upper():
                emoji, css = "🟡", "yellow"
            elif "ОСТОРОЖНО" in raw.upper():
                emoji, css = "🟠", "orange"
            elif "ВОЗДЕРЖАТЬСЯ" in raw.upper():
                emoji, css = "🔴", "red"
            # Обратная совместимость со старыми вердиктами
            elif "🟢" in raw:
                emoji, css = "🟢", "green"
            elif "🔴" in raw:
                emoji, css = "🔴", "red"
            else:
                emoji, css = "🟡", "yellow"
        elif ls.lower().startswith("обоснование:"):
            body = ls.partition(":")[2].strip()
    return emoji, label, body, css


def build_html(company_name: str, company_profile: str, web_research: str,
               raw_analysis: str, annual_period: str, quarterly_period: str,
               cost: float, metrics: dict = None) -> str:

    sections = parse_response(raw_analysis)
    emoji, v_label, v_body, v_css = verdict_parts(sections.get("ВЕРДИКТ", ""))
    fc_html = build_forecast_html(sections.get("ПРОГНОЗ", ""))
    t_badges, t_watches = build_tips_html(sections.get("СОВЕТЫ", ""))
    safe_web = web_research.replace("<", "&lt;").replace(">", "&gt;")

    # Скоринг из секции
    score_text = sections.get("СКОРИНГ", "")
    score_num, score_grade_str, score_desc_str = "—", "—", ""
    for line in score_text.splitlines():
        ls = line.strip()
        if ls.lower().startswith("оценка:"):
            raw = ls.partition(":")[2].strip().split("/")[0].strip()
            score_num = raw
        elif ls.lower().startswith("класс:"):
            score_grade_str = ls.partition(":")[2].strip()
        elif ls.lower().startswith("расшифровка:"):
            score_desc_str = ls.partition(":")[2].strip()

    # Если в секции нет — берём из Python-метрик
    if score_num == "—" and metrics and "total_score" in metrics:
        score_num = str(metrics["total_score"]["score"])
        score_grade_str = metrics["total_score"]["grade"]

    return HTML_TEMPLATE.format(
        company=company_name,
        annual_period=annual_period,
        quarterly_period=quarterly_period,
        cost=cost,
        analyzed_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        score=score_num,
        score_grade=score_grade_str,
        score_desc=score_desc_str,
        company_profile=company_profile,
        web_research=safe_web,
        verdict_class=v_css,
        verdict_emoji=emoji,
        verdict_label=v_label,
        verdict_text=v_body,
        trends_html=build_trends_html(metrics or {}),
        what_money=sections.get("ЧТО_С_ДЕНЬГАМИ", ""),
        trend_text=sections.get("ТРЕНД", ""),
        fibonacci_text=sections.get("ФИБОНАЧЧИ", ""),
        price_valuation=sections.get("ОЦЕНКА_ЦЕНЫ", ""),
        catalysts_html=build_catalysts_html(sections.get("КАТАЛИЗАТОРЫ", "")),
        metrics_html=build_metrics_html(metrics or {}),
        liquidity_html=build_liquidity_html(metrics or {}),
        strengths_html=swot_items_html(sections.get("СИЛЬНЫЕ_СТОРОНЫ", "")),
        weaknesses_html=swot_items_html(sections.get("СЛАБЫЕ_СТОРОНЫ", "")),
        forecast_html=fc_html,
        tips_badges_html=t_badges,
        watch_html=t_watches,
        itog=(
            sections.get("ИТОГ")
            or sections.get("ВЕРДИКТ", "").split("Обоснование:")[-1].strip()
            or "Анализ завершён. Смотри вердикт выше."
        ),
    )


# ─────────────────────────────────────────────────────────
# ТОЧКА ВХОДА
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    total_cost = 0.0

    print("🌐 Собираю данные с сайта...")
    annual_df, quarter_df, liquidity_df, company_name = get_data()

    if annual_df is None or quarter_df is None:
        raise RuntimeError("❌ Не удалось получить данные.")

    print("🔧 Обрабатываю финансовые данные...")
    annual_data    = df_to_annual(annual_df)
    quarterly_data = df_to_quarterly(quarter_df)
    liquidity_data = (
        liquidity_df.iloc[0].to_dict()
        if liquidity_df is not None and not liquidity_df.empty
        else None
    )

    web_research = research_company_online(company_name)
    company_profile = build_company_profile(
        company_name, annual_data, quarterly_data, web_research, liquidity_data
    )

    raw_analysis, annual_period, quarterly_period, analysis_cost, metrics = run_analysis(
        company_name, company_profile, web_research, annual_data, quarterly_data, liquidity_data
    )
    total_cost += analysis_cost

    html_report = build_html(
        company_name, company_profile, web_research,
        raw_analysis, annual_period, quarterly_period,
        cost=total_cost, metrics=metrics,
    )

    output_path = Path(OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(html_report)

    print(f"\n✅ Отчёт сохранён: {output_path}")
    print(f"💰 Стоимость: ~${total_cost:.3f}")

"""Classify industries and compare supplied metrics to sector benchmarks."""
from __future__ import annotations




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


DEBT_BURDEN_LEVELS = {
    "good":     {"ru": "Низкая",     "en": "Low",      "uz": "Past"},
    "ok":       {"ru": "Умеренная",  "en": "Moderate", "uz": "O'rtacha"},
    "weak":     {"ru": "Высокая",    "en": "High",     "uz": "Yuqori"},
    "critical": {"ru": "Критическая","en": "Critical", "uz": "Kritik"},
}


def compare_to_industry(metrics: dict, industry: dict) -> dict:
    """
    Сравнивает ключевые метрики компании с отраслевыми бенчмарками.
    Возвращает dict с оценкой каждого показателя: weak / ok / good / critical (долг).
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

    def rate(val, bench, higher_is_better=True, four_level=False):
        """Оцениваем показатель относительно бенчмарков.

        four_level=True добавляет уровень "critical" для долговой нагрузки
        (ТЗ Блок 2: Низкая / Умеренная / Высокая / Критическая), используя
        отраслевой порог bench["weak"] как границу критической зоны.
        """
        if higher_is_better:
            if val >= bench["good"]: return "good"
            if val >= bench["ok"]:   return "ok"
            return "weak"
        else:  # для долга — чем меньше, тем лучше
            if val <= bench["good"]: return "good"
            if val <= bench["ok"]:   return "ok"
            if four_level and val > bench["weak"]: return "critical"
            return "weak"

    debt_rating = rate(de, industry["debt_equity"], higher_is_better=False, four_level=True)
    ratings = {
        "net_margin":     {"value": round(margin,1), "rating": rate(margin, industry["net_margin"])},
        "roe":            {"value": round(roe,1),    "rating": rate(roe,    industry["roe"])},
        "roa":            {"value": round(roa*100,1),"rating": rate(roa*100, industry["roa"])},
        "debt_equity":    {"value": round(de,2),     "rating": debt_rating, "burden": DEBT_BURDEN_LEVELS.get(debt_rating, DEBT_BURDEN_LEVELS["weak"])},
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

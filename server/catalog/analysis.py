from __future__ import annotations

from typing import Any


def _catalog_number(value: Any, language: str) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    separator = " " if language in {"ru", "uz"} else ","
    rendered = f"{value:,.1f}".rstrip("0").rstrip(".")
    return rendered.replace(",", separator)


def _catalog_change(current: Any, previous: Any) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)) or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def _catalog_nonfinance_sections(
    analysis_type: str,
    company_name: str,
    period: str,
    current: dict[str, Any],
    previous: dict[str, Any],
    language: str,
    compare_name: str | None = None,
    compare: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Localized, deterministic report lenses over one verified filing row."""
    values = current.get("all_values") or {}
    prev_values = previous.get("all_values") or {}
    metrics = current.get("metrics") or {}
    revenue_growth = _catalog_change(values.get("revenue"), prev_values.get("revenue"))
    income_growth = _catalog_change(values.get("net_income"), prev_values.get("net_income"))

    def n(key: str) -> str:
        return _catalog_number(values.get(key), language)

    def pct(value: Any) -> str:
        return f"{_catalog_number(value, language)}%" if isinstance(value, (int, float)) else "—"

    if language == "uz":
        labels = {
            "period": f"{company_name} uchun {period} davridagi tanlangan hisobot tahlil qilindi. Barcha summalar hisobotdagi birlikda — ming so‘mda ko‘rsatilgan.",
            "income": f"Tushum: {n('revenue')} ming so‘m. Sof foyda: {n('net_income')} ming so‘m.",
            "balance": f"Aktivlar: {n('total_assets')}, majburiyatlar: {n('total_liabilities')}, kapital: {n('total_equity')} ming so‘m.",
            "trend": f"Solishtirma davrga nisbatan tushum o‘zgarishi: {pct(revenue_growth)}; sof foyda o‘zgarishi: {pct(income_growth)}.",
            "eff": f"ROA: {pct(metrics.get('ROA'))}; ROE: {pct(metrics.get('ROE'))}; sof marja: {pct(metrics.get('net_margin'))}; qarz ulushi: {pct(metrics.get('debt_ratio'))}.",
            "price": "Faqat moliyaviy hisobot asosida adolatli aksiya narxi hisoblanmaydi; buning uchun tasdiqlangan bozor narxi va baholash modeli kerak.",
            "market": "Ushbu natija tanlangan moliyaviy hisobotga tegishli. Bozor kotirovkasi bu hisob-kitobga aralashtirilmagan.",
        }
    elif language == "en":
        labels = {
            "period": f"The selected {period} filing for {company_name} was analysed. All statement amounts are shown in the filing unit: thousand UZS.",
            "income": f"Revenue: {n('revenue')} thousand UZS. Net income: {n('net_income')} thousand UZS.",
            "balance": f"Assets: {n('total_assets')}, liabilities: {n('total_liabilities')}, equity: {n('total_equity')} thousand UZS.",
            "trend": f"Versus the comparable period, revenue changed by {pct(revenue_growth)} and net income by {pct(income_growth)}.",
            "eff": f"ROA: {pct(metrics.get('ROA'))}; ROE: {pct(metrics.get('ROE'))}; net margin: {pct(metrics.get('net_margin'))}; debt ratio: {pct(metrics.get('debt_ratio'))}.",
            "price": "A fair share price is not calculated from a financial statement alone; it requires a verified market price and a valuation model.",
            "market": "This result is limited to the selected financial filing. Market quotes were not mixed into the calculation.",
        }
    else:
        labels = {
            "period": f"Проанализирован выбранный отчёт {company_name} за {period}. Все суммы показаны в единице отчётности — тысячах сумов.",
            "income": f"Выручка: {n('revenue')} тыс. сум. Чистая прибыль: {n('net_income')} тыс. сум.",
            "balance": f"Активы: {n('total_assets')}, обязательства: {n('total_liabilities')}, капитал: {n('total_equity')} тыс. сум.",
            "trend": f"К сопоставимому периоду выручка изменилась на {pct(revenue_growth)}, чистая прибыль — на {pct(income_growth)}.",
            "eff": f"ROA: {pct(metrics.get('ROA'))}; ROE: {pct(metrics.get('ROE'))}; чистая маржа: {pct(metrics.get('net_margin'))}; доля обязательств: {pct(metrics.get('debt_ratio'))}.",
            "price": "Справедливая цена акции не рассчитывается только по финансовому отчёту: для неё нужны подтверждённая рыночная цена и модель оценки.",
            "market": "Результат относится только к выбранному финансовому отчёту. Рыночные котировки в расчёт не подмешивались.",
        }

    # Never print a dash as though it were a reported value.  Build the factual
    # sentences again from fields that actually exist in this filing; a sparse
    # report therefore stays concise instead of showing rows of nulls.
    amount_names = {
        "ru": {"revenue": "Выручка", "net_income": "Чистая прибыль",
               "total_assets": "Активы", "total_liabilities": "Обязательства",
               "total_equity": "Капитал"},
        "uz": {"revenue": "Tushum", "net_income": "Sof foyda",
               "total_assets": "Aktivlar", "total_liabilities": "Majburiyatlar",
               "total_equity": "Kapital"},
        "en": {"revenue": "Revenue", "net_income": "Net income",
               "total_assets": "Assets", "total_liabilities": "Liabilities",
               "total_equity": "Equity"},
    }[language]
    ratio_names = {
        "ru": {"ROA": "ROA", "ROE": "ROE", "net_margin": "Чистая маржа",
               "debt_ratio": "Доля обязательств"},
        "uz": {"ROA": "ROA", "ROE": "ROE", "net_margin": "Sof marja",
               "debt_ratio": "Majburiyatlar ulushi"},
        "en": {"ROA": "ROA", "ROE": "ROE", "net_margin": "Net margin",
               "debt_ratio": "Debt ratio"},
    }[language]
    income_parts = [
        f"{amount_names[key]}: {_catalog_number(values.get(key), language)}"
        for key in ("revenue", "net_income") if isinstance(values.get(key), (int, float))
    ]
    balance_parts = [
        f"{amount_names[key]}: {_catalog_number(values.get(key), language)}"
        for key in ("total_assets", "total_liabilities", "total_equity")
        if isinstance(values.get(key), (int, float))
    ]
    ratio_parts = [
        f"{ratio_names[key]}: {pct(metrics.get(key))}"
        for key in ("ROA", "ROE", "net_margin", "debt_ratio")
        if isinstance(metrics.get(key), (int, float))
    ]
    trend_parts = []
    if isinstance(revenue_growth, (int, float)):
        trend_parts.append(("tushum" if language == "uz" else "revenue" if language == "en" else "выручка")
                           + f": {pct(revenue_growth)}")
    if isinstance(income_growth, (int, float)):
        trend_parts.append(("sof foyda" if language == "uz" else "net income" if language == "en" else "чистая прибыль")
                           + f": {pct(income_growth)}")
    unit = "ming so‘m" if language == "uz" else "thousand UZS" if language == "en" else "тыс. сум"
    unavailable = ("Taqqoslanadigan ma’lumot yo‘q." if language == "uz" else
                   "No comparable data is available." if language == "en" else
                   "Сопоставимые данные отсутствуют.")
    labels["income"] = ("; ".join(income_parts) + (f" {unit}." if income_parts else ""))
    labels["balance"] = ("; ".join(balance_parts) + (f" {unit}." if balance_parts else ""))
    labels["trend"] = "; ".join(trend_parts) + "." if trend_parts else unavailable
    labels["eff"] = "; ".join(ratio_parts) + "." if ratio_parts else unavailable

    if analysis_type == "financial":
        return {
            "ДОСЬЕ": labels["period"],
            "ЧТО_С_ДЕНЬГАМИ": f"{labels['income']} {labels['balance']}",
            "ТРЕНД": labels["trend"],
            "ЭФФЕКТИВНОСТЬ": labels["eff"],
            "ОЦЕНКА_ЦЕНЫ": labels["price"],
            "РЫНОЧНЫЕ_ДАННЫЕ": labels["market"],
        }

    available_checks: list[bool] = []
    net_income = values.get("net_income")
    debt_ratio = metrics.get("debt_ratio")
    roe = metrics.get("ROE")
    margin = metrics.get("net_margin")
    for value, check in (
        (net_income, lambda v: v > 0),
        (revenue_growth, lambda v: v > 0),
        (income_growth, lambda v: v > 0),
        (debt_ratio, lambda v: v < 70),
        (roe, lambda v: v > 0),
        (margin, lambda v: v > 0),
    ):
        if isinstance(value, (int, float)):
            available_checks.append(bool(check(value)))
    # A score based on one or two available cells looks precise but is not
    # representative.  Require four independent checks; sparse filings keep a
    # clear "insufficient" state instead of receiving an artificial 100/100.
    score = (round(sum(available_checks) / len(available_checks) * 100)
             if len(available_checks) >= 4 else None)

    if analysis_type == "swot":
        if language == "uz":
            strengths = []
            weaknesses = []
            if isinstance(net_income, (int, float)):
                (strengths if net_income > 0 else weaknesses).append("kompaniya foyda bilan ishlamoqda" if net_income > 0 else "tanlangan davrda zarar qayd etilgan")
            if isinstance(revenue_growth, (int, float)):
                (strengths if revenue_growth > 0 else weaknesses).append(f"tushum dinamikasi {pct(revenue_growth)}")
            if isinstance(debt_ratio, (int, float)):
                (strengths if debt_ratio < 70 else weaknesses).append(f"majburiyatlarning aktivlardagi ulushi {pct(debt_ratio)}")
            return {
                "СИЛЬНЫЕ_СТОРОНЫ": "; ".join(strengths) or "Tasdiqlangan ma’lumotlarda aniq ijobiy signal yetarli emas.",
                "СЛАБЫЕ_СТОРОНЫ": "; ".join(weaknesses) or "Tanlangan mezonlarda aniq salbiy signal topilmadi.",
                "КАТАЛИЗАТОРЫ": "Keyingi taqqoslanadigan hisobotda tushum, foyda va balans ko‘rsatkichlarining yaxshilanishi asosiy kuzatiladigan katalizator bo‘ladi.",
            }
        if language == "en":
            strengths = []
            weaknesses = []
            if isinstance(net_income, (int, float)):
                (strengths if net_income > 0 else weaknesses).append("the company is profitable" if net_income > 0 else "the selected period is loss-making")
            if isinstance(revenue_growth, (int, float)):
                (strengths if revenue_growth > 0 else weaknesses).append(f"revenue change is {pct(revenue_growth)}")
            if isinstance(debt_ratio, (int, float)):
                (strengths if debt_ratio < 70 else weaknesses).append(f"liabilities equal {pct(debt_ratio)} of assets")
            return {
                "СИЛЬНЫЕ_СТОРОНЫ": "; ".join(strengths) or "The verified data does not contain enough clear positive signals.",
                "СЛАБЫЕ_СТОРОНЫ": "; ".join(weaknesses) or "No clear negative signal was found in the selected checks.",
                "КАТАЛИЗАТОРЫ": "Improvement in revenue, profit and balance-sheet indicators in the next comparable filing is the principal catalyst to monitor.",
            }
        strengths = []
        weaknesses = []
        if isinstance(net_income, (int, float)):
            (strengths if net_income > 0 else weaknesses).append("компания прибыльна" if net_income > 0 else "в выбранном периоде получен убыток")
        if isinstance(revenue_growth, (int, float)):
            (strengths if revenue_growth > 0 else weaknesses).append(f"динамика выручки {pct(revenue_growth)}")
        if isinstance(debt_ratio, (int, float)):
            (strengths if debt_ratio < 70 else weaknesses).append(f"обязательства составляют {pct(debt_ratio)} активов")
        return {
            "СИЛЬНЫЕ_СТОРОНЫ": "; ".join(strengths) or "В подтверждённых данных недостаточно выраженных положительных сигналов.",
            "СЛАБЫЕ_СТОРОНЫ": "; ".join(weaknesses) or "По выбранным критериям явных отрицательных сигналов не найдено.",
            "КАТАЛИЗАТОРЫ": "Главный наблюдаемый катализатор — улучшение выручки, прибыли и балансовых показателей в следующем сопоставимом отчёте.",
        }

    if analysis_type == "recommendation":
        score_text = _catalog_number(score, language) if score is not None else None
        if language == "uz":
            verdict = "moliyaviy signallar ijobiy" if score is not None and score >= 60 else "moliyaviy signallar aralash"
            scoring = (f"Mavjud ko‘rsatkichlar bo‘yicha faktik ball: {score_text}/100."
                       if score_text else "Ishonchli ball uchun kamida to‘rtta mustaqil ko‘rsatkich kerak.")
            return {"СКОРИНГ": scoring,
                    "ОЦЕНКА_ЦЕНЫ": labels["price"], "ВЕРДИКТ": f"{period} uchun {verdict}.",
                    "ИТОГ": "Bu investitsiya tavsiyasi emas; yakun faqat tanlangan hisobotdagi mavjud ko‘rsatkichlarga asoslangan."}
        if language == "en":
            verdict = "financial signals are positive" if score is not None and score >= 60 else "financial signals are mixed"
            scoring = (f"Evidence score from available metrics: {score_text}/100."
                       if score_text else "At least four independent metrics are required for a reliable score.")
            return {"СКОРИНГ": scoring,
                    "ОЦЕНКА_ЦЕНЫ": labels["price"], "ВЕРДИКТ": f"For {period}, {verdict}.",
                    "ИТОГ": "This is not investment advice; the conclusion uses only available figures in the selected filing."}
        verdict = "финансовые сигналы положительные" if score is not None and score >= 60 else "финансовые сигналы смешанные"
        scoring = (f"Фактическая оценка по доступным показателям: {score_text}/100."
                   if score_text else "Для надёжной оценки нужны минимум четыре независимых показателя.")
        return {"СКОРИНГ": scoring,
                "ОЦЕНКА_ЦЕНЫ": labels["price"], "ВЕРДИКТ": f"За {period} {verdict}.",
                "ИТОГ": "Это не инвестиционная рекомендация; вывод основан только на доступных показателях выбранного отчёта."}

    if analysis_type == "multi_company" and compare is not None:
        other_values = compare.get("all_values") or {}
        other_metrics = compare.get("metrics") or {}
        revenue_diff = _catalog_change(values.get("revenue"), other_values.get("revenue"))
        income_diff = _catalog_change(values.get("net_income"), other_values.get("net_income"))
        diff_parts = []
        if isinstance(revenue_diff, (int, float)):
            diff_parts.append(("tushum farqi" if language == "uz" else
                               "revenue difference" if language == "en" else
                               "разница выручки") + f" {pct(revenue_diff)}")
        if isinstance(income_diff, (int, float)):
            diff_parts.append(("sof foyda farqi" if language == "uz" else
                               "net-income difference" if language == "en" else
                               "разница чистой прибыли") + f" {pct(income_diff)}")
        comparison_text = "; ".join(diff_parts) if diff_parts else unavailable
        roe_parts = []
        if isinstance(metrics.get("ROE"), (int, float)):
            roe_parts.append(f"{company_name} ROE {pct(metrics.get('ROE'))}")
        if isinstance(other_metrics.get("ROE"), (int, float)):
            roe_parts.append(f"{compare_name} ROE {pct(other_metrics.get('ROE'))}")
        efficiency_text = "; ".join(roe_parts) if roe_parts else unavailable
        if language == "uz":
            return {"СРАВНЕНИЕ": f"{company_name} va {compare_name}: {comparison_text}.",
                    "ЭФФЕКТИВНОСТЬ": f"{efficiency_text}. Taqqoslash bir xil {period} davri va bir xil hisobot standarti bo‘yicha bajarildi."}
        if language == "en":
            return {"СРАВНЕНИЕ": f"{company_name} versus {compare_name}: {comparison_text}.",
                    "ЭФФЕКТИВНОСТЬ": f"{efficiency_text}. Both use the same {period} period and reporting standard."}
        return {"СРАВНЕНИЕ": f"{company_name} против {compare_name}: {comparison_text}.",
                "ЭФФЕКТИВНОСТЬ": f"{efficiency_text}. Сравнение выполнено за один период {period} и по одному стандарту."}
    return {}


def _catalog_no_cached_data(language: str, form: str, period: str) -> str:
    if form == "Audition":
        return ({"ru": "Аудиторский отчёт не содержит стандартизированной финансовой таблицы для этого анализа.",
                 "uz": "Auditorlik hisobotida ushbu tahlil uchun standartlashtirilgan moliyaviy jadval yo‘q.",
                 "en": "An audit report has no standardized financial table for this analysis."})[language]
    return ({"ru": f"Подтверждённые финансовые данные за {period} ещё не загружены.",
             "uz": f"{period} uchun tasdiqlangan moliyaviy ma’lumotlar hali yuklanmagan.",
             "en": f"Verified financial data for {period} has not been loaded yet."})[language]

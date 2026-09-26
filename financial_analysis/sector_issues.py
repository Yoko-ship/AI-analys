"""Sector issues. Pure deterministic rules."""
from __future__ import annotations

import financial_analysis.sector_language as financial_analysis_sector_language


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
            title, solution_code, metrics, solution = financial_analysis_sector_language.tr(lang, *entry[:3]), entry[3], entry[4], financial_analysis_sector_language.tr(lang, *entry[5])
        else:
            title = financial_analysis_sector_language.label(key, lang) + " — " + financial_analysis_sector_language.tr(lang, "ухудшение", "yomonlashish", "deterioration")
            solution_code, metrics = "check_next_comparable_result", [key, "net_income", "total_equity"]
            solution = financial_analysis_sector_language.tr(lang, "Не считать рост других статей достаточным улучшением; проверить результат следующего сопоставимого периода.", "Boshqa satrlar o‘sishini yetarli yaxshilanish deb hisoblamang; keyingi taqqoslanadigan davrni tekshiring.", "Do not treat improvements elsewhere as sufficient; check the next comparable result.")
        evidence = [f for f in facts.values() if f["id"] in signal["evidence_fact_ids"]]
        cause = "verified" if signal["code"] == "profit_quality" and quality["driver"] != "unknown" else "unknown"
        impact = financial_analysis_sector_language.tr(lang, "Снижает качество результата или запас финансовой устойчивости.", "Natija sifati yoki moliyaviy barqarorlik zaxirasini kamaytiradi.", "Reduces earnings quality or financial resilience.")
        cause_label = financial_analysis_sector_language.tr(lang, "Подтверждён нереализованный эффект переоценки.", "Realizatsiya qilinmagan qayta baholash ta’siri tasdiqlangan.", "An unrealized revaluation effect is confirmed.") if quality["driver"] == "unrealized_revaluation" else financial_analysis_sector_language.tr(lang, "Подтверждено влияние курсовых разниц.", "Kurs farqlari ta’siri tasdiqlangan.", "The foreign-exchange contribution is confirmed.")
        issue = {"issue_code": signal["code"], "title": title, "evidence_fact_ids": signal["evidence_fact_ids"],
                 "actual_value": signal["value_current"], "comparison_value": signal["value_previous"], "period": period,
                 "cause_status": cause, "cause_text": cause_label if cause == "verified" else financial_analysis_sector_language.tr(lang, "Причина не установлена по публичным данным.", "Sabab ochiq ma’lumotlarda aniqlanmagan.", "The cause is not established by public data."),
                 "verified_cause_fact_ids": signal["evidence_fact_ids"] if cause == "verified" else [],
                 "impact": impact, "verdict": verdict if verdict != "no_signal" else "insufficient_data",
                 "verdict_text": financial_analysis_sector_language.tr(lang, "Положительный вывод без проверки этого сигнала преждевременен", "Bu signal tekshirilmasdan ijobiy xulosa qilish erta", "A positive conclusion is premature without resolving this signal"),
                 "solution_code": solution_code, "solution_text": solution, "solution_priority": signal["materiality"],
                 "monitoring_metrics": metrics, "next_trigger": financial_analysis_sector_language.tr(lang, "Следующий сопоставимый отчёт", "Keyingi taqqoslanadigan hisobot", "Next comparable filing"),
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

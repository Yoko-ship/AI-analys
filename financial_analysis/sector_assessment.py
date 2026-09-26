"""Derive evidence-backed signals, risks and monitoring points."""
from __future__ import annotations
from financial_analysis.sector_models import ReportEvidence
from financial_analysis.sector_models import SectorAssessment
from financial_analysis.sector_models import ValidatedFiling
import financial_analysis.sector_calculations as financial_analysis_sector_calculations
import financial_analysis.sector_issues as financial_analysis_sector_issues
import financial_analysis.sector_language as financial_analysis_sector_language
import financial_analysis.sector_numbers as financial_analysis_sector_numbers


def assess_filing(filing: ValidatedFiling, evidence: ReportEvidence):
    signals = []

    def signal(code, keys, direction, actual, prior=None, threshold=0, category="financial"):
        signal_facts = [evidence.by_code[k] for k in keys if k in evidence.by_code]
        if not filing.publishable or len(signal_facts) != len(keys) or any(not f.get("source_url") for f in signal_facts):
            return
        signals.append({"id": financial_analysis_sector_numbers.digest([code, [f["id"] for f in signal_facts]])[:24], "code": code,
                        "issuer_id": filing.issuer["id"], "sector_template_code": filing.template, "metric_code": keys[0],
                        "signal_type": code, "direction": direction, "category": category,
                        "value_current": actual, "value_previous": prior, "change_value": financial_analysis_sector_numbers.number(financial_analysis_sector_numbers.difference(actual, prior)),
                        "threshold": threshold, "comparison_change_pct": financial_analysis_sector_numbers.change(actual, prior)["change_pct"],
                        "period_current": filing.period, "period_previous": filing.snapshot.get("previous_comparable_period"),
                        "materiality": "high" if code in {"net_loss", "net_income_decline", "profit_quality"} else "medium",
                        "evidence_fact_ids": [f["id"] for f in signal_facts], "source_url": filing.source_url,
                        "verification_status": "verified"})

    for code in ("revenue", "net_income", "operating_income"):
        movement = financial_analysis_sector_numbers.change(filing.values.get(code), filing.previous.get(code))
        pct = movement["change_pct"]
        if pct is not None and pct > 3 and not movement["base_effect"]:
            signal(f"{code}_growth", [code], "positive", movement["current"], movement["previous"], 3)
        elif pct is not None and pct <= -20:
            signal(f"{code}_decline", [code], "negative", movement["current"], movement["previous"], -20)
        elif code == "operating_income" and pct is not None and pct < -3:
            signal("operating_income_decline", [code], "negative", movement["current"], movement["previous"], -3)
    if financial_analysis_sector_numbers.decimal(filing.values.get("net_income")) is not None and financial_analysis_sector_numbers.decimal(filing.values["net_income"]) < 0:
        signal("net_loss", ["net_income"], "negative", financial_analysis_sector_numbers.number(filing.values["net_income"]), financial_analysis_sector_numbers.number(filing.previous.get("net_income")))
    if financial_analysis_sector_numbers.decimal(filing.values.get("operating_income")) is not None and financial_analysis_sector_numbers.decimal(filing.values["operating_income"]) < 0:
        signal("negative_operating_result", ["operating_income"], "negative", financial_analysis_sector_numbers.number(filing.values["operating_income"]), financial_analysis_sector_numbers.number(filing.previous.get("operating_income")))
    if filing.quality["driver"] != "unknown":
        keys = ["unrealized_fair_value_gain", "net_income"] if filing.quality["driver"] == "unrealized_revaluation" else ["fx_income", "fx_expenses", "net_income"]
        signal("profit_quality", keys, "negative", financial_analysis_sector_numbers.number(filing.values.get(keys[0])), threshold="share_of_profit_growth >= 50%")
    if filing.template == "investment_fund_ifrs_annual" and (financial_analysis_sector_numbers.decimal(filing.values.get("dividend_income")) or 0) > 0:
        signal("dividend_income_positive", ["dividend_income"], "positive", financial_analysis_sector_numbers.number(filing.values["dividend_income"]))
    for asset in ("receivables", "inventories"):
        growth, sales = financial_analysis_sector_numbers.change(filing.values.get(asset), filing.opening.get(asset)), financial_analysis_sector_numbers.change(filing.values.get("revenue"), filing.previous.get("revenue"))
        if growth["change_pct"] is not None and sales["change_pct"] is not None and growth["change_pct"] > max(20, sales["change_pct"] + 10):
            signal(f"{asset}_outpace_revenue", [asset, "revenue"], "negative", growth["current"], growth["previous"], "growth exceeds revenue by 10pp")
    debt_growth = financial_analysis_sector_numbers.change(filing.values.get("total_liabilities"), filing.opening.get("total_liabilities"))
    equity_growth = financial_analysis_sector_numbers.change(filing.values.get("total_equity"), filing.opening.get("total_equity"))
    if debt_growth["change_pct"] is not None and equity_growth["change_pct"] is not None and debt_growth["change_pct"] > max(3, equity_growth["change_pct"] + 3):
        signal("liabilities_outpace_equity", ["total_liabilities", "total_equity"], "negative", debt_growth["current"], debt_growth["previous"], "growth exceeds equity by 3pp")
    if equity_growth["change_pct"] is not None and equity_growth["change_pct"] > 3:
        signal("equity_growth", ["total_equity"], "positive", equity_growth["current"], equity_growth["previous"], 3)
    claims, premiums = financial_analysis_sector_numbers.change(filing.values.get("insurance_claims"), filing.previous.get("insurance_claims")), financial_analysis_sector_numbers.change(filing.values.get("insurance_premiums"), filing.previous.get("insurance_premiums"))
    if claims["change_pct"] is not None and premiums["change_pct"] is not None and claims["change_pct"] > premiums["change_pct"] + 10:
        signal("claims_outpace_premiums", ["insurance_claims", "insurance_premiums"], "negative", claims["current"], claims["previous"], "growth exceeds premiums by 10pp")
    negatives = [s for s in signals if s["direction"] == "negative"]
    positives = [s for s in signals if s["direction"] == "positive"]
    verdict_status = "no_signal" if len(signals) < 2 or filing.template == "generic_nsbu" else "mixed" if positives and negatives else "negative" if negatives else "positive"
    if filing.quality["net_profit_change"]["base_effect"] and verdict_status == "positive":
        verdict_status = "mixed"
    verdict_label = {"positive": financial_analysis_sector_language.tr(filing.lang, "Финансовая динамика положительная", "Moliyaviy dinamika ijobiy", "Financial trends are positive"),
                     "negative": financial_analysis_sector_language.tr(filing.lang, "Финансовая динамика отрицательная", "Moliyaviy dinamika salbiy", "Financial trends are negative"),
                     "mixed": financial_analysis_sector_language.tr(filing.lang, "Картина смешанная", "Natijalar aralash", "Financial trends are mixed"),
                     "no_signal": financial_analysis_sector_language.tr(filing.lang, "Недостаточно сопоставимых данных для вердикта", "Xulosa uchun taqqoslanadigan ma’lumotlar yetarli emas", "Insufficient comparable data for a verdict")}[verdict_status]
    issues, risks = financial_analysis_sector_issues.make_issues(negatives, evidence.by_code, filing.quality, verdict_status, filing.lang, filing.period)
    watch_candidates = {
        "bank": ("net_income", "loan_portfolio", "customer_funds", "total_equity"),
        "microfinance_bank": ("net_income", "loan_portfolio", "customer_funds", "total_equity"),
        "microfinance": ("net_income", "loan_portfolio", "total_liabilities", "cash"),
        "insurance": ("operating_income", "net_income", "net_insurance_reserves", "insurance_claims"),
        "investment_fund_ifrs_annual": ("dividend_income", "unrealized_fair_value_gain", "cash", "management_expenses"),
        "commodity_exchange": ("operating_income", "own_cash", "client_cash", "settlement_liabilities"),
    }.get(filing.template, ("operating_income", "net_income", "cash", "total_liabilities", "revenue"))
    monitoring_points = []
    for key in watch_candidates:
        fact = evidence.by_code.get(key)
        if not fact or len(monitoring_points) >= 2:
            continue
        comparison = fact.get("previous")
        monitoring_points.append({
            "id": financial_analysis_sector_numbers.digest([filing.issuer["id"], filing.period, "watch", key])[:24],
            "metric_code": key, "label": fact["label"], "period": filing.period,
            "current_baseline": {"value": fact["value"], "unit": fact["unit"], "period": filing.period},
            "comparison_baseline": ({"value": comparison, "unit": fact["unit"],
                                     "period": filing.snapshot.get("previous_comparable_period")} if comparison is not None else None),
            "improvement_signal": financial_analysis_sector_language.tr(
                filing.lang,
                "в следующем отчёте показатель лучше текущего значения при сравнении одинаковых периодов",
                "bir xil davrlar taqqoslanganda, keyingi hisobotdagi ko‘rsatkich joriy qiymatdan yaxshiroq bo‘ladi",
                "in the next report, the metric is better than its current value when equivalent periods are compared",
            ),
            "risk_signal": financial_analysis_sector_language.tr(
                filing.lang,
                "показатель хуже текущего значения либо отчёты составлены по-разному и сравнение ненадёжно",
                "ko‘rsatkich joriy qiymatdan yomonroq yoki hisobotlar turlicha tuzilganligi sababli taqqoslash ishonchsiz",
                "the metric is worse than its current value, or the reports were prepared differently and the comparison is unreliable",
            ),
            "required_disclosure": financial_analysis_sector_language.tr(
                filing.lang,
                "значение в следующем отчёте и объяснение причин изменения",
                "keyingi hisobotdagi qiymat va o‘zgarish sabablari izohi",
                "the value in the next report and an explanation of what caused the change",
            ),
            "evidence_fact_ids": [fact["id"]], "source_url": fact.get("source_url"),
        })

    series = filing.snapshot.get("comparable_series") or []
    if isinstance(series, dict):
        series = series.get("net_income") or series.get("revenue") or []
    if not series:
        trend_key = "net_income" if filing.values.get("net_income") is not None else "revenue"
        series = []
        if filing.previous.get(trend_key) is not None:
            series.append({"period": filing.snapshot.get("previous_comparable_period") or "previous",
                           "value": financial_analysis_sector_numbers.number(filing.previous[trend_key]), "period_basis": filing.snapshot.get("period_basis"),
                           "accounting_standard": filing.standard, "consolidation_scope": filing.snapshot.get("scope")})
        if filing.values.get(trend_key) is not None:
            series.append({"period": filing.period, "value": financial_analysis_sector_numbers.number(filing.values[trend_key]),
                           "period_basis": filing.snapshot.get("period_basis"), "accounting_standard": filing.standard,
                           "consolidation_scope": filing.snapshot.get("scope")})
    trend = financial_analysis_sector_calculations.trend_state(series)

    key_metrics = ("revenue", "net_income", "total_assets", "total_liabilities", "total_equity", "cash")
    missing_metrics = [financial_analysis_sector_language.label(key, filing.lang) for key in key_metrics if filing.values.get(key) is None]
    checked = []
    if filing.source_url:
        checked.append(financial_analysis_sector_language.tr(filing.lang, "исходный документ и период", "asl hujjat va davr", "source document and period"))
    if filing.balance.get("status") == "passed":
        checked.append(financial_analysis_sector_language.tr(filing.lang, "равенство активов, капитала и обязательств", "aktivlar, kapital va majburiyatlar tengligi", "assets, equity and liabilities identity"))
    if filing.previous:
        checked.append(financial_analysis_sector_language.tr(filing.lang, "сопоставимая база изменения", "o‘zgarishning taqqoslanadigan bazasi", "comparable movement basis"))
    if filing.ratios:
        checked.append(financial_analysis_sector_language.tr(filing.lang, "формулы и входы применимых коэффициентов", "qo‘llanadigan koeffitsiyent formulalari va kirishlari", "formulas and inputs for applicable ratios"))
    cannot_assess = []
    if filing.values.get("cfo") is None:
        cannot_assess.append(financial_analysis_sector_language.tr(
            filing.lang,
            "качество прибыли и свободный денежный поток без данных об операционном денежном потоке и капитальных вложениях",
            "operatsion pul oqimi va kapital qo‘yilmalar ma’lumotlarisiz foyda sifati hamda erkin pul oqimi",
            "earnings quality and free cash flow without operating-cash-flow and capital-investment inputs",
        ))
    if filing.template in {"bank", "microfinance_bank", "microfinance"}:
        cannot_assess.append(financial_analysis_sector_language.tr(filing.lang, "регуляторные нормативы без раскрытых компонентов и методики", "oshkor qilingan qismlar va metodikasiz regulyativ me’yorlar", "regulatory ratios without disclosed components and methodology"))
    elif filing.values.get("interest_expenses") is None:
        cannot_assess.append(financial_analysis_sector_language.tr(filing.lang, "покрытие долга без графика платежей и процентных расходов", "to‘lov jadvali va foiz xarajatlarisiz qarz qoplamasi", "debt-service coverage without a payment schedule and interest expense"))
    verification_summary = {
        "checked": checked,
        "missing": missing_metrics,
        "cannot_assess": cannot_assess,
    }
    return SectorAssessment(signals=signals, negatives=negatives, positives=positives, verdict_status=verdict_status, verdict_label=verdict_label, issues=issues, risks=risks, monitoring_points=monitoring_points, trend=trend, verification_summary=verification_summary)

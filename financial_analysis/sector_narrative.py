"""Assemble report headlines, sections and compact summaries."""
from __future__ import annotations
from financial_analysis.sector_paragraphs import SectorLanguage
from financial_analysis.sector_models import ReportEvidence
from financial_analysis.sector_models import ReportNarrative
from financial_analysis.sector_models import SectorAssessment
from financial_analysis.sector_models import ValidatedFiling
import financial_analysis.sector_language as financial_analysis_sector_language
import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import financial_analysis.sector_templates as financial_analysis_sector_templates


def render_narrative(filing: ValidatedFiling, evidence: ReportEvidence, assessment: SectorAssessment):
    writer = SectorLanguage(filing, evidence, assessment)
    display_divisor = writer.display_divisor
    headline_facts = [writer.fact_sentence("net_income"), writer.fact_sentence("operating_income")]
    if filing.quality["driver"] == "FX-driven":
        headline_facts.append(financial_analysis_sector_language.tr(filing.lang, "Драйвер — курсовые разницы", "Asosiy omil — kurs farqlari", "Driven by foreign-exchange movements") + f": Δ {financial_analysis_sector_language.format_number(filing.quality['net_fx_result_change'])} {writer.money_unit}")
    elif filing.quality["driver"] == "unrealized_revaluation":
        headline_facts.append(financial_analysis_sector_language.tr(filing.lang, "Прибыль преимущественно от нереализованной переоценки", "Foyda asosan realizatsiya qilinmagan qayta baholashdan", "Profit is predominantly unrealized revaluation"))
    if filing.quality["net_profit_change"]["base_effect"]:
        headline_facts.append(financial_analysis_sector_language.tr(filing.lang, "Эффект низкой базы / смены знака", "Past baza / ishora o‘zgarishi ta’siri", "Low-base / sign-change effect"))
    headline = f"{filing.issuer['ticker']} · {filing.period_text}. {assessment.verdict_label}. " + "; ".join(f for f in headline_facts if f) + "."
    unavailable = {
        "no_source": financial_analysis_sector_language.tr(filing.lang, "Анализ временно недоступен: подходящая отчётность НСБУ не найдена.", "Tahlil mavjud emas: mos hisobot topilmadi.", "Analysis unavailable: no suitable filing was found."),
        "quality_blocked": financial_analysis_sector_language.tr(filing.lang, "Анализ временно недоступен: данные не прошли автоматическую сверку.", "Tahlil mavjud emas: ma’lumotlar tekshiruvdan o‘tmadi.", "Analysis unavailable: the data failed automated validation."),
        "mapping_failed": financial_analysis_sector_language.tr(filing.lang, "Отчёт пока готовится.", "Hisobot hozir tayyorlanmoqda.", "The report is being prepared."),
        "stale": financial_analysis_sector_language.tr(filing.lang, "Доступен только старый отчёт", "Faqat eski hisobot mavjud", "Only an old filing is available") + f": {filing.period_text}.",
    }
    if not filing.publishable:
        headline, verdict_status = unavailable.get(filing.status, unavailable["quality_blocked"]), "no_signal"
    headline_words = headline.split()
    if len(headline_words) > 40:
        headline = " ".join(headline_words[:40]).rstrip(" ,;:") + "…"
    complete_content = filing.publishable and len(evidence.verified) >= 7
    bank_without_income_comparison = filing.template == "bank" and not any(
        filing.previous.get(key) is not None for key in ("net_income", "profit_before_tax", "interest_income")
    )
    paragraphs = []
    if complete_content and filing.template in {"bank", "microfinance_bank", "microfinance"}:
        paragraphs = writer.bank_analysis_paragraphs(headline)
    elif complete_content and filing.template == "insurance":
        paragraphs = writer.insurance_analysis_paragraphs(headline)
    elif complete_content and filing.template == "investment_fund_ifrs_annual":
        paragraphs = writer.fund_analysis_paragraphs(headline)
    elif complete_content:
        paragraphs = writer.general_analysis_paragraphs(headline)
    elif filing.publishable:
        paragraphs = [headline]
        for group in ("financial_result", "cash_and_working_capital", "investment_base"):
            sentences = [writer.fact_sentence(key) for key in filing.codes[group]]
            if any(sentences):
                paragraphs.append("; ".join(item for item in sentences if item) + ".")
        paragraphs.append(financial_analysis_sector_language.tr(filing.lang, "Отчёт сокращён: подтверждённых фактов недостаточно; пропуски не заменены нулями или предположениями.", "Hisobot qisqartirilgan: tasdiqlangan faktlar yetarli emas; bo‘sh qiymatlar nol yoki taxmin bilan almashtirilmagan.", "The report is shortened because too few facts are verified; gaps were not replaced by zero or assumptions."))
    else:
        paragraphs = [headline]
    if bank_without_income_comparison and paragraphs:
        paragraphs[0] += " " + financial_analysis_sector_language.tr(
            filing.lang,
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
        key_evidence = [evidence.by_code.get(key) for key in metric_codes]
        if len(key_changes) >= 5 or not text_value or any(not item or not item.get("source_url") for item in key_evidence):
            return
        key_changes.append({
            "id": financial_analysis_sector_numbers.digest([filing.issuer["id"], filing.period, "key-change", code, [item["id"] for item in key_evidence]])[:24],
            "code": code,
            "category": category,
            "text": text_value,
            "metric_codes": list(metric_codes),
            "evidence_fact_ids": [item["id"] for item in key_evidence],
            "verification_status": "verified",
        })

    fact_change = lambda key: (evidence.by_code.get(key) or {}).get("change_pct")
    fact_value = lambda key: financial_analysis_sector_numbers.decimal((evidence.by_code.get(key) or {}).get("value"))
    if filing.publishable and filing.template == "investment_fund_ifrs_annual":
        portfolio_share = financial_analysis_sector_numbers.ratio(fact_value("portfolio_fair_value"), fact_value("total_assets"), True)
        if portfolio_share is not None:
            add_key_change("fund_portfolio", "business", financial_analysis_sector_language.tr(filing.lang, f"Инвестиционный портфель составляет {financial_analysis_sector_language.format_number(portfolio_share)}% активов фонда.", f"Investitsiya portfeli fond aktivlarining {financial_analysis_sector_language.format_number(portfolio_share)}%ini tashkil etadi.", f"The investment portfolio represents {financial_analysis_sector_language.format_number(portfolio_share)}% of fund assets."), ("portfolio_fair_value", "total_assets"))
        unrealized_share = financial_analysis_sector_numbers.ratio(fact_value("unrealized_fair_value_gain"), fact_value("net_income"), True)
        if unrealized_share is not None:
            add_key_change("fund_profit_quality", "profit_driver", financial_analysis_sector_language.tr(filing.lang, f"Нереализованная переоценка равна {financial_analysis_sector_language.format_number(unrealized_share)}% чистой прибыли: итог существенно зависит от оценочного эффекта.", f"Realizatsiya qilinmagan qayta baholash sof foydaning {financial_analysis_sector_language.format_number(unrealized_share)}%iga teng: yakun baholash ta’siriga sezilarli darajada bog‘liq.", f"Unrealized revaluation equals {financial_analysis_sector_language.format_number(unrealized_share)}% of net profit, making the result materially dependent on valuation effects."), ("unrealized_fair_value_gain", "net_income"))
        top5_share = financial_analysis_sector_numbers.ratio(fact_value("top5_holdings"), fact_value("portfolio_fair_value"), True)
        if top5_share is not None:
            add_key_change("fund_concentration", "balance", financial_analysis_sector_language.tr(filing.lang, f"Пять крупнейших позиций формируют {financial_analysis_sector_language.format_number(top5_share)}% портфеля.", f"Beshta eng yirik pozitsiya portfelning {financial_analysis_sector_language.format_number(top5_share)}%ini shakllantiradi.", f"The five largest holdings account for {financial_analysis_sector_language.format_number(top5_share)}% of the portfolio."), ("top5_holdings", "portfolio_fair_value"))
        level3_share = financial_analysis_sector_numbers.ratio(fact_value("level3_investments"), fact_value("portfolio_fair_value"), True)
        if level3_share is not None:
            add_key_change("fund_level3", "attention", financial_analysis_sector_language.tr(filing.lang, f"Инструменты Level 3 составляют {financial_analysis_sector_language.format_number(level3_share)}% портфеля, поэтому качество моделей оценки требует особого внимания.", f"Level 3 vositalari portfelning {financial_analysis_sector_language.format_number(level3_share)}%ini tashkil etadi, shu sababli baholash modellari sifati alohida e’tibor talab qiladi.", f"Level 3 instruments represent {financial_analysis_sector_language.format_number(level3_share)}% of the portfolio, making valuation-model quality a key area of attention."), ("level3_investments", "portfolio_fair_value"))
    elif filing.publishable and filing.template in {"bank", "microfinance_bank", "microfinance"}:
        loan_change = fact_change("loan_portfolio")
        if loan_change is not None:
            loan_direction = financial_analysis_sector_language.tr(filing.lang, "вырос", "oshdi", "grew") if loan_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизился", "kamaydi", "fell")
            add_key_change("loan_book", "business", financial_analysis_sector_language.tr(filing.lang, f"Кредитный портфель {loan_direction} на {financial_analysis_sector_language.format_number(abs(loan_change))}% и составляет {writer.display_money(fact_value('loan_portfolio'))} {writer.money_unit}.", f"Kredit portfeli {financial_analysis_sector_language.format_number(abs(loan_change))}% ga {loan_direction} va {writer.display_money(fact_value('loan_portfolio'))} {writer.money_unit}ni tashkil etdi.", f"The loan portfolio {loan_direction} {financial_analysis_sector_language.format_number(abs(loan_change))}% to {writer.display_money(fact_value('loan_portfolio'))} {writer.money_unit}."), ("loan_portfolio",))
        ldr_value = financial_analysis_sector_numbers.ratio(fact_value("loan_portfolio"), fact_value("customer_funds"), True)
        if ldr_value is not None:
            add_key_change("deposit_funding", "balance", financial_analysis_sector_language.tr(filing.lang, f"Средства клиентов составили {writer.display_money(fact_value('customer_funds'))} {writer.money_unit}, LDR — {financial_analysis_sector_language.format_number(ldr_value)}%.", f"Mijozlar mablag‘i {writer.display_money(fact_value('customer_funds'))} {writer.money_unit}ni tashkil etdi, LDR — {financial_analysis_sector_language.format_number(ldr_value)}%.", f"Customer funds were {writer.display_money(fact_value('customer_funds'))} {writer.money_unit} and LDR was {financial_analysis_sector_language.format_number(ldr_value)}%."), ("loan_portfolio", "customer_funds"))
        nii_value = financial_analysis_sector_numbers.difference(fact_value("interest_income"), fact_value("interest_expenses"))
        if nii_value is not None:
            add_key_change("net_interest_income", "profitability", financial_analysis_sector_language.tr(filing.lang, f"Чистый процентный доход составил {writer.display_money(nii_value)} {writer.money_unit}; доля процентных расходов в процентных доходах — {financial_analysis_sector_language.format_number(financial_analysis_sector_numbers.ratio(fact_value('interest_expenses'), fact_value('interest_income'), True))}%.", f"Sof foizli daromad {writer.display_money(nii_value)} {writer.money_unit}; foizli xarajatlarning daromaddagi ulushi — {financial_analysis_sector_language.format_number(financial_analysis_sector_numbers.ratio(fact_value('interest_expenses'), fact_value('interest_income'), True))}%.", f"Net interest income was {writer.display_money(nii_value)} {writer.money_unit}; interest expense equalled {financial_analysis_sector_language.format_number(financial_analysis_sector_numbers.ratio(fact_value('interest_expenses'), fact_value('interest_income'), True))}% of interest income."), ("interest_income", "interest_expenses"))
        coi_value = financial_analysis_sector_numbers.ratio(fact_value("operating_expenses"), fact_value("net_revenue_before_operating_expenses"), True)
        if coi_value is not None:
            add_key_change("cost_to_income", "profitability", f"Cost-to-Income = {financial_analysis_sector_language.format_number(coi_value)}%.", ("operating_expenses", "net_revenue_before_operating_expenses"))
        if fact_value("net_income") is not None:
            change_text = f" ({financial_analysis_sector_language.format_number(fact_change('net_income'))}%)" if fact_change("net_income") is not None else ""
            add_key_change("bottom_line", "profitability", financial_analysis_sector_language.tr(filing.lang, f"Чистая прибыль составила {writer.display_money(fact_value('net_income'))} {writer.money_unit}{change_text}.", f"Sof foyda {writer.display_money(fact_value('net_income'))} {writer.money_unit}{change_text}ni tashkil etdi.", f"Net profit was {writer.display_money(fact_value('net_income'))} {writer.money_unit}{change_text}."), ("net_income",))
    elif filing.publishable and filing.template == "insurance":
        if fact_change("insurance_premiums") is not None:
            premium_change = fact_change("insurance_premiums")
            premium_direction = financial_analysis_sector_language.tr(filing.lang, "выросли", "oshdi", "grew") if premium_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизились", "kamaydi", "fell")
            add_key_change("premium_scale", "business", financial_analysis_sector_language.tr(filing.lang, f"Страховые премии {premium_direction} на {financial_analysis_sector_language.format_number(abs(premium_change))}% до {writer.display_money(fact_value('insurance_premiums'))} {writer.money_unit}.", f"Sug‘urta mukofotlari {financial_analysis_sector_language.format_number(abs(premium_change))}% ga {premium_direction} va {writer.display_money(fact_value('insurance_premiums'))} {writer.money_unit}ga yetdi.", f"Insurance premiums {premium_direction} {financial_analysis_sector_language.format_number(abs(premium_change))}% to {writer.display_money(fact_value('insurance_premiums'))} {writer.money_unit}."), ("insurance_premiums",))
        retention_value = financial_analysis_sector_numbers.ratio(fact_value("net_insurance_reserves"), fact_value("gross_insurance_reserves"), True)
        if retention_value is not None:
            add_key_change("reserve_retention", "balance", financial_analysis_sector_language.tr(filing.lang, f"Чистые резервы составляют {financial_analysis_sector_language.format_number(retention_value)}% валовых резервов после учёта доли перестраховщиков.", f"Qayta sug‘urtalovchilar ulushi hisobga olingach, sof zaxiralar yalpi zaxiralarning {financial_analysis_sector_language.format_number(retention_value)}%ini tashkil etadi.", f"Net reserves equal {financial_analysis_sector_language.format_number(retention_value)}% of gross reserves after the reinsurer share."), ("gross_insurance_reserves", "reinsurer_share_in_reserves", "net_insurance_reserves"))
        if fact_change("operating_income") is not None and fact_change("net_income") is not None:
            op_change, profit_change = fact_change("operating_income"), fact_change("net_income")
            op_direction = financial_analysis_sector_language.tr(filing.lang, "вырос", "oshdi", "grew") if op_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизился", "kamaydi", "fell")
            profit_direction = financial_analysis_sector_language.tr(filing.lang, "выросла", "oshdi", "grew") if profit_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизилась", "kamaydi", "fell")
            op_now, op_before = fact_value("operating_income"), financial_analysis_sector_numbers.decimal((evidence.by_code.get("operating_income") or {}).get("previous"))
            # A percentage change of a loss is not a readable movement; show the amounts.
            if op_now is not None and op_before is not None and op_now > 0 and op_before > 0:
                op_part = financial_analysis_sector_language.tr(filing.lang, f"Операционный результат {op_direction} на {financial_analysis_sector_language.format_number(abs(op_change))}%", f"Operatsion natija {financial_analysis_sector_language.format_number(abs(op_change))}% ga {op_direction}", f"The operating result {op_direction} {financial_analysis_sector_language.format_number(abs(op_change))}%")
            else:
                op_part = financial_analysis_sector_language.tr(filing.lang, f"Операционный результат: {writer.display_money(op_before)} → {writer.display_money(op_now)} {writer.money_unit}", f"Operatsion natija: {writer.display_money(op_before)} → {writer.display_money(op_now)} {writer.money_unit}", f"The operating result moved from {writer.display_money(op_before)} to {writer.display_money(op_now)} {writer.money_unit}")
            # Only opposite movements mean the bottom line did not track operations.
            diverges = (op_change >= 0) != (profit_change >= 0)
            add_key_change("profit_divergence", "profit_driver", financial_analysis_sector_language.tr(
                filing.lang,
                f"{op_part}, а чистая прибыль {profit_direction} на {financial_analysis_sector_language.format_number(abs(profit_change))}%" + (": итоговая прибыль не повторяет динамику основной деятельности." if diverges else "."),
                f"{op_part}, sof foyda esa {financial_analysis_sector_language.format_number(abs(profit_change))}% ga {profit_direction}" + (": yakuniy foyda asosiy faoliyat dinamikasini takrorlamadi." if diverges else "."),
                f"{op_part}, while net profit {profit_direction} {financial_analysis_sector_language.format_number(abs(profit_change))}%" + ("; the bottom line did not track core operations." if diverges else "."),
            ), ("operating_income", "net_income"))
        if fact_change("total_assets") is not None and fact_change("total_equity") is not None:
            add_key_change("insurance_balance", "balance", financial_analysis_sector_language.tr(filing.lang, f"Активы изменились на {financial_analysis_sector_language.format_number(fact_change('total_assets'))}%, капитал — на {financial_analysis_sector_language.format_number(fact_change('total_equity'))}%.", f"Aktivlar {financial_analysis_sector_language.format_number(fact_change('total_assets'))}%, kapital {financial_analysis_sector_language.format_number(fact_change('total_equity'))}% ga o‘zgardi.", f"Assets changed {financial_analysis_sector_language.format_number(fact_change('total_assets'))}% and equity {financial_analysis_sector_language.format_number(fact_change('total_equity'))}%."), ("total_assets", "total_equity"))
    elif filing.publishable and filing.template == "commodity_exchange":
        revenue_change, op_change = fact_change("revenue"), fact_change("operating_income")
        if revenue_change is not None and op_change is not None:
            revenue_direction = financial_analysis_sector_language.tr(filing.lang, "выросла", "oshdi", "grew") if revenue_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизилась", "kamaydi", "fell")
            op_direction = financial_analysis_sector_language.tr(filing.lang, "выросла", "oshdi", "grew") if op_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизилась", "kamaydi", "fell")
            add_key_change("exchange_business", "business", financial_analysis_sector_language.tr(filing.lang, f"Выручка {revenue_direction} на {financial_analysis_sector_language.format_number(abs(revenue_change))}%, операционная прибыль {op_direction} на {financial_analysis_sector_language.format_number(abs(op_change))}%.", f"Tushum {financial_analysis_sector_language.format_number(abs(revenue_change))}% ga {revenue_direction}, operatsion foyda {financial_analysis_sector_language.format_number(abs(op_change))}% ga {op_direction}.", f"Revenue {revenue_direction} {financial_analysis_sector_language.format_number(abs(revenue_change))}% and operating profit {op_direction} {financial_analysis_sector_language.format_number(abs(op_change))}%."), ("revenue", "operating_income"))
        if fact_change("net_income") is not None:
            profit_change = fact_change("net_income")
            profit_direction = financial_analysis_sector_language.tr(filing.lang, "выросла", "oshdi", "grew") if profit_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизилась", "kamaydi", "fell")
            add_key_change("exchange_profit", "profitability", financial_analysis_sector_language.tr(filing.lang, f"Чистая прибыль {profit_direction} на {financial_analysis_sector_language.format_number(abs(profit_change))}% до {writer.display_money(fact_value('net_income'))} {writer.money_unit}.", f"Sof foyda {financial_analysis_sector_language.format_number(abs(profit_change))}% ga {profit_direction} va {writer.display_money(fact_value('net_income'))} {writer.money_unit}ga yetdi.", f"Net profit {profit_direction} {financial_analysis_sector_language.format_number(abs(profit_change))}% to {writer.display_money(fact_value('net_income'))} {writer.money_unit}."), ("net_income",))
        cash_share = financial_analysis_sector_numbers.ratio(fact_value("cash"), fact_value("total_assets"), True)
        if cash_share is not None:
            add_key_change("exchange_cash", "balance", financial_analysis_sector_language.tr(filing.lang, f"Деньги составляют {financial_analysis_sector_language.format_number(cash_share)}% активов; без разделения собственных и клиентских средств эта доля не является показателем свободной ликвидности биржи.", f"Pul aktivlarning {financial_analysis_sector_language.format_number(cash_share)}%ini tashkil etadi; o‘z va mijoz mablag‘lari ajratilmasa, bu ulush birjaning erkin likvidligini ko‘rsatmaydi.", f"Cash equals {financial_analysis_sector_language.format_number(cash_share)}% of assets; without separating own and client funds, this is not a measure of the exchange's freely available liquidity."), ("cash", "total_assets"))
        settlement_share = financial_analysis_sector_numbers.ratio(fact_value("current_liabilities"), fact_value("total_assets"), True)
        if settlement_share is not None:
            add_key_change("exchange_settlements", "attention", financial_analysis_sector_language.tr(filing.lang, f"Текущие обязательства равны {financial_analysis_sector_language.format_number(settlement_share)}% активов, но могут включать клиентские расчёты и не трактуются автоматически как корпоративный долг.", f"Joriy majburiyatlar aktivlarning {financial_analysis_sector_language.format_number(settlement_share)}%iga teng, ammo mijozlar hisob-kitoblarini o‘z ichiga olishi mumkin va avtomatik ravishda korporativ qarz deb talqin qilinmaydi.", f"Current liabilities equal {financial_analysis_sector_language.format_number(settlement_share)}% of assets but may include client settlements and are not automatically treated as corporate debt."), ("current_liabilities", "total_assets"))
    elif filing.publishable:
        if fact_change("revenue") is not None and fact_change("operating_income") is not None:
            revenue_change, op_change = fact_change("revenue"), fact_change("operating_income")
            revenue_direction = financial_analysis_sector_language.tr(filing.lang, "выросла", "oshdi", "grew") if revenue_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизилась", "kamaydi", "fell")
            op_direction = financial_analysis_sector_language.tr(filing.lang, "выросла", "oshdi", "grew") if op_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизилась", "kamaydi", "fell")
            add_key_change("core_business", "business", financial_analysis_sector_language.tr(filing.lang, f"Выручка {revenue_direction} на {financial_analysis_sector_language.format_number(abs(revenue_change))}%, операционная прибыль {op_direction} на {financial_analysis_sector_language.format_number(abs(op_change))}%.", f"Tushum {financial_analysis_sector_language.format_number(abs(revenue_change))}% ga {revenue_direction}, operatsion foyda {financial_analysis_sector_language.format_number(abs(op_change))}% ga {op_direction}.", f"Revenue {revenue_direction} {financial_analysis_sector_language.format_number(abs(revenue_change))}% and operating profit {op_direction} {financial_analysis_sector_language.format_number(abs(op_change))}%."), ("revenue", "operating_income"))
        finance_now = financial_analysis_sector_numbers.difference(fact_value("financial_income"), fact_value("financial_expenses"))
        finance_before = financial_analysis_sector_numbers.difference((evidence.by_code.get("financial_income") or {}).get("previous"), (evidence.by_code.get("financial_expenses") or {}).get("previous"))
        finance_delta = financial_analysis_sector_numbers.difference(finance_now, finance_before)
        if finance_delta is not None and fact_change("net_income") is not None:
            profit_change = fact_change("net_income")
            profit_direction = financial_analysis_sector_language.tr(filing.lang, "выросла", "oshdi", "grew") if profit_change >= 0 else financial_analysis_sector_language.tr(filing.lang, "снизилась", "kamaydi", "fell")
            bridge_text = financial_analysis_sector_language.tr(filing.lang, f"Чистая прибыль {profit_direction} на {financial_analysis_sector_language.format_number(abs(profit_change))}%, при этом чистый финансовый результат улучшился на {writer.display_money(finance_delta)} {writer.money_unit}.", f"Sof foyda {financial_analysis_sector_language.format_number(abs(profit_change))}% ga {profit_direction}, sof moliyaviy natija esa {writer.display_money(finance_delta)} {writer.money_unit}ga yaxshilandi.", f"Net profit {profit_direction} {financial_analysis_sector_language.format_number(abs(profit_change))}%, while the net finance result improved by {writer.display_money(finance_delta)} {writer.money_unit}.")
            bridge_metrics = ("financial_income", "financial_expenses", "net_income")
            if filing.quality.get("driver") == "FX-driven" and all(key in evidence.by_code for key in ("fx_income", "fx_expenses")):
                bridge_text += " " + financial_analysis_sector_language.tr(filing.lang, f"Внутри финансового результата чистый эффект курсовых разниц улучшился на {writer.display_money(filing.quality['net_fx_result_change'])} {writer.money_unit}; он уже включён в финансовый результат и повторно не суммируется.", f"Moliyaviy natija tarkibida kurs farqlarining sof ta’siri {writer.display_money(filing.quality['net_fx_result_change'])} {writer.money_unit}ga yaxshilandi; u moliyaviy natijaga allaqachon kiritilgan va qayta qo‘shilmaydi.", f"Within the finance result, the net FX effect improved by {writer.display_money(filing.quality['net_fx_result_change'])} {writer.money_unit}; it is already included and is not added twice.")
                bridge_metrics += ("fx_income", "fx_expenses")
            add_key_change("profit_bridge", "profit_driver", bridge_text, bridge_metrics)
        asset_candidates = (financial_analysis_sector_templates.SECTOR_PROFILES.get(filing.template) or {}).get("assets", ("cash", "receivables", "inventories", "fixed_assets"))
        assets_total = fact_value("total_assets")
        available_assets = [(key, fact_value(key)) for key in asset_candidates if fact_value(key) is not None]
        if assets_total is not None and available_assets:
            dominant_key, dominant_value = max(available_assets, key=lambda item: item[1])
            add_key_change("asset_concentration", "balance", financial_analysis_sector_language.tr(filing.lang, f"Крупнейшая раскрытая статья активов — «{financial_analysis_sector_language.label(dominant_key, filing.lang)}»: {financial_analysis_sector_language.format_number(financial_analysis_sector_numbers.ratio(dominant_value, assets_total, True))}% активов.", f"Oshkor qilingan eng yirik aktiv moddasi — «{financial_analysis_sector_language.label(dominant_key, filing.lang)}»: aktivlarning {financial_analysis_sector_language.format_number(financial_analysis_sector_numbers.ratio(dominant_value, assets_total, True))}%i.", f"The largest disclosed asset item is {financial_analysis_sector_language.label(dominant_key, filing.lang)}, at {financial_analysis_sector_language.format_number(financial_analysis_sector_numbers.ratio(dominant_value, assets_total, True))}% of assets."), (dominant_key, "total_assets"))
        if fact_change("total_liabilities") is not None and fact_change("total_equity") is not None:
            add_key_change("capital_balance", "attention", financial_analysis_sector_language.tr(filing.lang, f"Обязательства изменились на {financial_analysis_sector_language.format_number(fact_change('total_liabilities'))}%, капитал — на {financial_analysis_sector_language.format_number(fact_change('total_equity'))}%.", f"Majburiyatlar {financial_analysis_sector_language.format_number(fact_change('total_liabilities'))}%, kapital {financial_analysis_sector_language.format_number(fact_change('total_equity'))}% ga o‘zgardi.", f"Liabilities changed {financial_analysis_sector_language.format_number(fact_change('total_liabilities'))}% and equity {financial_analysis_sector_language.format_number(fact_change('total_equity'))}%."), ("total_liabilities", "total_equity"))

    text = "\n\n".join(paragraphs)

    # The company-page narrative follows the information architecture of
    # IELTS Writing Task 1: introduce the dataset, state the main pattern, and
    # then support it with two grouped detail paragraphs.  The underlying
    # verified facts, sector tables and calculation trace stay unchanged.
    task1_sections = []
    if filing.publishable:
        scope_text = {
            "ru": {"separate": "отдельной отчётности", "consolidated": "консолидированной отчётности"},
            "uz": {"separate": "alohida hisobot", "consolidated": "konsolidatsiyalangan hisobot"},
            "en": {"separate": "separate reporting", "consolidated": "consolidated reporting"},
        }.get(filing.lang, {}).get(filing.snapshot.get("scope"), filing.snapshot.get("scope") or "—")
        comparable_period = filing.snapshot.get("previous_comparable_period")
        issuer_name = filing.issuer.get("name") or filing.issuer["ticker"]
        if comparable_period:
            comparison_text = financial_analysis_sector_language.tr(
                filing.lang,
                f"Результаты сопоставляются с {comparable_period}, а балансовые показатели — с началом года.",
                f"Natijalar {comparable_period} bilan, balans ko‘rsatkichlari esa yil boshi bilan taqqoslanadi.",
                f"Performance is compared with {comparable_period}, while balance-sheet figures are compared with the start of the year.",
            )
        else:
            comparison_text = financial_analysis_sector_language.tr(
                filing.lang,
                "Сопоставимый период для результатов не раскрыт; балансовые изменения показаны только при наличии начальных значений.",
                "Natijalar uchun taqqoslanadigan davr oshkor qilinmagan; balansdagi o‘zgarishlar faqat boshlang‘ich qiymatlar mavjud bo‘lsa ko‘rsatiladi.",
                "No comparable performance period is disclosed; balance-sheet movements are shown only where opening values are available.",
            )
        introduction = financial_analysis_sector_language.tr(
            filing.lang,
            f"Анализ описывает финансовые результаты и положение {issuer_name} ({filing.issuer['ticker']}) по {filing.standard.upper()} за {filing.period_text} на уровне {scope_text}. {comparison_text} Все суммы приведены в {writer.money_unit} и взяты только из проверяемой отчётности.",
            f"Tahlil {issuer_name} ({filing.issuer['ticker']}) kompaniyasining {filing.period_text} davridagi {filing.standard.upper()} standarti bo‘yicha moliyaviy natijalari va holatini {scope_text} doirasida tavsiflaydi. {comparison_text} Barcha summalar {writer.money_unit}da berilgan va faqat tekshiriladigan hisobotdan olingan.",
            f"This analysis describes the financial performance and position of {issuer_name} ({filing.issuer['ticker']}) under {filing.standard.upper()} for {filing.period_text} on a {scope_text} basis. {comparison_text} All amounts are in {writer.money_unit} and come only from traceable filings.",
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
                "business": financial_analysis_sector_language.tr(filing.lang, "Что изменилось в бизнесе", "Biznesda nima o‘zgardi", "What changed in the business"),
                "profitability": financial_analysis_sector_language.tr(filing.lang, "Прибыльность", "Rentabellik", "Profitability"),
                "profit_driver": financial_analysis_sector_language.tr(filing.lang, "Драйвер прибыли", "Foyda drayveri", "Profit driver"),
                "balance": financial_analysis_sector_language.tr(filing.lang, "Баланс", "Balans", "Balance sheet"),
                "attention": financial_analysis_sector_language.tr(filing.lang, "Что требует внимания", "Nimaga e’tibor kerak", "What needs attention"),
            }
            leads = lead_catalog.get(filing.lang, lead_catalog["ru"])
            overview_blocks = [
                {"lead": leads.get(item["code"], fallback_leads.get(item["category"])), "text": item["text"],
                 "evidence_fact_ids": item["evidence_fact_ids"]}
                for item in key_changes[:5]
            ] or [{"text": overview}]
            performance_blocks = writer.narrative_blocks["performance"] or [{"text": performance_detail}]
            position_blocks = writer.narrative_blocks["position"] or [{"text": position_detail}]
        else:
            overview = f"{headline} " + financial_analysis_sector_language.tr(
                filing.lang,
                "Общая картина ограничена раскрытыми показателями; пропуски не заменены нулями или предположениями.",
                "Umumiy manzara oshkor qilingan ko‘rsatkichlar bilan cheklangan; bo‘sh qiymatlar nol yoki taxmin bilan almashtirilmagan.",
                "The overall picture is limited to disclosed metrics; missing values were not replaced with zero or estimates.",
            )
            performance_facts = [writer.fact_sentence(key) for key in ("revenue", "operating_income", "profit_before_tax", "net_income")]
            position_facts = [writer.fact_sentence(key) for key in ("total_assets", "cash", "total_liabilities", "total_equity")]
            performance_detail = "; ".join(item for item in performance_facts if item) or financial_analysis_sector_language.tr(
                filing.lang,
                "Подтверждённых данных о доходах и прибыли недостаточно для содержательного сравнения.",
                "Daromad va foydani mazmunli taqqoslash uchun tasdiqlangan ma’lumot yetarli emas.",
                "There is insufficient verified income and profit data for a meaningful comparison.",
            )
            position_detail = "; ".join(item for item in position_facts if item) or financial_analysis_sector_language.tr(
                filing.lang,
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
        }.get(filing.lang, ("Introduction", "Overview", "Details I — Financial performance", "Details II — Financial position"))
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
    outline = section_titles.get(filing.lang, section_titles["ru"])
    if filing.publishable and complete_content and filing.template in {"bank", "microfinance_bank", "microfinance"}:
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
        outline = bank_section_titles.get(filing.lang, bank_section_titles["ru"])
    elif filing.publishable and complete_content and filing.template == "insurance":
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
        outline = insurance_section_titles.get(filing.lang, insurance_section_titles["ru"])
    elif filing.publishable and complete_content:
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
        outline = general_section_titles.get(filing.lang, general_section_titles["ru"])
    report_sections = [
        {"id": section_id, "number": f"{index:02d}", "title": title, "text": paragraphs[index - 1]}
        for index, (section_id, title) in enumerate(outline, 1)
        if index <= len(paragraphs)
    ] if filing.publishable else []

    card_text = None
    if filing.publishable:
        brief_labels = {
            "revenue": financial_analysis_sector_language.tr(filing.lang, "выручка", "tushum", "revenue"),
            "operating_income": financial_analysis_sector_language.tr(filing.lang, "операционная прибыль", "operatsion foyda", "operating profit"),
            "net_income": financial_analysis_sector_language.tr(filing.lang, "чистая прибыль", "sof foyda", "net profit"),
        }
        brief_facts = []
        brief_directions = []
        for code in ("revenue", "operating_income", "net_income"):
            fact = evidence.by_code.get(code)
            if not fact or fact.get("change_pct") is None:
                continue
            if filing.lang == "ru":
                direction = "выросла" if fact["change_pct"] >= 0 else "снизилась"
            else:
                direction = financial_analysis_sector_language.tr(filing.lang, "", "o‘sdi", "rose") if fact["change_pct"] >= 0 else financial_analysis_sector_language.tr(filing.lang, "", "pasaydi", "fell")
            connector = "by " if filing.lang == "en" else "на "
            brief_facts.append(f"{brief_labels[code]} {direction} {connector}{financial_analysis_sector_language.format_number(abs(fact['change_pct']))}%")
            brief_directions.append("positive" if fact["change_pct"] >= 0 else "negative")
            if len(brief_facts) == 2:
                break
        if "positive" in brief_directions and "negative" in brief_directions:
            card_verdict = financial_analysis_sector_language.tr(filing.lang, "Картина смешанная", "Natijalar aralash", "The picture is mixed")
        elif brief_directions and all(item == "positive" for item in brief_directions):
            card_verdict = financial_analysis_sector_language.tr(filing.lang, "Динамика положительная", "Dinamika ijobiy", "The trend is positive")
        elif brief_directions and all(item == "negative" for item in brief_directions):
            card_verdict = financial_analysis_sector_language.tr(filing.lang, "Динамика отрицательная", "Dinamika salbiy", "The trend is negative")
        else:
            card_verdict = assessment.verdict_label
        card_text = f"{filing.issuer['ticker']}: {', '.join(brief_facts)}. {card_verdict}." if brief_facts else f"{filing.issuer['ticker']}: {card_verdict}."
    return ReportNarrative(key_changes=key_changes, task1_sections=task1_sections, narrative_blocks=writer.narrative_blocks, display_divisor=display_divisor, headline=headline, complete_content=complete_content, paragraphs=paragraphs, text=text, report_sections=report_sections, card_text=card_text)

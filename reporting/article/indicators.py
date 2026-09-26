"""Interpret financial signals, indicator groups, and report conclusions."""

from __future__ import annotations
from reporting.article.signals import (
    _article_period_label_from_table,
    _article_period_phrase,
    _article_table_signals,
    _format_bln_sum_from_thousand,
    _tone_from_threshold,
)
from reporting.localization import _normalize_language
from reporting.presentation import _format_report_number, _format_report_pct, _table_from_rows


def _article_indicator_items(signals: dict, language: str) -> list[dict]:
    lang = _normalize_language(language)

    items: list[dict] = []

    def assessment(tone: str) -> str:
        labels = {
            "ru": {
                "good": "Норма / сильная сторона",
                "warning": "Зона внимания",
                "danger": "Риск",
                "neutral": "Нейтрально",
            },
            "en": {
                "good": "Normal / strength",
                "warning": "Watch zone",
                "danger": "Risk",
                "neutral": "Neutral",
            },
            "uz": {
                "good": "Me'yor / kuchli tomon",
                "warning": "E'tibor zonasi",
                "danger": "Risk",
                "neutral": "Neytral",
            },
        }
        return (labels.get(lang) or labels["ru"]).get(tone, (labels.get(lang) or labels["ru"])["neutral"])

    def add_pct(
        category: str,
        title: str,
        key: str,
        formula: str,
        hint: str,
        benchmark: str,
        good: float,
        warn: float,
        *,
        reverse: bool = False,
    ):
        value = signals.get(key)
        if value is None:
            return
        tone = _tone_from_threshold(value, good, warn, reverse=reverse)
        result = _format_report_pct(value, language)
        items.append({
            "category": category,
            "label": title,
            "value": result,
            "hint": hint,
            "formula": formula,
            "benchmark": benchmark,
            "assessment": assessment(tone),
            "tone": tone,
        })

    def add_ratio(
        category: str,
        title: str,
        key: str,
        formula: str,
        hint: str,
        benchmark: str,
        good: float,
        warn: float,
    ):
        value = signals.get(key)
        if value is None:
            return
        tone = _tone_from_threshold(value, good, warn)
        result = f"{_format_report_number(value, language=language, digits=2)}×"
        items.append({
            "category": category,
            "label": title,
            "value": result,
            "hint": hint,
            "formula": formula,
            "benchmark": benchmark,
            "assessment": assessment(tone),
            "tone": tone,
        })

    def add_pct_neutral(
        category: str,
        title: str,
        key: str,
        formula: str,
        hint: str,
        benchmark: str,
    ):
        value = signals.get(key)
        if value is None:
            return
        items.append({
            "category": category,
            "label": title,
            "value": _format_report_pct(value, language),
            "hint": hint,
            "formula": formula,
            "benchmark": benchmark,
            "assessment": assessment("neutral"),
            "tone": "neutral",
        })

    def add_ratio_neutral(
        category: str,
        title: str,
        key: str,
        formula: str,
        hint: str,
        benchmark: str,
    ):
        value = signals.get(key)
        if value is None:
            return
        items.append({
            "category": category,
            "label": title,
            "value": f"{_format_report_number(value, language=language, digits=2)}×",
            "hint": hint,
            "formula": formula,
            "benchmark": benchmark,
            "assessment": assessment("neutral"),
            "tone": "neutral",
        })

    net_profit = signals.get("net_profit")
    if net_profit is not None:
        tone = "good" if net_profit > 0 else "danger" if net_profit < 0 else "neutral"
        items.append({
            "category": "profitability",
            "label": "Чистая прибыль",
            "value": _format_bln_sum_from_thousand(net_profit, language),
            "hint": "Финальный финансовый результат периода после расходов и налога.",
            "formula": "Финансовый результат после операционных расходов, налога и поправок",
            "benchmark": "> 0",
            "assessment": assessment(tone),
            "tone": tone,
        })

    add_pct(
        "liquidity",
        "LDR — кредиты / депозиты",
        "ldr_pct",
        "(Кредиты и лизинг нетто / клиентские депозиты) × 100",
        "Показывает, насколько кредитный портфель покрыт клиентской депозитной базой. Значение выше 100% означает зависимость от дополнительного фондирования.",
        "< 100%",
        100,
        120,
        reverse=True,
    )
    add_pct(
        "liquidity",
        "Ликвидность первой линии",
        "first_line_pct",
        "(Касса + средства в ЦБРУ) / активы × 100",
        "Показывает быстрый запас денег, который можно использовать без продажи кредитов или ценных бумаг.",
        "> 8%",
        8,
        4,
    )
    add_ratio(
        "profitability",
        "Покрытие процентных расходов",
        "interest_coverage",
        "Процентные доходы / процентные расходы",
        "Показывает, насколько процентные доходы перекрывают стоимость денег. Чем ближе к 1×, тем меньше запас маржи.",
        "> 1,5×",
        1.5,
        1.2,
    )
    add_pct(
        "profitability",
        "ROA (аннуализ.)",
        "roa_annual_pct",
        "(Чистая прибыль / активы) × (4 / номер квартала) × 100",
        "Показывает доходность активов в годовом выражении. Для квартального отчёта показатель аннуализируется, чтобы его можно было сравнить с банковскими ориентирами.",
        "1–2% для банков",
        1,
        0.5,
    )
    add_pct(
        "profitability",
        "ROE (аннуализ.)",
        "roe_annual_pct",
        "(Чистая прибыль / капитал) × (4 / номер квартала) × 100",
        "Показывает доходность капитала акционеров в годовом выражении. Очень высокий ROE нужно читать вместе с капитализацией и риском резервов.",
        "10–20%",
        10,
        5,
    )
    add_pct(
        "profitability",
        "NIM (аннуализ.)",
        "nim_annual_pct",
        "(Процентные доходы − процентные расходы) / активы × (4 / номер квартала) × 100",
        "Показывает годовую чистую процентную маржу банка относительно активов.",
        "3–5%",
        3,
        1,
    )
    add_pct(
        "profitability",
        "Чистая маржа прибыли",
        "net_margin_pct",
        "Чистая прибыль / процентные доходы × 100",
        "Показывает, сколько чистой прибыли остаётся на 100 сум процентного дохода после расходов, резервов и налога.",
        "> 15%",
        15,
        5,
    )
    add_pct_neutral(
        "profitability",
        "Эффективная ставка налога",
        "effective_tax_pct",
        "Налог на прибыль / прибыль до налога × 100",
        "Помогает понять, насколько чистая прибыль зависит от налоговой нагрузки, льгот или разовых налоговых эффектов.",
        "сравнить со стандартной ставкой",
    )
    add_pct(
        "asset_quality",
        "Покрытие брутто-кредитов резервами",
        "reserve_coverage_pct",
        "Резерв на потери / брутто-кредиты × 100",
        "Показывает, какую часть кредитного портфеля банк уже закрыл резервом. Резкий рост ухудшает качество прибыли.",
        "< 2%",
        2,
        3,
        reverse=True,
    )
    add_pct(
        "asset_quality",
        "Резервная нагрузка",
        "reserve_burden_pct",
        "Расходы на резервы / процентные доходы × 100",
        "Показывает, какую часть процентного дохода банк направляет на покрытие возможных кредитных потерь.",
        "< 10%",
        10,
        20,
        reverse=True,
    )
    add_pct(
        "capital",
        "Капитал / активы",
        "capital_assets_pct",
        "Собственный капитал / активы × 100",
        "Показывает запас прочности баланса до привлечённых денег.",
        "> 12%",
        12,
        8,
    )
    add_ratio_neutral(
        "capital",
        "Левередж активы / капитал",
        "leverage_assets_equity",
        "Активы / собственный капитал",
        "Показывает, во сколько раз активы превышают капитал. Для банков высокий рычаг нормален, но рост рычага снижает запас прочности.",
        "≈ 6–12× для банков",
    )
    add_pct_neutral(
        "capital",
        "Коэффициент задолженности D/A",
        "debt_assets_pct",
        "Обязательства / активы × 100",
        "Показывает долю привлечённых средств в балансе. Для банка высокий показатель нормален, но его нужно читать вместе с капиталом и ликвидностью.",
        "≈ 80–90% для банков",
    )
    add_ratio_neutral(
        "capital",
        "D/E — долг / капитал",
        "debt_equity",
        "Обязательства / собственный капитал",
        "Показывает финансовый рычаг: сколько обязательств приходится на 1 сум капитала.",
        "≈ 4–8× для банков",
    )
    add_pct(
        "efficiency",
        "CIR — расходы / доход",
        "cir_pct",
        "Операционные расходы / чистый доход до операционных расходов × 100",
        "Показывает, сколько операционных затрат съедает доход до налога. Чем ниже, тем лучше операционная эффективность.",
        "< 60%",
        60,
        70,
        reverse=True,
    )
    add_pct(
        "efficiency",
        "Доля непроцентных доходов",
        "non_interest_share_pct",
        "Беспроцентные доходы / (процентные + беспроцентные доходы) × 100",
        "Показывает, насколько прибыль зависит не только от кредитно-депозитной маржи.",
        "20–40%",
        20,
        10,
    )
    if lang == "en":
        categories = {
            "liquidity": "Liquidity",
            "profitability": "Profitability",
            "asset_quality": "Asset quality",
            "capital": "Capital",
            "efficiency": "Efficiency",
        }
        translations = {
            "Чистая прибыль": ("Net profit", "Financial result after operating expenses, tax and adjustments", "Final financial result of the period after expenses and tax."),
            "LDR — кредиты / депозиты": ("LDR — loans / deposits", "(Net loans and leasing / client deposits) x 100", "Shows how much of the loan portfolio is covered by client deposits. A value above 100% means dependence on additional funding."),
            "Ликвидность первой линии": ("First-line liquidity", "(Cash + Central Bank balances) / assets x 100", "Shows the fast money buffer available without selling loans or securities."),
            "Покрытие процентных расходов": ("Interest expense coverage", "Interest income / interest expense", "Shows how far interest income covers the cost of funding. The closer it is to 1x, the thinner the margin buffer."),
            "ROA (аннуализ.)": ("ROA, annualized", "(Net profit / assets) x (4 / quarter) x 100", "Shows annualized return on assets. Quarterly figures are annualized so they can be compared with banking benchmarks."),
            "ROE (аннуализ.)": ("ROE, annualized", "(Net profit / equity) x (4 / quarter) x 100", "Shows annualized return on shareholder capital. Very high ROE should be read together with capitalization and reserve risk."),
            "NIM (аннуализ.)": ("NIM, annualized", "(Interest income - interest expense) / assets x (4 / quarter) x 100", "Shows annualized net interest margin relative to assets."),
            "Чистая маржа прибыли": ("Net profit margin", "Net profit / interest income x 100", "Shows how much net profit remains per 100 UZS of interest income after expenses, provisions and tax."),
            "Эффективная ставка налога": ("Effective tax rate", "Income tax / profit before tax x 100", "Helps understand how much net profit depends on taxes, tax benefits or one-off tax effects."),
            "Покрытие брутто-кредитов резервами": ("Gross loan coverage by allowances", "Loss allowance / gross loans x 100", "Shows what part of the loan portfolio is already covered by allowances. A sharp increase weakens profit quality."),
            "Резервная нагрузка": ("Provision burden", "Provision expenses / interest income x 100", "Shows what share of interest income is used to cover potential credit losses."),
            "Капитал / активы": ("Capital / assets", "Equity / assets x 100", "Shows the balance-sheet safety buffer above borrowed money."),
            "Левередж активы / капитал": ("Assets / equity leverage", "Assets / equity", "Shows how many times assets exceed equity. High leverage is normal for banks, but rising leverage reduces the safety buffer."),
            "Коэффициент задолженности D/A": ("Debt ratio D/A", "Liabilities / assets x 100", "Shows the share of borrowed funds in the balance sheet. For banks a high value is normal, but it must be read together with capital and liquidity."),
            "D/E — долг / капитал": ("D/E — debt / equity", "Liabilities / equity", "Shows financial leverage: how much liabilities sit on each 1 UZS of equity."),
            "CIR — расходы / доход": ("CIR — cost / income", "Operating expenses / net income before operating expenses x 100", "Shows how much operating cost consumes pre-tax income. Lower is better for operating efficiency."),
            "Доля непроцентных доходов": ("Non-interest income share", "Non-interest income / (interest + non-interest income) x 100", "Shows whether profit depends only on the loan-deposit margin."),
        }
        for item in items:
            item["category_label"] = categories.get(item.get("category"), "Metric")
            translated = translations.get(item.get("label"))
            if translated:
                item["label"], item["formula"], item["hint"] = translated
            item["benchmark"] = (
                str(item.get("benchmark") or "")
                .replace("для банков", "for banks")
                .replace("сравнить со стандартной ставкой", "compare with the standard tax rate")
            )
    return items


def _article_ratio_category_intro(category: str, items: list[dict], signals: dict, language: str) -> str:
    if _normalize_language(language) != "ru":
        return ""
    by_key = {item.get("label"): item for item in items}
    if category == "liquidity":
        ldr = by_key.get("LDR — кредиты / депозиты")
        first_line = by_key.get("Ликвидность первой линии")
        parts = []
        if ldr:
            parts.append(f"LDR равен {ldr['value']}: это показывает, хватает ли депозитов для покрытия кредитного портфеля.")
        if first_line:
            parts.append(f"Ликвидность первой линии составляет {first_line['value']}: это быстрые деньги для покрытия оттока.")
        return " ".join(parts) or "Ликвидность показывает, есть ли у банка быстрый запас денег и насколько кредитный портфель зависит от устойчивой депозитной базы."
    if category == "profitability":
        net_profit = by_key.get("Чистая прибыль")
        coverage = by_key.get("Покрытие процентных расходов")
        parts = []
        if net_profit:
            parts.append(f"Чистая прибыль составила {net_profit['value']}, поэтому банк завершил период с положительным результатом.")
        if coverage:
            parts.append(f"Покрытие процентных расходов — {coverage['value']}, что показывает запас процентной маржи над стоимостью фондирования.")
        return " ".join(parts) or "Рентабельность показывает, превращается ли доходная база банка в реальную прибыль после расходов и резервов."
    if category == "asset_quality":
        reserve = by_key.get("Покрытие брутто-кредитов резервами")
        reserve_change = signals.get("reserve_change")
        text = "Качество активов показывает, насколько кредитный портфель требует резервов и как это влияет на прибыль."
        if reserve:
            text += f" Покрытие брутто-кредитов резервами — {reserve['value']}."
        if reserve_change is not None and reserve_change > 0:
            text += f" Рост резерва на {_format_bln_sum_from_thousand(reserve_change, language)} делает вывод осторожнее: часть результата уходит на покрытие возможных потерь."
        return text
    if category == "capital":
        capital = by_key.get("Капитал / активы")
        equity_change = signals.get("equity_change")
        text = "Достаточность капитала показывает, какой запас прочности есть у банка поверх привлечённых денег."
        if capital:
            text += f" Капитал к активам — {capital['value']}."
        if equity_change is not None and equity_change < 0:
            text += f" Снижение капитала на {_format_bln_sum_from_thousand(abs(equity_change), language)} уменьшает буфер для покрытия ошибок в активах."
        return text
    if category == "efficiency":
        cir = by_key.get("CIR — расходы / доход")
        non_interest = by_key.get("Доля непроцентных доходов")
        parts = []
        if cir:
            parts.append(f"CIR равен {cir['value']}: это показывает, сколько дохода съедают операционные расходы.")
        if non_interest:
            parts.append(f"Доля непроцентных доходов — {non_interest['value']}, то есть доходная база не ограничивается только процентной маржей.")
        return " ".join(parts) or "Операционная эффективность показывает качество бизнес-модели: доход должен расти быстрее расходов и не зависеть от одной статьи."
    return ""


def _article_ratio_category_followups(category: str, signals: dict, language: str) -> list[dict]:
    if _normalize_language(language) != "ru":
        return []

    def block(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    def pct(key: str) -> str:
        return _format_report_pct(signals.get(key), language)

    def money(key: str) -> str:
        return _format_bln_sum_from_thousand(signals.get(key), language)

    out: list[dict] = []
    if category == "liquidity":
        ldr = signals.get("ldr_pct")
        first_line = signals.get("first_line_pct")
        deposits_change = signals.get("deposits_change")
        if ldr is not None and ldr > 100:
            text = (
                f"Значение LDR на уровне {pct('ldr_pct')} означает, что кредитный портфель больше клиентской депозитной базы. "
                "Банк покрывает этот разрыв за счёт других источников фондирования: привлечённых кредитов, межбанковского рынка, РЕПО или капитала."
            )
            if deposits_change is not None and deposits_change < 0:
                text += f" Отток клиентских депозитов на {_format_bln_sum_from_thousand(abs(deposits_change), language)} усиливает этот риск и должен стать одним из главных пунктов мониторинга."
            out.append(block(text))
        if first_line is not None:
            out.append(block(
                f"Ликвидные активы первой линии составляют {pct('first_line_pct')} активов. Для банка с крупной депозитной базой это нижняя часть комфортной зоны: показатель не критичен сам по себе, но при оттоке депозитов запас быстрых денег становится важнее прибыли."
            ))

    if category == "profitability":
        net_profit = signals.get("net_profit")
        if net_profit is not None:
            tax_text = ""
            if signals.get("effective_tax_pct") is not None:
                tax_text = f" Эффективная ставка налога составила {pct('effective_tax_pct')}, поэтому чистую прибыль нужно читать вместе с налоговыми эффектами периода."
            out.append(block(
                f"Чистая прибыль за квартал составила {money('net_profit')}.{tax_text} Это сильный результат, если он поддержан процентной маржой, а не только разовыми статьями."
            ))
        if signals.get("roa_quarter_pct") is not None or signals.get("roe_quarter_pct") is not None:
            out.append(block(
                f"Квартальный ROA составляет {pct('roa_quarter_pct')} ({pct('roa_annual_pct')} в годовом выражении), ROE — {pct('roe_quarter_pct')} за квартал ({pct('roe_annual_pct')} годовых). Аннуализация нужна потому, что отчёт покрывает один квартал, а банковские ориентиры обычно читаются в годовом формате."
            ))
        if signals.get("nim_quarter_pct") is not None or signals.get("net_margin_pct") is not None:
            out.append(block(
                f"Чистая процентная маржа до резервов составляет {pct('nim_quarter_pct')} за квартал ({pct('nim_annual_pct')} годовых), а чистая маржа прибыли — {pct('net_margin_pct')}. Это показывает, сколько процентного бизнеса превращается в итоговую прибыль после фондирования, резервов, расходов и налога."
            ))

    if category == "asset_quality":
        if signals.get("reserve_burden_pct") is not None:
            out.append(block(
                f"Резервная нагрузка равна {pct('reserve_burden_pct')} процентных доходов. Это означает, что заметная часть процентной маржи уходит на покрытие возможных потерь, поэтому высокая прибыль не должна оцениваться отдельно от качества кредитного портфеля."
            ))
        if signals.get("reserve_change") is not None and signals.get("reserve_change") > 0:
            out.append(block(
                f"Резерв под потери вырос на {money('reserve_change')}. Если это отражает ухудшение портфеля, будущая прибыль может быть менее устойчивой; если это консервативное доформирование резервов, эффект может быть временным. Без раскрытия NPL это нужно оставлять как риск для следующего квартала."
            ))

    if category == "capital":
        if signals.get("capital_assets_pct") is not None:
            out.append(block(
                f"Капитал/активы составляет {pct('capital_assets_pct')}, что выше базового ориентира 8% и даёт банку буфер прочности. Но сам факт достаточного капитала не отменяет контроля за дивидендами, резервами и ростом активов."
            ))
        if signals.get("debt_assets_pct") is not None or signals.get("debt_equity") is not None:
            out.append(block(
                f"Коэффициент задолженности D/A равен {pct('debt_assets_pct')}, D/E — {_format_report_number(signals.get('debt_equity'), language=language, digits=2)}×, левередж активы/капитал — {_format_report_number(signals.get('leverage_assets_equity'), language=language, digits=2)}×. Для банка высокий финансовый рычаг нормален, но снижение капитализации делает итоговый вывод осторожнее."
            ))
        if signals.get("equity_change") is not None and signals.get("equity_change") < 0 and signals.get("net_profit") is not None and signals.get("net_profit") > 0:
            implied_distribution = abs(signals["equity_change"]) + signals["net_profit"]
            out.append(block(
                f"Капитал снизился на {_format_bln_sum_from_thousand(abs(signals['equity_change']), language)} при прибыли {money('net_profit')}. Расчётно это указывает на крупное распределение прибыли или прочие движения капитала около {_format_bln_sum_from_thousand(implied_distribution, language)}, что похоже на логику HTML-отчёта с акцентом на дивидендное давление."
            ))

    if category == "efficiency":
        if signals.get("cir_pct") is not None:
            out.append(block(
                f"CIR составляет {pct('cir_pct')}. Чем ниже этот показатель, тем больше операционного дохода остаётся после административных расходов; для банка это один из главных признаков управляемости бизнес-модели."
            ))
        if signals.get("non_interest_share_pct") is not None:
            out.append(block(
                f"Доля непроцентных доходов равна {pct('non_interest_share_pct')}. Это полезно для диверсификации, но слишком высокая зависимость от разовых валютных, торговых или прочих доходов снижает предсказуемость прибыли."
            ))
    return out


def _article_ratio_section_blocks(
    assets_h: dict | None,
    liab_h: dict | None,
    income_table: dict | None,
    language: str,
) -> list[dict]:
    lang = _normalize_language(language)
    signals = _article_table_signals(assets_h, liab_h, income_table)
    items = _article_indicator_items(signals, language)
    blocks: list[dict] = []

    if items:
        blocks.append({"type": "kpi_grid", "items": items[:8]})

    category_titles = {
        "ru": {
            "liquidity": "5.1. Анализ ликвидности",
            "profitability": "5.2. Анализ рентабельности",
            "asset_quality": "5.3. Анализ качества активов",
            "capital": "5.4. Достаточность капитала",
            "efficiency": "5.5. Операционная эффективность",
        },
        "en": {
            "liquidity": "5.1. Liquidity analysis",
            "profitability": "5.2. Profitability analysis",
            "asset_quality": "5.3. Asset quality analysis",
            "capital": "5.4. Capital adequacy",
            "efficiency": "5.5. Operating efficiency",
        },
        "uz": {
            "liquidity": "5.1. Likvidlik tahlili",
            "profitability": "5.2. Rentabellik tahlili",
            "asset_quality": "5.3. Aktivlar sifati tahlili",
            "capital": "5.4. Kapital yetarliligi",
            "efficiency": "5.5. Operatsion samaradorlik",
        },
    }
    title_map = category_titles.get(lang) or category_titles["ru"]
    category_order = [
        ("liquidity", title_map["liquidity"]),
        ("profitability", title_map["profitability"]),
        ("asset_quality", title_map["asset_quality"]),
        ("capital", title_map["capital"]),
        ("efficiency", title_map["efficiency"]),
    ]
    for category, title in category_order:
        category_items = [item for item in items if item.get("category") == category]
        if not category_items:
            continue
        blocks.append({"type": "subheading", "text": title})
        intro = _article_ratio_category_intro(category, category_items, signals, language)
        if intro:
            blocks.append({"type": "paragraph", "text": intro})
        for item in category_items:
            blocks.append({
                "type": "formula",
                "title": item["label"],
                "formula": item["formula"],
                "result": item["value"],
                "description": item["hint"],
                "tone": item["tone"],
            })
        blocks.extend(_article_ratio_category_followups(category, signals, language))
    return blocks


def _key_indicators_article_table(
    assets_h: dict | None,
    liab_h: dict | None,
    income_table: dict | None,
    language: str,
) -> dict | None:
    lang = _normalize_language(language)
    signals = _article_table_signals(assets_h, liab_h, income_table)
    items = _article_indicator_items(signals, language)
    category_labels = {
        "ru": {
            "liquidity": "Ликвидность",
            "profitability": "Рентабельность",
            "asset_quality": "Качество активов",
            "capital": "Капитал",
            "efficiency": "Эффективность",
            "fallback": "Показатель",
        },
        "en": {
            "liquidity": "Liquidity",
            "profitability": "Profitability",
            "asset_quality": "Asset quality",
            "capital": "Capital",
            "efficiency": "Efficiency",
            "fallback": "Metric",
        },
        "uz": {
            "liquidity": "Likvidlik",
            "profitability": "Rentabellik",
            "asset_quality": "Aktivlar sifati",
            "capital": "Kapital",
            "efficiency": "Samaradorlik",
            "fallback": "Ko'rsatkich",
        },
    }.get(lang)
    captions = {
        "ru": "Таблица 8 — Сводная таблица ключевых показателей",
        "en": "Table 8 — Key indicator summary",
        "uz": "Jadval 8 — Asosiy ko'rsatkichlar xulosasi",
    }
    headers = {
        "ru": ["Блок", "Показатель", "Значение", "Ориентир", "Вывод", "Как влияет на анализ"],
        "en": ["Block", "Metric", "Value", "Benchmark", "Conclusion", "How it affects the analysis"],
        "uz": ["Blok", "Ko'rsatkich", "Qiymat", "Me'yor", "Xulosa", "Tahlilga ta'siri"],
    }
    rows = [
        [
            (category_labels or {}).get(item.get("category"), (category_labels or {}).get("fallback", "Metric")),
            item["label"],
            item["value"],
            item["benchmark"],
            item["assessment"],
            item["hint"],
        ]
        for item in items
    ]
    return _table_from_rows(
        "key_indicators_summary",
        captions.get(lang, captions["en"]),
        headers.get(lang, headers["en"]),
        rows,
        source="openinfo_excel.derived_ratios",
    )


def _article_rating_from_signals(signals: dict, language: str) -> dict:
    items = _article_indicator_items(signals, language)
    danger_count = sum(1 for item in items if item.get("tone") == "danger")
    warning_count = sum(1 for item in items if item.get("tone") == "warning")
    for key in ("assets_change", "deposits_change", "equity_change"):
        value = signals.get(key)
        if value is not None and value < 0:
            warning_count += 1
    reserve_change = signals.get("reserve_change")
    if reserve_change is not None and reserve_change > 0:
        warning_count += 1

    if danger_count >= 3 or (danger_count >= 2 and warning_count >= 3):
        return {
            "tone": "danger",
            "value": "Повышенный риск",
            "text": "Прибыль есть, но несколько ключевых коэффициентов одновременно указывают на давление ликвидности, фондирования или качества активов.",
        }
    if danger_count >= 1 or warning_count >= 3:
        return {
            "tone": "warning",
            "value": "Умеренно рискованное финансовое состояние",
            "text": "Банк сохраняет рабочую прибыльность, но итоговая оценка требует осторожности из-за отдельных слабых сигналов в балансе и коэффициентах.",
        }
    if warning_count:
        return {
            "tone": "neutral",
            "value": "Устойчивое состояние с зонами внимания",
            "text": "Ключевые показатели в целом читаются приемлемо, но отдельные строки нужно отслеживать в следующих кварталах.",
        }
    return {
        "tone": "good",
        "value": "Устойчивое финансовое состояние",
        "text": "Ключевые показатели не показывают критических разрывов между прибыльностью, капиталом и ликвидностью.",
    }


def _article_verdict_summary_items(signals: dict, language: str) -> list[dict]:
    if _normalize_language(language) != "ru":
        return []

    items: list[dict] = []

    def add(label: str, value: str, text: str, tone: str = "neutral"):
        items.append({"label": label, "value": value, "text": text, "tone": tone})

    capital_assets = signals.get("capital_assets_pct")
    if capital_assets is None:
        add("Устойчивость", "Данных мало", "Капитальный буфер не удалось посчитать из XLSX, поэтому итоговую оценку нужно читать осторожнее.")
    elif capital_assets >= 12:
        add("Устойчивость", _format_report_pct(capital_assets, language), "Капитал выглядит достаточным: у банка есть запас, который помогает пережить ошибки в активах и рыночные колебания.", "good")
    elif capital_assets >= 8:
        add("Устойчивость", _format_report_pct(capital_assets, language), "Капитал есть, но запас не широкий. Рост кредитов, падение прибыли или переоценка активов быстро ухудшат картину.", "warning")
    else:
        add("Устойчивость", _format_report_pct(capital_assets, language), "Капитальный буфер слабый. Даже положительная прибыль не полностью снимает риск, если баланс продолжит расти или резервы увеличатся.", "danger")

    first_line = signals.get("first_line_pct")
    ldr = signals.get("ldr_pct")
    if first_line is not None and first_line >= 8 and (ldr is None or ldr <= 100):
        add("Ликвидность", _format_report_pct(first_line, language), "Быстрые деньги и соотношение кредитов к депозитам выглядят спокойно: риск срочного дефицита ликвидности ниже.", "good")
    elif (first_line is not None and first_line < 4) or (ldr is not None and ldr > 120):
        value = _format_report_pct(first_line, language) if first_line is not None else _format_report_pct(ldr, language)
        add("Ликвидность", value, "Ликвидность требует проверки: нужно смотреть, не финансируются ли кредиты слишком тонким запасом быстрых активов или дорогими ресурсами.", "danger")
    else:
        value = _format_report_pct(first_line, language) if first_line is not None else (_format_report_pct(ldr, language) if ldr is not None else "—")
        add("Ликвидность", value, "Картина смешанная: критического сигнала может не быть, но следующий квартал должен подтвердить устойчивость депозитов и быстрых активов.", "warning")

    net_profit = signals.get("net_profit")
    interest_coverage = signals.get("interest_coverage")
    cir = signals.get("cir_pct")
    if net_profit is not None and net_profit > 0 and (interest_coverage is None or interest_coverage >= 1.2) and (cir is None or cir <= 70):
        add("Качество прибыли", _format_bln_sum_from_thousand(net_profit, language), "Прибыль поддержана базовой банковской маржой и не выглядит полностью зависимой от разовых строк.", "good")
    elif net_profit is not None and net_profit > 0:
        add("Качество прибыли", _format_bln_sum_from_thousand(net_profit, language), "Прибыль положительная, но её качество нужно проверять через стоимость фондирования, резервы и операционные расходы.", "warning")
    elif net_profit is not None:
        add("Качество прибыли", _format_bln_sum_from_thousand(net_profit, language), "Отрицательный или слабый результат делает оценку заметно осторожнее: капитал и ликвидность должны компенсировать давление на прибыль.", "danger")

    reserve_change = signals.get("reserve_change")
    deposits_change = signals.get("deposits_change")
    assets_change = signals.get("assets_change")
    if reserve_change is not None and reserve_change > 0:
        add("Главный риск", "Резервы растут", f"Резерв под потери вырос на {_format_bln_sum_from_thousand(reserve_change, language)}. Это главный сигнал проверить качество кредитного портфеля.", "danger")
    elif deposits_change is not None and deposits_change < 0:
        add("Главный риск", "Отток депозитов", f"Клиентские депозиты снизились на {_format_bln_sum_from_thousand(abs(deposits_change), language)}. Следующий шаг — проверить, чем банк заменяет эту ресурсную базу.", "warning")
    elif assets_change is not None and assets_change < 0:
        add("Главный риск", "Сжатие баланса", f"Активы сократились на {_format_bln_sum_from_thousand(abs(assets_change), language)}. Нужно понять, это плановая переоценка/погашение или сигнал давления на бизнес.", "warning")
    elif ldr is not None and ldr > 120:
        add("Главный риск", "Высокий LDR", "Кредитный портфель заметно выше депозитной базы. Это повышает зависимость от альтернативного фондирования.", "danger")
    else:
        add("Главный риск", "Без явного красного флага", "Главные показатели не дают одного доминирующего риска; итог нужно строить по сочетанию капитала, ликвидности и качества прибыли.", "good")

    watch = []
    if deposits_change is None or deposits_change < 0:
        watch.append("депозиты")
    if reserve_change is None or reserve_change > 0:
        watch.append("резервы к брутто-кредитам")
    if capital_assets is None or capital_assets < 12:
        watch.append("капитал / активы")
    if cir is None or cir > 60:
        watch.append("CIR и операционные расходы")
    if not watch:
        watch = ["устойчивость маржи", "рост кредитов", "долю ликвидных активов"]
    add("Следующий квартал", "Что проверить", "В следующем отчёте в первую очередь смотреть: " + ", ".join(watch[:4]) + ".", "neutral")
    return items[:5]


def _article_conclusion_blocks(
    base_text: str,
    assets_h: dict | None,
    liab_h: dict | None,
    income_table: dict | None,
    ratio_table: dict | None,
    language: str,
) -> list[dict]:
    if _normalize_language(language) != "ru":
        return [{"type": "paragraph", "text": base_text or "Final assessment depends on profit quality, balance structure and data completeness."}]

    signals = _article_table_signals(assets_h, liab_h, income_table)
    assets_total = signals.get("assets_total")
    assets_change = signals.get("assets_change")
    equity_change = signals.get("equity_change")
    net_profit = signals.get("net_profit")
    period_phrase = _article_period_phrase(_article_period_label_from_table(assets_h), language)
    rating = _article_rating_from_signals(signals, language)
    summary_items = _article_verdict_summary_items(signals, language)

    if assets_total is not None:
        period_part = f" {period_phrase}" if period_phrase else ""
        intro = (
            f"Итоговая картина{period_part} строится вокруг трёх фактов: активы составляют "
            f"{_format_bln_sum_from_thousand(assets_total, language)}, изменение баланса за период — "
            f"{_format_bln_sum_from_thousand(assets_change, language)}, чистая прибыль — "
            f"{_format_bln_sum_from_thousand(net_profit, language)}. Поэтому вывод нужно читать не только через прибыль, "
            "а через качество фондирования, ликвидность и то, сколько риска уже видно в резервах."
        )
    else:
        intro = base_text or "Итоговая оценка зависит от качества прибыли, структуры баланса и полноты раскрытых данных."

    items: list[dict] = []

    def add(label: str, text: str, tone: str):
        items.append({"label": label, "text": text, "tone": tone})

    if net_profit is not None and net_profit > 0:
        add("Сильная сторона", f"Банк остаётся прибыльным: чистая прибыль составила {_format_bln_sum_from_thousand(net_profit, language)}. Это поддерживает базовую оценку, но не отменяет проверки резервов и капитала.", "good")

    interest_coverage = signals.get("interest_coverage")
    if interest_coverage is not None and interest_coverage >= 1.2:
        add("Маржа", f"Процентные доходы покрывают процентные расходы в {_format_report_number(interest_coverage, language=language, digits=2)}×. Это значит, что основной банковский бизнес генерирует запас над стоимостью денег.", "good" if interest_coverage >= 1.5 else "warning")

    capital_assets = signals.get("capital_assets_pct")
    if capital_assets is not None:
        tone = _tone_from_threshold(capital_assets, 12, 8)
        add("Капитал", f"Капитал к активам равен {_format_report_pct(capital_assets, language)}. Чем ниже этот запас, тем осторожнее нужно читать прибыль и рост портфеля.", tone)

    first_line = signals.get("first_line_pct")
    if first_line is not None:
        tone = _tone_from_threshold(first_line, 8, 4)
        add("Ликвидность", f"Ликвидность первой линии — {_format_report_pct(first_line, language)}. Это быстрые деньги на случай оттока ресурсов; низкое значение делает итоговый тон осторожнее.", tone)

    if assets_change is not None and assets_change < 0:
        add("Риск", f"Баланс сократился на {_format_bln_sum_from_thousand(abs(assets_change), language)}. Само по себе это не плохо, но нужно понимать, ушло ли снижение в плановую переоценку/погашение или в отток ресурсов.", "warning")

    deposits_change = signals.get("deposits_change")
    if deposits_change is not None and deposits_change < 0:
        add("Фондирование", f"Клиентские депозиты снизились на {_format_bln_sum_from_thousand(abs(deposits_change), language)}. Это усиливает важность ликвидности и стоимости альтернативного фондирования.", "warning")

    reserve_change = signals.get("reserve_change")
    if reserve_change is not None and reserve_change > 0:
        add("Кредитный риск", f"Резерв под потери вырос на {_format_bln_sum_from_thousand(reserve_change, language)}. Для анализа это сигнал проверить качество кредитного портфеля, а не смотреть только на чистую прибыль.", "danger")

    if equity_change is not None and equity_change < 0:
        add("Запас прочности", f"Собственный капитал снизился на {_format_bln_sum_from_thousand(abs(equity_change), language)}. Это уменьшает буфер, который покрывает ошибки в активах и рыночные шоки.", "warning")

    if not items:
        add("Что делать дальше", "Сравните самые крупные изменения в таблицах с коэффициентами выше: если слабые места совпадают сразу в балансе, прибыли и ликвидности, итоговую оценку нужно снижать.", "neutral")

    return [
        {"type": "rating", "label": "Итоговая оценка", **rating},
        {"type": "paragraph", "text": intro},
        *([{"type": "verdict_summary", "items": summary_items}] if summary_items else []),
        {"type": "verdict_list", "items": items[:8]},
    ]

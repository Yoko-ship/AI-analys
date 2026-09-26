"""Explain structured tables using their reported figures."""

from __future__ import annotations
from reporting.article.signals import (
    _format_bln_sum_from_thousand,
    _format_change_phrase,
    _largest_abs_table_row,
    _rank_report_rows,
    _table_label,
    _table_number,
    _table_row_by_keywords,
    _total_report_row,
)
from reporting.localization import _normalize_language


def _practical_table_explanation_blocks(table: dict | None, role: str, language: str) -> list[dict] | None:
    if not table:
        return []

    lang = _normalize_language(language)
    row_count = len(table.get("rows") or [])
    total_phrase = _format_change_phrase(_total_report_row(table))
    strongest_growth = next((item for item in _rank_report_rows(table, 3, reverse=True) if item[0] > 0), None)
    strongest_decline = next((item for item in _rank_report_rows(table, 3, reverse=False) if item[0] < 0), None)
    biggest_change = _largest_abs_table_row(table, 3)
    largest_share = _largest_abs_table_row(table, 2)
    largest_income_share = _largest_abs_table_row(table, 5)

    def block(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    def movement_text(growth_word: str, decline_word: str) -> str:
        parts = []
        if strongest_decline:
            parts.append(f"{decline_word}: {strongest_decline[1]} ({strongest_decline[2]})")
        if strongest_growth:
            parts.append(f"{growth_word}: {strongest_growth[1]} ({strongest_growth[2]})")
        return "; ".join(parts)

    if role == "multi_period_trend":
        if lang == "en":
            return [
                block(f"This table checks whether the current quarter is part of a stable trend or just a one-period jump across {max(row_count, 0)} key lines."),
                block("What to do: compare deposits, loans, capital and profit across columns. A good verdict needs consistency: profit should not improve while liquidity, capital or reserve coverage deteriorate at the same time."),
            ]
        if lang == "uz":
            return [
                block(f"Bu jadval joriy chorak barqaror trendning bir qismimi yoki {max(row_count, 0)} asosiy satr bo'yicha bir martalik sakrashmi, shuni tekshiradi."),
                block("Nima qilish kerak: depozitlar, kreditlar, kapital va foydani ustunlar bo'yicha solishtiring. Yaxshi xulosa izchil bo'lishi kerak: foyda yaxshilanayotganda likvidlik, kapital yoki rezerv qoplamasi bir vaqtda yomonlashmasligi kerak."),
            ]
        return [
            block(f"Эта таблица показывает не один квартал, а траекторию по {max(row_count, 0)} ключевым строкам: растёт ли банк устойчиво, сжимается ли баланс, ухудшается ли качество фондирования или прибыли."),
            block("Что делать: сначала сравните депозиты, кредиты, капитал и чистую прибыль по датам. Хороший итоговый вывод возможен только тогда, когда прибыль не улучшается ценой падения ликвидности, слабого капитала или роста резервов."),
        ]

    if role == "assets_horizontal":
        moves_en = movement_text("largest growth", "largest fall")
        moves_uz = movement_text("eng katta o'sish", "eng katta pasayish")
        moves_ru = movement_text("самый сильный рост", "самое сильное снижение")
        if lang == "en":
            headline = f"Use this table to see where the bank moved its money across {row_count} asset lines."
            if total_phrase:
                headline += f" Main movement: {total_phrase}."
            if moves_en:
                headline += f" Key rows: {moves_en}."
            return [
                block(headline),
                block("What to do: if loans grew, check provisions and portfolio quality; if cash/liquid assets fell, check liquidity pressure; if one asset line jumped sharply, treat concentration risk as a separate question in the final analysis."),
            ]
        if lang == "uz":
            headline = f"Bu jadval bank pullari {row_count} ta aktiv satri bo'yicha qayerga ko'chganini ko'rsatadi."
            if total_phrase:
                headline += f" Asosiy harakat: {total_phrase}."
            if moves_uz:
                headline += f" Muhim satrlar: {moves_uz}."
            return [
                block(headline),
                block("Nima qilish kerak: kreditlar o'ssa, rezervlar va portfel sifatini tekshiring; likvid aktivlar kamaygan bo'lsa, likvidlik bosimini ko'ring; bitta aktiv keskin o'ssa, yakuniy tahlilda konsentratsiya riskini alohida baholang."),
            ]
        headline = f"Эта таблица показывает, куда банк перераспределил деньги по {row_count} строкам активов."
        if total_phrase:
            headline += f" Главное движение: {total_phrase}."
        if moves_ru:
            headline += f" Ключевые строки: {moves_ru}."
        return [
            block(headline),
            block("Что делать: если выросли кредиты, проверьте резервы и качество портфеля; если снизились деньги или ликвидные активы, смотрите риск нехватки ликвидности; если резко выросла одна статья, учитывайте риск концентрации в итоговом выводе."),
        ]

    if role == "liabilities_horizontal":
        moves_en = movement_text("largest increase", "largest reduction")
        moves_uz = movement_text("eng katta o'sish", "eng katta kamayish")
        moves_ru = movement_text("самый сильный рост", "самое сильное сокращение")
        if lang == "en":
            headline = f"This table shows where the bank got funding for its assets across {row_count} lines."
            if total_phrase:
                headline += f" Main movement: {total_phrase}."
            if moves_en:
                headline += f" Key funding rows: {moves_en}."
            return [
                block(headline),
                block("What to do: falling deposits or rising borrowings mean liquidity and refinancing risk need extra attention; stronger equity makes the balance safer; a funding mix that changes quickly should make the final tone more cautious."),
            ]
        if lang == "uz":
            headline = f"Bu jadval bank aktivlari {row_count} ta manba bo'yicha qaysi pul bilan moliyalashtirilganini ko'rsatadi."
            if total_phrase:
                headline += f" Asosiy harakat: {total_phrase}."
            if moves_uz:
                headline += f" Muhim funding satrlari: {moves_uz}."
            return [
                block(headline),
                block("Nima qilish kerak: depozitlar kamayishi yoki qarzlar o'sishi likvidlik va qayta moliyalashtirish riskini kuchaytiradi; kapital o'sishi balansni xavfsizroq qiladi; funding tarkibi tez o'zgarsa, yakuniy bahoda ehtiyotkor bo'lish kerak."),
            ]
        headline = f"Эта таблица показывает, за счёт каких денег банк финансирует активы по {row_count} строкам."
        if total_phrase:
            headline += f" Главное движение: {total_phrase}."
        if moves_ru:
            headline += f" Ключевые строки фондирования: {moves_ru}."
        return [
            block(headline),
            block("Что делать: если депозиты падают или заёмные средства растут, отдельно проверьте ликвидность и риск рефинансирования; рост капитала делает баланс устойчивее; резкая смена источников денег должна делать итоговую оценку осторожнее."),
        ]

    if role == "assets_vertical":
        if lang == "en":
            detail = f" Largest weight: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"This table shows what the balance sheet is mostly made of, not just whether it grew.{detail}"),
                block("What to do: focus the analysis on the biggest asset block. Loans mean credit-quality risk, liquid assets mean safety but usually lower yield, securities mean market and interest-rate sensitivity."),
            ]
        if lang == "uz":
            detail = f" Eng katta ulush: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Bu jadval balans asosan nimadan iboratligini ko'rsatadi, faqat o'sishni emas.{detail}"),
                block("Nima qilish kerak: tahlilni eng katta aktiv blokiga qarating. Kreditlar bo'lsa kredit sifati, likvid aktivlar bo'lsa xavfsizlik va pastroq rentabellik, qimmatli qog'ozlar bo'lsa bozor va foiz riski muhim."),
            ]
        detail = f" Самая большая доля: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
        return [
            block(f"Эта таблица показывает, из чего в основном состоит баланс, а не просто вырос он или нет.{detail}"),
            block("Что делать: главный фокус анализа переносите на крупнейший блок активов. Кредиты означают риск качества портфеля, ликвидные активы дают запас прочности, но обычно ниже доходность, ценные бумаги добавляют рыночный и процентный риск."),
        ]

    if role == "liabilities_vertical":
        if lang == "en":
            detail = f" Largest weight: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"This table shows the bank's funding model: deposits, borrowings or equity.{detail}"),
                block("What to do: a high stable-deposit or equity share supports the score; a high debt/repo share means the conclusion must pay more attention to refinancing terms and liquidity buffers."),
            ]
        if lang == "uz":
            detail = f" Eng katta ulush: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Bu jadval bankning funding modelini ko'rsatadi: depozitlar, qarzlar yoki kapital.{detail}"),
                block("Nima qilish kerak: barqaror depozit yoki kapital ulushi yuqori bo'lsa baho mustahkamlanadi; qarz/REPO ulushi yuqori bo'lsa, xulosada qayta moliyalashtirish shartlari va likvidlik buferlariga ko'proq e'tibor bering."),
            ]
        detail = f" Самая большая доля: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
        return [
            block(f"Эта таблица показывает модель фондирования банка: депозиты, заёмные средства или собственный капитал.{detail}"),
            block("Что делать: высокая доля устойчивых депозитов или капитала поддерживает оценку; высокая доля долга/РЕПО означает, что в выводе нужно сильнее учитывать сроки рефинансирования и запас ликвидности."),
        ]

    if role == "income_statement":
        if lang == "en":
            detail = f" Largest P&L movement: {biggest_change[0]} ({biggest_change[1]})." if biggest_change else ""
            share = f" Largest current-period weight: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
            return [
                block(f"This table shows where profit is coming from and whether revenue growth is actually turning into profit. {detail}{share}".strip()),
                block("What to do: compare income growth with funding costs, provisions and operating expenses. If costs or provisions rise faster than income, the final analysis should be more cautious even when revenue is growing."),
            ]
        if lang == "uz":
            detail = f" Eng katta foyda-zarar harakati: {biggest_change[0]} ({biggest_change[1]})." if biggest_change else ""
            share = f" Joriy davrdagi eng katta ulush: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
            return [
                block(f"Bu jadval foyda qayerdan kelayotganini va tushum o'sishi haqiqiy foydaga aylanayotganini ko'rsatadi. {detail}{share}".strip()),
                block("Nima qilish kerak: daromad o'sishini funding xarajatlari, rezervlar va operatsion xarajatlar bilan solishtiring. Xarajatlar yoki rezervlar daromaddan tezroq o'ssa, tushum o'ssa ham yakuniy xulosa ehtiyotkor bo'lishi kerak."),
            ]
        detail = f" Самое крупное движение в прибыли/убытке: {biggest_change[0]} ({biggest_change[1]})." if biggest_change else ""
        share = f" Самая большая доля в текущем периоде: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
        return [
            block(f"Эта таблица показывает, откуда берётся прибыль и превращается ли рост доходов в реальный результат. {detail}{share}".strip()),
            block("Что делать: сравните рост доходов со стоимостью фондирования, резервами и операционными расходами. Если расходы или резервы растут быстрее доходов, итоговый вывод должен быть осторожнее даже при росте выручки."),
        ]

    if role == "ratio_summary":
        if lang == "en":
            return [
                block(f"This table turns the statements into {row_count} quick health checks: profitability, leverage, liquidity, funding and efficiency."),
                block("What to do: read weak ratios first and connect them with the tables above. One good ratio is not enough; the final view should improve only when profitability, liquidity and capital quality are consistent at the same time."),
            ]
        if lang == "uz":
            return [
                block(f"Bu jadval hisobotlarni {row_count} ta tezkor sog'liq signaliga aylantiradi: rentabellik, qarz yuki, likvidlik, funding va samaradorlik."),
                block("Nima qilish kerak: avval zaif koeffitsiyentlarni o'qing va ularni yuqoridagi jadvallar bilan bog'lang. Bitta yaxshi ko'rsatkich yetarli emas; yakuniy baho faqat rentabellik, likvidlik va kapital sifati bir vaqtda mos bo'lsa yaxshilanadi."),
            ]
        return [
            block(f"Эта таблица превращает отчётность в {row_count} быстрых проверок здоровья бизнеса: прибыльность, долговая нагрузка, ликвидность, фондирование и эффективность."),
            block("Что делать: сначала смотрите слабые коэффициенты и связывайте их с таблицами выше. Один хороший показатель не спасает картину; итоговая оценка улучшается только когда прибыльность, ликвидность и качество капитала совпадают одновременно."),
        ]

    if role == "key_indicators":
        if lang == "en":
            return [
                block("This summary table is the decision layer of the report: it keeps only the ratios that should directly influence the final assessment."),
                block("What to do: read the red and amber rows first. If the same weakness appears in liquidity, asset quality and capital, the final tone should be cautious even when profit is positive."),
            ]
        if lang == "uz":
            return [
                block("Bu xulosa jadvali hisobotning qaror qatlamidir: unda yakuniy bahoga bevosita ta'sir qiladigan ko'rsatkichlar qoldirilgan."),
                block("Nima qilish kerak: avval xavfli va ehtiyotkor satrlarni o'qing. Bir xil zaiflik likvidlik, aktiv sifati va kapitalda takrorlansa, foyda ijobiy bo'lsa ham yakuniy baho ehtiyotkor bo'lishi kerak."),
            ]
        return [
            block("Сводная таблица — это слой принятия решения: здесь оставлены только показатели, которые прямо меняют итоговую оценку банка."),
            block("Что делать: сначала смотрите строки с выводом «Риск» и «Зона внимания». Если слабый сигнал повторяется сразу в ликвидности, качестве активов и капитале, финальный вывод должен быть осторожным даже при положительной прибыли."),
        ]

    if role == "excel_source":
        return _excel_source_intro_blocks(1, lang)

    return None


def _excel_source_intro_blocks(table_count: int, language: str) -> list[dict]:
    lang = _normalize_language(language)

    def block(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    if lang == "en":
        return [
            block(f"Below are the raw XLSX rows used by the analysis ({table_count} source tables). Use this section only when you want to check where a number came from or why a line affected the conclusion."),
            block("What to do: compare suspicious or large rows with the explanation above. If an important line is here but not explained in the analysis, open the original report or rerun deep Excel analysis for a cleaner result."),
        ]
    if lang == "uz":
        return [
            block(f"Quyida tahlilda ishlatilgan XLSX manba satrlari bor ({table_count} ta manba jadval). Bu bo'lim raqam qayerdan kelganini yoki nima uchun xulosaga ta'sir qilganini tekshirish uchun kerak."),
            block("Nima qilish kerak: shubhali yoki katta satrlarni yuqoridagi izohlar bilan solishtiring. Muhim satr bu yerda bor, lekin tahlilda tushuntirilmagan bo'lsa, asl hisobotni oching yoki chuqur Excel tahlilini qayta ishga tushiring."),
        ]
    return [
        block(f"Ниже показаны исходные строки XLSX, которые использовались в анализе ({table_count} таблиц-источников). Этот раздел нужен не для чтения подряд, а чтобы быстро проверить, откуда взялась цифра и почему она повлияла на вывод."),
        block("Что делать: смотрите только подозрительные или самые крупные строки и сравнивайте их с объяснениями выше. Если важная статья есть здесь, но не объяснена в анализе, откройте исходный отчёт или перезапустите глубокий Excel-анализ."),
    ]


def _html_style_table_explanation_blocks(table: dict | None, role: str, language: str) -> list[dict] | None:
    if not table or _normalize_language(language) != "ru":
        return None

    def block(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    rows = table.get("rows") or []
    total_row = _total_report_row(table)
    total_current = _table_number(total_row, 1)
    total_previous = _table_number(total_row, 2)
    total_change = _table_number(total_row, 3)
    total_pct = str(total_row[4]).strip() if total_row and len(total_row) > 4 else "—"
    strongest_growth = next((item for item in _rank_report_rows(table, 3, reverse=True) if item[0] > 0), None)
    strongest_decline = next((item for item in _rank_report_rows(table, 3, reverse=False) if item[0] < 0), None)

    if role == "assets_horizontal":
        investment = _table_row_by_keywords(table, "инвест")
        loans = _table_row_by_keywords(table, "кредит")
        reserves = _table_row_by_keywords(table, "резерв")
        liquid_cbu = _table_row_by_keywords(table, "цбру")
        interbank = _table_row_by_keywords(table, "других банков")
        intro = "Горизонтальный анализ активов показывает, какие части баланса реально изменились за период, а какие только сохранили прежний вес."
        if total_row:
            intro = (
                f"За анализируемый период совокупные активы изменились на "
                f"{_format_bln_sum_from_thousand(total_change, language)} ({total_pct}) и составили "
                f"{_format_bln_sum_from_thousand(total_current, language)}. Это главный масштаб изменения баланса, от которого зависит тон всего дальнейшего анализа."
            )
        main = "Наиболее заметные движения нужно читать не по количеству строк, а по абсолютному влиянию на баланс."
        if strongest_decline:
            main += f" Самое сильное сокращение: «{strongest_decline[1]}» ({strongest_decline[2]})."
        if strongest_growth:
            main += f" Самый сильный рост: «{strongest_growth[1]}» ({strongest_growth[2]})."
        loan_bits = []
        if loans:
            loan_bits.append(f"кредитный портфель: {_table_label(loans)} изменился на {loans[3]} ({loans[4] if len(loans) > 4 else '—'})")
        if reserves:
            loan_bits.append(f"резервы: {_table_label(reserves)} изменились на {reserves[3]} ({reserves[4] if len(reserves) > 4 else '—'})")
        if investment:
            loan_bits.append(f"инвестиции: {_table_label(investment)} изменились на {investment[3]} ({investment[4] if len(investment) > 4 else '—'})")
        detail = "Для пользователя важен практический вывод: изменение активов показывает, где банк зарабатывает будущий доход и где появляется риск."
        if loan_bits:
            detail += " По ключевым строкам видно: " + "; ".join(loan_bits) + "."
        liquidity = "Ликвидность смотрим отдельно: если строки денег, ЦБРУ или межбанковских размещений падают, банк мог использовать быстрые активы для покрытия оттока ресурсов; если они растут, запас манёвра становится выше."
        if liquid_cbu or interbank:
            pieces = []
            if liquid_cbu:
                pieces.append(f"ЦБРУ: {liquid_cbu[3]} ({liquid_cbu[4] if len(liquid_cbu) > 4 else '—'})")
            if interbank:
                pieces.append(f"другие банки: {interbank[3]} ({interbank[4] if len(interbank) > 4 else '—'})")
            liquidity += " В этой таблице ключевые сигналы: " + "; ".join(pieces) + "."
        return [block(intro), block(main), block(detail), block(liquidity)]

    if role == "liabilities_horizontal":
        deposits_demand = _table_row_by_keywords(table, "депозит", "востреб")
        deposits_term = _table_row_by_keywords(table, "сроч")
        debt = _table_row_by_keywords(table, "кредит", "оплат")
        equity = _table_row_by_keywords(table, "собственного капитала")
        intro = "Горизонтальный анализ пассивов показывает, какими деньгами профинансирован баланс: депозитами клиентов, заёмными средствами или собственным капиталом."
        if total_row:
            intro += f" Совокупная строка изменилась на {total_row[3]} ({total_row[4] if len(total_row) > 4 else '—'})."
        funding = "Главный вопрос здесь — устойчивость ресурсной базы."
        moves = []
        for row in (deposits_demand, deposits_term, debt, equity):
            if row:
                moves.append(f"{_table_label(row)}: {row[3]} ({row[4] if len(row) > 4 else '—'})")
        if moves:
            funding += " Ключевые движения: " + "; ".join(moves) + "."
        risk = "Если депозиты сокращаются, а заёмные средства растут, банк сильнее зависит от оптового фондирования и условий рефинансирования. Если капитал снижается, запас прочности хуже даже при сохранении прибыли."
        verdict = "Эта таблица напрямую влияет на итоговую оценку ликвидности и долговой нагрузки: стабильные депозиты и капитал улучшают вывод, отток депозитов и рост дорогого фондирования делают вывод осторожнее."
        return [block(intro), block(funding), block(risk), block(verdict)]

    if role == "assets_vertical":
        largest_ranked = _rank_report_rows(table, 2, reverse=True)
        largest = (largest_ranked[0][1], largest_ranked[0][2]) if largest_ranked else None
        intro = "Вертикальный анализ активов показывает структуру баланса: не сколько банк вырос или снизился, а из чего он состоит."
        if largest:
            intro += f" Крупнейшая доля в текущем периоде — «{largest[0]}» ({largest[1]})."
        loans = _table_row_by_keywords(table, "кредит")
        liquid = _table_row_by_keywords(table, "цбру") or _table_row_by_keywords(table, "касс")
        securities = _table_row_by_keywords(table, "инвест")
        detail = "Для анализа это важнее простой динамики: большая доля кредитов означает зависимость от качества портфеля, большая доля ликвидных активов — запас безопасности, большая доля ценных бумаг — чувствительность к ставкам и переоценке."
        facts = []
        for row in (loans, liquid, securities):
            if row and len(row) > 4:
                facts.append(f"{_table_label(row)}: {row[2]} сейчас против {row[4]} ранее")
        if facts:
            detail += " По структуре видно: " + "; ".join(facts) + "."
        return [block(intro), block(detail)]

    if role == "liabilities_vertical":
        largest_ranked = _rank_report_rows(table, 2, reverse=True)
        largest = (largest_ranked[0][1], largest_ranked[0][2]) if largest_ranked else None
        intro = "Вертикальный анализ пассивов показывает модель фондирования банка: какую долю занимают депозиты, долг и собственный капитал."
        if largest:
            intro += f" Крупнейшая доля в текущем периоде — «{largest[0]}» ({largest[1]})."
        capital = _table_row_by_keywords(table, "собственного капитала")
        liabilities = _table_row_by_keywords(table, "обязательств")
        detail = "Для пользователя это отвечает на простой вопрос: баланс держится на устойчивой клиентской базе и капитале или на более чувствительных заёмных источниках."
        facts = []
        for row in (liabilities, capital):
            if row and len(row) > 4:
                facts.append(f"{_table_label(row)}: {row[2]} сейчас против {row[4]} ранее")
        if facts:
            detail += " Ключевые доли: " + "; ".join(facts) + "."
        return [block(intro), block(detail)]

    if role == "income_statement":
        interest_income = _table_row_by_keywords(table, "итого процентных доход")
        interest_expense = _table_row_by_keywords(table, "итого процентных расход")
        non_interest_income = _table_row_by_keywords(table, "итого беспроцентных доход")
        profit = _table_row_by_keywords(table, "чистая прибыль")
        provisions = _table_row_by_keywords(table, "убыт", "кредит") or _table_row_by_keywords(table, "резерв")
        intro = "Отчёт о финансовых результатах показывает не только размер прибыли, но и качество её источников: процентная маржа, комиссии, валютные операции, резервы и операционные расходы."
        facts = []
        for row in (interest_income, non_interest_income, interest_expense, provisions, profit):
            if row:
                facts.append(f"{_table_label(row)} — {row[1]}")
        if facts:
            intro += " Ключевые суммы: " + "; ".join(facts) + "."
        quality = "Хороший результат считается устойчивым, когда процентные доходы покрывают стоимость фондирования, резервы не съедают маржу, а прибыль не держится только на разовых или плохо раскрытых строках."
        if interest_expense and interest_income:
            expense_ratio = _table_number(interest_expense, 2)
            if expense_ratio is not None:
                quality += f" В этой таблице процентные расходы составляют {interest_expense[2]} от процентных доходов, поэтому маржу нужно оценивать вместе с резервами."
        verdict = "Для итогового вывода это главный раздел по качеству прибыли: рост доходов сам по себе не достаточен, если одновременно растут резервы, стоимость фондирования или операционные расходы."
        return [block(intro), block(quality), block(verdict)]

    if role == "ratio_summary":
        weak_rows = []
        strong_rows = []
        for row in rows:
            text = " ".join(str(cell) for cell in row).lower()
            if "⚠" in text or "высок" in text and any(token in text for token in ("риск", "ухуд", "нагруз")):
                weak_rows.append(row)
            elif "✓" in text or "хорош" in text or "норм" in text:
                strong_rows.append(row)
        intro = "Коэффициентный анализ переводит таблицы в набор быстрых сигналов: ликвидность, рентабельность, качество активов, капитал и эффективность."
        if weak_rows:
            intro += " Сначала стоит смотреть слабые места: " + "; ".join(_table_label(row) for row in weak_rows[:3]) + "."
        balance = "Сводный вывод строится не по одному коэффициенту, а по сочетанию сигналов. Высокая прибыльность улучшает картину только тогда, когда ликвидность, резервы и капитал не дают встречных красных флагов."
        if strong_rows:
            balance += " Поддерживающие показатели: " + "; ".join(_table_label(row) for row in strong_rows[:3]) + "."
        return [block(intro), block(balance)]

    return None


def _table_explanation_blocks(table: dict | None, role: str, language: str) -> list[dict]:
    if not table:
        return []
    html_style_blocks = _html_style_table_explanation_blocks(table, role, language)
    if html_style_blocks is not None:
        return html_style_blocks
    practical_blocks = _practical_table_explanation_blocks(table, role, language)
    if practical_blocks is not None:
        return practical_blocks
    lang = _normalize_language(language)
    row_count = len(table.get("rows") or [])
    total_row = _total_report_row(table)
    total_phrase = _format_change_phrase(total_row)
    strongest_growth = next((item for item in _rank_report_rows(table, 3, reverse=True) if item[0] > 0), None)
    strongest_decline = next((item for item in _rank_report_rows(table, 3, reverse=False) if item[0] < 0), None)
    biggest_change = _largest_abs_table_row(table, 3)
    largest_share = _largest_abs_table_row(table, 2)
    largest_income_share = _largest_abs_table_row(table, 5)

    def block(text: str) -> dict:
        return {"type": "paragraph", "text": text}

    if role == "assets_horizontal":
        if lang == "en":
            opening = f"The horizontal asset table shows the direction and scale of change across {row_count} asset lines."
            if total_phrase:
                opening += f" The headline movement is {total_phrase}, so the first analytical question is whether the balance sheet is expanding normally or shrinking/reallocating capital."
            outlier = ""
            if strongest_decline:
                outlier += f" The largest negative contribution is {strongest_decline[1]} ({strongest_decline[2]})."
            if strongest_growth and strongest_growth[0] > 0:
                outlier += f" The main positive offset is {strongest_growth[1]} ({strongest_growth[2]})."
            return [
                block(opening),
                block((outlier or "The individual line movements show where the balance sheet changed most materially.") + " This matters because asset contraction in liquid reserves, loans or securities has different meanings for future income and liquidity."),
                block("For the final analysis, this table affects the risk tone: falling liquid assets can weaken the safety buffer, falling loans can reduce future interest income, and rapid growth in one asset category can signal concentration or risk accumulation."),
            ]
        if lang == "uz":
            opening = f"Gorizontal aktiv jadvali {row_count} ta aktiv satri bo'yicha o'zgarish yo'nalishi va hajmini ko'rsatadi."
            if total_phrase:
                opening += f" Asosiy harakat: {total_phrase}; shuning uchun balans oddiy o'syaptimi yoki kapital qayta taqsimlanyaptimi, degan savol muhim."
            outlier = ""
            if strongest_decline:
                outlier += f" Eng katta salbiy hissa: {strongest_decline[1]} ({strongest_decline[2]})."
            if strongest_growth and strongest_growth[0] > 0:
                outlier += f" Asosiy ijobiy qarshi harakat: {strongest_growth[1]} ({strongest_growth[2]})."
            return [
                block(opening),
                block((outlier or "Alohida satrlar balans qayerda eng ko'p o'zgarganini ko'rsatadi.") + " Bu muhim, chunki likvid zaxiralar, kreditlar yoki qimmatli qog'ozlardagi o'zgarish kelajakdagi daromad va likvidlikka turlicha ta'sir qiladi."),
                block("Yakuniy tahlilda bu jadval risk tonini o'zgartiradi: likvid aktivlar kamayishi xavfsizlik yostig'ini susaytiradi, kreditlar kamayishi foiz daromadini pasaytiradi, bitta aktiv guruhi tez o'sishi esa konsentratsiya riskini kuchaytiradi."),
            ]
        opening = f"Горизонтальная таблица активов показывает направление и масштаб изменений по {row_count} строкам актива."
        if total_phrase:
            opening += f" Ключевое движение: {total_phrase}; поэтому главный вопрос анализа — баланс реально растёт или происходит сжатие и перераспределение активов."
        outlier = ""
        if strongest_decline:
            outlier += f" Наибольший отрицательный вклад даёт статья «{strongest_decline[1]}» ({strongest_decline[2]})."
        if strongest_growth and strongest_growth[0] > 0:
            outlier += f" Главный положительный противовес — «{strongest_growth[1]}» ({strongest_growth[2]})."
        return [
            block(opening),
            block((outlier or "Движения отдельных строк показывают, где баланс изменился наиболее существенно.") + " Это важно, потому что снижение ликвидных резервов, кредитов или ценных бумаг по-разному влияет на будущий доход и запас ликвидности."),
            block("В итоговой оценке эта таблица меняет тон риска: падение ликвидных активов ослабляет защитный буфер, сокращение кредитов может давить на будущие процентные доходы, а резкий рост одной группы активов указывает на возможную концентрацию риска."),
        ]

    if role == "liabilities_horizontal":
        if lang == "en":
            opening = f"The liabilities and equity table explains how the asset base is funded across {row_count} lines."
            if total_phrase:
                opening += f" The aggregate movement is {total_phrase}, which shows whether the bank is losing resources, replacing deposits with debt, or strengthening its own capital."
            pressure = ""
            if strongest_decline:
                pressure += f" The largest funding reduction is {strongest_decline[1]} ({strongest_decline[2]})."
            if strongest_growth and strongest_growth[0] > 0:
                pressure += f" The largest compensating increase is {strongest_growth[1]} ({strongest_growth[2]})."
            return [
                block(opening),
                block((pressure or "The composition of funding determines how stable the balance sheet is.") + " Deposit outflows are usually more important for liquidity risk than accounting movements inside equity, while rising borrowings can increase dependence on wholesale or regulated funding."),
                block("For the final verdict, this table affects leverage and liquidity assessment: stable capital and deposits support resilience; shrinking deposits, rising short-term debt or falling retained earnings make the analysis more cautious."),
            ]
        if lang == "uz":
            opening = f"Majburiyatlar va kapital jadvali {row_count} satr bo'yicha aktivlar qaysi manbalar bilan moliyalashtirilganini ko'rsatadi."
            if total_phrase:
                opening += f" Umumiy harakat: {total_phrase}; bu bank resurs yo'qotyaptimi, depozitlarni qarz bilan almashtiryaptimi yoki kapitalni kuchaytiryaptimi degan savolga javob beradi."
            pressure = ""
            if strongest_decline:
                pressure += f" Eng katta funding kamayishi: {strongest_decline[1]} ({strongest_decline[2]})."
            if strongest_growth and strongest_growth[0] > 0:
                pressure += f" Eng katta kompensatsion o'sish: {strongest_growth[1]} ({strongest_growth[2]})."
            return [
                block(opening),
                block((pressure or "Funding tarkibi balans barqarorligini belgilaydi.") + " Depozit chiqib ketishi likvidlik riski uchun odatda kapital ichidagi buxgalteriya harakatlaridan muhimroq, qarzlar o'sishi esa ulgurji yoki regulyator fundingiga bog'liqlikni oshiradi."),
                block("Yakuniy xulosada bu jadval leverage va likvidlik bahosiga ta'sir qiladi: barqaror kapital va depozitlar kuch beradi; depozitlar kamayishi, qisqa muddatli qarz o'sishi yoki taqsimlanmagan foyda pasayishi tahlilni ehtiyotkor qiladi."),
            ]
        opening = f"Таблица обязательств и капитала объясняет, за счёт каких источников профинансирована база активов по {row_count} строкам."
        if total_phrase:
            opening += f" Совокупное движение: {total_phrase}; оно показывает, теряет ли банк ресурсную базу, замещает ли депозиты долгом или усиливает собственный капитал."
        pressure = ""
        if strongest_decline:
            pressure += f" Самое крупное сокращение фондирования — «{strongest_decline[1]}» ({strongest_decline[2]})."
        if strongest_growth and strongest_growth[0] > 0:
            pressure += f" Крупнейший компенсирующий рост — «{strongest_growth[1]}» ({strongest_growth[2]})."
        return [
            block(opening),
            block((pressure or "Структура фондирования определяет устойчивость баланса.") + " Отток депозитов обычно важнее для риска ликвидности, чем бухгалтерские движения внутри капитала, а рост заёмных ресурсов повышает зависимость от оптового или регуляторного фондирования."),
            block("Для итогового вердикта эта таблица влияет на оценку долговой нагрузки и ликвидности: стабильный капитал и депозиты поддерживают устойчивость; сокращение депозитов, рост краткосрочного долга или снижение нераспределённой прибыли делают вывод более осторожным."),
        ]

    if role == "assets_vertical":
        if lang == "en":
            detail = f" The largest visible weight is {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Vertical asset analysis is needed because it shows concentration, not just growth.{detail} The same asset change has different meaning when it is a small line item versus a dominant balance-sheet block."),
                block("If loans dominate, the analysis becomes more sensitive to credit quality and reserve dynamics. If liquid assets dominate, liquidity is stronger but profitability can be lower; if securities dominate, valuation and interest-rate risk become more important."),
            ]
        if lang == "uz":
            detail = f" Eng katta ko'rinadigan ulush: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Vertikal aktiv tahlili faqat o'sishni emas, konsentratsiyani ko'rsatgani uchun kerak.{detail} Bir xil o'zgarish kichik satrda va dominant balans blokida turlicha ma'no beradi."),
                block("Kreditlar ustun bo'lsa, tahlil kredit sifati va rezervlar dinamikasiga sezgir bo'ladi. Likvid aktivlar ustun bo'lsa, likvidlik kuchliroq, lekin rentabellik pastroq bo'lishi mumkin; qimmatli qog'ozlar ustun bo'lsa, baholash va foiz stavkasi riski muhimlashadi."),
            ]
        detail = f" Самая крупная видимая доля: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
        return [
            block(f"Вертикальный анализ активов нужен, потому что показывает не только рост, но и концентрацию.{detail} Одно и то же изменение имеет разный смысл, если оно находится в малой строке или в доминирующем блоке баланса."),
            block("Если доминируют кредиты, итоговая оценка становится чувствительнее к качеству портфеля и резервам. Если велика доля ликвидных активов, запас ликвидности выше, но доходность может быть ниже; если велика доля ценных бумаг, важнее становятся переоценка и процентный риск."),
        ]

    if role == "liabilities_vertical":
        if lang == "en":
            detail = f" The largest visible weight is {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Vertical liabilities/equity analysis shows the funding model rather than only the change in amounts.{detail} A bank with the same asset size can have very different risk depending on whether it is funded by retail deposits, wholesale debt or own capital."),
                block("This section affects the final solvency view: a high capital share creates a buffer, a high deposit share can be stable if deposits are sticky, and a rising debt or repo share increases sensitivity to refinancing conditions."),
            ]
        if lang == "uz":
            detail = f" Eng katta ko'rinadigan ulush: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
            return [
                block(f"Passiv va kapitalning vertikal tahlili faqat summalar o'zgarishini emas, funding modelini ko'rsatadi.{detail} Bir xil aktiv hajmiga ega bank retail depozit, ulgurji qarz yoki kapital bilan moliyalashtirilganiga qarab turlicha riskka ega bo'ladi."),
                block("Bu bo'lim yakuniy to'lov qobiliyati bahosiga ta'sir qiladi: kapital ulushi yuqori bo'lsa bufer kuchli, depozit ulushi barqaror bo'lsa funding sifatli, qarz yoki REPO ulushi oshsa qayta moliyalashtirish sharoitlariga sezgirlik kuchayadi."),
            ]
        detail = f" Самая крупная видимая доля: {largest_share[0]} ({largest_share[1]})." if largest_share else ""
        return [
            block(f"Вертикальный анализ пассивов и капитала показывает не только изменение сумм, но и модель фондирования.{detail} Банк с одинаковым размером активов может иметь разный риск в зависимости от того, профинансирован он розничными депозитами, оптовым долгом или собственным капиталом."),
            block("Этот раздел влияет на итоговую оценку платёжеспособности: высокая доля капитала создаёт буфер, высокая доля устойчивых депозитов поддерживает качество фондирования, а рост долга или РЕПО повышает чувствительность к условиям рефинансирования."),
        ]

    if role == "income_statement":
        if lang == "en":
            detail = f" The largest absolute profit-and-loss movement is {biggest_change[0]}: {biggest_change[1]}." if biggest_change else ""
            share = f" The largest visible weight in the current-period structure is {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
            return [
                block(f"The income statement table links growth to profit quality, not just headline revenue.{detail}{share} It shows whether the bank earns from core interest business, commissions, trading/FX operations or one-off lines."),
                block("This matters because revenue growth is not automatically good: if funding costs, provisions or operating expenses grow faster than income, the final analysis becomes more cautious even when the top line looks strong."),
                block("For the final verdict, recurring interest margin and controlled expenses improve quality; dependence on unclear 'other' income, high provisions or fast cost growth reduces confidence in sustainability."),
            ]
        if lang == "uz":
            detail = f" Eng katta foyda-zarar o'zgarishi: {biggest_change[0]}: {biggest_change[1]}." if biggest_change else ""
            share = f" Joriy davr tarkibidagi eng katta ko'rinadigan ulush: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
            return [
                block(f"Moliyaviy natijalar jadvali o'sishni faqat tushum bilan emas, foyda sifati bilan bog'laydi.{detail}{share} U bank asosiy foiz biznesidanmi, komissiyalardanmi, savdo/valyuta operatsiyalaridanmi yoki bir martalik satrlardanmi daromad olayotganini ko'rsatadi."),
                block("Bu muhim, chunki tushum o'sishi avtomatik ravishda yaxshi signal emas: funding xarajatlari, rezervlar yoki operatsion xarajatlar daromaddan tezroq o'ssa, yuqori tushumga qaramay yakuniy baho ehtiyotkor bo'ladi."),
                block("Yakuniy xulosada takrorlanuvchi foiz marjasi va nazoratdagi xarajatlar sifatni oshiradi; noaniq 'boshqa' daromadlar, yuqori rezervlar yoki xarajatlarning tez o'sishi barqarorlikka ishonchni pasaytiradi."),
            ]
        detail = f" Самое крупное движение в отчёте о прибылях и убытках: {biggest_change[0]}: {biggest_change[1]}." if biggest_change else ""
        share = f" Самая крупная видимая доля в структуре текущего периода: {largest_income_share[0]} ({largest_income_share[1]})." if largest_income_share else ""
        return [
            block(f"Таблица финансовых результатов связывает рост бизнеса не только с выручкой, но и с качеством прибыли.{detail}{share} Она показывает, за счёт чего банк зарабатывает: базового процентного бизнеса, комиссий, торговых/валютных операций или разовых статей."),
            block("Это важно, потому что рост доходов сам по себе ещё не является хорошим сигналом: если стоимость фондирования, резервы или операционные расходы растут быстрее доходов, итоговая оценка становится осторожнее даже при сильной верхней строке."),
            block("Для финального вердикта устойчивую оценку поддерживают повторяемая процентная маржа и контролируемые расходы; зависимость от нерасшифрованных «прочих» доходов, высоких резервов или быстрого роста затрат снижает уверенность в устойчивости прибыли."),
        ]

    if role == "ratio_summary":
        if lang == "en":
            return [
                block(f"Ratio analysis turns the raw statements into comparable risk and quality signals across {row_count} metrics. Unlike absolute balance-sheet lines, these indicators show whether the business is efficient relative to its assets, capital and funding base."),
                block("For banks the table includes bank-specific ratios: LDR (loan-to-deposit), first-line liquidity, NIM, CIR, coverage ratio (loan-loss reserve / gross loans), reserve burden (provision expense / interest income), interest income coverage (interest income / interest expense), and non-interest income share. These ratios are computed from XLSX data where available and supplement the standard scoring metrics."),
                block("These figures affect the final verdict because they connect profitability, leverage, liquidity and operating efficiency in one scoring layer. Strong profitability can be offset by weak liquidity or aggressive leverage, while moderate growth can still be attractive if capital quality and coverage are strong."),
            ]
        if lang == "uz":
            return [
                block(f"Koeffitsiyentlar tahlili xom hisobotlarni {row_count} ta solishtiriladigan risk va sifat signaliga aylantiradi. Mutlaq balans satrlaridan farqli ravishda ular biznes aktivlar, kapital va funding bazasiga nisbatan qanchalik samarali ishlayotganini ko'rsatadi."),
                block("Banklar uchun jadvalga bank-spetsifik nisbatlar kiritilgan: LDR, birinchi qator likvidlik, NIM, CIR, qoplama koeffitsienti (zararlar uchun rezerv / brutto kreditlar), rezerv yuki (ta'minotlar / foiz daromadlari), foiz daromadlari qoplanishi (foiz daromadlari / foiz xarajatlari) va nofoiz daromadlar ulushi."),
                block("Bu ko'rsatkichlar yakuniy xulosaga ta'sir qiladi, chunki rentabellik, leverage, likvidlik va operatsion samaradorlikni bitta baholash qatlamida bog'laydi. Kuchli rentabellik zaif likvidlik yoki agressiv leverage bilan neytrallashishi mumkin; o'rtacha o'sish esa kapital sifati va qoplama kuchli bo'lsa jozibali qoladi."),
            ]
        return [
            block(f"Коэффициентный анализ превращает сырые отчёты в {row_count} сопоставимых сигналов риска и качества. В отличие от абсолютных строк баланса, эти показатели показывают, насколько эффективно бизнес работает относительно активов, капитала и ресурсной базы."),
            block("Для банков таблица включает специфические банковские коэффициенты: LDR (кредиты/депозиты), ликвидность 1-й линии, NIM, CIR, коэффициент покрытия (резерв на убытки / брутто-кредиты), нагрузку резервирования (резервы периода / процентные доходы), покрытие процентных расходов доходами и долю непроцентных доходов. Эти показатели вычисляются из данных XLSX там, где они доступны."),
            block("Эти показатели влияют на итоговый вердикт, потому что связывают прибыльность, долговую нагрузку, ликвидность и операционную эффективность в один слой оценки. Сильная рентабельность может быть нейтрализована слабой ликвидностью или агрессивным рычагом, а умеренный рост всё ещё может быть привлекательным при сильном капитале и хорошем покрытии рисков."),
        ]

    if role == "excel_source":
        if lang == "en":
            return [
                block("These appendix tables are included for auditability: they show the source XLSX rows behind the analytical tables. They should not be read as separate conclusions; they are the evidence layer that lets the reader trace where the numbers came from."),
                block("They affect the analysis indirectly: if an important line appears here but not in the analytical sections, it flags a need for manual review; if period columns look unusual, the conclusion should be treated with more caution."),
            ]
        if lang == "uz":
            return [
                block("Bu ilova jadvallari tekshirish uchun qo'shilgan: ular tahliliy jadvallar ortidagi XLSX manba satrlarini ko'rsatadi. Ularni alohida xulosa deb o'qimaslik kerak; ular raqamlar qayerdan kelganini kuzatish uchun dalil qatlamidir."),
                block("Ular tahlilga bilvosita ta'sir qiladi: muhim satr bu yerda bor, lekin tahliliy bo'limlarda yo'q bo'lsa, qo'lda tekshiruv kerak; davr ustunlari noodatiy ko'rinsa, xulosaga ehtiyotkorroq qarash kerak."),
            ]
        return [
            block("Таблицы приложения нужны для проверяемости: они показывают исходные строки XLSX, из которых собраны аналитические таблицы. Их не нужно читать как отдельные выводы; это доказательная база, позволяющая проследить происхождение чисел."),
            block("На анализ они влияют косвенно: если важная строка есть здесь, но не попала в аналитические разделы, это сигнал для ручной проверки; если колонки периодов выглядят нестандартно, итоговый вывод нужно читать осторожнее."),
        ]

    return []


def _table_with_explanation(table: dict | None, role: str, language: str) -> list[dict]:
    if not table:
        return []
    return [
        {"type": "table", **table},
        *_table_explanation_blocks(table, role, language),
    ]

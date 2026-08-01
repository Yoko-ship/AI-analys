"""The rule registry — ТЗ v1.3 §12.3, all sixty-four of them.

Six groups. Every rule has a code, a plain-language title, a severity and the
threshold key it reads. Thresholds live in configuration, never here, so
changing one does not need a deploy.

Severity is not decoration — §12.2 defines what each one DOES:

  blocking  the number is knowably wrong or impossible. It is not published:
            the interface shows a dash and the reason, and the run is failed.
  warning   the number is suspect but may be right. It is published with a
            «проверьте данные» badge beside it.
  info      a deviation inside normal bounds, recorded for observation only.

The policy behind that table: a blocking finding outranks any wish to show a
number. An empty cell with a reason is more honest than a wrong figure.
"""
from __future__ import annotations

from dataclasses import dataclass

BLOCKING = "blocking"
WARNING = "warning"
INFO = "info"

GROUPS: dict[str, str] = {
    "FIN": "парсинг и осмысленность отчётности",
    "MUL": "мультипликаторы",
    "MKT": "топы, падения и агрегаты вкладки «Рынок»",
    "CND": "свечи, история и графики",
    "CAT": "каталог и справочники",
    "XSC": "сверка между экранами",
    "BND": "облигационный контур",
    "SRC": "каталог отчётности и происхождение чисел",
}


@dataclass(frozen=True)
class Rule:
    code: str
    group: str
    title: str
    severity: str
    threshold: str | None = None      # dotted path into config/thresholds.json
    note: str | None = None           # what the ТЗ observed when it wrote the rule


ALL_RULES: tuple[Rule, ...] = (
    # -- FIN: does the statement parse into something that can be true? -------
    Rule("FIN-01", "FIN", "баланс сходится: активы = обязательства + капитал", BLOCKING,
         "audit.balance_tolerance_pct"),
    Rule("FIN-02", "FIN", "активы в отчётности и в коэффициентах совпадают", BLOCKING,
         "audit.balance_tolerance_pct", "UQEQ: 162 млрд против 143 млрд"),
    Rule("FIN-03", "FIN", "выручка за 6 месяцев не больше годовой с разумным запасом", BLOCKING,
         "financials.half_year_vs_annual_max", "UQEQ: 131x"),
    Rule("FIN-04", "FIN", "валовая прибыль не больше выручки", BLOCKING,
         "financials.gross_profit_vs_revenue_max"),
    Rule("FIN-05", "FIN", "чистая прибыль не больше валовой прибыли", WARNING,
         "audit.net_vs_gross_tolerance_pct", "допуск на прочие доходы"),
    Rule("FIN-06", "FIN", "масштаб единиц: порядок величины не скачет между периодами", BLOCKING,
         "audit.unit_scale_max_ratio",
         "самый частый и самый незаметный класс ошибок парсинга: тысячи сумов вместо сумов"),
    Rule("FIN-07", "FIN", "накопительность: 6 мес >= 3 мес, 9 мес >= 6 мес", BLOCKING),
    Rule("FIN-08", "FIN", "период отчётности не старше 18 месяцев", WARNING,
         "audit.stale_report_months", "UZNG, UZNGP: 2023"),
    Rule("FIN-09", "FIN", "годовая отчётность существует хотя бы за один год", WARNING,
         None, "9 эмитентов без годовой"),
    Rule("FIN-10", "FIN", "выручка не равна нулю при наличии капитализации", WARNING),
    Rule("FIN-11", "FIN", "капитал строго больше нуля", BLOCKING),
    Rule("FIN-12", "FIN", "период отчётности и период коэффициентов совпадают", BLOCKING,
         None, "102 из 107 бумаг расходились"),
    Rule("FIN-13", "FIN", "заполненность обязательных полей", WARNING,
         "audit.required_field_coverage_min", "current_ratio: 57 из 107"),
    Rule("FIN-14", "FIN", "один тикер — один набор за период, дублей нет", BLOCKING),
    Rule("FIN-15", "FIN", "знаки: расходы отрицательные, выручка положительная", BLOCKING),

    # -- MUL: does the published multiple survive being recomputed? -----------
    Rule("MUL-01", "MUL", "независимый пересчёт P/E совпадает с опубликованным", BLOCKING,
         "audit.recompute_tolerance_pct"),
    Rule("MUL-02", "MUL", "независимый пересчёт P/B совпадает с опубликованным", BLOCKING,
         "audit.recompute_tolerance_pct"),
    Rule("MUL-03", "MUL", "капитализация = цена × количество бумаг", BLOCKING,
         "audit.market_cap_tolerance_pct"),
    Rule("MUL-04", "MUL", "знаменатель P/E — прибыль ЭМИТЕНТА, не класса акций", BLOCKING,
         None, "KFSK 203,56 против KFSKP 0,19 при одной прибыли"),
    Rule("MUL-05", "MUL", "капитализация класса согласована с его ценой и числом акций", BLOCKING,
         "multiples.cap_vs_price_shares_max",
         "ALKB 1,05 против ALKBP 1042,5 — ровно тысячекратно"),
    Rule("MUL-06", "MUL", "согласованность: P/B примерно равно P/E × ROE", WARNING,
         "audit.pb_identity_tolerance_pct"),
    Rule("MUL-07", "MUL", "P/E в допустимом диапазоне", WARNING, "multiples.pe_range"),
    Rule("MUL-08", "MUL", "P/B в допустимом диапазоне", WARNING, "multiples.pb_range",
         "29 из 96 вне диапазона"),
    Rule("MUL-09", "MUL", "ROE по модулю в разумных пределах", BLOCKING, "multiples.roe_abs_max",
         "UTGAP: 10 715 %"),
    Rule("MUL-10", "MUL", "при убытке P/E не число, а статус", BLOCKING, None, "11 эмитентов"),
    Rule("MUL-11", "MUL", "год отчётности в знаменателе указан и не старше порога", WARNING,
         "audit.stale_report_months"),
    Rule("MUL-12", "MUL", "доля бумаг с непубликуемыми мультипликаторами не растёт", WARNING,
         "audit.suppressed_share_max"),

    # -- MKT: the board, its tops and its totals ------------------------------
    Rule("MKT-01", "MKT", "независимый пересчёт дневного изменения по каждой бумаге", BLOCKING,
         "audit.change_tolerance_pp"),
    Rule("MKT-02", "MKT", "в топ роста и падения не попадают бумаги с единичными сделками",
         BLOCKING, "market_map.min_trades_confident",
         "UQEQ +20 % на одной сделке в одну бумагу за 30 720 сум"),
    Rule("MKT-03", "MKT", "изменение не равно минус 100 % из-за отсутствия цены", BLOCKING,
         None, "13 бумаг"),
    Rule("MKT-04", "MKT", "нулевое изменение отличается от отсутствия сделок", BLOCKING,
         None, "10 бумаг"),
    Rule("MKT-05", "MKT", "у бумаг с ценой ниже 0,01 сума изменение не обнуляется округлением",
         BLOCKING, None, "KASU: 232 сделки, 0 %"),
    Rule("MKT-06", "MKT", "в топах нет двух классов одной компании подряд без пометки", WARNING),
    Rule("MKT-07", "MKT", "сумма счётчиков равна числу бумаг", BLOCKING),
    Rule("MKT-08", "MKT", "оборот по таблице равен сумме оборотов из итогов дня", BLOCKING,
         "audit.turnover_tolerance_pct"),
    Rule("MKT-09", "MKT", "капитализация рынка = сумма капитализаций активных бумаг, "
                          "облигации исключены", BLOCKING, "audit.market_cap_tolerance_pct",
         "9 облигаций с капитализацией"),
    Rule("MKT-10", "MKT", "неторгуемые листинги в капитализации помечены отдельно", WARNING,
         None, "23 листинга на 29 088 млрд"),
    Rule("MKT-11", "MKT", "сектор бумаги одинаков во всех справочниках", BLOCKING,
         None, "UTGA, UTGAP, UZNF"),
    Rule("MKT-12", "MKT", "сектор считается взвешенно по обороту и только по плиткам "
                          "со статусом ok", BLOCKING),
    Rule("MKT-13", "MKT", "экспорт CSV число в число совпадает с экраном", BLOCKING),
    Rule("MKT-14", "MKT", "сортировка топов устойчива", INFO),

    # -- CND: candles, history and the charts ---------------------------------
    Rule("CND-01", "CND", "OHLC корректен: low <= open, close <= high", BLOCKING),
    Rule("CND-02", "CND", "доля свечей без внутридневного диапазона", BLOCKING,
         "quality.flat_share_max", "UQEQ 12 мес: 82 %"),
    Rule("CND-03", "CND", "покрытие торговых дней", BLOCKING, "quality.coverage_min"),
    Rule("CND-04", "CND", "медианный разрыв между точками", WARNING, "audit.median_gap_warn_days"),
    Rule("CND-05", "CND", "максимальный разрыв в истории", INFO, None, "UQEQ 3г: 59 дней"),
    Rule("CND-06", "CND", "MA20 покрывает не больше 45 календарных дней", BLOCKING,
         "audit.ma20_max_calendar_days", "медиана 133 дня у 81 из 84 бумаг"),
    Rule("CND-07", "CND", "MA в режиме свечей и в режиме линии считается по одному правилу",
         BLOCKING, "audit.ma_mode_tolerance_days", "расхождение > 7 дней у 81 из 84"),
    Rule("CND-08", "CND", "агрегация периода выбрана по календарю, а не по числу точек", BLOCKING),
    Rule("CND-09", "CND", "скачок цены при единичной сделке помечается", WARNING,
         "audit.spike_change_pct"),
    Rule("CND-10", "CND", "разрывы не заполнены выдуманными значениями", BLOCKING),
    Rule("CND-11", "CND", "тикер, а не ISIN, используется как ключ истории", BLOCKING),
    Rule("CND-12", "CND", "классификация качества устойчива: tier не мигает между прогонами",
         WARNING),

    # -- CAT: one universe ----------------------------------------------------
    Rule("CAT-01", "CAT", "все экраны используют одну вселенную инструментов", BLOCKING,
         None, "82 / 85 / 96 / 107 / 108"),
    Rule("CAT-02", "CAT", "у каждого тикера есть эмитент и сектор", BLOCKING),
    Rule("CAT-03", "CAT", "ISIN уникален, тикер уникален", BLOCKING),
    Rule("CAT-04", "CAT", "бумага из итогов дня присутствует в каталоге", BLOCKING,
         None, "15 бумаг вне справочника"),
    Rule("CAT-05", "CAT", "классы акций связаны с одним эмитентом", BLOCKING,
         None, "привилегированная без обыкновенной"),
    Rule("CAT-06", "CAT", "количество бумаг в выпуске заполнено", WARNING),

    # -- XSC: the screens must agree with each other --------------------------
    Rule("XSC-01", "XSC", "последняя цена одинакова на карточке, в таблице, на карте и в CSV",
         BLOCKING),
    Rule("XSC-02", "XSC", "дневное изменение одинаково на карте и в таблице", BLOCKING),
    Rule("XSC-03", "XSC", "абсолютные метрики не зависят от выбранного периода графика", BLOCKING,
         None, "YTD менялся у 83 из 84 бумаг — главный инвариант задания"),
    Rule("XSC-04", "XSC", "капитализация в карточке равна капитализации в таблице", BLOCKING),
    Rule("XSC-05", "XSC", "число инструментов в шапке равно числу строк таблицы", BLOCKING),

    # -- BND: the bond contour (Дополнение 1 §А.7) ---------------------------
    Rule("BND-01", "BND", "тип инструмента bond, класс не ordinary", BLOCKING,
         None, "сейчас у облигаций стоит ordinary — из-за этого они попадают "
               "в акционерные ветки кода"),
    Rule("BND-02", "BND", "акционные мультипликаторы отсутствуют", BLOCKING,
         None, "наличие P/E или P/B у долгового инструмента"),
    Rule("BND-03", "BND", "стоимость выпуска не входит в капитализацию акций", BLOCKING,
         None, "798 млрд по 9 выпускам"),
    Rule("BND-04", "BND", "номинал заполнен", WARNING, None, "нет — no_bond_reference"),
    Rule("BND-05", "BND", "дата погашения в будущем или выпуск помечен погашенным", BLOCKING),
    Rule("BND-06", "BND", "цена в разумном коридоре от номинала", WARNING,
         "bonds.price_pct_range"),
    Rule("BND-07", "BND", "купонные периоды не пересекаются и покрывают срок без разрывов",
         BLOCKING),
    Rule("BND-08", "BND", "доходность к погашению сошлась", WARNING, None, "not_converged"),
    Rule("BND-09", "BND", "НКД не превышает купон за период", BLOCKING),
    Rule("BND-10", "BND", "независимый пересчёт YTM совпадает", BLOCKING,
         "audit.ytm_tolerance"),
    Rule("BND-11", "BND", "цена есть при наличии сделок", BLOCKING, None, "ACMT1B2, CTFB3"),
    Rule("BND-12", "BND", "базис расчёта дней указан в ответе", BLOCKING),

    # -- SRC: the reporting catalog as a provenance layer (Дополнение 1 §Б.8) -
    Rule("SRC-01", "SRC", "счётчик в шапке равен длине списка", BLOCKING,
         None, "85 против 73"),
    Rule("SRC-02", "SRC", "сумма отчётов по эмитентам равна общей", BLOCKING,
         None, "2021 против 1659"),
    Rule("SRC-03", "SRC", "у каждого опубликованного числа есть ссылка на отчёт", BLOCKING,
         None, "report_id пуст"),
    Rule("SRC-04", "SRC", "отчёт в состоянии rejected не используется в публикуемых числах",
         BLOCKING),
    Rule("SRC-05", "SRC", "возраст каталога не больше суток", WARNING,
         "catalog.staleness_warn_hours", "сейчас 10 дней"),
    Rule("SRC-06", "SRC", "у эмитента с бумагами есть хотя бы один синхронизированный отчёт",
         WARNING, None, "7 строк ни разу не синхронизированы"),
    Rule("SRC-07", "SRC", "серии одного эмитента показывают его отчётность, а не ноль",
         BLOCKING, None, "5 серий с нулём"),
    Rule("SRC-08", "SRC", "очередь неразобранных не растёт между прогонами", WARNING),
    Rule("SRC-09", "SRC", "ссылки на первоисточник отвечают кодом 200", WARNING),
    Rule("SRC-10", "SRC", "масштаб единиц в разобранных числах совпадает с публикуемым",
         BLOCKING),
)

RULES_BY_CODE: dict[str, Rule] = {r.code: r for r in ALL_RULES}


def rules_in_group(group: str) -> tuple[Rule, ...]:
    return tuple(r for r in ALL_RULES if r.group == group)

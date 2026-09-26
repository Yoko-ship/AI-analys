"""Rank company metrics and prepare comparison tables and charts."""

from __future__ import annotations
from reporting.numbers import _safe_float


COMPARISON_FIELDS = [
    {"key": "score", "label": "Общий score", "unit": "/100", "better": "higher"},
    {"key": "grade", "label": "Класс", "unit": "", "better": "higher"},
    {"key": "latest_year", "label": "Год", "unit": "", "better": "neutral"},
    {"key": "revenue", "label": "Выручка", "unit": "UZS млн", "better": "higher"},
    {"key": "revenue_growth_pct", "label": "Рост выручки", "unit": "%", "better": "higher"},
    {"key": "net_income", "label": "Чистая прибыль", "unit": "UZS млн", "better": "higher"},
    {"key": "net_income_growth_pct", "label": "Рост прибыли", "unit": "%", "better": "higher"},
    {"key": "net_profit_margin_pct", "label": "Чистая маржа", "unit": "%", "better": "higher"},
    {"key": "gross_profit_margin_pct", "label": "Валовая маржа", "unit": "%", "better": "higher"},
    {"key": "roe_pct", "label": "ROE", "unit": "%", "better": "higher"},
    {"key": "roa_pct", "label": "ROA", "unit": "%", "better": "higher"},
    {"key": "debt_ratio_pct", "label": "Долг/активы", "unit": "%", "better": "lower"},
    {"key": "debt_to_equity_ratio", "label": "Debt/Equity", "unit": "x", "better": "lower"},
    {"key": "current_ratio", "label": "Current ratio", "unit": "x", "better": "higher"},
    {"key": "quick_ratio", "label": "Quick ratio", "unit": "x", "better": "higher"},
    {"key": "balance_quality_score", "label": "Качество баланса", "unit": "/100", "better": "higher"},
    {"key": "piotroski_score", "label": "Piotroski", "unit": "/9", "better": "higher"},
    {"key": "altman_score", "label": "Altman Z", "unit": "", "better": "higher"},
    {"key": "latest_price", "label": "Цена", "unit": "UZS", "better": "neutral"},
    {"key": "day_change_percent", "label": "За день", "unit": "%", "better": "neutral"},
    {"key": "period_change_percent", "label": "За период", "unit": "%", "better": "neutral"},
    {"key": "avg_daily_trading_value", "label": "Ср. оборот", "unit": "UZS", "better": "higher"},
    {"key": "total_trading_value", "label": "Всего оборот", "unit": "UZS", "better": "higher"},
    {"key": "dividend_count", "label": "Дивиденды", "unit": "шт.", "better": "higher"},
    {"key": "report_document_count", "label": "Отчеты", "unit": "шт.", "better": "higher"},
    {"key": "pdf_report_count", "label": "PDF отчетов", "unit": "шт.", "better": "higher"},
    {"key": "excel_report_count", "label": "Excel отчетов", "unit": "шт.", "better": "higher"},
]


COMPARISON_CATEGORY_METRICS = {
    "overall": ["score", "piotroski_score", "altman_score"],
    "profitability": ["net_profit_margin_pct", "roe_pct", "roa_pct"],
    "growth": ["revenue_growth_pct", "net_income_growth_pct"],
    "balance": ["current_ratio", "debt_ratio_pct", "debt_to_equity_ratio", "altman_score"],
    "market": ["avg_daily_trading_value", "period_change_percent"],
    "reporting": ["report_document_count", "dividend_count"],
}


COMPARISON_TABLES = {
    "overview": ["score", "grade", "latest_year", "ticker"],
    "profitability": ["revenue", "net_income", "net_profit_margin_pct", "roe_pct", "roa_pct"],
    "growth": ["revenue_growth_pct", "net_income_growth_pct", "period_change_percent"],
    "balance": ["debt_ratio_pct", "debt_to_equity_ratio", "current_ratio", "quick_ratio", "altman_score"],
    "market": ["latest_price", "day_change_percent", "avg_daily_trading_value", "total_trading_value"],
    "documents": ["dividend_count", "report_document_count", "pdf_report_count", "excel_report_count"],
}


def _round_metric(value, digits: int = 2):
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return round(parsed, digits)


def _balance_quality_score(
    debt_ratio_pct,
    current_ratio,
    quick_ratio,
    debt_to_equity,
) -> float | None:
    """Composite balance-sheet quality on a 0–100 scale.

    Each available component maps linearly onto [0..1] between a weak and a
    strong threshold (leverage lower-is-better, liquidity higher-is-better);
    the score is the mean of the available components ×100, so companies with
    partial data (e.g. banks without current assets) are scored on what they
    do report instead of defaulting to zero. None when nothing is available.
    """
    def linear(value, weak: float, strong: float) -> float | None:
        parsed = _safe_float(value)
        if parsed is None:
            return None
        if strong > weak:  # higher is better
            return max(0.0, min(1.0, (parsed - weak) / (strong - weak)))
        return max(0.0, min(1.0, (weak - parsed) / (weak - strong)))

    components = [
        linear(debt_ratio_pct, 80.0, 30.0),   # % liabilities/assets
        linear(current_ratio, 0.8, 2.0),
        linear(quick_ratio, 0.3, 1.0),
        linear(debt_to_equity, 4.0, 1.0),
    ]
    available = [c for c in components if c is not None]
    if not available:
        return None
    return sum(available) / len(available) * 100.0


def _best_by(rows: list[dict], key: str, reverse: bool = True) -> dict | None:
    candidates = [row for row in rows if _safe_float(row.get(key)) is not None]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: _safe_float(row.get(key)), reverse=reverse)[0]


def _leader_payload(row: dict | None, key: str) -> dict | None:
    if not row:
        return None
    return {
        "company": row.get("company_name"),
        "ticker": row.get("ticker"),
        "metric": key,
        "value": row.get(key),
    }


def _field_by_key() -> dict[str, dict]:
    return {field["key"]: field for field in COMPARISON_FIELDS}


def _normalize_value(value, min_value: float, max_value: float, better: str) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    if max_value == min_value:
        return 50.0
    if better == "lower":
        normalized = (max_value - parsed) / (max_value - min_value) * 100
    else:
        normalized = (parsed - min_value) / (max_value - min_value) * 100
    return round(max(0, min(100, normalized)), 2)


def _rank_metric(rows: list[dict], key: str, better: str) -> dict[str, int]:
    ranked = [
        row for row in rows
        if _safe_float(row.get(key)) is not None
    ]
    if not ranked:
        return {}
    reverse = better != "lower"
    ranked.sort(key=lambda row: _safe_float(row.get(key)), reverse=reverse)
    ranks = {}
    previous_value = None
    previous_rank = 0
    for index, row in enumerate(ranked, start=1):
        current_value = _safe_float(row.get(key))
        rank = previous_rank if current_value == previous_value else index
        ranks[row.get("input") or row.get("company_name")] = rank
        previous_value = current_value
        previous_rank = rank
    return ranks


def _build_normalized_comparison(rows: list[dict]) -> dict:
    normalized_fields = []
    row_map = {
        row.get("input") or row.get("company_name"): {
            "company_name": row.get("company_name"),
            "ticker": row.get("ticker"),
            "metrics": {},
        }
        for row in rows
    }

    for field in COMPARISON_FIELDS:
        key = field["key"]
        if field.get("better") == "neutral":
            continue
        values = [_safe_float(row.get(key)) for row in rows]
        values = [value for value in values if value is not None]
        if not values:
            continue
        min_value = min(values)
        max_value = max(values)
        ranks = _rank_metric(rows, key, field.get("better", "higher"))
        normalized_fields.append({
            **field,
            "min": round(min_value, 4),
            "max": round(max_value, 4),
        })
        for row in rows:
            row_key = row.get("input") or row.get("company_name")
            row_map[row_key]["metrics"][key] = {
                "raw": row.get(key),
                "normalized": _normalize_value(
                    row.get(key),
                    min_value,
                    max_value,
                    field.get("better", "higher"),
                ),
                "rank": ranks.get(row_key),
            }

    return {
        "method": "min_max_0_100",
        "description": (
            "Все числовые показатели приведены к шкале 0-100. "
            "Для метрик higher большее значение лучше; для lower меньшее значение лучше."
        ),
        "fields": normalized_fields,
        "rows": list(row_map.values()),
    }


def _category_score(row_metrics: dict, keys: list[str]) -> float | None:
    values = []
    for key in keys:
        metric = row_metrics.get(key) or {}
        normalized = _safe_float(metric.get("normalized"))
        if normalized is not None:
            values.append(normalized)
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _build_category_scores(normalized: dict) -> list[dict]:
    score_rows = []
    for row in normalized.get("rows", []):
        metrics = row.get("metrics") or {}
        categories = {
            category: _category_score(metrics, keys)
            for category, keys in COMPARISON_CATEGORY_METRICS.items()
        }
        available = [value for value in categories.values() if value is not None]
        composite = round(sum(available) / len(available), 2) if available else None
        score_rows.append({
            "company_name": row.get("company_name"),
            "ticker": row.get("ticker"),
            "composite_score": composite,
            **categories,
        })
    return score_rows


def _build_comparison_tables(rows: list[dict], normalized: dict, category_scores: list[dict]) -> dict:
    fields = _field_by_key()
    normalized_by_company = {
        row.get("company_name"): row.get("metrics") or {}
        for row in normalized.get("rows", [])
    }
    tables = {}
    for table_name, keys in COMPARISON_TABLES.items():
        columns = [
            {"key": "company_name", "label": "Компания"},
            {"key": "ticker", "label": "Тикер"},
        ]
        columns.extend(
            fields.get(key, {"key": key, "label": key, "unit": "", "better": "neutral"})
            for key in keys
            if key not in {"ticker"}
        )
        table_rows = []
        for row in rows:
            metrics = normalized_by_company.get(row.get("company_name"), {})
            table_row = {
                "company_name": row.get("company_name"),
                "ticker": row.get("ticker"),
            }
            for key in keys:
                if key == "ticker":
                    continue
                table_row[key] = {
                    "raw": row.get(key),
                    "normalized": (metrics.get(key) or {}).get("normalized"),
                    "rank": (metrics.get(key) or {}).get("rank"),
                }
            table_rows.append(table_row)
        tables[table_name] = {"columns": columns, "rows": table_rows}

    tables["category_scores"] = {
        "columns": [
            {"key": "company_name", "label": "Компания"},
            {"key": "ticker", "label": "Тикер"},
            {"key": "composite_score", "label": "Сводный балл", "unit": "/100"},
            {"key": "profitability", "label": "Прибыльность", "unit": "/100"},
            {"key": "growth", "label": "Рост", "unit": "/100"},
            {"key": "balance", "label": "Баланс", "unit": "/100"},
            {"key": "market", "label": "Рынок", "unit": "/100"},
            {"key": "reporting", "label": "Раскрытие", "unit": "/100"},
        ],
        "rows": category_scores,
    }
    return tables


def _build_comparison_charts(rows: list[dict], category_scores: list[dict]) -> list[dict]:
    labels = [
        {"key": "overall", "label": "Общая оценка"},
        {"key": "profitability", "label": "Прибыльность"},
        {"key": "growth", "label": "Рост"},
        {"key": "balance", "label": "Баланс"},
        {"key": "market", "label": "Рынок"},
        {"key": "reporting", "label": "Отчеты"},
    ]
    radar_datasets = [
        {
            "label": row.get("ticker") or row.get("company_name"),
            "company_name": row.get("company_name"),
            "data": [
                row.get("overall"),
                row.get("profitability"),
                row.get("growth"),
                row.get("balance"),
                row.get("market"),
                row.get("reporting"),
            ],
        }
        for row in category_scores
    ]
    company_axis = [
        {"company_name": row.get("company_name"), "ticker": row.get("ticker")}
        for row in rows
    ]
    return [
        {
            "id": "normalized_radar",
            "type": "radar",
            "title": "Сопоставимый профиль 0-100",
            "labels": labels,
            "datasets": radar_datasets,
        },
        {
            "id": "score_bar",
            "type": "bar",
            "title": "Общий score и сводный нормализованный балл",
            "x": company_axis,
            "series": [
                {"key": "score", "label": "Score", "data": [row.get("score") for row in rows]},
                {"key": "composite_score", "label": "Сводный 0-100", "data": [row.get("composite_score") for row in category_scores]},
            ],
        },
        {
            "id": "profitability_grouped_bar",
            "type": "grouped_bar",
            "title": "Прибыльность",
            "x": company_axis,
            "series": [
                {"key": "net_profit_margin_pct", "label": "Чистая маржа, %", "data": [row.get("net_profit_margin_pct") for row in rows]},
                {"key": "roe_pct", "label": "ROE, %", "data": [row.get("roe_pct") for row in rows]},
                {"key": "roa_pct", "label": "ROA, %", "data": [row.get("roa_pct") for row in rows]},
            ],
        },
        {
            "id": "balance_grouped_bar",
            "type": "grouped_bar",
            "title": "Баланс и риск",
            "x": company_axis,
            "series": [
                {"key": "debt_ratio_pct", "label": "Долг/активы, %", "data": [row.get("debt_ratio_pct") for row in rows]},
                {"key": "current_ratio", "label": "Current ratio", "data": [row.get("current_ratio") for row in rows]},
                {"key": "altman_score", "label": "Altman Z", "data": [row.get("altman_score") for row in rows]},
            ],
        },
        {
            "id": "market_bar",
            "type": "bar",
            "title": "Рыночная ликвидность",
            "x": company_axis,
            "series": [
                {"key": "avg_daily_trading_value", "label": "Средний дневной оборот", "data": [row.get("avg_daily_trading_value") for row in rows]},
                {"key": "period_change_percent", "label": "Изменение за период, %", "data": [row.get("period_change_percent") for row in rows]},
            ],
        },
        {
            "id": "documents_bar",
            "type": "stacked_bar",
            "title": "Доступность отчетов",
            "x": company_axis,
            "series": [
                {"key": "pdf_report_count", "label": "PDF", "data": [row.get("pdf_report_count") for row in rows]},
                {"key": "excel_report_count", "label": "Excel", "data": [row.get("excel_report_count") for row in rows]},
            ],
        },
    ]


def _comparison_summary(rows: list[dict], leaders: dict, language: str) -> dict:
    leader = leaders.get("overall_leader") or {}
    profitability = leaders.get("profitability_leader") or {}
    balance = leaders.get("balance_quality_leader") or {}
    liquidity = leaders.get("market_liquidity_leader") or {}
    if language == "en":
        short = (
            f"Overall leader: {leader.get('company') or 'n/a'}. "
            f"Best profitability: {profitability.get('company') or 'n/a'}. "
            f"Best balance quality: {balance.get('company') or 'n/a'}. "
            f"Best market liquidity: {liquidity.get('company') or 'n/a'}."
        )
    elif language == "uz":
        short = (
            f"Umumiy lider: {leader.get('company') or 'n/a'}. "
            f"Rentabellik bo'yicha: {profitability.get('company') or 'n/a'}. "
            f"Balans sifati bo'yicha: {balance.get('company') or 'n/a'}. "
            f"Bozor likvidligi bo'yicha: {liquidity.get('company') or 'n/a'}."
        )
    else:
        short = (
            f"По общей оценке лидирует: {leader.get('company') or 'нет данных'}. "
            f"По прибыльности сильнее выглядит: {profitability.get('company') or 'нет данных'}. "
            f"По качеству баланса: {balance.get('company') or 'нет данных'}. "
            f"По рыночной ликвидности: {liquidity.get('company') or 'нет данных'}."
        )
    return {
        "short": short,
        "methodology": (
            "Сравнение детерминированное: финансовые метрики считаются из отчетности, "
            "рыночные данные берутся из OpenInfo, лидеры выбираются только по доступным числам."
        ),
        "compared_count": len(rows),
    }

"""Attach deterministic financial tables to analysis sections."""

from __future__ import annotations
from reporting.numbers import _pct_from_fraction
from reporting.presentation import (
    _format_report_number,
    _format_report_pct,
    _markdown_table,
    _report_table_labels,
)


def _build_horizontal_report_table(metrics: dict, language: str) -> dict | None:
    labels = _report_table_labels(language)
    items = ((metrics or {}).get("horizontal_analysis") or {}).get("items") or {}
    rows = []
    for item in items.values():
        if not isinstance(item, dict):
            continue
        rows.append([
            item.get("label") or "—",
            _format_report_number(item.get("current"), language),
            _format_report_number(item.get("previous"), language),
            _format_report_number(item.get("change"), language, signed=True),
            _format_report_pct(item.get("pct"), language, signed=True),
        ])
    if not rows:
        return None
    headers = [labels["line"], labels["current"], labels["previous"], labels["change"], labels["change_pct"]]
    markdown = _markdown_table(labels["horizontal_caption"], headers, rows[:10])
    return {
        "id": "horizontal_key_lines",
        "caption": labels["horizontal_caption"],
        "headers": headers,
        "rows": rows[:10],
        "markdown": markdown,
        "source": "metrics.horizontal_analysis",
    }


def _build_trend_report_table(ifrs_snapshot: dict, language: str) -> dict | None:
    labels = _report_table_labels(language)
    annual = (((ifrs_snapshot or {}).get("series") or {}).get("annual") or [])[-5:]
    rows = []
    for row in annual:
        if not isinstance(row, dict):
            continue
        rows.append([
            row.get("year") or "—",
            _format_report_number(row.get("revenue"), language),
            _format_report_number(row.get("net_income"), language),
            _format_report_number(row.get("total_assets"), language),
            _format_report_number(row.get("equity"), language),
            _format_report_pct(_pct_from_fraction(row.get("net_profit_margin")), language),
        ])
    if len(rows) < 2:
        return None
    headers = [
        labels["year"],
        labels["revenue"],
        labels["net_income"],
        labels["assets"],
        labels["equity"],
        labels["net_margin"],
    ]
    markdown = _markdown_table(labels["trend_caption"], headers, rows)
    return {
        "id": "annual_financial_dynamics",
        "caption": labels["trend_caption"],
        "headers": headers,
        "rows": rows,
        "markdown": markdown,
        "source": "ifrs_snapshot.series.annual",
    }


def _build_vertical_balance_table(metrics: dict, language: str) -> dict | None:
    labels = _report_table_labels(language)
    items = ((((metrics or {}).get("vertical_analysis") or {}).get("balance_sheet") or {}).get("items") or {})
    rows = []
    for item in items.values():
        if not isinstance(item, dict):
            continue
        rows.append([
            item.get("label") or "—",
            _format_report_number(item.get("value"), language),
            _format_report_pct(item.get("pct_of_assets"), language),
        ])
    if not rows:
        return None
    headers = [labels["line"], labels["amount"], labels["share"]]
    markdown = _markdown_table(labels["vertical_caption"], headers, rows[:10])
    return {
        "id": "vertical_balance_structure",
        "caption": labels["vertical_caption"],
        "headers": headers,
        "rows": rows[:10],
        "markdown": markdown,
        "source": "metrics.vertical_analysis.balance_sheet",
    }


def _build_report_tables(metrics: dict, ifrs_snapshot: dict, language: str) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {}
    horizontal = _build_horizontal_report_table(metrics, language)
    vertical = _build_vertical_balance_table(metrics, language)
    trend = _build_trend_report_table(ifrs_snapshot, language)
    if horizontal:
        tables.setdefault("ЧТО_С_ДЕНЬГАМИ", []).append(horizontal)
    if vertical:
        tables.setdefault("ЧТО_С_ДЕНЬГАМИ", []).append(vertical)
    if trend:
        tables.setdefault("ТРЕНД", []).append(trend)
    return tables


def _section_has_markdown_table(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines()]
    return any(line.startswith("|") and "---" in line for line in lines)


def _insert_after_tldr(text: str, payload: str) -> str:
    lines = str(text or "").splitlines()
    first = lines[0].strip().lower() if lines else ""
    if first not in {"кратко", "brief", "qisqacha", "tl;dr", "tldr"}:
        return f"{payload}\n\n{text}".strip()

    insert_at = None
    for idx, line in enumerate(lines):
        lowered = line.strip().lower()
        if lowered.startswith(("для тебя:", "for you:", "siz uchun:")):
            insert_at = idx + 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            break
    if insert_at is None:
        return f"{payload}\n\n{text}".strip()

    before = "\n".join(lines[:insert_at]).rstrip()
    after = "\n".join(lines[insert_at:]).lstrip()
    if after:
        return f"{before}\n\n{payload}\n\n{after}".strip()
    return f"{before}\n\n{payload}".strip()


def _enrich_sections_with_report_tables(
    sections: dict,
    metrics: dict,
    ifrs_snapshot: dict,
    language: str,
) -> tuple[dict, dict[str, list[dict]]]:
    if not isinstance(sections, dict):
        return sections, {}
    tables = _build_report_tables(metrics or {}, ifrs_snapshot or {}, language)
    if not tables:
        return sections, tables

    enriched = dict(sections)
    for section_key, section_tables in tables.items():
        if section_key not in enriched:
            continue
        current = str(enriched.get(section_key) or "")
        if _section_has_markdown_table(current):
            continue
        markdown_blocks = [table.get("markdown") for table in section_tables if table.get("markdown")]
        if markdown_blocks:
            enriched[section_key] = _insert_after_tldr(current, "\n\n".join(markdown_blocks))
    return enriched, tables

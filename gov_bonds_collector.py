"""Collect ГЦБ (government bond) auction results from the Central Bank.

The Central Bank is the fiscal agent for the Ministry of Economy and Finance's
bond placements, and it publishes every auction on
``/ru/monetary-policy/operations/fiscal-agent/``: identification number, ISIN,
term in days, maturity date, income type (coupon/discount), placed volume and
the weighted-average / minimum / maximum rate. That table is the primary market
of the UZS curve — the base every corporate bond's spread is measured against —
and it is the only public source of it.

The page is a Bitrix grid: the head row names each column
(``data-name="PROPERTY_NNNN"`` + a title), body cells repeat the column id.
Columns are mapped by their TITLE, not their PROPERTY number, because the
number is a site-build artifact and the title is the published meaning.

The key rate lives on the site's front page ("Основная ставка 14% с
29.07.2026") — one more fetch, parsed by the same rule of reading what the
source states rather than configuring a number by hand.

Pure fetch/parse: no DB writes here. ``collector_financials.push_gov_auctions``
posts the result to ``/api/admin/gov-auctions``.
"""
from __future__ import annotations

import html as _html
import logging
import re
from typing import Any

import requests

log = logging.getLogger("gov_bonds")

CBU_BASE = "https://cbu.uz"
FISCAL_AGENT_PATH = "/ru/monetary-policy/operations/fiscal-agent/"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
_MAX_PAGES = 20

# Header title fragment → our field name. Matched by substring so a cosmetic
# retitle ("(млрд. сум)" → "(млрд сум)") does not silently drop a column.
_COLUMNS = (
    ("Дата размещения", "auction_date"),
    ("Идентификационный номер", "sec_id"),
    ("ISIN", "isin"),
    ("Объем выпуска", "announced_volume"),
    ("Срок обращения", "term_days"),
    ("Дата погашения", "maturity_date"),
    ("Вид дохода", "income_type"),
    ("Число дилеров", "dealers"),
    ("Количество размещенных", "placed_qty"),
    ("Сумма размещения", "placed_value"),
    ("Средневзвешенная", "wavg_rate"),
    ("Минимальная", "min_rate"),
    ("Максимальная", "max_rate"),
)
_NUMERIC = {"announced_volume", "term_days", "dealers", "placed_qty",
            "placed_value", "wavg_rate", "min_rate", "max_rate"}
_DATES = {"auction_date", "maturity_date"}
_INCOME_TYPES = {"купон": "coupon", "дисконт": "discount"}


def _num(text: str) -> float | None:
    cleaned = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value


def _iso_date(text: str) -> str | None:
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", text.strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _header_map(page: str) -> dict[str, str]:
    """PROPERTY id → field name, read from the head row's own titles."""
    head_start = page.find("main-grid-row-head")
    if head_start < 0:
        return {}
    head = page[head_start:page.find("</tr>", head_start)]
    out: dict[str, str] = {}
    for m in re.finditer(
            r'data-name="(PROPERTY_\d+)"(?:(?!</th>).)*?main-grid-head-title[^>]*>\s*([^<]+)',
            head, re.S):
        title = _html.unescape(m.group(2)).strip()
        for fragment, field in _COLUMNS:
            if fragment in title:
                out[m.group(1)] = field
                break
    return out


def parse_auction_rows(page: str, source_url: str = "") -> list[dict[str, Any]]:
    """Every auction row on one page, or [] when the grid is not there."""
    columns = _header_map(page)
    if not columns:
        return []
    rows: list[dict[str, Any]] = []
    for row_match in re.finditer(
            r'<tr class="main-grid-row main-grid-row-body"(?:(?!</tr>).)*</tr>', page, re.S):
        cells = re.findall(
            r'data-column-id="(PROPERTY_\d+)"(?:(?!</td>).)*?main-grid-cell-content"[^>]*>\s*([^<]*)',
            row_match.group(0), re.S)
        row: dict[str, Any] = {}
        for prop, raw in cells:
            field = columns.get(prop)
            if not field:
                continue
            text = _html.unescape(raw).strip()
            if field in _DATES:
                row[field] = _iso_date(text)
            elif field in _NUMERIC:
                row[field] = _num(text)
            elif field == "income_type":
                row[field] = _INCOME_TYPES.get(text.lower(), text.lower() or None)
            else:
                row[field] = text or None
        if row.get("sec_id") and row.get("auction_date"):
            row["source_url"] = source_url or (CBU_BASE + FISCAL_AGENT_PATH)
            rows.append(row)
    return rows


def _page_param(page: str) -> str | None:
    """The grid's pagination parameter, read from its own page-2 link."""
    m = re.search(r"[?&](lists_list_elements_\d+)=page-2", page)
    return m.group(1) if m else None


def collect_gov_auctions(session: requests.Session | None = None,
                         max_pages: int = _MAX_PAGES) -> list[dict[str, Any]]:
    """Walk the fiscal-agent grid until a page adds nothing new."""
    session = session or requests.Session()
    url = CBU_BASE + FISCAL_AGENT_PATH
    first = session.get(url, headers=_HEADERS, timeout=30)
    first.raise_for_status()
    rows = parse_auction_rows(first.text, url)
    seen = {(r["sec_id"], r["auction_date"]) for r in rows}
    param = _page_param(first.text)
    if param:
        for page_no in range(2, max_pages + 1):
            page_url = f"{url}?{param}=page-{page_no}"
            try:
                resp = session.get(page_url, headers=_HEADERS, timeout=30)
                resp.raise_for_status()
            except Exception:  # noqa: BLE001 — history pages must not sink the fresh ones
                log.warning("fiscal-agent page %d failed", page_no, exc_info=True)
                break
            page_rows = parse_auction_rows(resp.text, page_url)
            fresh = [r for r in page_rows
                     if (r["sec_id"], r["auction_date"]) not in seen]
            if not fresh:
                break
            rows.extend(fresh)
            seen.update((r["sec_id"], r["auction_date"]) for r in fresh)
    log.info("gov auctions: %d rows", len(rows))
    return rows


def collect_key_rate(session: requests.Session | None = None) -> dict[str, Any] | None:
    """The key rate as the Central Bank's own front page states it."""
    session = session or requests.Session()
    try:
        resp = session.get(CBU_BASE + "/ru/", headers=_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception:  # noqa: BLE001
        log.warning("cbu.uz front page unreachable", exc_info=True)
        return None
    text = re.sub(r"<[^>]+>", "|", resp.text)
    m = re.search(r"Основная ставка[|\s]*(\d+(?:[.,]\d+)?)\s*%"
                  r"(?:(?!Основная).){0,120}?с\s*(\d{2}\.\d{2}\.\d{4})", text, re.S)
    if not m:
        log.warning("key rate not found on cbu.uz front page")
        return None
    return {"rate": _num(m.group(1)),
            "effective_from": _iso_date(m.group(2)),
            "source_url": CBU_BASE + "/ru/"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    auctions = collect_gov_auctions()
    for row in auctions[:5]:
        print(row)
    print(f"... {len(auctions)} auctions")
    print(collect_key_rate())

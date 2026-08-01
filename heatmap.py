"""heatmap.py — the market map computed once, on the server.

ТЗ v1.2 §9. The map is assembled from one universe in one place because it used
to be stitched together on the client from several endpoints that disagreed
about which instruments exist — which is where tiles without a price, and one
issuer appearing under two sectors, came from.

Three rules the tiles obey:

**No trades is not zero percent.** A security with no price gets its own status
and is excluded from every sector aggregate. Colouring it neutral grey put it
next to genuinely unchanged securities and let it vote in the average as a zero.

**A sector moves by turnover, not by headcount.** A simple mean over tiles gives
NMKB — 860 trades, 98.4 mn turnover — the same weight as a security that traded
one share, and the sector then reports a move nobody could have made. The count
of tiles that actually entered the number travels with it.

**One trade is not a market.** Below the confidence thresholds the tile is marked
and carries the real figures, so "+20 %" cannot be read without also reading
"1 trade, 1 share, 30 720 sums".
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

from formulas import _num, thresholds

logger = logging.getLogger(__name__)

# Tile statuses (ТЗ §10.4.4).
TILE_OK = "ok"
TILE_NO_PRICE = "no_price"          # trades exist, last price missing — a join gap
TILE_NOT_TRADED = "not_traded"      # no session for this security at all
TILE_INACTIVE = "inactive"          # listed but dormant


def day_change(last_price: float | None, prev_close: float | None) -> float | None:
    """Percent move on UNROUNDED prices (ТЗ §9).

    KASU trades at 0.01 sum: round to two decimals before dividing and every
    move it ever makes becomes exactly zero, on 232 trades and 146 mn shares.
    """
    if last_price is None or prev_close is None or prev_close <= 0:
        return None
    return (last_price - prev_close) / prev_close * 100.0


def classify_tile(row: dict[str, Any], stats: dict[str, Any] | None = None) -> dict[str, Any]:
    """One tile: its move, how much trading is behind it, and its status."""
    cfg = thresholds()["market_map"]
    stats = stats or {}

    last = _num(row.get("last_price"))
    prev = _num(row.get("close_price"))
    trades = _num(row.get("trade_count"))
    if trades is None:
        trades = _num(stats.get("trade_count"))
    quantity = _num(row.get("quantity"))
    if quantity is None:
        quantity = _num(stats.get("total_qty"))
    turnover = _num(row.get("volume"))
    if turnover is None:
        turnover = _num(stats.get("total_value"))

    traded_today = bool((trades or 0) > 0 or (turnover or 0) > 0 or (quantity or 0) > 0)
    inactive = bool(row.get("inactive"))

    change = day_change(last, prev)

    if change is None:
        if traded_today:
            # ТЗ §9: "Если по бумаге есть сделки в статистике торгов, последняя
            # цена обязана существовать." Thirteen securities were in this state
            # — UTYK with 8 trades on 34 050 000 sums — and the map showed them
            # as a 100 % fall. It is a gap between two feeds, not a price move.
            status = TILE_NO_PRICE
            reason = "нет последней цены, хотя сделки есть"
        elif inactive:
            status = TILE_INACTIVE
            reason = "листинг неактивен"
        else:
            status = TILE_NOT_TRADED
            reason = "нет сделок за торговый день"
    else:
        status = TILE_OK
        reason = None

    low_confidence = (
        status == TILE_OK
        and ((trades is not None and trades < float(cfg["min_trades_confident"]))
             or (quantity is not None and quantity < float(cfg["min_quantity_confident"])))
    )

    return {
        "ticker": str(row.get("ticker") or "").upper(),
        "name": row.get("name"),
        "sector": row.get("sector"),
        "type": row.get("type"),
        "share_type": row.get("share_type"),
        "change_pct": change,
        "last_price": last,
        "prev_close": prev,
        "trades": int(trades) if trades is not None else None,
        "quantity": quantity,
        "turnover": turnover,
        "market_cap": _num(row.get("market_cap")),
        "status": status,
        "reason": reason,
        "confidence": "low" if low_confidence else ("normal" if status == TILE_OK else None),
        # Tile area follows the day's turnover (ТЗ §9). A tile with no turnover
        # still has to be visible, so the client floors it — but the honest
        # number travels with it and the floor is never mistaken for trading.
        "weight": turnover if (turnover or 0) > 0 else 0.0,
    }


def aggregate_sector(tiles: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Turnover-weighted move of a group, over tiles with a real price only."""
    counted = [t for t in tiles if t["status"] == TILE_OK and t["change_pct"] is not None]
    weight_total = sum((t["turnover"] or 0.0) for t in counted)
    if counted and weight_total > 0:
        change = sum(t["change_pct"] * (t["turnover"] or 0.0) for t in counted) / weight_total
        weighting = "turnover"
    elif counted:
        # Every tile that moved did so on zero recorded turnover: fall back to an
        # equal-weight mean and SAY so, rather than reporting a weighted figure
        # that no turnover supports.
        change = sum(t["change_pct"] for t in counted) / len(counted)
        weighting = "equal_no_turnover"
    else:
        change, weighting = None, None
    return {
        "change_pct": change,
        "weighting": weighting,
        "turnover": weight_total,
        "tiles_total": len(tiles),
        "tiles_counted": len(counted),
        "tiles_no_price": sum(1 for t in tiles if t["status"] == TILE_NO_PRICE),
        "tiles_not_traded": sum(1 for t in tiles if t["status"] in (TILE_NOT_TRADED, TILE_INACTIVE)),
    }


def build_heatmap(board: Iterable[dict[str, Any]],
                  securities: dict[str, dict[str, Any]] | None = None,
                  stats: dict[str, dict[str, Any]] | None = None,
                  trade_date: str | None = None) -> dict[str, Any]:
    """Tiles, sector aggregates and the market total — one universe, one answer."""
    securities = securities or {}
    stats = stats or {}
    tiles: list[dict[str, Any]] = []
    for row in board:
        ticker = str(row.get("ticker") or "").upper()
        meta = securities.get(ticker) or {}
        merged = {
            **row,
            "sector": row.get("sector") or meta.get("sector"),
            "type": row.get("type") or meta.get("type"),
            "share_type": row.get("share_type") or meta.get("share_type"),
            "name": row.get("name") or meta.get("name"),
        }
        isin = str(row.get("isin") or meta.get("isin") or "")
        tiles.append(classify_tile(merged, stats.get(isin) or stats.get(ticker)))

    by_sector: dict[str, list[dict[str, Any]]] = {}
    for tile in tiles:
        by_sector.setdefault(tile["sector"] or "прочее", []).append(tile)

    sectors = [{"name": name, **aggregate_sector(group)}
               for name, group in sorted(by_sector.items())]
    total = aggregate_sector(tiles)

    return {
        "trade_date": trade_date,
        "tiles": tiles,
        "sectors": sectors,
        "total": total,
        "counts": {
            "tiles": len(tiles),
            "ok": sum(1 for t in tiles if t["status"] == TILE_OK),
            "no_price": sum(1 for t in tiles if t["status"] == TILE_NO_PRICE),
            "not_traded": sum(1 for t in tiles if t["status"] == TILE_NOT_TRADED),
            "inactive": sum(1 for t in tiles if t["status"] == TILE_INACTIVE),
            "low_confidence": sum(1 for t in tiles if t.get("confidence") == "low"),
        },
    }

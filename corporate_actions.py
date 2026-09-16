"""Back-adjustment of quoted prices for share-count corporate actions.

UZSE prints what was traded and openinfo republishes it — neither restates the past
when an issuer redenominates its shares or capitalises reserves into free stock. So on
the first session after the new share count reaches the exchange the quote steps down
by the ratio, and every earlier price in the series describes a share that no longer
exists. The chart reads it as a crash.

ALSKOM (ALSM) is the case this was written for. Its last trade before the
recapitalisation was 1 495 on 2025-04-03; the first one after was 897 on 2025-10-07, a
40% hole in the middle of an otherwise flat series. Nothing happened to the company in
between: the par value was halved, so one share became two (2025-05-19), and then every
two shares drew a third free one out of the company's own funds (2025-09-26). One April
share is three of today's. Rescaled onto today's share that 1 495 is 498 — and the
holder who did nothing across the window is up, not down. Aloqabank (ALKB) is the same
story at 205×, and it is the ratio that makes the chart unreadable, not the company.

Only prices are rescaled. Volume stays exactly as printed: the bars are read as "how
much stock changed hands that day", and restating a 2024 bar in today's denomination
would make the pre-split market look more liquid than it was. Nothing on the site plots
price × volume, so there is no consistency to keep.

Entries are curated, not derived. openinfo's "Выпуск ценных бумаг" (fact 25) carries the
numbers but not on a consistent basis — a redenomination re-registers the whole charter
capital while an additional issue reports only its own tranche, and the two are told
apart by prose in ``placement_method``, in either Russian or Uzbek. So every entry below
was read off the filing and then confirmed against a figure the filing does not control:
the share count uzse.uz reports today equals the registered emissions summed, exactly,
for all five securities here.

What is deliberately *not* adjusted: ordinary cash issues, including the ones placed
among existing holders under a pre-emptive right (CBSK doubled its count that way in
May 2025, KASU and ALKB several times). Those raise money at a price, so the drop that
follows is a real transfer of value and not a change of unit — and CBSK's 2025 series
shows no step at all across its issue, which is the point.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_FACT_URL = "https://new-api.openinfo.uz/api/v2/disclosure/facts/{}/"

# The fields of an ``/iuzse/conclusions/`` point that are quoted per share. ``change`` is a
# day-over-day price move, so it scales with the price; ``trading_volume`` (share count) and
# ``trading_value`` (sums) are deliberately left alone.
_PRICE_FIELDS = ("open", "high", "low", "close", "change")


@dataclass(frozen=True)
class ShareAction:
    """One event that multiplied an issuer's share count without adding value.

    ``ex_date`` is the first session that traded on the new count — prices strictly
    before it are the ones that need rescaling. It is the registration date only when
    the security was suspended around the event; where trading ran through it, it is the
    session the exchange actually switched over, which can be weeks later. ``ratio`` is
    new shares per old share: 2.0 for a two-for-one split, 1.5 for one free share per two
    held. The price factor is its reciprocal.
    """

    ex_date: str
    ratio: float
    kind: str  # "split" (par value redenominated) | "bonus" (issue out of own funds)
    source: str


# ALSKOM, both classes. Ordinary: 29 062 358 shares at a par value of 1 380 through April
# 2025 → 58 124 716 at 690 (P0170-18, charter capital unchanged at 40 106 054 040) →
# 87 187 074 (P0170-19, +29 062 358 "капитализация за счет собственных средств"), which is
# the count uzse.uz reports today. Preferred moved in lockstep: 55 000 → 110 000 → 165 000.
# The dividend is the independent check — 966 per preferred share for 2023 and 483 for
# 2024, both 70% of par, the same 53.1m sums in total.
#
# Both registrations fall inside a six-month suspension (2025-04-03 → 2025-10-07), so no
# quoted price sits between them and splitting the 3× into 2× and 1.5× is bookkeeping.
_ALSKOM_ORDINARY = (
    ShareAction("2025-05-19", 2.0, "split", _FACT_URL.format(90472)),
    ShareAction("2025-09-26", 1.5, "bonus", _FACT_URL.format(93381)),
)
_ALSKOM_PREFERRED = (
    ShareAction("2025-05-19", 2.0, "split", _FACT_URL.format(90473)),
    ShareAction("2025-09-26", 1.5, "bonus", _FACT_URL.format(93383)),
)

# Aloqabank, both classes, 205× in five weeks and again inside a suspension
# (2024-06-20 → 2024-10-08). Par 121 → 1 with the capital untouched, ordinary
# 9 826 990 473 → 1 189 065 847 233 and preferred 18 000 000 → 2 178 000 000 (P0021-28);
# then P0021-29 hands shareholders 84 more shares per 121 held "банкнинг тақсимланмаган
# фойдаси ҳисобидан" — out of retained earnings, so free — taking preferred to
# 3 690 000 000, the count uzse.uz reports today to the share.
_ALOQABANK_ORDINARY = (
    ShareAction("2024-08-21", 121.0, "split", _FACT_URL.format(84492)),
    ShareAction("2024-09-26", 205 / 121, "bonus", _FACT_URL.format(85510)),
)
_ALOQABANK_PREFERRED = (
    ShareAction("2024-08-21", 121.0, "split", _FACT_URL.format(84491)),
    ShareAction("2024-09-26", 205 / 121, "bonus", _FACT_URL.format(85511)),
)

CORPORATE_ACTIONS: dict[str, tuple[ShareAction, ...]] = {
    "ALSM": _ALSKOM_ORDINARY,
    "ALSMP": _ALSKOM_PREFERRED,
    "ALKB": _ALOQABANK_ORDINARY,
    "ALKBP": _ALOQABANK_PREFERRED,
    # Universal Bank: par 10 → 1, 2 929 305 573 → 29 293 055 730 shares at an unchanged
    # 29 293 055 730 sums of capital (Q0117-11, registered 2021-04-30). Traded through it,
    # so the ex-date is the exchange's own switch: 10.00 on 2021-05-06, then 2021-05-17
    # opens at 1.05.
    "CBSK": (ShareAction("2021-05-17", 10.0, "split", _FACT_URL.format(45593)),),
    # Kafolat: par 1 → 0.01 (Р0272-15, registered 2022-08-05), ordinary 32 000 000 000 →
    # 3 200 000 000 000 and preferred 8 000 000 000 → 800 000 000 000. Same story on the
    # ex-date — 1.00 through 2022-08-09, then 2022-08-19 opens at 0.80 and closes 0.24 on
    # its way to the 0.01 tick the stock has sat on since.
    "KASU": (ShareAction("2022-08-19", 100.0, "split", _FACT_URL.format(62348)),),
    "KASUP": (ShareAction("2022-08-19", 100.0, "split", _FACT_URL.format(62349)),),
}

# The exchange detail endpoint occasionally serves an issuer-level historical
# ``parval`` instead of the current security denomination.  Aloqabank is the
# concrete case: after fact P0021-28 changed the par from 121 to 1 sum, the
# endpoint still returns 100 000 for ALKB on some responses.  Keep the verified
# post-redenomination value next to the actions that establish it, so every
# collector and API response can reject that stale field consistently.
CURRENT_PAR_VALUES: dict[str, float] = {
    "ALKB": 1.0,
    "ALKBP": 1.0,
}


def current_par(ticker: str | None, observed: Any = None) -> float | None:
    """Return the verified current par, otherwise a valid observed value."""
    known = CURRENT_PAR_VALUES.get(str(ticker or "").strip().upper())
    if known is not None:
        return known
    try:
        value = float(observed)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None

# openinfo's conclusions payload names the ticker itself, but only for securities it has
# indexed — this is the fallback for the ones covered here.
ISIN_TICKERS: dict[str, str] = {
    "UZ7045320007": "ALSM",
    "UZ704532K019": "ALSMP",
    "UZ7044760005": "ALKB",
    "UZ704476K019": "ALKBP",
    "UZ7038380000": "CBSK",
    "UZ7028660007": "KASU",
    "UZ702866K013": "KASUP",
}


def actions_for(ticker: str | None) -> tuple[ShareAction, ...]:
    """Known share-count events for a ticker, oldest first."""
    if not ticker:
        return ()
    return CORPORATE_ACTIONS.get(str(ticker).strip().upper(), ())


def resolve_ticker(ticker: str | None, isin: str | None = None) -> str | None:
    """Ticker to look actions up under, falling back to the ISIN map."""
    resolved = str(ticker or "").strip().upper()
    if resolved:
        return resolved
    return ISIN_TICKERS.get(str(isin or "").strip().upper()) or None


def _day_key(value: Any) -> str:
    """A date as bare digits, so «2025-09-26» and «20250926» compare as one thing.

    The two shapes are both in the codebase — the openinfo archive dates a point
    ISO, the stored daily-close table keys its sessions YYYYMMDD — and an event
    date compared against the wrong one silently rescales nothing (a dash-free
    "20250926" is greater than every "2025-.." string).
    """
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:8]


def adjust_history(
    points: Iterable[dict[str, Any]] | None,
    ticker: str | None,
    isin: str | None = None,
    *,
    date_key: str = "date",
    price_fields: tuple[str, ...] = _PRICE_FIELDS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rescale pre-event prices onto the current share.

    Returns ``(points, applied)`` — a copied point list with the price fields restated,
    and the actions that actually moved at least one point, so a caller can say so on the
    chart. Points are never dropped or reordered, and a series that begins after every
    known event comes back untouched.

    ``date_key`` and ``price_fields`` exist for the stored daily-close series
    (`catalog_quote_history`: ``trade_date`` + ``close_price``), which the market
    board's period changes and every sparkline are drawn from. That series was
    NOT adjusted, so a window spanning ALSM's 2025 recapitalisation would have
    reported a 40 % collapse to a holder who had in fact gained.
    """
    adjusted = [dict(point) for point in (points or [])]
    actions = actions_for(resolve_ticker(ticker, isin))
    if not actions or not adjusted:
        return adjusted, []

    touched = [0] * len(actions)
    for point in adjusted:
        day = _day_key(point.get(date_key))
        # A point with no date cannot be placed either side of an event; leaving it raw
        # keeps it wrong in one known way instead of silently rescaled into another.
        if not day:
            continue
        # One factor per point rather than one pass per action: a price that predates two
        # events would otherwise be rounded twice, and ALKB's 121 × 205/121 does not
        # survive that intact.
        factor = 1.0
        for index, action in enumerate(actions):
            if day < _day_key(action.ex_date):
                factor /= action.ratio
                touched[index] += 1
        if factor == 1.0:
            continue
        for field in price_fields:
            value = point.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                point[field] = round(value * factor, 8)

    applied: list[dict[str, Any]] = [
        {
            "ex_date": action.ex_date,
            "ratio": round(action.ratio, 6),
            "kind": action.kind,
            "factor": round(1.0 / action.ratio, 8),
            "source": action.source,
            "points": count,
        }
        for action, count in zip(actions, touched) if count
    ]

    if applied:
        logger.debug(
            "price history for %s back-adjusted by %s",
            ticker, " x ".join(f"1/{item['ratio']:g}" for item in applied),
        )
    return adjusted, applied

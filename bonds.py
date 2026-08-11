"""bonds.py — the bond contour (ТЗ Дополнение 1, часть А).

Eleven issues trade on this exchange and the interface does not contain them.
The market table shows 96 rows — shares only. The 265 659 bn capitalisation
excludes them, and their own 798 bn of issue value appears nowhere. They trade
genuinely: 8 622 securities changed hands in ACMT2B5 on 31 July, and their price
history is BETTER than most shares' (226–231 points a year, 7–23 % flat candles
against UQEQ's 65 %).

Worse than invisible, they leak into the equity arithmetic. Their type is `bond`
but their share class says `ordinary`; nine of the eleven carry a market_cap
computed as price × issue volume, which must never be added to a share
capitalisation. Bonds have no financial statements, so P/E, P/B and ROE are not
merely empty for them — they are undefined.

So the contour is closed explicitly, in two halves.

**This module is the first half**: everything that can be computed honestly from
data we already hold — price, change, turnover, trades, issue value, history
quality — plus the structural exclusion of equity multiples.

**The second half needs a reference — and the source publishes half of it.**
§А.3 recorded that no endpoint carries a nominal, a coupon rate or a maturity
date. That was half wrong: the exchange's own security card
(``/isu_infos/{isin}/detail``) returns ``parval`` — 100 000 for every ACMT
series — and the BND page prints "Номинал (UZS)" in the open. So the par is
loaded from the exchange (``listings_collector.collect_bond_reference_rows``)
and the price is shown as a percentage of it, which is how a bond is actually
read: 100 301 in one issue and 10 062 465 in another are different pars, and
comparing them in absolute sums is meaningless.

What remains genuinely absent is the coupon rate, the maturity date and the
payment schedule — nowhere on the exchange's pages, nowhere in the API. Accrued
interest, yield, duration and spread therefore keep returning
`no_bond_reference` until those arrive. Inventing a coupon "because the issue
looks like the others" is the same class of error as interpolating a gap in a
price series.
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

from formulas import _metric, _num, thresholds

logger = logging.getLogger(__name__)

STATUS_NO_REFERENCE = "no_bond_reference"
NO_REFERENCE_NOTE = "нет справочных данных по выпуску"
# Redeemed is not "we lack the data": the reference is complete and the answer
# is that there is nothing left to discount or accrue. Kept apart so the page
# never blames a data gap for a fact about the issue.
STATUS_MATURED = "matured"
MATURED_NOTE = "выпуск погашен {date}"

# Day-count basis. ТЗ А.5 requires this to be configuration AND to be stated in
# the response: two developers who assume different bases both get a number and
# both believe they are right.
DAY_COUNT_BASES = {"ACT/365": 365.0, "ACT/360": 360.0, "ACT/ACT": None}


def day_count_basis() -> str:
    return str(thresholds().get("bonds", {}).get("day_count_basis", "ACT/365"))


def _days_in_year(basis: str, when: date | None = None) -> float:
    if basis == "ACT/ACT":
        year = (when or date.today()).year
        return 366.0 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365.0
    return DAY_COUNT_BASES.get(basis) or 365.0


def is_bond(row: dict[str, Any], meta: dict[str, Any] | None = None) -> bool:
    kind = str(row.get("type") or (meta or {}).get("type") or "").lower()
    return kind == "bond"


def share_class(row: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    """A bond's class is `bond`.

    It currently reads `ordinary`, which is why bonds fall into the equity
    branches of the code at all. Fixing the class is what makes the exclusion
    structural instead of a filter somebody has to remember to apply.
    """
    if is_bond(row, meta):
        return "bond"
    if row.get("is_preferred") or str((meta or {}).get("share_type") or "").lower().startswith("prefer"):
        return "preferred"
    return "ordinary"


# ---------------------------------------------------------------------------
# Reference completeness
# ---------------------------------------------------------------------------

REQUIRED_REFERENCE_FIELDS = ("nominal", "coupon_rate", "maturity_date")


def reference_state(reference: dict[str, Any] | None) -> dict[str, Any]:
    """Is the issue reference complete enough to compute yields from?

    ``is_complete`` is the master switch for the YIELDS (ТЗ А.4): while it is
    false no discounting metric is computed or displayed, and the moment the
    coupon and the maturity arrive they turn on with no code change.

    ``has_nominal`` is a second, smaller switch, and it exists because the
    exchange does publish the par value even though §А.3 recorded that nothing
    did: ``/isu_infos/{isin}/detail`` carries ``parval`` and the BND page prints
    "Номинал (UZS)" outright. A par alone cannot produce a yield, but it does
    produce the reading a bond is actually quoted in. Holding that behind the
    yield switch withheld a number we have.
    """
    reference = reference or {}
    missing = [f for f in REQUIRED_REFERENCE_FIELDS if _num(reference.get(f)) is None
               and not reference.get(f)]
    nominal, rate = _num(reference.get("nominal")), _num(reference.get("coupon_rate"))
    return {"is_complete": not missing, "missing": missing,
            "has_nominal": nominal is not None and nominal > 0,
            # The coupon is filed per payment; the maturity is filed only once
            # the issuer starts redeeming. So accrued interest and the running
            # yield are knowable long before a redemption date exists.
            "has_coupon": bool(nominal and rate),
            # The terms themselves, so a reader can see WHAT was found and not
            # only that something was: a 28% coupon is the answer to "why is
            # this trading at 120% of par", and it belongs on the screen.
            "nominal": nominal,
            "coupon_rate": rate,
            "coupon_freq": _num(reference.get("coupon_freq")),
            "maturity_date": reference.get("maturity_date"),
            # How many securities the issue IS, as registered — a different size
            # from what they are worth today, and the one the regulator states.
            "issue_volume": _num(reference.get("issue_volume")),
            "source_url": reference.get("source_url"),
            "synced_at": reference.get("synced_at")}


def _unavailable(reason: str = NO_REFERENCE_NOTE, **extra: Any) -> dict[str, Any]:
    return _metric(None, STATUS_NO_REFERENCE, note=reason, **extra)


def _matured(maturity: date) -> dict[str, Any]:
    """Absent because the issue is redeemed — its own status, not a missing reference."""
    return _metric(None, STATUS_MATURED, note=MATURED_NOTE.format(date=maturity.isoformat()))


# ---------------------------------------------------------------------------
# Reference-dependent formulas (ТЗ А.5) — inert until the reference exists
# ---------------------------------------------------------------------------

def price_pct(price: Any, nominal: Any) -> dict[str, Any]:
    """Price as a percentage of par — how a bond is actually quoted."""
    p, n = _num(price), _num(nominal)
    if n is None or n <= 0:
        return _unavailable()
    if p is None:
        # The par is known and the price is not — ACMT1B2 and CTFB3 are exactly
        # this case. Answering `no_bond_reference` here would blame the issue
        # reference for a missing quote; the row's own status already says why.
        return _metric(None, "no_price", note="нет последней цены")
    return _metric(p / n * 100.0, "ok", nominal=n)


def accrued_interest(nominal: Any, coupon_rate: Any, days_from_coupon: Any,
                     basis: str | None = None, when: date | None = None) -> dict[str, Any]:
    """Coupon earned since the last payment and not yet paid."""
    n, rate, days = _num(nominal), _num(coupon_rate), _num(days_from_coupon)
    if None in (n, rate, days) or n <= 0 or days < 0:
        return _unavailable()
    basis = basis or day_count_basis()
    value = n * (rate / 100.0) * days / _days_in_year(basis, when)
    return _metric(value, "ok", day_count_basis=basis, days_from_coupon=days)


def dirty_price(clean: Any, accrued: Any) -> float | None:
    c, a = _num(clean), _num(accrued)
    if c is None:
        return None
    return c + (a or 0.0)


def simple_yield(coupon_annual: Any, price: Any) -> dict[str, Any]:
    ca, p = _num(coupon_annual), _num(price)
    if ca is None or p is None or p <= 0:
        return _unavailable()
    return _metric(ca / p * 100.0, "ok")


def _pv(cashflows: Sequence[tuple[float, float]], rate: float) -> float:
    return sum(cf / (1.0 + rate) ** t for t, cf in cashflows)


def yield_to_maturity(cashflows: Sequence[tuple[float, float]], dirty: float,
                      guess: float = 0.1, tolerance: float = 1e-8,
                      max_iterations: int = 100) -> dict[str, Any]:
    """Newton's method on the dirty price (ТЗ А.5).

    ``cashflows`` is [(years_from_now, amount)]. The yield is solved against the
    DIRTY price and displayed beside the clean one; swapping the two makes the
    error the size of the accrued coupon. Non-convergence is reported, never
    approximated — `not_converged` is a fact, a wrong yield is not.
    """
    if not cashflows or dirty is None or dirty <= 0:
        return _unavailable()
    rate = guess
    for _ in range(max_iterations):
        value = _pv(cashflows, rate) - dirty
        derivative = sum(-t * cf / (1.0 + rate) ** (t + 1) for t, cf in cashflows)
        if derivative == 0 or not math.isfinite(derivative):
            break
        step = value / derivative
        rate -= step
        if not math.isfinite(rate) or rate <= -0.999:
            break
        if abs(step) < tolerance:
            return _metric(rate * 100.0, "ok", iterations=_, basis=day_count_basis())
    return _metric(None, "not_converged",
                   note="уравнение доходности не сошлось за 100 итераций")


def macaulay_duration(cashflows: Sequence[tuple[float, float]], dirty: float,
                      ytm_pct: float | None) -> dict[str, Any]:
    if not cashflows or not dirty or ytm_pct is None:
        return _unavailable()
    y = ytm_pct / 100.0
    weighted = sum(t * cf / (1.0 + y) ** t for t, cf in cashflows)
    return _metric(weighted / dirty, "ok")


def modified_duration(macaulay: float | None, ytm_pct: float | None,
                      frequency: int | None) -> dict[str, Any]:
    if macaulay is None or ytm_pct is None:
        return _unavailable()
    freq = int(frequency or 1) or 1
    return _metric(macaulay / (1.0 + (ytm_pct / 100.0) / freq), "ok")


def spread_to_key_rate(ytm_pct: float | None, key_rate_pct: Any) -> dict[str, Any]:
    key = _num(key_rate_pct)
    if ytm_pct is None or key is None:
        return _unavailable("нет ключевой ставки" if ytm_pct is not None else NO_REFERENCE_NOTE)
    return _metric(ytm_pct - key, "ok", key_rate=key)


def coupon_cashflows(reference: dict[str, Any], coupons: Iterable[dict[str, Any]],
                     today: date | None = None) -> list[tuple[float, float]]:
    """Remaining coupons plus redemption, as (years_from_today, amount)."""
    today = today or date.today()
    basis = day_count_basis()
    year_days = _days_in_year(basis, today)
    nominal = _num(reference.get("nominal")) or 0.0
    maturity = reference.get("maturity_date")
    if isinstance(maturity, str):
        try:
            maturity = date.fromisoformat(maturity[:10])
        except ValueError:
            maturity = None
    flows: list[tuple[float, float]] = []
    for coupon in coupons or []:
        pay = coupon.get("pay_date")
        if isinstance(pay, str):
            try:
                pay = date.fromisoformat(pay[:10])
            except ValueError:
                continue
        amount = _num(coupon.get("amount"))
        if not pay or amount is None or pay <= today:
            continue
        flows.append(((pay - today).days / year_days, amount))
    if maturity and maturity > today and nominal > 0:
        flows.append(((maturity - today).days / year_days, nominal))
    return sorted(flows)


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    # The three spellings this codebase carries: YYYY-MM-DD (registry), YYYYMMDD
    # (day statistics) and DD.MM.YYYY (live feed). A parser that knew only the
    # first read every statistics day as "no day" and silently took the branch
    # for "these stats belong to no session".
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    elif len(text) == 10 and text[2] == "." and text[5] == ".":
        text = f"{text[6:]}-{text[3:5]}-{text[:2]}"
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def apply_day_stats(row: dict[str, Any], stats: dict[str, Any] | None) -> dict[str, Any]:
    """Restate a feed row against the exchange's own day statistics.

    The quote feed and the day statistics are two feeds and they describe
    different sessions. The board screen has reconciled them since day one; the
    bond section never did, and it showed:

    * IQMK5B8 at its **3 April** price and April turnover — 101,92 млрд — while
      the statistics held its trade of today, 124,53 млрд at 1 037 753,42. Four
      months of staleness printed in the same column as this morning's prints.
    * «Сделки» empty for 15 of 17 issues. The feed carries no trade count for a
      bond at all; the statistics carry one for every single issue.

    Two rules, the same ones the board applies:

    * statistics OLDER than the row are ignored outright — a turnover from
      another week belongs to no quote on this page;
    * statistics NEWER than the row win the session: their close is the price,
      their day is the row's day, and the row's stale close IS the previous
      close, so the change is close-to-close, matching the daily bulletin.

    Returns a NEW row; the input is left alone.
    """
    if not stats:
        return row
    ts_day = _as_date(stats.get("trade_date"))
    if not ts_day:
        return row
    row_day = _as_date(row.get("last_trade_date")) or _as_date(row.get("close_date"))
    if row_day and ts_day < row_day:
        return row

    out = dict(row)
    for src, dst in (("total_value", "volume"), ("total_qty", "quantity"),
                     ("trade_count", "trade_count")):
        if stats.get(src) is not None:
            out[dst] = stats[src]
    if row_day and ts_day > row_day:
        # The session's own close, or its VWAP when the protocol filed no close
        # (the older statistics rows carry prices only in `avg_price`/`vwap`).
        close = stats.get("close_price")
        if close is None:
            close = stats.get("vwap") if stats.get("vwap") is not None else stats.get("avg_price")
        if close is not None:
            out["close_price"] = row.get("last_price")
            out["close_date"] = row.get("last_trade_date")
            out["last_price"] = close
        out["last_trade_date"] = ts_day.isoformat()
        for src, dst in (("open_price", "open"), ("high_price", "high"), ("low_price", "low")):
            if stats.get(src) is not None:
                out[dst] = stats[src]
    return out


def _days_since_coupon(reference: dict[str, Any], coupons: Sequence[dict[str, Any]] | None,
                       freq: int, today: date) -> float | None:
    """Days of coupon earned and not yet paid.

    Counted from the last coupon the issuer has actually filed. Filings arrive
    per payment, so the newest one can be older than a full period — the issuer
    simply has not filed the next yet. Since the coupon is periodic by the
    formula in the decision itself, the elapsed time is folded back into the
    current period rather than reported as months of accrual, which would put
    the accrued interest above a whole coupon.
    """
    explicit = _num(reference.get("days_from_coupon"))
    if explicit is not None:
        return explicit
    paid = sorted(d for d in (_as_date(c.get("pay_date")) for c in coupons or []) if d and d <= today)
    if not paid:
        return None
    period = 365.0 / max(freq, 1)
    elapsed = (today - paid[-1]).days
    return float(elapsed % period) if period else float(elapsed)


# ---------------------------------------------------------------------------
# The row the bonds table shows
# ---------------------------------------------------------------------------

def bond_row(row: dict[str, Any], meta: dict[str, Any] | None = None,
             quality: dict[str, Any] | None = None,
             reference: dict[str, Any] | None = None,
             coupons: Sequence[dict[str, Any]] | None = None,
             key_rate: Any = None, today: date | None = None,
             stats: dict[str, Any] | None = None,
             board_day: date | None = None) -> dict[str, Any]:
    """One issue: what is computable today, and a reason for what is not."""
    meta = meta or {}
    row = apply_day_stats(row, stats)
    ref_state = reference_state(reference)
    price = _num(row.get("last_price"))
    prev = _num(row.get("close_price"))
    change = ((price - prev) / prev * 100.0) if (price and prev and prev > 0) else None
    traded = (_num(row.get("trade_count")) or 0) > 0 or (_num(row.get("volume")) or 0) > 0
    session_day = _as_date(row.get("last_trade_date"))

    out: dict[str, Any] = {
        "ticker": str(row.get("ticker") or "").upper(),
        "isin": row.get("isin") or meta.get("isin"),
        "name": row.get("name") or meta.get("name"),
        "issuer": meta.get("name"),
        "type": "bond",
        "share_class": "bond",
        "price": price,
        "change_pct": change,
        "turnover": _num(row.get("volume")),
        "trades": _num(row.get("trade_count")),
        "quantity": _num(row.get("quantity")),
        # The value of the issue, kept as its own line. It is NOT part of the
        # equity market's capitalisation and may never be summed into it.
        "issue_value": _num(row.get("market_cap")),
        # WHICH session this row is. Five of the seventeen issues last traded
        # days or months ago, and with no date beside them every one read as
        # this morning's — a four-month-old turnover in the same column as a
        # live one. `is_current` is that comparison made once, here, rather
        # than left for each reader of the payload to make differently.
        "last_trade_date": (session_day.isoformat() if session_day else None),
        "is_current": (None if not (session_day and board_day)
                       else session_day >= board_day),
        "quality": quality,
        "reference": ref_state,
        # ТЗ А.2: equity multiples are structurally unavailable for a bond —
        # the fields are absent, not null. A null invites "we could not compute
        # it"; absence says the question does not apply.
        "multiples": {"available": False, "reason": "долговой инструмент"},
        "day_count_basis": day_count_basis(),
    }

    if price is None:
        out["status"] = "no_price" if traded else "not_traded"
        out["reason"] = ("нет последней цены при наличии сделок" if traded
                         else "нет сделок за торговый день")
    else:
        out["status"] = "ok"
        out["reason"] = None

    reference = reference or {}
    nominal = _num(reference.get("nominal"))
    rate = _num(reference.get("coupon_rate"))
    freq = int(_num(reference.get("coupon_freq")) or 1) or 1
    maturity = _as_date(reference.get("maturity_date"))
    today = today or date.today()

    # Stage one — the par, which the exchange publishes. Price as a percentage
    # of par depends on it and on nothing else: 105 310 in one issue and
    # 10 062 465 in another are not comparable numbers, 105.3% and 100.6% are.
    out["price_pct"] = (price_pct(price, nominal) if ref_state["has_nominal"]
                        else _unavailable(missing=ref_state["missing"] or None))

    # A filed redemption date in the past explains a missing price better than
    # "no trades" does — ACMT1B2 stopped printing because it is being redeemed.
    matured = bool(maturity and maturity <= today)
    if matured:
        out["status"] = "matured"
        out["reason"] = f"выпуск погашается с {maturity.isoformat()}"

    # Stage two — the coupon, which the issuer files payment by payment. It
    # needs no maturity: what a bond has earned since its last coupon is
    # knowable years before anyone files a redemption date.
    if not ref_state["has_coupon"]:
        for field in ("accrued", "clean", "dirty", "simple_yield", "ytm",
                      "duration", "modified_duration", "spread"):
            out[field] = _unavailable(missing=ref_state["missing"] or None)
        return out

    # Accrual stops at redemption. Past its maturity ACMT1B2 was still earning
    # a coupon on this page — 19 days of it — for an issue whose principal had
    # already been paid back. There is no accrual to state after that date, and
    # a number there is worse than a dash.
    days_from_coupon = None if matured else _days_since_coupon(reference, coupons, freq, today)
    accrued = (accrued_interest(nominal, rate, days_from_coupon, when=today)
               if days_from_coupon is not None
               else (_matured(maturity) if matured
                     else _unavailable("нет даты последней купонной выплаты")))
    clean = price
    dirty = dirty_price(clean, accrued.get("value"))
    out.update({
        "accrued": accrued,
        "clean": _metric(clean, "ok") if clean is not None else _unavailable("нет цены"),
        "dirty": _metric(dirty, "ok") if dirty is not None else _unavailable("нет цены"),
        "simple_yield": simple_yield((nominal or 0) * (rate or 0) / 100.0, price),
    })

    # Stage three — the maturity, which exists only once the issuer files the
    # redemption window. Without it there are no cashflows to discount, and a
    # term reconstructed from "N days after placement began" lands days away
    # from the filed date — near enough to look right and not near enough to be.
    if not ref_state["is_complete"]:
        for field in ("ytm", "duration", "modified_duration", "spread"):
            out[field] = _unavailable(missing=ref_state["missing"] or None)
        return out

    # A redeemed issue has no cashflows left, so there is nothing to discount —
    # and the reason must SAY that. It used to fall through to the solver, come
    # back empty-handed and report «нет справочных данных по выпуску» about the
    # one issue on the board whose reference is complete.
    if matured:
        for field in ("ytm", "duration", "modified_duration", "spread"):
            out[field] = _matured(maturity)
        return out

    flows = coupon_cashflows(reference, coupons or [], today)
    ytm = yield_to_maturity(flows, dirty) if dirty else _unavailable()
    duration = macaulay_duration(flows, dirty, ytm.get("value")) if dirty else _unavailable()
    out.update({
        "ytm": ytm,
        "duration": duration,
        "modified_duration": modified_duration(duration.get("value"), ytm.get("value"), freq),
        "spread": spread_to_key_rate(ytm.get("value"), key_rate),
    })
    return out


def build_bond_board(board: Iterable[dict[str, Any]],
                     securities: dict[str, dict[str, Any]] | None = None,
                     references: dict[str, dict[str, Any]] | None = None,
                     coupons: dict[str, list[dict[str, Any]]] | None = None,
                     quality: dict[str, dict[str, Any]] | None = None,
                     key_rate: Any = None,
                     stats: dict[str, dict[str, Any]] | None = None,
                     board_day: date | None = None) -> dict[str, Any]:
    """The bond section of the market screen.

    ``stats`` is the exchange's day statistics keyed by ISIN — the same store the
    board screen reconciles its rows against. Passing them here is what stops
    this section from printing one issue's April session next to another's this
    morning, and what fills the trade count the quote feed never carries for a
    bond.
    """
    securities = securities or {}
    references = references or {}
    stats = stats or {}
    rows = []
    for row in board:
        ticker = str(row.get("ticker") or "").upper()
        meta = securities.get(ticker) or {}
        if not is_bond(row, meta):
            continue
        isin = str(row.get("isin") or meta.get("isin") or "")
        # The statistics are keyed by the ISIN as the store spells it; the board
        # row may spell it either way, so try both rather than lose the join.
        day_stats = stats.get(isin) or stats.get(isin.upper()) or stats.get(isin.lower())
        rows.append(bond_row(row, meta, (quality or {}).get(ticker),
                             references.get(ticker), (coupons or {}).get(ticker), key_rate,
                             stats=day_stats, board_day=board_day))
    rows.sort(key=lambda r: r["ticker"])
    # The board's own day, as the ROWS report it — so «за сессию» on this
    # section means the same session the rows do, even when the caller passes
    # nothing. Recomputed after the statistics are applied, since applying them
    # is what can move a row forward to today.
    if board_day is None:
        days = [_as_date(r.get("last_trade_date")) for r in rows]
        board_day = max([d for d in days if d], default=None)
        for r in rows:
            day = _as_date(r.get("last_trade_date"))
            r["is_current"] = (day >= board_day) if (day and board_day) else None
    total_issue_value = sum(r["issue_value"] for r in rows if r.get("issue_value"))
    with_reference = sum(1 for r in rows if r["reference"]["is_complete"])
    with_nominal = sum(1 for r in rows if r["reference"].get("has_nominal"))
    with_coupon = sum(1 for r in rows if r["reference"].get("has_coupon"))
    return {
        "count": len(rows),
        "items": rows,
        # Reported separately and labelled: this is not equity capitalisation.
        "issue_value_total": total_issue_value,
        "issue_value_note": "стоимость выпусков, не капитализация акционерного рынка",
        "with_reference": with_reference,
        # Three counters, because the contour turns on in three stages: the par
        # comes from the exchange, the coupon from the issuer's payment filings,
        # and the maturity only once a redemption window is filed.
        "with_nominal": with_nominal,
        "with_coupon": with_coupon,
        # The session the rows are read against, and how many of them are not
        # from it. A section whose rows span April to today has to say so; the
        # alternative is a reader taking every line for this morning.
        "board_day": board_day.isoformat() if board_day else None,
        "traded_today": sum(1 for r in rows if r.get("is_current")),
        "stale": sum(1 for r in rows if r.get("is_current") is False),
        "day_count_basis": day_count_basis(),
    }

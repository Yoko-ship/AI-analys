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

**And the other half is published too — on a page nobody had read.** The
exchange keeps a register of circulating issues at ``/abouts/bonds/``
(«Облигации доступные на торгах фондовой биржи»), and it states, per issue, the
coupon rate, the payment cycle, the placement date and the redemption date —
all 65 of them. ``bond_registry`` reads it. What was left inert here is
therefore live: accrued interest, yield to maturity, duration, convexity, BPV
and the spread to the ГЦБ curve now compute for every issue whose terms the
register carries.

Two rules keep that from becoming an invention:

* **The schedule is reconstructed, and says so.** The register gives the two
  ends and the cycle, not the dates in between, so the payment dates are laid
  evenly from placement to redemption. Every payload that rests on them carries
  ``schedule_source: "reconstructed"``; where the issuer has actually filed the
  payments, it says ``"filed"`` instead.
* **A registered undertaking is not an executed fact.** The register states
  what the issuer promised; openinfo's material fact #31 states what it did.
  Where both exist the filing wins, and ``maturity_source``/``coupon_source``
  name which one the number came from.

Inventing a coupon "because the issue looks like the others" remains the same
class of error as interpolating a gap in a price series — nothing here does it,
and an issue the register does not carry keeps its dash and its reason.
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
            #
            # A rate of ZERO is a rate. The register states «0,00%» for the five
            # UMRC SPV series, whose whole return is the discount to par — and a
            # truth test on the rate read that as "no coupon disclosed" and
            # withheld their yields, which are the most computable on the board.
            "has_coupon": nominal is not None and nominal > 0 and rate is not None,
            # The terms themselves, so a reader can see WHAT was found and not
            # only that something was: a 28% coupon is the answer to "why is
            # this trading at 120% of par", and it belongs on the screen.
            "nominal": nominal,
            "coupon_rate": rate,
            # A detected-but-unstated kind ("floating") is itself information:
            # the column shows «плав.» instead of a dash that reads as silence.
            "coupon_type": reference.get("coupon_type"),
            "coupon_freq": _num(reference.get("coupon_freq")),
            "float_base": reference.get("float_base"),
            "maturity_date": reference.get("maturity_date"),
            "issue_date": reference.get("issue_date"),
            # Rule 1 of the section: a term carries the source that states it.
            # «Раскрыто эмитентом» (a filed material fact) and «реестр биржи»
            # (a registered undertaking) are different strengths of evidence and
            # the interface is not allowed to blur them.
            "coupon_source": reference.get("coupon_source"),
            "maturity_source": reference.get("maturity_source"),
            # How many securities the issue IS, as registered — a different size
            # from what they are worth today, and the one the regulator states.
            "issue_volume": _num(reference.get("issue_volume")),
            # And how many of them found a buyer: the register states both, and
            # they differ wherever a placement is unfinished.
            "placed_volume": _num(reference.get("placed_volume")),
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


def convexity(cashflows: Sequence[tuple[float, float]], dirty: float | None,
              ytm_pct: float | None) -> dict[str, Any]:
    """Second-order price sensitivity — the correction duration alone misses."""
    if not cashflows or not dirty or ytm_pct is None:
        return _unavailable()
    y = ytm_pct / 100.0
    weighted = sum(t * (t + 1.0) * cf / (1.0 + y) ** (t + 2.0) for t, cf in cashflows)
    return _metric(weighted / dirty, "ok")


def bpv(mod_duration: float | None, dirty: float | None) -> dict[str, Any]:
    """Price change of one bond for a 1 b.p. move, in the bond's own currency."""
    if mod_duration is None or not dirty:
        return _unavailable()
    return _metric(mod_duration * dirty * 1e-4, "ok")


# ---------------------------------------------------------------------------
# The ГЦБ base curve (primary-market auctions, cbu.uz fiscal agent)
# ---------------------------------------------------------------------------

# An auction older than this no longer describes today's curve. Six months
# covers the Ministry's monthly cadence with room for a skipped auction, while
# keeping a two-year-old 12-month rate from posing as current.
GOV_CURVE_WINDOW_DAYS = 200


def gov_curve_points(auctions: Iterable[dict[str, Any]],
                     today: date | None = None,
                     window_days: int = GOV_CURVE_WINDOW_DAYS) -> list[dict[str, Any]]:
    """The freshest weighted-average rate per tenor, one point per term.

    The fiscal agent places two tenors a month (364 and 1 095 days of late,
    other terms in earlier years). The curve takes each tenor's LATEST auction
    inside the window — a curve mixing this month's 3-year with last year's
    1-year would carry two different monetary regimes as one line.
    """
    today = today or date.today()
    best: dict[int, tuple[date, dict[str, Any]]] = {}
    for auction in auctions or []:
        term, rate = _num(auction.get("term_days")), _num(auction.get("wavg_rate"))
        day = _as_date(auction.get("auction_date"))
        if not term or term <= 0 or rate is None or not day:
            continue
        if (today - day).days > window_days:
            continue
        held = best.get(int(term))
        if held is None or day > held[0]:
            best[int(term)] = (day, auction)
    return [{"term_days": term, "rate": _num(a.get("wavg_rate")),
             "auction_date": day.isoformat(), "sec_id": a.get("sec_id"),
             "isin": a.get("isin")}
            for term, (day, a) in sorted(best.items())]


def gov_curve_yield(years: float | None, points: Sequence[dict[str, Any]]) -> float | None:
    """Linear interpolation on the auction tenors, clamped at the ends.

    Clamped, not extrapolated: beyond the last auctioned tenor there is no
    market evidence, and a straight line extended past it manufactures some.
    """
    if years is None or not points:
        return None
    days = years * 365.0
    usable = [(float(p["term_days"]), float(p["rate"])) for p in points
              if _num(p.get("term_days")) and _num(p.get("rate")) is not None]
    if not usable:
        return None
    usable.sort()
    if days <= usable[0][0]:
        return usable[0][1]
    if days >= usable[-1][0]:
        return usable[-1][1]
    for (t0, r0), (t1, r1) in zip(usable, usable[1:]):
        if t0 <= days <= t1:
            return r0 + (r1 - r0) * (days - t0) / (t1 - t0) if t1 > t0 else r0
    return None


def g_spread(ytm_pct: float | None, years: float | None,
             points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Yield over the ГЦБ curve at the bond's own horizon, in percentage points."""
    if ytm_pct is None:
        return _unavailable()
    base = gov_curve_yield(years, points)
    if base is None:
        return _metric(None, "no_curve", note="нет данных аукционов ГЦБ")
    return _metric(ytm_pct - base, "ok", curve_rate=base, term_years=years)


def _add_months(when: date, months: int) -> date:
    """Calendar-month arithmetic, clamped to the month's last day.

    The 31st plus one month is the 30th, not the 1st of the month after: an
    issue that pays on the 31st does not skip February.
    """
    total = when.year * 12 + (when.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = [31, 29 if (year % 4 == 0 and (year % 100 or year % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(when.day, last))


def coupon_schedule(reference: dict[str, Any],
                    coupons: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every payment date of the issue, from placement to redemption.

    The exchange's register states the two ends and the cycle — «Har chorakda»,
    «Har oyda» — never the dates in between. So the periods are laid evenly
    across the issue's life: ``n = round(life_days / 365 * freq)`` payments, the
    i-th falling ``round(life_days * i / n)`` days after placement. That is a
    **reconstruction**, and the return says so.

    Where the issuer has filed its payments on openinfo the filed dates are used
    instead — they are the fact the reconstruction approximates. A filing set
    that stops short of the redemption date is still only a partial schedule
    (issuers file one payment at a time), so it is used as the schedule only
    when it reaches the maturity; otherwise the reconstruction runs and the
    filed dates correct it where the two line up.

    Returns ``{"dates": [date], "source": "filed"|"reconstructed"|None,
    "amount": float|None, "freq": int|None}`` — ``amount`` being one coupon per
    security, ``nominal × rate / 100 / freq``.
    """
    nominal = _num(reference.get("nominal"))
    rate = _num(reference.get("coupon_rate"))
    freq = int(_num(reference.get("coupon_freq")) or 0)
    issue = _as_date(reference.get("issue_date"))
    maturity = _as_date(reference.get("maturity_date"))
    amount = (nominal * rate / 100.0 / freq) if (nominal and rate and freq) else None
    today = date.today()
    # HOW a period is stepped is published, and it is not always 365/freq. The
    # register writes «Har oyda» for a calendar month and «Har 30 kunda» for
    # thirty days, and the issuers' own filings bear the difference out:
    # ACMT1B3 has paid on the 11th–13th of every month for a year, while
    # DMMT2B3's payments walk back a day a month exactly as "every 30 days"
    # implies. Over three years the two are a fortnight apart.
    basis = str(reference.get("coupon_basis") or "").lower()
    period_days = _num(reference.get("coupon_period_days"))
    months = (12 // freq) if (basis == "calendar" and freq and 12 % freq == 0) else None

    filed = sorted({d for d in (_as_date(c.get("pay_date")) for c in coupons or []) if d})
    if filed and maturity and filed[-1] >= maturity - timedelta(days=5):
        return {"dates": filed, "source": "filed", "amount": amount, "freq": freq or None}

    if maturity and freq > 0 and not issue and maturity > today:
        # No placement date, but a redemption date and a cycle: the periods are
        # counted BACKWARDS from redemption, one step of 365/freq at a time, as
        # far back as the period the issue is in now. That is every payment a
        # yield needs plus the boundary the accrual runs from — and not one date
        # further, because how long the paper has existed is genuinely unknown
        # and a count reaching back to an invented placement would be fiction.
        step_days = period_days or (365.0 / freq)
        dates: list[date] = []
        i = 0
        while i <= 1000:
            when = (_add_months(maturity, -(12 // freq) * i)
                    if (basis == "calendar" and 12 % freq == 0)
                    else maturity - timedelta(days=round(step_days * i)))
            dates.append(when)
            if when <= today:
                break
            i += 1
        return {"dates": sorted(d for d in dates if d > min(dates)) or [maturity],
                "source": "reconstructed", "partial": True,
                "amount": amount, "freq": freq}

    if not (issue and maturity and freq > 0 and maturity > issue):
        # No two ends, no schedule. The filed payments are still a list of
        # payments — just not one that reaches redemption.
        return {"dates": filed, "source": "filed" if filed else None,
                "amount": amount, "freq": freq or None}

    life = (maturity - issue).days
    n = max(1, round(life / 365.0 * freq))
    step = life / n

    def advance(start: date, periods: int) -> date:
        if months:
            return _add_months(start, months * periods)
        return start + timedelta(days=round((period_days or step) * periods))

    # An even split from the placement date is only a first guess at WHERE in
    # the month the payments fall. ACMT2B5 was placed on 6 May and pays on the
    # 22nd — filed twice, seventeen days off the even split — so a schedule
    # anchored on placement alone put every future coupon two weeks early and
    # then reported that the issuer had filed none of them.
    #
    # Where the issuer HAS filed payments, the newest one anchors the run: the
    # periods are stepped out from it in both directions. The redemption date
    # stays pinned regardless, because the principal falls due on the date the
    # register states and not on a multiple of a period.
    # The run is grown from its anchor in both directions and stops where a
    # period would be a stub — rather than a fixed count laid down in advance.
    # A count assumed 365/freq periods evenly; a calendar month is not 30,42
    # days and «every 30 days» is not a month, and either assumption left a
    # short payment glued to one end of the schedule.
    # Only a filing that falls inside the issue's own life may anchor it.
    # ACMT2B4 carries a payment dated a year before its own placement — a
    # mis-joined series — and anchoring on it walked the whole schedule back
    # into the year before the bond existed.
    inside = [d for d in filed if issue < d < maturity]
    anchor = max(inside) if inside else advance(issue, 1)
    half = step / 2
    # A filing numbered 1 is the issuer saying "this was the first" — so the
    # walk backwards stops AT it instead of inventing a short period in front
    # of it. ACMT2B5's first coupon fell 46 days after placement; without this
    # the reconstruction put a sixteen-day stub before it.
    first = min((d for d in (_as_date(c.get("pay_date")) for c in coupons or []
                             if _num(c.get("coupon_no")) == 1) if d), default=None)
    floor = first if (first and issue < first < maturity) else None

    dates: list[date] = []
    for direction, start in ((-1, 0), (1, 1)):
        i = start
        while i <= 1000:
            when = advance(anchor, direction * i)
            if when <= issue or when > maturity:
                break
            if floor and when < floor:
                break
            if floor is None and (when - issue).days < half:
                break
            if when < maturity and (maturity - when).days < half:
                if direction > 0:
                    break
                i += 1
                continue
            if when < maturity:
                dates.append(when)
            i += 1
    dates = sorted(set(dates)) + [maturity]

    # A filed payment is a fact and takes the slot nearest to it, however far
    # the guess had drifted: BFMT3V2 paid on the 29th in its first winter and
    # on the 13th two years later, and a fixed window declared its own filings
    # unmatched. Each filing claims a distinct slot — never the redemption,
    # which the register states outright — so two of them cannot collapse into
    # one period.
    claimed: set[int] = set()
    for one in sorted(filed):
        if not (issue <= one < maturity):
            continue
        order = sorted((i for i in range(len(dates) - 1) if i not in claimed),
                       key=lambda i: abs((one - dates[i]).days))
        if order:
            dates[order[0]] = one
            claimed.add(order[0])
    return {"dates": sorted(set(dates)), "source": "reconstructed",
            "amount": amount, "freq": freq}


def effective_yield_at_par(rate: Any, freq: Any) -> dict[str, Any]:
    """What the coupon alone returns at a price of par, compounded.

    A 27% coupon paid monthly is not 27% a year to a holder who reinvests: it is
    ``(1 + 0.27/12)^12 − 1`` = 30,6%. Half the register's issues pay monthly, so
    the difference between the headline rate and what the paper actually yields
    at par is worth its own column — and it is the only yield figure that exists
    for an issue nobody has traded yet.
    """
    r, f = _num(rate), _num(freq)
    if r is None or not f or f <= 0:
        return _unavailable("нет ставки или периодичности купона")
    if r == 0:
        return _metric(0.0, "ok", note="бескупонный выпуск")
    return _metric((math.pow(1 + r / 100.0 / f, f) - 1) * 100.0, "ok")


def realized_return(reference: dict[str, Any], schedule: dict[str, Any],
                    today: date | None = None) -> dict[str, Any]:
    """A redeemed issue's return over its life, at par in and par out.

    Replaces the yield block on a matured issue rather than leaving it blank:
    the question "what did this pay" has an answer once the paper is gone, and
    it is not the same question as "what will it pay".

    Two assumptions, both stated in the note the metric carries, because either
    one silently changed turns this into a different number: the holder **bought
    at par** (no purchase price is recorded per holder) and **did not reinvest**
    the coupons (nothing records what they did with them). Compounding the
    coupons at the coupon rate would print the effective-at-par figure back at
    the reader and call it a realised result.
    """
    today = today or date.today()
    nominal = _num(reference.get("nominal"))
    issue = _as_date(reference.get("issue_date"))
    maturity = _as_date(reference.get("maturity_date"))
    amount = schedule.get("amount")
    if not (nominal and issue and maturity and maturity > issue):
        return _unavailable("нет дат размещения и погашения")
    paid = [d for d in schedule.get("dates") or [] if d <= min(today, maturity)]
    total = (amount or 0.0) * len(paid)
    years = (maturity - issue).days / 365.0
    if years <= 0 or nominal <= 0:
        return _unavailable("срок обращения не определён")
    return _metric((math.pow((nominal + total) / nominal, 1 / years) - 1) * 100.0, "ok",
                   note=(f"{len(paid)} купонов на {total:.0f} сум плюс номинал; "
                         "покупка по номиналу, купоны не реинвестируются"),
                   coupons_paid=len(paid), coupons_total=total, years=years)


def coupon_cashflows(reference: dict[str, Any], coupons: Iterable[dict[str, Any]],
                     today: date | None = None,
                     schedule: dict[str, Any] | None = None) -> list[tuple[float, float]]:
    """Remaining coupons plus redemption, as (years_from_today, amount).

    Built from the issue's schedule when there is one. Before the register was
    read, this discounted only the coupons an issuer had already ANNOUNCED —
    typically the next one alone — against the full redemption of principal,
    which understates the stream and overstates nothing honestly: a three-year
    bond was priced as if it paid one coupon and then the par. With the whole
    schedule the yield is the yield.
    """
    today = today or date.today()
    basis = day_count_basis()
    year_days = _days_in_year(basis, today)
    nominal = _num(reference.get("nominal")) or 0.0
    maturity = _as_date(reference.get("maturity_date"))
    schedule = schedule if schedule is not None else coupon_schedule(reference, list(coupons or []))
    amount = schedule.get("amount")

    filed_amounts = {}
    for coupon in coupons or []:
        pay, value = _as_date(coupon.get("pay_date")), _num(coupon.get("amount"))
        if pay and value is not None:
            filed_amounts[pay] = value

    flows: list[tuple[float, float]] = []
    for pay in schedule.get("dates") or []:
        if pay <= today:
            continue
        value = filed_amounts.get(pay, amount)
        if value is None:
            continue
        flows.append(((pay - today).days / year_days, value))
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
    # A day whose only executions were negotiated deals is NOT a session: the
    # exchange's bulletin says nothing traded, and a bilaterally agreed price
    # must not become the row's close. IQMK5B8 13.08.2026 was exactly this —
    # one T1 deal of 120 000 bonds at 1 069 393,45 printed as the market price.
    # The deal itself stays visible through the block_* fields below.
    if not ((_num(stats.get("total_qty")) or 0) > 0 or (_num(stats.get("trade_count")) or 0) > 0):
        out = dict(row)
        if _num(stats.get("block_value")):
            out["block_value"] = _num(stats.get("block_value"))
            out["block_qty"] = _num(stats.get("block_qty"))
            out["block_date"] = ts_day.isoformat()
        return out

    out = dict(row)
    # The day's negotiated deals, apart from the session — real money, not a
    # market price; shown as its own line, never summed into the turnover.
    if _num(stats.get("block_value")):
        out["block_value"] = _num(stats.get("block_value"))
        out["block_qty"] = _num(stats.get("block_qty"))
        out["block_date"] = ts_day.isoformat()
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
                       freq: int, today: date,
                       schedule: dict[str, Any] | None = None) -> float | None:
    """Days of coupon earned and not yet paid.

    Counted from the most recent evidence that a period closed: the last
    payment the issuer filed, or the last date of the issue's schedule, or the
    placement itself for an issue whose first coupon has not come due. The
    latest of those is the one that counts — a filing that has gone quiet must
    not hold the accrual open for months.

    Where nothing but stale filings exist the elapsed time is still folded back
    into one period, because the coupon is periodic by the formula in the
    decision itself and months of accrual would put the accrued interest above
    a whole coupon.
    """
    explicit = _num(reference.get("days_from_coupon"))
    if explicit is not None:
        return explicit
    marks = [d for d in (_as_date(c.get("pay_date")) for c in coupons or []) if d and d <= today]
    if schedule:
        marks += [d for d in schedule.get("dates") or [] if d <= today]
        issue = _as_date(reference.get("issue_date"))
        # Between placement and the first coupon the accrual runs from placement.
        if issue and issue <= today:
            marks.append(issue)
    if not marks:
        return None
    period = 365.0 / max(freq, 1)
    elapsed = (today - max(marks)).days
    return float(elapsed) if elapsed < period else float(elapsed % period)


# ---------------------------------------------------------------------------
# The row the bonds table shows
# ---------------------------------------------------------------------------

def _bond_row_unchecked(row: dict[str, Any], meta: dict[str, Any] | None = None,
             quality: dict[str, Any] | None = None,
             reference: dict[str, Any] | None = None,
             coupons: Sequence[dict[str, Any]] | None = None,
             key_rate: Any = None, today: date | None = None,
             stats: dict[str, Any] | None = None,
             board_day: date | None = None,
             gov_points: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
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
        # The day's negotiated deals, carried through from the statistics —
        # real money at an off-book price, shown beside the session and never
        # summed into it.
        "block_value": _num(row.get("block_value")),
        "block_qty": _num(row.get("block_qty")),
        "block_date": row.get("block_date"),
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
    issue_day = _as_date(reference.get("issue_date"))
    today = today or date.today()
    schedule = coupon_schedule(reference, list(coupons or []))
    dates = schedule.get("dates") or []
    paid_dates = [d for d in dates if d <= today]
    future_dates = [d for d in dates if d > today]

    # What the coupon returns at par, compounded at the issue's own frequency.
    # It needs no price, so it is the one yield figure an untraded issue has —
    # and forty-odd of the sixty-five have never printed a trade.
    out["effective_at_par"] = effective_yield_at_par(rate, reference.get("coupon_freq"))
    out["schedule"] = {
        "source": schedule.get("source"),
        # Counted backwards from redemption because no placement date is
        # published: these are every payment a yield needs, but NOT the issue's
        # whole life, and a screen must not print them as «всего N периодов».
        "partial": bool(schedule.get("partial")) or None,
        "freq": schedule.get("freq"),
        "amount": schedule.get("amount"),
        "total": len(dates) or None,
        "paid": len(paid_dates) if dates else None,
        "left": len(future_dates) if dates else None,
        "issue_date": issue_day.isoformat() if issue_day else None,
        "next_date": future_dates[0].isoformat() if future_dates else None,
        "last_paid_date": paid_dates[-1].isoformat() if paid_dates else None,
    }
    # Five states, and each one changes which blocks are worth drawing:
    # a redeemed issue has no yield to show but does have a result.
    out["state"] = ("matured" if (maturity and maturity <= today)
                    else "placing" if (issue_day and issue_day > today)
                    else "last" if len(future_dates) == 1
                    else "live")

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
                      "duration", "modified_duration", "spread",
                      "convexity", "bpv", "g_spread"):
            out[field] = _unavailable(missing=ref_state["missing"] or None)
        return out

    # Accrual stops at redemption. Past its maturity ACMT1B2 was still earning
    # a coupon on this page — 19 days of it — for an issue whose principal had
    # already been paid back. There is no accrual to state after that date, and
    # a number there is worse than a dash.
    days_from_coupon = (None if matured
                        else _days_since_coupon(reference, coupons, freq, today, schedule))
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
        for field in ("ytm", "duration", "modified_duration", "spread",
                      "convexity", "bpv", "g_spread"):
            out[field] = _unavailable(missing=ref_state["missing"] or None)
        return out

    # A redeemed issue has no cashflows left, so there is nothing to discount —
    # and the reason must SAY that. It used to fall through to the solver, come
    # back empty-handed and report «нет справочных данных по выпуску» about the
    # one issue on the board whose reference is complete.
    if matured:
        for field in ("ytm", "duration", "modified_duration", "spread",
                      "convexity", "bpv", "g_spread"):
            out[field] = _matured(maturity)
        # What it DID return, in place of what it will: the issue's own result
        # over its life, rather than an empty block where a yield used to be.
        out["realized"] = realized_return(reference, schedule, today)
        return out

    flows = coupon_cashflows(reference, coupons or [], today, schedule)
    ytm = yield_to_maturity(flows, dirty) if dirty else _unavailable()
    duration = macaulay_duration(flows, dirty, ytm.get("value")) if dirty else _unavailable()
    mod = modified_duration(duration.get("value"), ytm.get("value"), 1)
    # The curve is read at the bond's own horizon — its duration when the solver
    # produced one, its remaining term otherwise.
    horizon = duration.get("value")
    if horizon is None and maturity:
        horizon = (maturity - today).days / 365.0
    out.update({
        "ytm": ytm,
        "duration": duration,
        "modified_duration": mod,
        "spread": spread_to_key_rate(ytm.get("value"), key_rate),
        "convexity": convexity(flows, dirty, ytm.get("value")),
        "bpv": bpv(mod.get("value"), dirty),
        "g_spread": g_spread(ytm.get("value"), horizon, gov_points or []),
    })
    return out


def bond_row(row: dict[str, Any], meta: dict[str, Any] | None = None,
             quality: dict[str, Any] | None = None,
             reference: dict[str, Any] | None = None,
             coupons: Sequence[dict[str, Any]] | None = None,
             key_rate: Any = None, today: date | None = None,
             stats: dict[str, Any] | None = None, board_day: date | None = None,
             gov_points: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    from bond_quality import apply_quality
    result = _bond_row_unchecked(row, meta, quality, reference, coupons, key_rate, today,
                                stats, board_day, gov_points)
    return apply_quality(result, reference or {}, list(coupons or []), today or date.today(), gov_points or [])


def issue_schedule(reference: dict[str, Any] | None,
                   coupons: Sequence[dict[str, Any]] | None = None,
                   today: date | None = None) -> list[dict[str, Any]]:
    """One issue's payments, past and future, ready to draw.

    The filed amount wins on any date the issuer has filed; every other date
    carries the periodic amount the terms imply, and says which of the two it
    is. ``paid`` is a statement about the calendar, not about the issuer: a date
    in the past is a payment that fell due, and only a filing proves it was met.
    """
    today = today or date.today()
    reference = reference or {}
    schedule = coupon_schedule(reference, list(coupons or []))
    amount = schedule.get("amount")
    nominal = _num(reference.get("nominal"))
    maturity = _as_date(reference.get("maturity_date"))
    filed: dict[date, dict[str, Any]] = {}
    for coupon in coupons or []:
        when = _as_date(coupon.get("pay_date"))
        if when:
            filed[when] = coupon
    out: list[dict[str, Any]] = []
    for n, when in enumerate(schedule.get("dates") or [], start=1):
        record = filed.get(when)
        value = _num((record or {}).get("amount"))
        out.append({
            "no": (record or {}).get("coupon_no", n),
            "date": when.isoformat(),
            "coupon": value if value is not None else amount,
            "principal": (nominal if (maturity and when == maturity and nominal) else None),
            "due": when <= today,
            "filed": record is not None,
            "source": "filed" if record is not None else schedule.get("source"),
        })
    return out


def market_cashflows(references: dict[str, dict[str, Any]] | None = None,
                     coupons: dict[str, list[dict[str, Any]]] | None = None,
                     today: date | None = None,
                     horizon_months: int = 14) -> dict[str, Any]:
    """Every future payment the market owes, issue by issue and month by month.

    One coupon per security times the number of securities placed, on every date
    of every issue's schedule, plus the redemption of principal on the last one.
    The register is what makes this possible at all: before it, the only future
    payment known was the one an issuer had already announced.

    Two sizes are published and they are not the same number — «QQ soni» is what
    was registered and «Joylashtirilgan QQ soni» is what found a buyer. The
    money that actually leaves the issuer follows the placed count, so that is
    the one used, falling back to the registered count where the register
    leaves the placed cell empty.
    """
    today = today or date.today()
    horizon_end = date(today.year + (today.month - 1 + horizon_months) // 12,
                       (today.month - 1 + horizon_months) % 12 + 1, 1)
    flows: list[dict[str, Any]] = []
    for ticker, reference in sorted((references or {}).items()):
        reference = reference or {}
        schedule = coupon_schedule(reference, (coupons or {}).get(ticker) or [])
        dates = schedule.get("dates") or []
        if not dates:
            continue
        per_security = schedule.get("amount")
        count = _num(reference.get("placed_volume")) or _num(reference.get("issue_volume"))
        nominal = _num(reference.get("nominal"))
        maturity = _as_date(reference.get("maturity_date"))
        for when in dates:
            if when <= today or when >= horizon_end:
                continue
            coupon_sum = (per_security or 0.0) * (count or 0.0)
            principal = ((nominal or 0.0) * (count or 0.0)
                         if (maturity and when == maturity) else 0.0)
            if coupon_sum <= 0 and principal <= 0:
                continue
            flows.append({
                "date": when.isoformat(),
                "ticker": str(ticker).upper(),
                "issuer": reference.get("issuer"),
                "coupon": coupon_sum or None,
                "principal": principal or None,
                "per_security": per_security,
                "securities": count,
                # A reconstructed date is a plan, not a diary entry, and the
                # calendar has to be readable as one.
                "source": schedule.get("source"),
            })
    flows.sort(key=lambda f: (f["date"], -(f["coupon"] or 0) - (f["principal"] or 0)))

    months: list[dict[str, Any]] = []
    index: dict[tuple[int, int], dict[str, Any]] = {}
    for i in range(horizon_months):
        year, month = divmod(today.month - 1 + i, 12)
        bucket = {"year": today.year + year, "month": month + 1,
                  "coupon": 0.0, "principal": 0.0, "issues": 0}
        index[(bucket["year"], bucket["month"])] = bucket
        months.append(bucket)
    tickers_by_month: dict[tuple[int, int], set[str]] = {}
    for flow in flows:
        key = (int(flow["date"][:4]), int(flow["date"][5:7]))
        bucket = index.get(key)
        if not bucket:
            continue
        bucket["coupon"] += flow["coupon"] or 0.0
        bucket["principal"] += flow["principal"] or 0.0
        tickers_by_month.setdefault(key, set()).add(flow["ticker"])
    for key, bucket in index.items():
        bucket["issues"] = len(tickers_by_month.get(key, ()))

    def total(days: int, field: str) -> float:
        limit = (today + timedelta(days=days)).isoformat()
        return sum(f[field] or 0.0 for f in flows if f["date"] <= limit)

    return {
        "today": today.isoformat(),
        "flows": flows,
        "months": months,
        "next": flows[0] if flows else None,
        "coupon_30d": total(30, "coupon"),
        "principal_30d": total(30, "principal"),
        "coupon_365d": total(365, "coupon"),
        "principal_365d": total(365, "principal"),
        "payments_30d": sum(1 for f in flows
                            if f["date"] <= (today + timedelta(days=30)).isoformat()),
        "payments_365d": sum(1 for f in flows
                             if f["date"] <= (today + timedelta(days=365)).isoformat()),
        "issues": len({f["ticker"] for f in flows}),
        "reconstructed": sum(1 for f in flows if f["source"] == "reconstructed"),
    }


def build_bond_board(board: Iterable[dict[str, Any]],
                     securities: dict[str, dict[str, Any]] | None = None,
                     references: dict[str, dict[str, Any]] | None = None,
                     coupons: dict[str, list[dict[str, Any]]] | None = None,
                     quality: dict[str, dict[str, Any]] | None = None,
                     key_rate: Any = None,
                     stats: dict[str, dict[str, Any]] | None = None,
                     board_day: date | None = None,
                     gov_points: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
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
                             stats=day_stats, board_day=board_day, gov_points=gov_points))

    # The board is the list of issues that TRADED; the exchange's register is
    # the list that EXISTS. Sixty-five are registered and about a sixth of them
    # print on any given day, so a section built from the board alone told a
    # reader that the other fifty do not exist rather than that nobody has
    # bought one lately. They come in with no price — every term they have is
    # real, and the yield at par is computable without a trade.
    seen = {r["ticker"] for r in rows}
    for ticker, reference in sorted((references or {}).items()):
        ticker = str(ticker or "").upper()
        if ticker in seen or not reference:
            continue
        meta = securities.get(ticker) or {}
        rows.append(bond_row({"ticker": ticker, "type": "bond",
                              "isin": reference.get("isin") or meta.get("isin"),
                              "name": reference.get("issuer") or meta.get("name")},
                             meta, (quality or {}).get(ticker), reference,
                             (coupons or {}).get(ticker), key_rate,
                             board_day=board_day, gov_points=gov_points))
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
        "day_count_basis": None,
        "day_count_policy": "per_issue_disclosed_basis",
        "active_issues": sum(1 for r in rows if r.get("state") in {"live", "last"}),
        "with_trades": sum(1 for r in rows if r.get("quote_as_of")),
        "with_calculable_yield": sum(1 for r in rows if (r.get("ytm") or {}).get("value") is not None),
    }

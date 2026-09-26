"""bond_terms.py — the coupon and the redemption date, from openinfo material facts.

ТЗ Дополнение 1 §А.3 recorded that no endpoint publishes a coupon rate or a
maturity date, and the yield half of the bond contour was built inert on that.
The par turned out to be published by the exchange (``listings_collector.
collect_bond_reference_rows``). The rest is published too — by the issuer, as
material facts, never as a document. The prospectus («Эмиссия рисоласи») is only
*referenced* as an annex to the issue decision; no filing carries a file URL.

What each filing carries:

* **#25 «Выпуск ценных бумаг»** — structured: ``nominal_paper_cost``,
  ``paper_num``, ``paper_type`` (3 = облигация), ``num_registration``,
  ``date_registration``, ``date_decision``.
* **#32 «Начисление доходов по ценным бумагам»** — structured, one filing per
  coupon: ``sum_per`` (сум per one security), ``percentage_nominal`` and the
  payment window ``start/end_date_other_securities``.
* **#31 «Сроки исполнения обязательств по выкупу (погашению)»** — structured
  redemption window ``date_begin``/``date_end``.
* #6 «Решения ВОУ» states the rate and the term in PROSE, in Russian or in
  Uzbek in either alphabet. It is read here only as a cross-check, never as the
  source: BFMT3B4 has two same-day #6 filings whose terms disagree (720 vs 1080
  days) and whose prose says 27% where the accruals say 28%.

The exchange register supplies contractual rates and payment cycles. Accruals
corroborate those terms through ``N * C * days / 365`` before any rate is
inferred from announcement spacing. Monthly, quarterly and annual coupons must
use their own period; missing announcements do not lengthen that period.

This module supplies a maturity only from #31. Otherwise the collector keeps
the exchange register's maturity and placement dates. A registration date is
not a placement date, and an elapsed accrual window is not proof of payment.
"""
from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from datetime import date
from typing import Any, Iterable, Sequence

log = logging.getLogger("bond_terms")

OPENINFO_API_BASE = "https://new-api.openinfo.uz/api/v2"

FACT_ISSUE = 25        # Выпуск ценных бумаг
FACT_REDEMPTION = 31   # Сроки исполнения обязательств по выкупу (погашению)
FACT_ACCRUAL = 32      # Начисление доходов по ценным бумагам

PAPER_TYPE_BOND = 3

# Only `organization_id` filters. `organization`, `org`, `q` are silently
# ignored and answer with the unfiltered 64k set — which reads exactly like a
# filter that worked, so the page size is capped and the count is logged.
_PAGE_SIZE = 100
_MAX_FACT_PAGES = 20  # 2000 filings; the busiest issuer on the walk files ~1500
_ALLOWED_PERIOD_DRIFT = 3  # a 31-day month is the same coupon as a 30-day one


def _num(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).replace(" ", "").replace("\xa0", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _day(value: Any) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    import openinfo_http

    resp = openinfo_http.get(f"{OPENINFO_API_BASE}{path}", params=params, timeout=40)
    resp.raise_for_status()
    return resp.json()


def issuer_facts(org_id: Any) -> list[dict[str, Any]]:
    """Every material fact filed by one issuer (newest-first, paged).

    Reading one page regressed once: AGAT's matured first issue slid past the
    newest 100 as later filings arrived, its registration stopped matching and
    a run "lost" a coupon that was proved weeks earlier. An issuer's whole
    history is a handful of pages, so read them all (capped well above any real
    issuer, far below the portal).
    """
    results: list[dict[str, Any]] = []
    for page in range(1, (_MAX_FACT_PAGES) + 1):
        payload = _get("/disclosure/facts/",
                       {"organization_id": org_id, "page_size": _PAGE_SIZE, "page": page})
        batch = (payload.get("results") or []) if isinstance(payload, dict) else []
        count = payload.get("count") if isinstance(payload, dict) else None
        if count and count > 60000:
            # The filter was ignored and we are holding the whole portal.
            log.warning("org %s: facts filter ignored (count=%s) — skipping", org_id, count)
            return []
        results.extend(batch)
        if not batch or (count and len(results) >= count):
            break
    else:
        log.info("org %s: reading stopped at %d filings of %s", org_id, len(results), count)
    return results


def fact_detail(fact_id: Any) -> dict[str, Any] | None:
    """One filing's own fields."""
    try:
        payload = _get(f"/disclosure/facts/{fact_id}/")
    except Exception:  # noqa: BLE001 — one unreadable filing is not a failed run
        log.debug("fact %s unreadable", fact_id, exc_info=True)
        return None
    fact = (payload or {}).get("fact") or []
    fact = fact[0] if isinstance(fact, list) and fact else fact
    return fact if isinstance(fact, dict) else None


def resolve_org_id(ticker: str, issuer_name: str | None) -> Any | None:
    """The openinfo organisation behind a ticker.

    The catalog already holds the mapping for issuers we cover; a bond issuer
    that never filed financials is not in it, so the exchange's own name for the
    issuer is looked up instead. The lookup is by name only as a fallback,
    because a wrong organisation would attach another company's coupons.
    """
    try:
        import reports_catalog as rc
        import catalogue.storage as catalogue_storage

        conn = catalogue_storage.get_catalog_conn()
        try:
            row = conn.execute(
                "SELECT org_id FROM catalog_companies WHERE ticker = ? AND org_id IS NOT NULL",
                (ticker,)).fetchone()
        finally:
            conn.close()
        if row and row["org_id"]:
            return row["org_id"]
    except Exception:  # noqa: BLE001 — no catalog on this host is not fatal
        log.debug("catalog lookup failed for %s", ticker, exc_info=True)

    name = _issuer_name(issuer_name)
    if not name:
        return None
    # Autofill is a search, not an identity lookup: even a single result may
    # be an unrelated company. Try distinctive words as well as the full name,
    # but accept only one matching issuer, independently of result ordering.
    words = name.split()
    queries = dict.fromkeys([name, " ".join(words[:2]), *sorted(words, key=len, reverse=True)])
    for query in queries:
        if not query:
            continue
        try:
            found = _get("/home/autofill/", {"name": query})
        except Exception:  # noqa: BLE001
            return None
        matches = {item["id"] for item in found or []
                   if isinstance(item, dict) and item.get("id")
                   and _issuer_name(item.get("full_name_text")) == name}
        if len(matches) == 1:
            return matches.pop()
    return None


def _issuer_name(value: Any) -> str:
    """Comparable issuer name, without quoted-name punctuation or legal suffix."""
    text = str(value or "").strip()
    quoted = re.search(r'["«“<]([^"»”>]+)["»”>]', text)
    if quoted:
        text = quoted.group(1)
    else:
        text = re.split(r"\b(?:aksiyadorlik|mas[ʼ’'`ʻ]?uliyati|AJ|ATB|AITB|MChJ)\b",
                        text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.sub(r"[ʼ’'`ʻ]", "", text.casefold())
    return " ".join(re.findall(r"\w+", text))


def _issue_sequence(registration: Any) -> int | None:
    """Which issue of this programme the registration number denotes.

    "RU303P1079T0" is the third, "Q0845-2" and "1079-5" the second and the
    fifth, a bare "Q0845" the first. The exchange's ticker ends in the same
    digit (BFMT3V2 ↔ -2, ACMT2B5 ↔ -5) — verified on the six series where the
    issued quantity settles the match independently, and used ONLY to separate
    issues of one issuer that are identical in par and quantity.
    """
    text = str(registration or "").strip().upper()
    if not text:
        return None
    m = re.match(r"^RU(\d)0?(\d)", text)
    if m:  # RU30N… — N is the sequence
        return int(m.group(2))
    m = re.search(r"-(\d{1,2})$", text)
    if m:
        return int(m.group(1))
    return 1 if re.match(r"^[A-Z]?\d+$", text) else None


def _ticker_sequence(ticker: str) -> int | None:
    m = re.search(r"(\d)$", ticker or "")
    return int(m.group(1)) if m else None


def match_issue(row: dict[str, Any], issues: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """The registration filing that describes this exchange listing.

    Matched on par AND issued quantity, which the exchange and the regulator
    state independently — AGAT's four series share a par and three of them share
    a quantity, so neither field alone is a key. Where that still leaves more
    than one candidate the issue sequence decides, and where it does not, the
    row is dropped: a coupon attached to the wrong series is worse than none.
    """
    par, volume = _num(row.get("nominal")), _num(row.get("issue_volume"))
    if par is None or volume is None:
        return None
    hits = [i for i in issues
            if _num(i.get("nominal")) == par and _num(i.get("quantity")) == volume]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return None
    wanted = _ticker_sequence(row.get("ticker") or "")
    by_seq = [i for i in hits if i.get("sequence") == wanted]
    if len(by_seq) == 1:
        return by_seq[0]
    log.info("bond %s: %d registrations match par+quantity, none decisively", row.get("ticker"), len(hits))
    return None


def _repair_transposed(accruals: Sequence[dict[str, Any]]) -> None:
    """Un-swap filings whose ``sum_per`` and ``percentage_nominal`` traded places.

    DELTA's January 2026 accruals state sum_per 2.30 and percentage_nominal
    23 013.69 while every sibling filing of the same issue states the exact
    opposite — the two fields transposed at source, which read as a 2-сум coupon
    and made the whole series fail the fixed-rate check. The repair demands BOTH
    halves of the evidence: the filing's percentage matches the group's
    per-security amount AND its amount matches the group's percentage. One
    degenerate number alone stays as filed, so a genuinely broken series is
    still refused a rate. Mutates in place so the coupon rows heal too.
    """
    amounts = [a["amount"] for a in accruals if a.get("amount")]
    if len(amounts) < 3:
        return
    base = Counter(amounts).most_common(1)[0][0]
    pcts = [a["pct"] for a in accruals
            if a.get("pct") and a.get("amount") and abs(a["amount"] - base) <= base * 5e-3]
    if not pcts:
        return
    base_pct = Counter(pcts).most_common(1)[0][0]
    for a in accruals:
        amount, pct = a.get("amount"), a.get("pct")
        if not amount or not pct:
            continue
        if abs(pct - base) <= base * 5e-3 and abs(amount - base_pct) <= max(base_pct * 5e-3, 0.01):
            log.info("accrual fact %s: sum_per and percentage_nominal transposed — repaired",
                     a.get("fact_id"))
            a["amount"], a["pct"] = pct, amount


# Coupon period in days for each frequency the exchange register publishes.
# The filings count whole periods this way (ASAK4B5 paid 90 days a quarter).
PERIOD_BY_FREQ = {12: 30, 6: 60, 4: 90, 2: 182, 1: 365}


def _coupon_rate(nominal: float, accruals: Sequence[dict[str, Any]],
                 known_freq: Any = None, known_rate: Any = None,
                 known_period_days: Any = None) -> tuple[float | None, int | None, str]:
    """Annual rate, period length and coupon type from the filed accruals.

    Each filing states what one security earns for one period; the decision
    states the formula (``N * C * d / 365``). Inverting the most common amount
    gives the rate, and every other amount then has to fall out of the same rate
    with a day count near the period — a floating coupon or a mis-joined series
    fails that and returns no rate.

    ``known_freq`` is the coupon frequency the exchange register states. It is
    what sets the period when only ONE coupon has been filed and the filings
    cannot show their own spacing: guessing «monthly» there turned ANBK3B's
    quarterly 22 % into 66 % and ONLJ4's annual 15 % into 182.5 %.
    """
    _repair_transposed(accruals)
    amounts = [a["amount"] for a in accruals if a.get("amount")]
    starts = sorted({a["pay_date"] for a in accruals if a.get("pay_date")})
    if nominal <= 0 or not amounts or not starts:
        return None, None, "unknown"

    frequency = _num(known_freq)
    declared_period = _num(known_period_days) or PERIOD_BY_FREQ.get(frequency)
    declared_rate = _num(known_rate)
    if declared_period and declared_rate and declared_rate > 0:
        # Missing filings lengthen the gap between payment announcements, not
        # the coupon period. Prefer terms corroborated by the filed amounts.
        if all(abs(amount * 365 / (nominal * declared_rate / 100) - declared_period)
               <= _ALLOWED_PERIOD_DRIFT for amount in amounts):
            return declared_rate, int(declared_period), "fixed"

    gaps = [(b - a).days for a, b in zip(starts, starts[1:]) if 20 <= (b - a).days <= 370]
    if gaps:
        median = statistics.median(gaps)
        period = min(PERIOD_BY_FREQ.values(), key=lambda days: abs(days - median))
        if abs(period - median) > _ALLOWED_PERIOD_DRIFT:
            return None, None, "unknown"
    else:
        period = None
    if period is None:
        if len(starts) > 1:
            return None, None, "unknown"
        # A single filed coupon cannot show its own spacing: the register's
        # frequency sets it. Without one, no rate — a guessed period is a
        # fabricated rate.
        period = int(declared_period) if declared_period else None
        if period is None:
            return None, None, "unknown"

    base = Counter(amounts).most_common(1)[0][0]
    rate = base * 365.0 / (nominal * period) * 100.0
    for amount in amounts:
        implied_days = amount * 365.0 / (nominal * rate / 100.0)
        if abs(implied_days - period) > _ALLOWED_PERIOD_DRIFT:
            log.info("coupon amounts disagree (%.2f implies %.1f days, period %d) — no rate stated",
                     amount, implied_days, period)
            return None, period, "floating"
    # The filed amount is rounded to the tiyin ("Изоҳ: фоизли даромад миқдори
    # бир тийинга қадар аниқлик билан белгиланади"), so inverting 2 054.79 over
    # 30 days lands at 24.9999 rather than 25. Two decimals give the rate back
    # its own precision without inventing any: a real 11.5% survives unchanged.
    return round(rate, 2), period, "fixed"


def collect_bond_terms(reference_rows: Iterable[dict[str, Any]],
                       today: date | None = None) -> dict[str, list[dict[str, Any]]]:
    """Coupon rate, coupon schedule and redemption date for exchange bonds.

    Takes the rows already built from the exchange (ticker, ISIN, par, issue
    size) and fills in what only the issuer publishes. Returns reference updates
    and coupon rows; an issue whose filings do not add up appears in neither.
    """
    rows = [r for r in (reference_rows or []) if r.get("ticker") and r.get("nominal")]
    by_issuer: dict[Any, list[dict[str, Any]]] = {}
    org_by_name: dict[str, Any] = {}
    for row in rows:
        name = _issuer_name(row.get("issuer"))
        org = org_by_name.get(name) if name else None
        if org is None:
            org = resolve_org_id(row["ticker"], row.get("issuer"))
            if name and org is not None:
                org_by_name[name] = org
        if org is None:
            log.info("bond %s: no openinfo organisation", row["ticker"])
            continue
        by_issuer.setdefault(org, []).append(row)

    reference: list[dict[str, Any]] = []
    coupons: list[dict[str, Any]] = []
    for org, issuer_rows in by_issuer.items():
        facts = issuer_facts(org)
        if not facts:
            continue
        issues, accruals, redemptions = [], [], []
        for fact in facts:
            number = int(_num(fact.get("fact_number")) or 0)
            if number not in (FACT_ISSUE, FACT_REDEMPTION, FACT_ACCRUAL):
                continue
            detail = fact_detail(fact.get("id"))
            if not detail:
                continue
            if number == FACT_ISSUE:
                if int(_num(detail.get("paper_type")) or 0) != PAPER_TYPE_BOND:
                    continue  # a share issue of the same issuer
                issues.append({
                    "registration": detail.get("num_registration"),
                    "sequence": _issue_sequence(detail.get("num_registration")),
                    "nominal": _num(detail.get("nominal_paper_cost")),
                    "quantity": _num(detail.get("paper_num")),
                    "decision_date": _day(detail.get("date_decision")),
                    "registration_date": _day(detail.get("date_registration")),
                    "fact_id": fact.get("id"),
                })
            elif number == FACT_ACCRUAL:
                amount = _num(detail.get("sum_per"))
                pay = _day(detail.get("start_date_other_securities"))
                if amount and pay:
                    accruals.append({"decision_date": _day(detail.get("date_solution")),
                                     "amount": amount, "pay_date": pay,
                                     # Kept for the transposition repair below —
                                     # some filings state the two fields swapped.
                                     "pct": _num(detail.get("percentage_nominal")),
                                     "window_end": _day(detail.get("end_date_other_securities")),
                                     "fact_id": fact.get("id")})
            else:
                redemptions.append({"decision_date": _day(detail.get("date_solution")),
                                    "begins": _day(detail.get("date_begin")),
                                    "ends": _day(detail.get("date_end")),
                                    "fact_id": fact.get("id")})

        for row in issuer_rows:
            issue = match_issue(row, issues)
            if not issue or not issue.get("decision_date"):
                continue
            by_day = {}
            for accrual in accruals:
                if (accrual["decision_date"] == issue["decision_date"]
                        and (not issue.get("registration_date")
                             or accrual["pay_date"] >= issue["registration_date"])):
                    # Facts arrive newest first: a correction replaces the
                    # earlier announcement of the same payment, not a second coupon.
                    by_day.setdefault(accrual["pay_date"], accrual)
            mine = sorted(by_day.values(), key=lambda a: a["pay_date"])
            if not mine:
                continue
            rate, period, kind = _coupon_rate(float(row["nominal"]), mine, row.get("coupon_freq"),
                                             row.get("coupon_rate"), row.get("coupon_period_days"))
            redemption = next((r for r in redemptions
                               if r["decision_date"] == issue["decision_date"] and r["begins"]), None)
            reference.append({
                "ticker": row["ticker"],
                "isin": row.get("isin"),
                "nominal": row.get("nominal"),
                "issue_volume": row.get("issue_volume"),
                "coupon_rate": rate,
                "coupon_freq": int(round(365 / period)) if period else None,
                # How many filed coupons the rate rests on: one is an inversion
                # through the register's frequency, several prove themselves.
                "coupon_evidence": len(mine),
                # "floating" survives without a rate: the detector concluding
                # "no single annual rate fits the filings" is information the
                # coupon column can state, where a bare NULL reads as silence.
                "coupon_type": kind if kind != "unknown" else None,
                # Only a filed redemption window is a maturity. A term of "N days
                # from the start of placement" is not a date.
                "maturity_date": redemption["begins"].isoformat() if redemption else None,
                # Registration precedes placement; it cannot replace the
                # register's placement date used to build the payment schedule.
                "source_url": f"{OPENINFO_API_BASE}/disclosure/facts/{mine[-1]['fact_id']}/",
            })
            for no, accrual in enumerate(mine, start=1):
                coupons.append({
                    "ticker": row["ticker"],
                    "coupon_no": no,
                    "pay_date": accrual["pay_date"].isoformat(),
                    "amount": accrual["amount"],
                    # The filing publishes the PAYMENT window, not the accrual
                    # period — see provenance.bond_coupons.
                    "period_from": None,
                    "period_to": None,
                    # Fact 32 announces accrual, not proof that cash was paid.
                    "is_paid": None,
                    "source_url": f"{OPENINFO_API_BASE}/disclosure/facts/{accrual['fact_id']}/",
                })
            log.info("bond %s: coupon %s%% every %s days, %d filed, maturity %s",
                     row["ticker"], rate, period, len(mine),
                     reference[-1]["maturity_date"] or "не подано")
    return {"reference": reference, "coupons": coupons}

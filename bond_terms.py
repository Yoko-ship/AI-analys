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

**The rate is inverted from the accruals, not parsed from prose.** Every filing
states the same formula — ``Dn = N * C * 30 / 365`` — so the annual rate follows
from the published per-security amount by arithmetic on published numbers. It is
then validated against EVERY other coupon of the same issue (each must equal
``N * C * d / 365`` for a day count within a few days of the period); an issue
that fails gets no rate at all rather than a plausible one. The check earns its
keep: all twelve issues come out at whole percentages, which a wrong par, a
wrong period or a mis-joined series could not produce.

**The maturity is taken only from #31.** Nowhere is a redemption DATE published
— the decision says "N days from the start of placement", and the start of
placement is itself derived ("the 15th calendar day after the registration
notice"). Reconstructing it lands within about three days of the filed date
(checked against ACMT1B2: derived 26.07.2026, filed 23.07.2026), and three days
of guesswork is not a maturity date. So an issue whose redemption has not been
filed keeps ``maturity_date`` NULL and its yield stays a dash.
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
    """Every material fact filed by one issuer (newest-first, one page)."""
    payload = _get("/disclosure/facts/", {"organization_id": org_id, "page_size": _PAGE_SIZE})
    results = (payload.get("results") or []) if isinstance(payload, dict) else []
    count = payload.get("count") if isinstance(payload, dict) else None
    if count and count > 60000:
        # The filter was ignored and we are holding the whole portal.
        log.warning("org %s: facts filter ignored (count=%s) — skipping", org_id, count)
        return []
    if count and count > len(results):
        log.info("org %s: %s filings, reading the newest %d", org_id, count, len(results))
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

        conn = rc.get_catalog_conn()
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

    name = re.sub(r"[<>«»\"']", " ", str(issuer_name or "")).strip()
    if not name:
        return None
    # "«CONTACT FINANSE» mas'uliyati cheklangan jamiyati" → "CONTACT FINANSE",
    # then "CONTACT": autofill matches the head of the name, not the legal form,
    # and the two registers spell the same issuer FINANSE and FINANCE. Shortest
    # query last, because a one-word query is the one that can match a stranger.
    words = name.split()
    for query in (" ".join(words[:2]), words[0]):
        if not query:
            continue
        try:
            found = _get("/home/autofill/", {"name": query})
        except Exception:  # noqa: BLE001
            return None
        for item in found or []:
            if isinstance(item, dict) and item.get("id"):
                return item["id"]
    return None


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


def _coupon_rate(nominal: float, accruals: Sequence[dict[str, Any]]) -> tuple[float | None, int | None, str]:
    """Annual rate, period length and coupon type from the filed accruals.

    Each filing states what one security earns for one period; the decision
    states the formula (``N * C * d / 365``). Inverting the most common amount
    gives the rate, and every other amount then has to fall out of the same rate
    with a day count near the period — a floating coupon or a mis-joined series
    fails that and returns no rate.
    """
    amounts = [a["amount"] for a in accruals if a.get("amount")]
    starts = sorted(a["pay_date"] for a in accruals if a.get("pay_date"))
    if not amounts or len(starts) < 1:
        return None, None, "unknown"

    gaps = [(b - a).days for a, b in zip(starts, starts[1:]) if 20 <= (b - a).days <= 200]
    period = int(round(statistics.median(gaps) / 30.0) * 30) if gaps else None
    if period is None:
        # A single filed coupon cannot show its own spacing. The two issues in
        # that state pay quarterly on a par of ten million and above; anything
        # else is a guess, and a guessed period would fabricate a rate.
        period = 90 if nominal >= 10_000_000 else 30
        if len(accruals) > 1:
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
    today = today or date.today()
    rows = [r for r in (reference_rows or []) if r.get("ticker") and r.get("nominal")]
    by_issuer: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        org = resolve_org_id(row["ticker"], row.get("issuer"))
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
            mine = sorted((a for a in accruals if a["decision_date"] == issue["decision_date"]),
                          key=lambda a: a["pay_date"])
            if not mine:
                continue
            rate, period, kind = _coupon_rate(float(row["nominal"]), mine)
            redemption = next((r for r in redemptions
                               if r["decision_date"] == issue["decision_date"] and r["begins"]), None)
            reference.append({
                "ticker": row["ticker"],
                "isin": row.get("isin"),
                "nominal": row.get("nominal"),
                "issue_volume": row.get("issue_volume"),
                "coupon_rate": rate,
                "coupon_freq": int(round(365 / period)) if period else None,
                "coupon_type": kind if rate else None,
                # Only a filed redemption window is a maturity. A term of "N days
                # from the start of placement" is not a date.
                "maturity_date": redemption["begins"].isoformat() if redemption else None,
                "issue_date": issue["registration_date"].isoformat() if issue.get("registration_date") else None,
                "source_url": f"{OPENINFO_API_BASE}/disclosure/facts/{issue['fact_id']}/",
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
                    "is_paid": 1 if (accrual["window_end"] and accrual["window_end"] < today) else 0,
                })
            log.info("bond %s: coupon %s%% every %s days, %d filed, maturity %s",
                     row["ticker"], rate, period, len(mine),
                     reference[-1]["maturity_date"] or "не подано")
    return {"reference": reference, "coupons": coupons}

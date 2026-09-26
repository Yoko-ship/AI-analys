"""Resolve and compare financial periods without collecting or storing data."""
from __future__ import annotations
from typing import Any

from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import catalogue.settings as catalogue_settings
import re


def _extract_year(report: dict[str, Any]) -> int | None:

    props = report.get("properties") or {}

    for field in ("reporting_year", "year"):

        v = props.get(field)

        if v is not None:

            try:

                yr = int(v)

                if 2000 <= yr <= 2100:

                    return yr

            except (TypeError, ValueError):

                pass

    title = str(props.get("report_title") or "")

    m = re.search(r"\b(20[12]\d)\b", title)

    if m:

        return int(m.group(1))

    # A publication date is not a PDF's accounting period. Late annuals and

    # interim IFRS filings otherwise silently become the wrong financial year.

    if report.get("report_type") in {"MSFO", "Audition"}:

        return None

    pub = str(report.get("pub_date") or "")

    if len(pub) >= 4:

        try:

            yr = int(pub[:4])

            pt = str(props.get("report_type") or "annual").lower()

            return yr - 1 if pt == "annual" else yr

        except (TypeError, ValueError):

            pass

    return None


def _extract_quarter(period_str: str) -> int | None:
    """Parse quarter number from strings like 'Q1 2024' or 'I квартал 2024'."""
    m = re.search(r"Q([1-3])", period_str, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"([1-3])\s*квартал", period_str, re.IGNORECASE)
    if m:
        return int(m.group(1))
    roman = {"I": 1, "II": 2, "III": 3}
    m = re.search(r"\b(III|II|I)\b\s*квартал", period_str, re.IGNORECASE)
    if m:
        return roman.get(m.group(1).upper())
    return None


def _period_key(period: str | None) -> tuple[int, int]:
    """Numeric sort key for fact-store period strings ('2025', '2025Q3').

    Replaces lexicographic comparison, under which corrupt periods from the
    source ('2025Q7' > '2025Q3', '2026Q5' > '2026') won every "latest period"
    pick. An annual period ranks above the year's quarters (it is the complete,
    most recently published figure for that year); anything unparseable or with
    an out-of-range quarter ranks below every valid period.
    """
    m = re.fullmatch(r"(\d{4})(?:Q(\d{1,2}))?", str(period or "").strip())
    if not m:
        return (0, 0)
    year = int(m.group(1))
    if m.group(2) is None:
        return (year, 5)  # annual: outranks Q1-Q4 of the same year
    quarter = int(m.group(2))
    if not 1 <= quarter <= 4:
        return (0, 0)  # corrupt source period — never wins
    return (year, quarter)


def _period_months(year: int | None, quarter: int | None) -> int | None:
    """Months of activity a P&L figure for this period covers.

    NSBU quarterly forms are cumulative from 1 January, so a Q2 figure is six
    months and a Q3 figure nine — not three each. Without this the market board
    puts a full prior year, a half year and a quarter in one column and calls them
    comparable. Balance-sheet lines are point-in-time and need no such number.
    """
    if year is None:
        return None
    if not quarter:
        return 12
    return int(quarter) * 3 if 1 <= int(quarter) <= 4 else None


def _is_future_period(year: int | None, quarter: int | None,
                      today: date | None = None) -> bool:
    """True for a period that has not finished yet — one no filing can describe.

    The last line of defence for the period label. openinfo mis-stamps period-ends
    (an annual filed mid-2026 carrying reporting_year=2026-12-31), and a row that
    reaches storage with such a label wins "latest period" forever and hides the
    issuer's real figures behind a quarter that has not happened. Callers reject
    rather than repair: by the time a row is being written, the filing date that
    would let it be dated correctly is no longer at hand.
    """
    if year is None:
        return False
    today = today or datetime.now(timezone.utc).date()
    q = int(quarter or 0)
    if not q:
        return int(year) > _latest_complete_fiscal_year()
    if not 1 <= q <= 4:
        return False  # corrupt quarter, excluded by its own rule
    end_month, end_day = ((3, 31), (6, 30), (9, 30), (12, 31))[q - 1]
    return date(int(year), end_month, end_day) > today


def _latest_complete_fiscal_year() -> int:
    """The most recent fiscal year for which a complete annual report can exist.

    Uzbek issuers file on a calendar fiscal year, so an annual report for year Y
    is only complete once Y has ended. During calendar year N the newest complete
    annual is therefore FY(N-1). openinfo, however, publishes a placeholder
    "annual" for the *current* year (both as an ``/accounting-report/`` record and
    as a ``financial_indicators`` row) that is either an in-progress figure or a
    duplicate of the prior year — treating it as the latest completed annual dates
    the headline figures a year into the future. This is the cutoff that separates
    a real completed annual from that premature one.
    """
    return datetime.now(timezone.utc).year - 1


def _is_premature_annual_year(year: int | None) -> bool:
    """True for an annual report whose fiscal year has not yet ended."""
    return year is not None and year > _latest_complete_fiscal_year()


def _completed_annual_is_recent(year: int | None, *, today: date | None = None) -> bool:
    """Whether a completed calendar-year annual is still a current analysis base.

    Annual filings remain preferable to their own quarters, but after the
    configured window a newer quarterly filing is more informative than a
    year-end balance that is already well into the past.
    """
    if year is None or int(year) != _latest_complete_fiscal_year():
        return False
    today = today or datetime.now(timezone.utc).date()
    return (today - date(int(year), 12, 31)).days <= catalogue_settings.FINANCIALS_ANNUAL_FRESH_DAYS


def _is_premature_annual_period(period: str | None) -> bool:
    """True for a fact-store *annual* period ('2026') whose year is not complete.

    Quarterly periods ('2026Q1') are point-in-time filings and stay valid.
    """
    y, k = _period_key(period)
    return k == 5 and y > _latest_complete_fiscal_year()


def _fact_period_rank(period: str | None) -> tuple[int, int, int]:
    """``_period_key`` with premature annuals demoted below every real period.

    Used only for "latest period" selection over the fact store, and only ever
    compared against other values of this same function — hence the explicit
    tier, which makes the three classes totally ordered:

        tier 0  junk / unparseable  ('2025Q7')
        tier 1  premature annual    (openinfo's current-year placeholder)
        tier 2  a real period

    A premature annual must never beat a real period, but it must still beat junk
    so an issuer whose *only* fact is the placeholder shows that rather than
    nothing. The previous ``(y - 10000, k)`` demotion overshot: it produced a
    negative year, which sorts BELOW junk's ``(0, 0)`` — so an issuer with one
    placeholder and one corrupt period preferred the corrupt one.
    """
    y, k = _period_key(period)
    if (y, k) == (0, 0):
        return (0, 0, 0)
    if k == 5 and y > _latest_complete_fiscal_year():
        return (1, y, k)
    return (2, y, k)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_fresh(last_synced_at: str | None) -> bool:
    if not last_synced_at:
        return False
    try:
        ts = datetime.fromisoformat(last_synced_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts < timedelta(hours=catalogue_settings.CATALOG_SYNC_TTL_HOURS)
    except (ValueError, TypeError):
        return False


def _effective_annual_year(labeled_year: int, pub_date: str | None) -> int:
    """The fiscal year an annual record can actually describe.

    openinfo stamps many annuals with the UPLOAD season's year rather than the
    fiscal year: fleet-wide, the FY2019 annual of almost every issuer is labeled
    "2020" (published mid-2020, next to a second, genuine 2020), and several
    issuers carry impossible "FY2026" labels on their FY2025 filings. A period
    cannot end after the report describing it was published, so the label is
    clamped to the last fiscal year complete at publication — the same invariant
    period_year_quarter (openinfo_reconcile) applies on the unified-feed path.
    A label EARLIER than the bound is left alone: late filings are normal
    (AGMKP published its FY2021 annual in 2023 and its label is correct).
    """
    if not pub_date:
        return labeled_year
    try:
        pub_year = int(str(pub_date)[:4])
    except (TypeError, ValueError):
        return labeled_year
    return min(labeled_year, pub_year - 1)


def _hours_since(stamp: Any) -> float | None:
    """Hours since an ISO timestamp, or None if there isn't one to read."""
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}


_STATED_QUARTER_LABELS = ("период квартала", "chorak davri", "chorak muddati")


_PUB_MONTH_QUARTER = {1: 3, 2: 3, 3: 3, 4: 1, 5: 1, 6: 1,
                      7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3}


def _stated_quarter(parsed: dict[str, Any] | None) -> int | None:
    """The quarter the workbook's own header states (1-4), or None if it does not."""
    for sheet in ((parsed or {}).get("sheets") or []):
        for row in (sheet.get("table_rows") or []):
            label = str(row.get("label") or "").lower()
            if not any(hint in label for hint in _STATED_QUARTER_LABELS):
                continue
            for value in (row.get("numeric_values") or []):
                try:
                    quarter = int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= quarter <= 4:
                    return quarter
    return None


def _quarter_period_from_publication(quarter: int, pub: datetime) -> tuple[int, int]:
    """(fiscal year, quarter) for a filing published on ``pub``.

    A period cannot end after the report describing it was published — the same
    invariant :func:`_effective_annual_year` applies to annuals. So the year is
    the publication year when the quarter had already closed by then, and the
    year before it otherwise (a late filing).
    """
    year = pub.year if pub.month > _QUARTER_END_MONTH[quarter] else pub.year - 1
    return year, quarter

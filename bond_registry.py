"""bond_registry.py — the exchange's own register of circulating bond issues.

``listings_collector.collect_bond_reference_rows`` records that the coupon
rate, the maturity date and the payment schedule "are genuinely absent —
searched for on the issue page and in the card, they are not there". That is
true of ``/isu_infos/{isin}/detail``. It is not true of the exchange as a whole:
uzse.uz publishes **«Облигации доступные на торгах фондовой биржи»**
(``/abouts/bonds/``) as an embedded Google Sheet, and that sheet is the register
of every circulating issue with, per row:

===========================================  ================================
``Tiker`` / ``QQ kodi``                      ticker and ISIN
``Nominal qiymati``                          par value
``QQ soni`` / ``Joylashtirilgan QQ soni*``   registered and placed count
``Foiz stavkasi``                            coupon rate (or a floating base)
``Joylashtirish/muomalaga kiritish sanasi``  placement date
``So'ndirish (to'lash) sanasi``              **redemption date**
``Kupon to'lovi davri (sikli)``              coupon cycle, in words
===========================================  ================================

So the two inputs the yield half of the section was declared inert on — the
coupon and the maturity — are published for all 65 issues, in one request.

**What this does and does not license.** The register states the issue's TERMS:
the rate the issuer undertook and the date the paper falls due. It does not
state that a payment happened. So the terms land in ``bond_reference`` (and a
schedule can be reconstructed from them), while ``bond_coupons`` stays what it
was: the payments the issuer has actually filed on openinfo. Where openinfo has
filed a redemption window (material fact #31), that filed date still wins — an
executed fact outranks a planned term.

The sheet is a spreadsheet a human maintains, so nothing here trusts its shape:
the header row is matched by name, a row without a ticker and an ISIN is
skipped, and a rate or a date that does not parse leaves its column NULL rather
than guessing.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date
from typing import Any, Iterable

log = logging.getLogger("bond_registry")

# The page uzse.uz embeds on /abouts/bonds/. Published-to-web sheets answer the
# CSV export without credentials; the /pubhtml the iframe loads renders its
# cells in JavaScript and carries no table in the HTML.
REGISTRY_SHEET = ("https://docs.google.com/spreadsheets/d/e/"
                  "2PACX-1vRIpxhOE3Pd5a0zR7fli8yzdUO5bp1RZ-rCtZpkVY9ciIbmLUt-"
                  "PY3pizs0zBaa2_TJLcwYqXmeXhoP")
REGISTRY_CSV = REGISTRY_SHEET + "/pub?output=csv"
REGISTRY_PAGE = "https://uzse.uz/abouts/bonds/"

# Column headers, keyed by a fragment that survives the Latin-Uzbek apostrophe
# soup (all four of the site's apostrophe glyphs appear in this sheet) and the
# odd trailing space.
_HEADERS: tuple[tuple[str, str], ...] = (
    ("issuer", "eminentning nomi"),
    ("segment", "bozor segmenti"),
    ("ticker", "tiker"),
    ("isin", "qq kodi"),
    ("nominal", "nominal qiymati"),
    ("registered", "qq soni"),
    ("rate", "foiz stavkasi"),
    ("issue_date", "joylashtirish"),
    ("maturity_date", "ndirish"),
    ("placed", "joylashtirilgan"),
    ("pay_method", "lovini amalga oshirish"),
    ("cycle", "lovi davri"),
)

# «Kupon to'lovi davri (sikli)» — the cycle in words, as the register writes it.
# A day count is spelled where the sheet spells one; everything else is the
# calendar word. Anything unlisted leaves the frequency NULL: a coupon cycle
# nobody can read is not a licence to assume two payments a year.
_CYCLE_DAYS = ((30, 12), (90, 4), (180, 2), (360, 1), (365, 1))
_CYCLE_WORDS: tuple[tuple[str, int], ...] = (
    ("har oyda", 12), ("oylik", 12),
    ("har chorakda", 4), ("choraklik", 4), ("kvartal", 4),
    ("yarim yillik", 2), ("yarim yil", 2),
    ("yillik", 1), ("har yili", 1),
)


def _clean(value: Any) -> str:
    """Trim, and fold the apostrophe variants and the non-breaking space."""
    text = str(value or "")
    text = text.replace(" ", " ").replace("’", "'").replace("ʻ", "'")
    return re.sub(r"\s+", " ", text).strip()


def _num(value: Any) -> float | None:
    """«1 000 000» / «27,00%» → a number. Anything else → None."""
    text = _clean(value).replace("%", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _day(value: Any) -> str | None:
    """«13.05.2020» → «2020-05-13». A cell that is not a date stays empty."""
    text = _clean(value)
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if iso:
        return text
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$", text)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def coupon_frequency(cycle: Any) -> int | None:
    """Payments a year, from the register's wording of the cycle."""
    text = _clean(cycle).lower()
    if not text:
        return None
    days = re.search(r"(\d+)\s*kun", text)
    if days:
        n = int(days.group(1))
        for span, freq in _CYCLE_DAYS:
            if abs(n - span) <= 3:
                return freq
        return max(1, round(365 / n)) if n else None
    for word, freq in _CYCLE_WORDS:
        if word in text:
            return freq
    log.info("bond registry: unreadable coupon cycle %r", text)
    return None


def coupon_rate(cell: Any) -> tuple[float | None, str | None, str | None]:
    """``(rate, coupon_type, float_base)`` from «Foiz stavkasi».

    One issue states a formula instead of a number — «MB qayta moliyalash
    stavkasi + 5 %», the refinancing rate plus a margin. That is a floating
    coupon, and it is recorded as one: the type and the base text are kept, the
    rate stays NULL. Resolving the formula would mean publishing a rate the
    register does not state, and the margin would silently freeze at whatever
    the key rate was on collection day.
    """
    text = _clean(cell)
    if not text:
        return None, None, None
    if re.fullmatch(r"[\d\s.,]+%?", text):
        rate = _num(text)
        if rate is None:
            return None, None, None
        # A zero-coupon issue states «0,00%» — the UMRC SPV series does. That is
        # a rate of zero, not a missing one, and the discount IS the return.
        return rate, ("zero" if rate == 0 else "fixed"), None
    return None, "floating", text


def parse_registry(text: str) -> list[dict[str, Any]]:
    """Rows of the register, as ``bond_reference`` upsert payloads."""
    rows = list(csv.reader(io.StringIO(text)))
    index: dict[str, int] = {}
    body: list[list[str]] = []
    for i, row in enumerate(rows):
        lowered = [_clean(c).lower() for c in row]
        hits = {key: n for key, fragment in _HEADERS
                for n, cell in enumerate(lowered) if fragment in cell}
        # The header is the row that names most of the columns — the sheet
        # carries a title row above it and, on a bad day, a merged banner.
        if len(hits) >= 8:
            index, body = hits, rows[i + 1:]
            break
    if not index:
        log.warning("bond registry: no header row found — sheet layout changed")
        return []

    def cell(row: list[str], key: str) -> str:
        n = index.get(key)
        return _clean(row[n]) if n is not None and n < len(row) else ""

    out: list[dict[str, Any]] = []
    issuer_carry = ""
    for row in body:
        # The issuer is written once and left blank down its series — the sheet
        # is formatted for a human reader, with the name merged over the block.
        issuer_carry = cell(row, "issuer") or issuer_carry
        ticker = cell(row, "ticker").upper()
        isin = cell(row, "isin").upper().replace(" ", "")
        if not ticker or not isin.startswith("UZ6"):
            continue
        rate, coupon_type, float_base = coupon_rate(cell(row, "rate"))
        nominal = _num(cell(row, "nominal"))
        out.append({
            "ticker": ticker,
            "isin": isin,
            "issuer": issuer_carry or None,
            "nominal": nominal if nominal else None,
            "currency": "UZS",
            "coupon_rate": rate,
            "coupon_type": coupon_type,
            "float_base": float_base,
            "coupon_freq": coupon_frequency(cell(row, "cycle")),
            "issue_date": _day(cell(row, "issue_date")),
            "maturity_date": _day(cell(row, "maturity_date")),
            # The registered count is the size of the issue; the placed count is
            # how much of it found a buyer, and it is the smaller of the two
            # wherever the sale is unfinished (IFMT4: 8 207 of 10 000).
            "issue_volume": _num(cell(row, "registered")),
            "placed_volume": _num(cell(row, "placed")),
            "source_url": REGISTRY_PAGE,
        })
    return out


def resolve_ticker_conflicts(rows: Iterable[dict[str, Any]],
                             isin_by_ticker: dict[str, str] | None = None,
                             ) -> list[dict[str, Any]]:
    """One row per ticker, or none where the register contradicts itself.

    Measured on the live sheet, 2026-08-20: **OUSP19B3 is written twice**, over
    two different ISINs (UZ6059364AA8 placed 31.07, UZ6059367AB9 placed 13.08),
    with different sizes and different redemption dates. One of the two is a
    typo for the next series in the run — but which one is not knowable from
    the sheet, and ``bond_reference`` is keyed by ticker, so taking the first
    would attach one series' terms to whichever paper actually trades under
    that code.

    The exchange's own ticker→ISIN mapping settles it where we have it: keep
    the row whose ISIN is the one the board trades. Where it does not, both
    rows are dropped and the collision is logged — a dash the operator can see
    beats a redemption date that belongs to another security.
    """
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        by_ticker.setdefault(str(row.get("ticker") or "").upper(), []).append(row)
    known = {str(k).upper(): str(v).upper() for k, v in (isin_by_ticker or {}).items() if v}
    out: list[dict[str, Any]] = []
    for ticker, group in by_ticker.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        wanted = known.get(ticker)
        picked = [r for r in group if str(r.get("isin") or "").upper() == wanted] if wanted else []
        if len(picked) == 1:
            log.info("bond registry: %s written %d times, kept the traded ISIN %s",
                     ticker, len(group), wanted)
            out.append(picked[0])
        else:
            log.warning("bond registry: %s claimed by %d ISINs (%s) — no terms published",
                        ticker, len(group),
                        ", ".join(str(r.get("isin")) for r in group))
    return out


def fetch_registry(session: Any = None) -> str:
    """The register's CSV export, as text."""
    if session is None:
        import requests

        session = requests.Session()
    response = session.get(REGISTRY_CSV, timeout=60)
    response.raise_for_status()
    # requests guesses ISO-8859-1 for a text/csv without a charset, which turns
    # every Uzbek apostrophe into mojibake. The sheet is UTF-8.
    return response.content.decode("utf-8", errors="replace")


def collect_registry_rows(session: Any = None,
                          isin_by_ticker: dict[str, str] | None = None,
                          ) -> list[dict[str, Any]]:
    """Fetch and parse the exchange's bond register."""
    try:
        rows = resolve_ticker_conflicts(parse_registry(fetch_registry(session)),
                                        isin_by_ticker)
    except Exception:  # noqa: BLE001 — an unreachable sheet must not fail the push
        log.exception("bond registry: fetch failed")
        return []
    with_terms = sum(1 for r in rows if r.get("coupon_rate") is not None
                     and r.get("maturity_date"))
    log.info("bond registry: %d issues, %d with both a rate and a redemption date",
             len(rows), with_terms)
    return rows


def merge_reference(base: Iterable[dict[str, Any]],
                    registry: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The exchange card's rows, filled in from the register.

    Field by field the card wins where it speaks — it is the per-security
    record, and its par is the one the price is quoted against — and the
    register fills what the card leaves empty, which is the coupon, the cycle
    and both dates. An issue that is in the register but not in the card walk
    is added: the walk starts from openinfo's ``info_rfb``, which has no entry
    for an LLC issuer, and the register does.
    """
    merged: dict[str, dict[str, Any]] = {}
    for row in registry or []:
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            merged[ticker] = dict(row)
    for row in base or []:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        combined = merged.get(ticker, {})
        combined.update({k: v for k, v in row.items() if v is not None})
        merged[ticker] = combined
    return list(merged.values())


if __name__ == "__main__":  # pragma: no cover
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(collect_registry_rows(), ensure_ascii=False, indent=2))

"""The exchange's own daily quote per security: close, previous close, change.

The board's "Изменение" is a close-to-close move against the exchange's OWN
previous close, and that close is *carried forward* through sessions with no
trades: UQEQ closed at 25 600 on 30.07 without a single execution, so its 20%
limit-up to 30 720 on 31.07 cannot be derived from executions, from openinfo's
conclusions archive (which last saw a trade on 24.07 at 32 000), or from any
registry price. Reading it from the exchange is the only way to state a change
the exchange would recognise.

The board's other source of truth, the ``/stocks`` mirror, is a *fixed* universe
of 78 securities. The exchange lists 122 shares and 40 bonds, so a security
outside that universe was either missing from the board altogether (KFSKP, EQQU)
or drawn from the openinfo registry's last-known trade — a week-old price, and a
percentage struck against it. On 31.07 that hid four of the exchange's own top
ten gainers (UQEQ +20%, METQ +19.74%, KFSKP +17.27%, PLST +11.37%) and its
third-largest loser (KFSK -6.82%).

``https://uzse.uz/isu_infos/{STK|BND}?isu_cd=<ISIN>`` publishes, per security:
the session's change / quantity / turnover, the session OHLC, the last trade with
its date, and ~21 sessions of daily closing prices (including the carried-forward
ones). That is everything the board needs, for every listed security, from the
exchange itself.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterable

import requests
import corporate_actions
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from numeric_parse import parse_decimal

logger = logging.getLogger(__name__)

UZSE_BASE = "https://uzse.uz"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
TIMEOUT = 30

# uzse.uz answers 406 to JSON-accepting clients on the HTML views, and serves the
# detail record as JSON only to an XHR-shaped request — hence two header sets.
_HTML_HEADERS = {"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"}
_JSON_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/javascript, */*; q=0.01",
                 "X-Requested-With": "XMLHttpRequest"}

_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
_UP, _DOWN = "▲", "▼"  # ▲ ▼ — the only marks that carry the change's sign


def _num(value: Any) -> float | None:
    """One board cell as a number ("1,234.56" → 1234.56, "▼ 6" → 6)."""
    return parse_decimal(value, group_sep=",", strip_non_numeric=True)


def _signed(cell: str) -> float | None:
    """A change cell as a signed number. The sign lives in the arrow, not the digits."""
    value = _num(cell)
    if value is None:
        return None
    if _DOWN in (cell or ""):
        return -abs(value)
    return abs(value)


def _iso_day(text: str) -> str | None:
    """First DD.MM.YYYY in ``text`` as YYYYMMDD (the form the catalog stores)."""
    m = _DATE_RE.search(text or "")
    return f"{m.group(3)}{m.group(2)}{m.group(1)}" if m else None


def _cells(row) -> list[str]:
    return [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]


def _find_table(tables: list, *, first_label: str, contains: str | None = None):
    """The table whose header row starts with ``first_label``.

    Position is not a contract — the page carries five tables and the executions
    log shares four of the daily history's five column names — so each table is
    located by what its header row says, and a page that stops saying it yields
    None rather than a plausible number read from the wrong grid.
    """
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue
        header = _cells(rows[0])
        if not header or not header[0].startswith(first_label):
            continue
        if contains and not any(contains in h for h in header):
            continue
        return table
    return None


def _card_session(paper) -> dict[str, Any] | None:
    """Read the security card introduced by UZSE in September 2026.

    Labels identify totals independently of their position. Missing totals are
    unreadable, whereas explicit zeroes describe a session with no trades yet.
    """
    def text(selector: str) -> str:
        node = paper.select_one(selector)
        return node.get_text(" ", strip=True) if node else ""

    values = {}
    for stat in paper.select(".stats .st"):
        label, value = stat.find("span"), stat.find("b")
        if label is not None and value is not None:
            values[label.get_text(" ", strip=True)] = value.get_text(" ", strip=True)
    quantity = _num(values.get("Кол-во ЦБ за день"))
    turnover = _num(values.get("Объём торгов, UZS"))
    if quantity is None or turnover is None:
        return None
    return {
        "isin": text(".pid .isin").upper(),
        "ticker": text(".pid .tick").upper(),
        "name": text(".pid .pname"),
        "last_price": _num(text(".pprice > b")),
        "last_trade_date": _iso_day(values.get("Дата последней сделки", "")),
        "change_value": _signed(text(".pprice .d")),
        "quantity": quantity,
        "turnover": turnover,
        "open_price": _num(values.get("Стартовая цена")),
        "high_price": _num(values.get("Максимальная цена")),
        "low_price": _num(values.get("Минимальная цена")),
    }


def parse_quote(html: str, isin: str | None = None, market: str = "STK") -> dict[str, Any] | None:
    """One security's session quote from its uzse.uz page.

    Returns None when the page is not a security page (a 404 body, a redirect to
    the default security, an error notice). ``traded`` says whether the security
    traded in the session the page currently describes — the caller must not
    attribute a quote to a session the security sat out, because the page shows
    the *current* session as 0/0/0 before a security's first trade of the day and
    that empty row would otherwise overwrite the real, stored one.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return None

    header = tables[0]
    link = header.find("a", href=re.compile(r"/isu_infos/[^/]+/detail"))
    parts = link.get_text("\n", strip=True).split("\n") if link else []
    page_isin = (parts[0].strip().upper() if parts else "")
    ticker = (parts[1].strip().upper() if len(parts) > 1 else "")
    # The issuer name is the one heading that is neither the security link
    # ("UZ7001100005 KFSK") nor a field label ("Номинал (UZS)").
    name = next((text for text in (h.get_text(" ", strip=True) for h in header.find_all("h4")
                                   if not h.find("a"))
                 if text and "(UZS)" not in text and text != ticker), "")

    price_span = header.select_one(".trd-price")
    last_price = _num(price_span.get_text(" ", strip=True)) if price_span else None
    last_trade_day = _iso_day(header.get_text(" ", strip=True))

    session = _find_table(tables, first_label="Изменение")
    ohlc = _find_table(tables, first_label="Стартовая цена")
    history = _find_table(tables, first_label="Дата", contains="Цена закрытия")
    paper = soup.select_one(".paper")
    if (session is None and paper is None) or history is None:
        logger.warning("uzse quote: %s page has no session/history table", page_isin or isin)
        return None

    session_rows = session.find_all("tr") if session is not None else []
    session_cells = _cells(session_rows[1]) if len(session_rows) > 1 else []
    change_value = _signed(session_cells[0]) if session_cells else None
    quantity = _num(session_cells[1]) if len(session_cells) > 1 else None
    turnover = _num(session_cells[2]) if len(session_cells) > 2 else None

    open_price = high_price = low_price = None
    if ohlc is not None:
        ohlc_rows = ohlc.find_all("tr")
        values = _cells(ohlc_rows[1]) if len(ohlc_rows) > 1 else []
        open_price = _num(values[0]) if values else None
        high_price = _num(values[1]) if len(values) > 1 else None
        low_price = _num(values[2]) if len(values) > 2 else None

    if paper is not None:
        card = _card_session(paper)
        if card is None:
            logger.warning("uzse quote: %s card has no readable session totals", isin)
            return None
        page_isin, ticker, name = card["isin"], card["ticker"], card["name"]
        last_price, last_trade_day = card["last_price"], card["last_trade_date"]
        change_value, quantity, turnover = card["change_value"], card["quantity"], card["turnover"]
        open_price, high_price, low_price = card["open_price"], card["high_price"], card["low_price"]

    # Both layouts must identify the security actually served. UZSE can return
    # another security's page for an unknown ISIN instead of answering 404.
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{10}", page_isin) or (isin and page_isin != isin.upper()):
        logger.warning("uzse quote: asked for %s, page identifies %s", isin, page_isin or "no ISIN")
        return None
    if quantity and (last_price is None or last_trade_day is None):
        logger.warning("uzse quote: %s session lacks a dated price", page_isin)
        return None

    # "Дата | Цена закрытия | Изменение | Кол-во ЦБ | Объём торгов" — the exchange's
    # own settled row for each of the last ~21 sessions. It is the only place a
    # finished session's numbers survive: the session table above it describes
    # whatever day is current, so by 08:00 the next morning it reads 0/0/0 and
    # yesterday's turnover exists nowhere else we can reach.
    closes: list[dict[str, Any]] = []
    for row in history.find_all("tr")[1:]:
        cells = _cells(row)
        if len(cells) < 2:
            continue
        day = _iso_day(cells[0])
        close = _num(cells[1])
        if day and close is not None:
            closes.append({"date": day, "close": close,
                           "change": _signed(cells[2]) if len(cells) > 2 else None,
                           "quantity": _num(cells[3]) if len(cells) > 3 else None,
                           "turnover": _num(cells[4]) if len(cells) > 4 else None})

    traded = bool(quantity and quantity > 0)
    # The session the page describes is dated by the trade that proves it: a page
    # showing 0/0/0 belongs to a session whose date the page never prints.
    trade_date = last_trade_day if traded else None
    close_price = last_price if traded else (closes[0]["close"] if closes else last_price)

    # The previous close is the newest daily close BEFORE this session — the row
    # the exchange carries forward, which is what its own change is struck from.
    previous = next((c for c in closes if not trade_date or c["date"] < trade_date), None)
    prev_close = previous["close"] if previous else None
    if prev_close is None and close_price is not None and change_value is not None:
        prev_close = close_price - change_value

    published = change_value
    if prev_close is not None and close_price is not None:
        change_value = close_price - prev_close
        if published is not None and abs(published - change_value) > 0.011:
            # Not fatal, but it means one of the two numbers describes another
            # session — say so rather than serving a percentage nobody published.
            logger.warning("uzse quote %s: change %s but close-prev = %s",
                           page_isin or isin, published, change_value)

    change_percent = None
    if prev_close and change_value is not None:
        change_percent = change_value / abs(prev_close) * 100

    return {
        "isin": page_isin or (isin or "").upper(),
        "ticker": ticker,
        "name": name,
        "market": market,
        "trade_date": trade_date,
        "traded": traded,
        "close_price": close_price,
        "prev_close": prev_close,
        "prev_close_date": previous["date"] if previous else None,
        "change_value": change_value,
        "change_percent": round(change_percent, 4) if change_percent is not None else None,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "quantity": quantity,
        "turnover": turnover,
        "last_price": last_price,
        "last_trade_date": last_trade_day,
        "history": closes,
        # NOTE: this page also carries an executions log ("Время | Цена | ...").
        # It is NOT parsed for the hourly series — the log cannot say which
        # trades were negotiated (T1) deals, and one block at an off-market
        # price poisons an hour's OHLC. trade_stats.hourly_bars reads the same
        # executions from the trade feed, which carries board_id and a
        # to-the-second moment in each record's header.
    }


def settled_quote(parsed: dict[str, Any] | None) -> dict[str, Any] | None:
    """The exchange's own settled row for the session this security last traded in.

    ``parse_quote`` describes the session the page is currently showing, and that
    session is empty for most securities most of the time — before the day's first
    execution, and for every security that has gone quiet. Nine board rows showed
    no price at all for that reason (UTGA, FRAZP, UZML, TRSBP, TKDMP, MXUS, UPOSP
    and two bonds) while uzse.uz published one for each of them, because the pass
    that was meant to backfill them dropped them at the same "did it trade today?"
    test.

    The page answers anyway — in its daily history, which prints each recent
    session's close, change, quantity and turnover, settled, and still there
    tomorrow morning after the session table has rolled over.

    **The session is found in that history, not from the page's heading.** The
    heading is a separate field and it is not always right: ACMT1B2's reads
    "16.07.2026 — 100 000,01", which is 17.07's price against 16.07's date, and
    the two sessions differ in every number (100 000,01 over 43 units against
    100 500 over 412). Trusting it would have published the wrong one. The
    exchange carries a close forward at zero volume, so the newest history row
    with a quantity IS the last session the security traded in — no heading
    required, and a security that has never traded has no such row.
    """
    if not parsed:
        return None
    history = parsed.get("history") or []
    row = next((h for h in history
                if (h.get("quantity") or 0) > 0 and h.get("close") is not None), None)
    if not row:
        return None
    day = row["date"]
    if parsed.get("last_trade_date") not in (None, day):
        logger.warning("uzse settled %s: the page heads it %s, its history says %s",
                       parsed.get("isin"), parsed.get("last_trade_date"), day)

    previous = next((h for h in history if h.get("date") < day), None)
    change = row.get("change")
    prev_close = previous["close"] if previous else None
    if prev_close is None and change is not None:
        prev_close = row["close"] - change
    if prev_close is not None:
        derived = row["close"] - prev_close
        if change is not None and abs(derived - change) > 0.011:
            # The exchange's own two numbers disagree — say which one we used
            # rather than publish a percentage it never printed.
            logger.warning("uzse settled %s %s: change %s but close-prev = %s",
                           parsed.get("isin"), day, change, derived)
        change = derived

    percent = (change / abs(prev_close) * 100) if (prev_close and change is not None) else None
    return {
        **parsed,
        "trade_date": day,
        "traded": True,
        "settled": True,
        "close_price": row["close"],
        "prev_close": prev_close,
        "prev_close_date": previous["date"] if previous else None,
        "change_value": change,
        "change_percent": round(percent, 4) if percent is not None else None,
        "quantity": row.get("quantity"),
        "turnover": row.get("turnover"),
        # The session's open/high/low are published only while it is the current
        # session; the history keeps the close. Saying nothing is the honest
        # answer, and the upsert keeps whatever it already holds for that day.
        "open_price": None,
        "high_price": None,
        "low_price": None,
    }


def _session() -> requests.Session:
    """A session that survives uzse.uz having a bad minute.

    A read here is not a nice-to-have: a page that times out is a security that
    silently keeps yesterday's quote, and the pass reads a hundred of them in a
    row. uzse.uz answers most of them in under a second and then, without
    warning, stops answering for a while — sixteen consecutive reads timed out
    at 30s while measuring this. Retrying with backoff (the same shape
    openinfo_http uses) turns that minute into a slow pass instead of a hole in
    the board.
    """
    s = requests.Session()
    retry = Retry(total=3, connect=3, read=3, backoff_factor=1.5,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "HEAD"), respect_retry_after_header=True)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(_HTML_HEADERS)
    return s


def fetch_quote(isin: str, market: str = "STK",
                session: requests.Session | None = None) -> dict[str, Any] | None:
    """Fetch and parse one security's quote page."""
    s = session or _session()
    try:
        resp = s.get(f"{UZSE_BASE}/isu_infos/{market}", headers=_HTML_HEADERS,
                     params={"isu_cd": isin, "locale": "ru"}, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        logger.warning("uzse quote fetch failed for %s", isin, exc_info=True)
        return None
    return parse_quote(resp.text, isin=isin, market=market)


def fetch_issue_detail(isin: str, session: requests.Session | None = None) -> dict[str, Any] | None:
    """Share count, class and issuer name for one ISIN (uzse's own registry).

    The board's market cap is shares x price, and a security the ``/stocks``
    mirror never carried has no shares outstanding from any other source we hold
    — openinfo's registry is keyed by issuer and skips whole share classes.
    """
    s = session or _session()
    try:
        resp = s.get(f"{UZSE_BASE}/isu_infos/{isin}/detail", headers=_JSON_HEADERS,
                     params={"locale": "ru"}, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        logger.warning("uzse detail fetch failed for %s", isin, exc_info=True)
        return None

    for record in (payload if isinstance(payload, list) else [payload]):
        if not isinstance(record, dict) or record.get("error"):
            continue
        for share in record.get("shares") or []:
            if str(share.get("isu_cd") or "").upper() != isin.upper():
                continue
            kind = str(share.get("type") or "")
            ticker = str(share.get("isu_srt_cd") or "").upper() or None
            return {
                "isin": isin.upper(),
                "ticker": ticker,
                "name": record.get("company_name") or None,
                "share_type": "preferred" if kind.startswith("Привилег") else "ordinary",
                "nominal": corporate_actions.current_par(ticker, share.get("parval")),
                "shares_outstanding": _num(share.get("list_shrs")),
            }
    return None


def fetch_session_quotes(targets: Iterable[tuple[str, str]], *, pace: float = 0.25,
                         with_detail: bool = True, settle: bool = False,
                         outcome: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Quotes for the securities that traded in the latest session.

    ``targets``: ``[(isin, market)]`` — the exchange's own execution feed says
    who traded and on which market, so the pages fetched are exactly the ones
    whose price moved. Securities that did not trade keep their stored quote:
    their close is unchanged by definition, and re-reading them would attribute
    an empty session row to a day they never traded.

    ``settle`` takes the exchange's settled row for the last session a security
    DID trade in when the current one is empty (see ``settled_quote``) — which is
    every security before the day's first execution, and every quiet security all
    the time. Forward-only storage makes that safe: a settled row is dated the
    session it describes, so it can only fill a gap, never overwrite a newer one.

    ``outcome``, when given, is filled with why each target produced no quote.
    An empty result means two different things — "the exchange has not opened
    yet, every page reads 0/0/0" and "no page could be read at all" — and only
    the second is a failure. The caller cannot tell them apart from the list.
    ``outcome["unread"]`` names the securities whose page could not be read, so a
    caller that waits and tries again asks only about those.
    """
    session = _session()
    out: list[dict[str, Any]] = []
    targets = list(targets)
    unread: list[tuple[str, str]] = []
    counts: dict[str, Any] = {"targets": len(targets), "unreadable": 0, "idle": 0,
                              "settled": 0, "quoted": 0}
    consecutive = 0
    for index, (isin, market) in enumerate(targets):
        # Retrying is what keeps one bad minute from becoming a hole in the board,
        # and it is also what turns uzse.uz being down into an hours-long run: a
        # hundred pages x four attempts x a thirty-second timeout. When the site
        # has stopped answering entirely, say so after a few and stop asking —
        # Railway skips a cron run whose predecessor is still going.
        if consecutive >= 5:
            unread.extend(targets[index:])
            counts["unreadable"] += len(targets) - index
            logger.error("uzse quotes: %d pages in a row unreadable — abandoning the "
                         "pass with %d securities unread", consecutive, len(targets) - index)
            break
        quote = fetch_quote(isin, market=market or "STK", session=session)
        if pace:
            time.sleep(pace)
        if not quote:
            counts["unreadable"] += 1
            unread.append((isin, market))
            consecutive += 1
            continue
        consecutive = 0
        if not quote.get("traded") or not quote.get("trade_date"):
            settled = settled_quote(quote) if settle else None
            if settled is None:
                counts["idle"] += 1
                logger.info("uzse quote %s: page shows no trade for the current session", isin)
                continue
            counts["settled"] += 1
            logger.info("uzse quote %s: quiet today, taking the exchange's settled %s row",
                        isin, settled["trade_date"])
            quote = settled
        if with_detail:
            detail = fetch_issue_detail(isin, session=session) or {}
            if pace:
                time.sleep(pace)
            # uzse's registry record is authoritative for what the page only
            # renders — share class, par value, issued count and the issuer's
            # full name (the page heading carries the security, not the issuer).
            for key in ("ticker", "name", "share_type", "nominal", "shares_outstanding"):
                if detail.get(key):
                    quote[key] = detail[key]
            shares, price = quote.get("shares_outstanding"), quote.get("close_price")
            quote["market_cap"] = shares * price if (shares and price) else None
        out.append(quote)
    counts["quoted"] = len(out)
    counts["unread"] = unread
    if outcome is not None:
        outcome.update(counts)
    return out


if __name__ == "__main__":  # pragma: no cover - manual probe
    import json
    import sys

    code = sys.argv[1] if len(sys.argv) > 1 else "UZ7001100005"
    mkt = sys.argv[2] if len(sys.argv) > 2 else "STK"
    q = fetch_quote(code, market=mkt)
    if q:
        q.pop("history", None)
    print(json.dumps(q, ensure_ascii=False, indent=1))

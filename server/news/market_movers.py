"""Daily post facts from the same dated auction quotes used by the market board."""
from contextlib import closing
from decimal import Decimal
from math import isfinite

from catalogue import market_store
from catalogue.storage import get_catalog_conn
from delisted import is_delisted_isin
from heatmap import day_change
from news_marketing import MAX_PITCHES
from server.market.dates import _iso_trade_date
from server.settings import BOARD_DENYLIST


def number(value):
    # The exchange also trades sub-sum stocks. Preserve all stored quote decimals.
    value = Decimal(str(value))
    return format(value.normalize(), ",f").replace(",", " ").replace(".", ",")


def change_label(change):
    sign = "+" if change > 0 else "−"
    magnitude = round(abs(change), 2)
    return sign + (number(magnitude) if magnitude else "<0,01") + "%"


def ranked_quotes(session):
    moves = []
    for row in market_store.get_all_quotes().values():
        if (row.get("market") != "STK" or not row.get("ticker") or row["ticker"] in BOARD_DENYLIST
                or is_delisted_isin(row["isin"]) or _iso_trade_date(row.get("trade_date")) != session):
            continue
        if (row.get("turnover") or 0) <= 0 and (row.get("quantity") or 0) <= 0:
            continue
        close = row.get("close_price")
        base_day = _iso_trade_date(row.get("prev_close_date"))
        if not close or close <= 0 or (base_day and base_day >= session):
            continue
        change = day_change(close, row.get("prev_close"))
        if change and isfinite(change):
            moves.append((row, change))
    moves.sort(key=lambda pair: (-round(abs(pair[1]), 10), -(pair[0].get("turnover") or 0), pair[0]["ticker"], pair[0]["isin"]))
    if moves:
        # Reserve a place for the leading opposite move even on a one-sided rally.
        opposite = next((i for i, (_, pct) in enumerate(moves) if pct * moves[0][1] < 0), None)
        if opposite is not None:
            moves.insert(1, moves.pop(opposite))
    return moves[:MAX_PITCHES]


def _post_ids(session, rows):
    # News ids are positive. A separate sequence gives each dated security a
    # stable negative editor id without hashing a ticker or changing old links.
    with closing(get_catalog_conn()) as conn, conn:
        saved = {r["isin"]: -r["id"] for r in conn.execute(
            "SELECT id,isin FROM marketing_movers WHERE session_day=?", (session,))}
        for row, _ in rows:
            isin = row["isin"]
            if isin not in saved:
                conn.execute("INSERT INTO marketing_movers(session_day,isin) VALUES(?,?) ON CONFLICT(session_day,isin) DO NOTHING",
                             (session, isin))
                saved[isin] = -conn.execute("SELECT id FROM marketing_movers WHERE session_day=? AND isin=?",
                                            (session, isin)).fetchone()["id"]
        return saved


def stories(site, link_for):
    day = market_store.latest_session_date()
    if not day:
        return []
    session = day.isoformat()
    rows = ranked_quotes(session)
    ids = _post_ids(session, rows)
    stories = []
    for row, change in rows:
        key = ids[row["isin"]]
        ticker = row["ticker"]
        title = f"{ticker} {change_label(change)}"
        before, after = number(row["prev_close"]), number(row["close_price"])
        excerpt = f"{before} → {after} UZS"
        story = dict(id=key, ticker=ticker, title=title, published_at=session, source="UZStock",
                     url=site+"/market", snippet=excerpt, excerpt=excerpt)
        for lang in ("ru", "uz"):
            ru = lang == "ru"
            name = (row.get("name") or ticker).strip()
            share = (" · привилегированные" if ru else " · imtiyozli") if row.get("share_type")=="preferred" else ""
            heading = f"{title} · {session}"
            price = (f"Предыдущее закрытие: {before} сум. Закрытие сессии: {after} сум." if ru else
                     f"Oldingi yopilish narxi: {before} so‘m. Sessiya yopilishi: {after} so‘m.")
            if (row.get("quantity") or 0) > 0:
                qty = number(row["quantity"])
                activity = f"Объём торгов: {qty} шт." if ru else f"Savdo hajmi: {qty} dona."
            else:
                turnover = number(row["turnover"])
                activity = f"Оборот: {turnover} сум." if ru else f"Savdo aylanmasi: {turnover} so‘m."
            reason = ("Изменение цены закрытия к предыдущему закрытию по данным биржи." if ru else
                      "Birja ma’lumotlari bo‘yicha oldingi yopilish narxiga nisbatan o‘zgarish.")
            cta = "Котировки на UZStock" if ru else "UZStock’da kotirovkalar"
            story[lang] = dict(text=f"{heading}\n{name}{share}\n\n{price}\n{activity}\n\n{cta}\n{link_for(key,lang)}",reason=reason)
        stories.append(story)
    return stories

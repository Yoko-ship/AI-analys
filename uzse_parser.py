import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

BASE_URL = "https://uzse.uz/trade_results"
DATE_FORMAT = "%d.%m.%Y"
DAYS_BACK = 30
TIMEOUT = 30

requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def _normalize_name(value: str) -> str:
    value = (value or "").lower()
    value = value.replace("<", " ").replace(">", " ")
    value = value.replace('"', " ")
    value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _parse_number(text: str) -> float | None:
    if not text:
        return None

    cleaned = re.sub(r"[^\d.,]", "", str(text).strip())
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        last_sep = max(cleaned.rfind(","), cleaned.rfind("."))
        integer_part = re.sub(r"[.,]", "", cleaned[:last_sep])
        decimal_part = re.sub(r"[.,]", "", cleaned[last_sep + 1:])
        cleaned = f"{integer_part}.{decimal_part}" if decimal_part else integer_part
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            cleaned = "".join(parts)
        else:
            cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        parts = cleaned.split(".")
        if all(len(part) == 3 for part in parts[1:]):
            cleaned = "".join(parts)
        else:
            cleaned = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(cleaned)
    except ValueError:
        return None


def _build_url() -> str:
    end = datetime.now()
    begin = end - timedelta(days=DAYS_BACK)
    return (
        f"{BASE_URL}?mkt_id=ALL"
        f"&begin={begin.strftime(DATE_FORMAT)}"
        f"&end={end.strftime(DATE_FORMAT)}"
    )


def _update_query_params(url: str, **params) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key, value in params.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = [str(value)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _build_page_url(url: str, page: int) -> str:
    return _update_query_params(url, page=page)


def _is_repo(text: str) -> bool:
    upper = (text or "").upper()
    return "REPO" in upper or "РЕПО" in upper


@lru_cache(maxsize=1)
def _load_isu_directory() -> tuple[dict, ...]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    response = requests.get(
        "https://uzse.uz/isu_infos/names",
        params={"mkt_id": "STK"},
        headers=headers,
        verify=False,
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    items = []
    for raw in response.json():
        if not isinstance(raw, list) or len(raw) < 3:
            continue
        isu_code, ticker, issuer_name = str(raw[0]), str(raw[1]), str(raw[2])
        items.append({
            "isu_code": isu_code,
            "ticker": ticker.upper(),
            "issuer_name": issuer_name,
            "issuer_name_normalized": _normalize_name(issuer_name),
        })
    return tuple(items)


def resolve_security(query: str, company_name: str | None = None) -> dict | None:
    normalized_query = query.strip().upper()
    normalized_company = _normalize_name(company_name or "")
    directory = _load_isu_directory()

    for item in directory:
        if normalized_query == item["ticker"] or normalized_query == item["isu_code"]:
            return item

    if normalized_company:
        for item in directory:
            if normalized_company == item["issuer_name_normalized"]:
                return item

    normalized_query_name = _normalize_name(query)
    if normalized_query_name:
        exact_matches = [
            item for item in directory
            if item["issuer_name_normalized"] == normalized_query_name
        ]
        if exact_matches:
            return exact_matches[0]

        partial_matches = [
            item for item in directory
            if normalized_query_name in item["issuer_name_normalized"]
            or item["issuer_name_normalized"] in normalized_query_name
        ]
        if len(partial_matches) == 1:
            return partial_matches[0]

    candidates = []
    names_to_match = [value for value in [normalized_company, normalized_query_name] if value]
    if names_to_match:
        for item in directory:
            best_score = max(
                SequenceMatcher(None, target, item["issuer_name_normalized"]).ratio()
                for target in names_to_match
            )
            if best_score >= 0.72:
                candidates.append((best_score, item))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

    return None


def _extract_last_page(soup: BeautifulSoup) -> int:
    pages = []
    for link in soup.select("ul.pagination a[href]"):
        text = link.get_text(" ", strip=True)
        href = link.get("href", "")
        if text.isdigit():
            pages.append(int(text))
        match = re.search(r"[?&]page=(\d+)", href)
        if match:
            pages.append(int(match.group(1)))
    return max(pages) if pages else 1


def _map_columns(headers: list[str], cells: list[str]) -> dict:
    result = {}
    keywords = {
        "date": ["дата", "date", "время", "time"],
        "trade_price": ["торговая цена", "цена", "price", "курс"],
        "quantity": ["кол-во", "количество", "qty", "число", "штук"],
        "volume": ["объём", "объем", "volume", "сумма", "оборот"],
        "market_type": ["рынок", "market"],
    }

    if headers:
        for field, field_keywords in keywords.items():
            for idx, header in enumerate(headers):
                if any(keyword in header.lower() for keyword in field_keywords):
                    if idx < len(cells):
                        value = cells[idx]
                        result[field] = _parse_number(value) if field in {"trade_price", "quantity", "volume"} else value
                    break
        return result

    fallback_positions = {
        "date": 0,
        "market_type": 5,
        "trade_price": 7,
        "quantity": 8,
        "volume": 9,
    }
    for field, idx in fallback_positions.items():
        if idx >= len(cells):
            continue
        value = cells[idx]
        result[field] = _parse_number(value) if field in {"trade_price", "quantity", "volume"} else value
    return result


def get_trade_data(query: str, company_name: str | None = None, verbose: bool = False) -> pd.DataFrame:
    security = resolve_security(query, company_name=company_name)
    if not security:
        return pd.DataFrame(columns=["ticker", "date", "trade_price", "quantity", "volume", "market_type"])

    url = _update_query_params(_build_url(), search_key=security["isu_code"], mkt_id="STK")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    session.verify = False

    first_page = session.get(_build_page_url(url, 1), timeout=TIMEOUT)
    first_page.raise_for_status()
    soup = BeautifulSoup(first_page.text, "html.parser")

    headers = [cell.get_text(" ", strip=True) for cell in soup.select("table.figma-table thead th, table.figma-table thead td")]
    last_page = _extract_last_page(soup)
    if verbose:
        print(f"UZSE: найдено страниц {last_page} для {security['ticker']}")

    records = []
    for page_no in range(1, last_page + 1):
        if page_no == 1:
            page_soup = soup
        else:
            page_response = session.get(_build_page_url(url, page_no), timeout=TIMEOUT)
            page_response.raise_for_status()
            page_soup = BeautifulSoup(page_response.text, "html.parser")

        for row in page_soup.select("table.figma-table tbody tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            if not cells:
                continue
            row_text = " ".join(cells)
            if _is_repo(row_text):
                continue
            if security["ticker"] not in row_text.upper() and security["isu_code"] not in row_text.upper():
                continue

            mapped = _map_columns(headers, cells)
            records.append({
                "ticker": security["ticker"],
                "date": mapped.get("date"),
                "trade_price": mapped.get("trade_price"),
                "quantity": mapped.get("quantity"),
                "volume": mapped.get("volume"),
                "market_type": mapped.get("market_type"),
            })

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["ticker", "date", "trade_price", "quantity", "volume", "market_type"])

    for column in ["trade_price", "quantity", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["date", "trade_price", "quantity", "volume"], how="all").reset_index(drop=True)
    return df


def build_liquidity_df(query: str, company_name: str | None = None, verbose: bool = False) -> pd.DataFrame:
    df = get_trade_data(query, company_name=company_name, verbose=verbose).copy()
    if df.empty:
        return pd.DataFrame(columns=[
            "ticker", "trade_days", "trade_count", "avg_trade_price", "avg_trade_size_shares",
            "avg_trade_value", "median_trade_value", "total_volume", "total_quantity",
            "active_days_share", "liquidity_label"
        ])

    trade_dates = pd.to_datetime(df["date"], format="%d %B %Y, %H:%M", errors="coerce")
    if trade_dates.isna().all():
        trade_day_series = df["date"].astype(str).str.split(",").str[0].str.strip()
    else:
        trade_day_series = trade_dates.dt.strftime("%Y-%m-%d")

    trade_days = int(trade_day_series.nunique())
    total_trades = int(len(df))
    total_volume = float(df["volume"].fillna(0).sum())
    total_quantity = float(df["quantity"].fillna(0).sum())
    avg_trade_value = float(df["volume"].dropna().mean()) if not df["volume"].dropna().empty else 0.0
    median_trade_value = float(df["volume"].dropna().median()) if not df["volume"].dropna().empty else 0.0
    avg_trade_size_shares = float(df["quantity"].dropna().mean()) if not df["quantity"].dropna().empty else 0.0
    avg_trade_price = float(df["trade_price"].dropna().mean()) if not df["trade_price"].dropna().empty else 0.0
    active_days_share = round(trade_days / DAYS_BACK, 4)

    if trade_days >= 15 and avg_trade_value >= 100000:
        liquidity_label = "high"
    elif trade_days >= 8 and avg_trade_value >= 10000:
        liquidity_label = "medium"
    else:
        liquidity_label = "low"

    return pd.DataFrame([{
        "ticker": df["ticker"].iloc[0],
        "trade_days": trade_days,
        "trade_count": total_trades,
        "avg_trade_price": round(avg_trade_price, 2),
        "avg_trade_size_shares": round(avg_trade_size_shares, 2),
        "avg_trade_value": round(avg_trade_value, 2),
        "median_trade_value": round(median_trade_value, 2),
        "total_volume": round(total_volume, 2),
        "total_quantity": round(total_quantity, 2),
        "active_days_share": active_days_share,
        "liquidity_label": liquidity_label,
    }])


if __name__ == "__main__":
    user_query = input("Введите тикер или название компании: ").strip() or "QATT"
    liquidity_df = build_liquidity_df(user_query, verbose=True)
    print(liquidity_df.to_string(index=False))

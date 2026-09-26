from __future__ import annotations

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import Response
from typing import Any
import asyncio
import formulas
import os
import provenance
import requests
import server.http as http
import threading
import time


router = APIRouter()


# Official daily exchange rates. cbu.uz publishes them as JSON — no scraping —
# and sets them once per business day, so a half-hour in-process cache keeps the
# site current without leaning on the bank's server. A failed refresh serves the
# last good answer: yesterday's official rate stays official until the bank
# publishes the next one.
CBU_RATES_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"


CBU_RATES_TTL_SEC = int(os.getenv("CBU_RATES_TTL_SEC", "1800"))


CBU_RATES_CURRENCIES = tuple(
    c.strip().upper()
    # GBP/CNY/JPY/KZT were dropped at the customer's request (2026-08-12);
    # the env var can widen the set back without a code change.
    for c in os.getenv("CBU_RATES_CURRENCIES", "USD,EUR,RUB").split(",")
    if c.strip())


_cbu_rates_cache: dict[str, Any] = {"at": 0.0, "payload": None}


_cbu_rates_lock = threading.Lock()


def _fetch_cbu_rates() -> list[dict[str, Any]]:
    resp = requests.get(CBU_RATES_URL, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _cbu_rates_payload() -> dict[str, Any]:
    raw = _fetch_cbu_rates()
    by_ccy = {str(r.get("Ccy", "")).upper(): r for r in raw if isinstance(r, dict)}
    rates = []
    for ccy in CBU_RATES_CURRENCIES:
        row = by_ccy.get(ccy)
        if not row:
            continue
        rates.append({
            "ccy": ccy,
            "name_ru": row.get("CcyNm_RU"),
            "name_uz": row.get("CcyNm_UZ"),
            "name_en": row.get("CcyNm_EN"),
            "nominal": formulas.to_number(row.get("Nominal")),
            "rate": formulas.to_number(row.get("Rate")),
            "diff": formulas.to_number(row.get("Diff")),
        })
    return {
        "ok": True,
        "source": "cbu.uz",
        "date": next((r.get("Date") for r in raw if r.get("Date")), None),
        "rates": rates,
    }


@router.get("/api/currency/rates")
async def api_currency_rates(request: Request) -> Response:
    now = time.time()
    if _cbu_rates_cache["payload"] is None or now - _cbu_rates_cache["at"] > CBU_RATES_TTL_SEC:
        loop = asyncio.get_running_loop()
        try:
            payload = await loop.run_in_executor(None, _cbu_rates_payload)
            with _cbu_rates_lock:
                _cbu_rates_cache["payload"] = payload
                _cbu_rates_cache["at"] = now
        except Exception:
            http.logger.exception("CBU rates refresh failed")
            if _cbu_rates_cache["payload"] is None:
                # Nothing cached and the bank unreachable — say so honestly
                # rather than 502: the strip simply does not render.
                return http._etag_json(request, {"ok": False, "rates": []}, max_age=60)
    return http._etag_json(request, _cbu_rates_cache["payload"], max_age=300)


def _bank_fx_payload() -> dict[str, Any]:
    """Group the flat rate-cell rows into one entry per bank, plus the best
    buy/sell across banks for each currency+channel — flagged cells are
    excluded from "best" so a suspect quote never wins the ranking, but they
    are still served on the bank's own card (ТЗ: show the real number, mark
    uncertainty, never hide it)."""
    rows = provenance.bank_fx_rates_latest()
    banks: dict[str, dict[str, Any]] = {}
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = r["bank_code"]
        bank = banks.setdefault(code, {
            "bank_code": code, "bank_name": r["bank_name"],
            "updated_at": r["bank_updated_at"], "rates": {},
        })
        # A bank's cards can carry more than one bank_updated_at across
        # currencies (a channel refreshed independently) — the newest wins as
        # the bank's headline "as of" stamp.
        if r["bank_updated_at"] and r["bank_updated_at"] > (bank["updated_at"] or ""):
            bank["updated_at"] = r["bank_updated_at"]
        bank["rates"].setdefault(r["ccy"], {})[r["channel"]] = {
            "buy": r["buy"], "sell": r["sell"], "flag": r["flag"],
        }
        if r["flag"]:
            continue
        slot = best.setdefault(r["ccy"], {}).setdefault(r["channel"], {"best_buy": None, "best_sell": None})
        if r["buy"] is not None and (slot["best_buy"] is None or r["buy"] > slot["best_buy"]["value"]):
            slot["best_buy"] = {"bank_code": code, "bank_name": r["bank_name"], "value": r["buy"]}
        if r["sell"] is not None and (slot["best_sell"] is None or r["sell"] < slot["best_sell"]["value"]):
            slot["best_sell"] = {"bank_code": code, "bank_name": r["bank_name"], "value": r["sell"]}
    return {
        "ok": True,
        "source": "bankxizmatlari.uz",
        "banks": sorted(banks.values(), key=lambda b: b["bank_name"] or ""),
        "best": best,
    }


@router.get("/api/bank-fx")
async def api_bank_fx(request: Request) -> Response:
    """Every commercial bank's published exchange rate, refreshed hourly by
    the collector — see bank_fx_collector.py for what the source publishes
    and why a wide spread is flagged rather than dropped."""
    try:
        payload = _bank_fx_payload()
    except Exception:
        http.logger.exception("bank-fx read failed")
        return http._etag_json(request, {"ok": False, "banks": [], "best": {}}, max_age=60)
    return http._etag_json(request, payload, max_age=300)

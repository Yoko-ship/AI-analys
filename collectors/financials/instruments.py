"""Financials instruments operations with explicit dependencies."""
from __future__ import annotations

import collectors.financials.delivery as collectors_financials_delivery
import collectors.financials.settings as collectors_financials_settings
import os
import requests


def _board_bonds() -> list[dict]:
    """Bonds the board shows that openinfo's listing registry does not.

    The reference walk starts from ``info_rfb.isin_codes`` of catalogued orgs,
    but the board's universe is the exchange's own trade feed — an LLC issuer
    (DELTA, UZUM SARMOYA, IMKON FINANS) has no info_rfb registry, so its bonds
    never entered the walk and their par stayed NULL while the exchange card
    states it. The board itself is the missing list: ask prod what it shows.
    """
    url = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/") + "/api/bonds"
    try:
        items = requests.get(url, timeout=60).json().get("items") or []
    except Exception:  # noqa: BLE001 — an unreachable board must not fail the push
        collectors_financials_settings.log.exception("board bond list fetch failed")
        return []
    return [{"ticker": str(it.get("ticker")).strip().upper(),
             "isin": str(it.get("isin") or "").strip().upper()}
            for it in items
            if it.get("ticker") and str(it.get("isin") or "").upper().startswith("UZ6")]


def push_bond_reference(listing_rows: list[dict]) -> int:

    """Push the bond issue reference (ТЗ Дополнение 1 §А.4).



    Three sources, in the order a field is allowed to overwrite:



    1. **The exchange's register of circulating issues** (``bond_registry``) —

       the coupon rate, the payment cycle, the placement date and the

       redemption date, for every issue on the board. This is the source that

       turns the yield half of the section on: before it, ``is_complete`` was

       false for all but the one issue already in redemption.

    2. **The exchange's security card** (``/isu_infos/{isin}/detail``) — the par

       and the issue size, per security. It wins over the register where both

       speak: it is the per-line record the price is quoted against.

    3. **The issuer's own filings on openinfo** (``bond_terms``) — a coupon

       inverted from the payments actually made, and a redemption date from

       material fact #31. An executed fact outranks a registered undertaking,

       so this wins last.



    Every term that lands also records WHICH of the three stated it, because

    the section's first rule is that a registered undertaking is never shown as

    a filed fact.

    """

    import bond_registry

    import listings_collector as lc



    walk = list(listing_rows or [])

    known = {str(r.get("isin") or "").strip().upper() for r in walk}

    extra = [b for b in _board_bonds() if b["isin"] not in known]

    if extra:

        collectors_financials_settings.log.info("bond reference: %d board bonds absent from the listing registry: %s",

                 len(extra), ", ".join(b["ticker"] for b in extra))

    card_rows = lc.collect_bond_reference_rows(walk + extra)



    # The board's own ticker→ISIN mapping settles the register's one collision

    # (two ISINs written under a single ticker); without it both are dropped.

    isin_by_ticker = {str(r.get("ticker") or "").upper(): str(r.get("isin") or "").upper()

                      for r in walk + extra + card_rows if r.get("ticker") and r.get("isin")}

    registry_rows = bond_registry.collect_registry_rows(isin_by_ticker=isin_by_ticker)

    for row in registry_rows:

        if row.get("coupon_rate") is not None or row.get("coupon_type"):

            row["coupon_source"] = "exchange_registry"

        if row.get("maturity_date"):

            row["maturity_source"] = "exchange_registry"



    rows = bond_registry.merge_reference(card_rows, registry_rows)

    if not rows:

        collectors_financials_settings.log.info("bond reference: nothing to push")

        return 0



    # The coupon and the redemption date as the ISSUER states them: there is no

    # prospectus document to read, and the rate is inverted from the filed

    # payments rather than parsed out of prose.

    coupons: list[dict] = []

    try:

        import bond_terms



        terms = bond_terms.collect_bond_terms(rows)

        by_ticker = {t["ticker"]: t for t in terms["reference"]}

        merged: list[dict] = []

        for row in rows:

            filed = _filed_terms_for(row, by_ticker.get(row["ticker"], {}))

            merged.append({**row, **filed})

        rows = merged

        coupons = terms["coupons"]

        collectors_financials_settings.log.info("bond terms: %d issues with a filed coupon, %d coupons filed",

                 sum(1 for t in by_ticker.values() if t.get("coupon_rate")), len(coupons))

    except Exception:  # noqa: BLE001 — the par must land even if openinfo is down

        collectors_financials_settings.log.exception("bond terms step failed — pushing the exchange half only")



    complete = sum(1 for r in rows if r.get("nominal") and r.get("coupon_rate") is not None

                   and r.get("maturity_date"))

    collectors_financials_settings.log.info("bond reference: %d issues, %d complete enough to discount", len(rows), complete)

    return collectors_financials_delivery._post("/api/admin/bonds/reference", {"rows": rows, "coupons": coupons})


def push_gov_auctions() -> int:
    """Push the ГЦБ primary market + the key rate (cbu.uz fiscal agent).

    Monthly auctions read on a daily cron: nearly every run re-states what prod
    already holds, and the upsert makes that a no-op. The base curve these rows
    build is what turns a bond's yield into a spread.
    """
    import gov_bonds_collector as gc

    rows = gc.collect_gov_auctions()
    if not rows:
        collectors_financials_settings.log.info("gov auctions: nothing parsed — leaving prod as it stands")
        return 0
    return collectors_financials_delivery._post("/api/admin/gov-auctions",
                 {"rows": rows, "key_rate": gc.collect_key_rate()})


def push_bank_fx() -> int:
    """Push commercial-bank exchange rates (bankxizmatlari.uz).

    Runs on its own hourly cron, separate from the daily pipeline: banks
    update through the business day, not once a day like a filing. Keyed on
    each bank's own stated update time, so a quiet poll pushes rows that just
    upsert to themselves — no history growth, no error either.
    """
    import bank_fx_collector as bf

    rows = bf.collect_bank_rates()
    if not rows:
        collectors_financials_settings.log.info("bank fx: nothing parsed — leaving prod as it stands")
        return 0
    return collectors_financials_delivery._post("/api/admin/bank-fx", {"rows": rows})


def _filed_terms_for(row: dict, terms: dict) -> dict:
    """What the issuer's filings add to one register row, with their sources.

    Filings win when several coupons agree — they prove the rate. A rate
    inverted from ONE coupon rests on the register's frequency, so when it
    still disagrees with the register's own rate the register stands (rate and
    frequency both) and the conflict is logged rather than published.
    """
    filed = {k: v for k, v in (terms or {}).items() if v is not None}
    evidence = filed.pop("coupon_evidence", 0) or 0
    listed = row.get("coupon_rate")
    # An irregular first/last coupon or a corrected filing does not change
    # a contractually fixed rate into a floating one.
    if (row.get("coupon_type") in {"fixed", "zero"}
            and listed is not None and filed.get("coupon_type") == "floating"):
        for key in ("coupon_rate", "coupon_freq", "coupon_type", "source_url"):
            filed.pop(key, None)
    if (evidence <= 1 and listed is not None and filed.get("coupon_rate") is not None
            and abs(float(filed["coupon_rate"]) - float(listed)) > 0.5):
        collectors_financials_settings.log.warning("bond %s: one filed coupon implies %.2f%%, the register states %.2f%% — "
                    "keeping the register", row.get("ticker"), filed["coupon_rate"], listed)
        filed.pop("coupon_rate", None)
        filed.pop("coupon_freq", None)
        filed.pop("coupon_type", None)
        filed.pop("source_url", None)
    if filed.get("coupon_rate") is not None:
        filed["coupon_source"] = "openinfo_facts"
    if filed.get("maturity_date"):
        filed["maturity_source"] = "openinfo_facts"
    return filed

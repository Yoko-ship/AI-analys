"""«Daromad Plus» (ODMP) is a catalogue-only issuer: filings, no exchange security."""

import delisted
import entity_resolver
import manual_company_info
import openinfo_reconcile
import securities_catalog
from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS

# openinfo's name byte for byte: curly quotes, a Cyrillic «Р», a double space.
# The /reports/main/ search runs on it, so a "tidied" key finds nothing.
OPENINFO_NAME = "“Daromad Рlus” investisiya fondi  aksiyadorlik jamiyati"


def test_odmp_is_pinned_to_openinfo_org_538() -> None:
    assert entity_resolver.ORG_OVERRIDES["ODMP"] == "538"
    assert openinfo_reconcile.ORG_ID_OVERRIDE["ODMP"] == 538
    # No ISIN exists, and inventing one would attach another issuer's line.
    assert "ODMP" not in entity_resolver.ISIN_OVERRIDES


def test_odmp_catalogue_entry_uses_openinfos_exact_name() -> None:
    assert COMPANY_CATALOG[OPENINFO_NAME] == "ODMP"
    assert COMPANY_SECTORS["ODMP"] == securities_catalog._TICKER_SECTORS["ODMP"] == "funds"


def test_odmp_is_not_treated_as_delisted() -> None:
    # A security-less issuer is exactly what delisted._NO_SECURITY removes.
    assert "ODMP" not in delisted.DELISTED_TICKERS


def test_odmp_profile_does_not_claim_exchange_trading() -> None:
    info = manual_company_info.MANUAL_INFO["ODMP"]
    for lang in ("ru", "en", "uz"):
        assert info[lang]
    assert "не входят в листинг" in info["ru"]


def test_single_ticker_backfill_catalogues_an_unlisted_issuer_first(monkeypatch) -> None:
    """The full report sync walks exchange securities, so ODMP never reached the
    catalogue the backfill reads — and its backfill found nothing to parse."""
    import catalogue.filings as filings
    import catalogue.sync as sync
    import collectors.financials.backfill as backfill

    synced = []
    monkeypatch.setattr(filings, "get_company_reports", lambda ticker: [])
    monkeypatch.setattr(sync, "sync_company",
                        lambda ticker, name, **kw: synced.append((ticker, name, kw)) or {"added": 19})

    backfill._ensure_catalogued("ODMP")
    assert synced == [("ODMP", OPENINFO_NAME, {"force": True, "org_id": "538"})]


def test_backfill_leaves_catalogued_or_unpinned_tickers_alone(monkeypatch) -> None:
    import catalogue.filings as filings
    import catalogue.sync as sync
    import collectors.financials.backfill as backfill

    monkeypatch.setattr(sync, "sync_company", lambda *a, **k: (_ for _ in ()).throw(AssertionError("synced")))
    monkeypatch.setattr(filings, "get_company_reports", lambda ticker: [{"year": 2025}])
    backfill._ensure_catalogued("ODMP")      # already has reports
    monkeypatch.setattr(filings, "get_company_reports", lambda ticker: [])
    backfill._ensure_catalogued("TNGB")      # catalogued name, but no org pin
    backfill._ensure_catalogued("NOPE")      # unknown ticker

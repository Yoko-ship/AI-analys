"""The PDF hierarchy is display metadata, not a replacement for financial templates."""
import heatmap
import instruments


def test_curated_industries_override_stale_display_sectors_for_both_classes():
    securities = {t: {"sector": old} for t, old in [
        ("DORI", "manufacturing"), ("PLST", "mining"), ("PLSTP", "mining"),
        ("UVGT", "transport"), ("UZGF", "mining"), ("UZGFP", "mining"),
        ("ORGS", "manufacturing"), ("METQ", "other"), ("TGBK", "other"),
    ]}
    expected = dict(DORI="trade", PLST="manufacturing", PLSTP="manufacturing",
                    UVGT="manufacturing", UZGF="professional", UZGFP="professional",
                    ORGS="construction", METQ="construction", TGBK="finance")
    catalog = instruments.build_catalog(securities=securities)
    assert {r["ticker"]: r["sector"] for r in catalog["items"]} == expected
    tiles = heatmap.build_heatmap([{"ticker": t} for t in securities], securities)["tiles"]
    assert {r["ticker"]: r["sector"] for r in tiles} == expected
    # The input's financial-sector fallback is not rewritten by display grouping.
    assert securities["DORI"]["sector"] == "manufacturing"


def test_classification_exposes_source_and_uncertainty_without_losing_new_listings():
    rows = instruments.build_catalog(securities={t: {} for t in ["CBSK", "ORGS", "UZGF", "NEW"]})["items"]
    classifications = {r["ticker"]: r.get("industry_classification") for r in rows}
    assert classifications["CBSK"] is not None
    assert classifications["CBSK"]["status"] == "inferred"
    assert classifications["CBSK"]["oked"] is None
    assert classifications["ORGS"]["status"] == "conflict"
    assert classifications["UZGF"]["oked"] == "71120"
    assert classifications["UZGF"]["evidence"][0]["url"].startswith("https://uzse.uz/")
    assert "NEW" in classifications and classifications["NEW"] is None


def test_pdf_coverage_and_explicit_share_class_identity():
    from company_industries import registry, classification_for
    data = registry()
    assert len(data["issuers"]) == 69
    assert len(data["sections"]) == 8
    assert len(data["groups"]) == 29
    tickers = [t for issuer in data["issuers"] for t in issuer["tickers"]]
    assert len(tickers) == len(set(tickers)) == 102
    assert classification_for("bngp")["issuer_id"] == classification_for("BNGPP")["issuer_id"]
    assert classification_for("BNG") is None  # BNGP is the ordinary ticker, not a suffix guess.
    assert classification_for("IPTB")["group"] == "banks"
    assert classification_for("IPTBP")["group"] == "banks"


def test_catalog_alias_resolves_to_the_exchange_issuer():
    from company_industries import classification_for
    assert classification_for("TNGB") is not None
    assert classification_for("TNGB")["issuer_id"] == "TGBK"

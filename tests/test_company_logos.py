"""Company logos should follow the deployed registry, not stale DB rows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

import securities_catalog
import company_imports


LOGO_ROOT = Path(__file__).resolve().parents[1]
REGISTERED_LOGOS = sorted({
    url for url in json.loads((LOGO_ROOT / "company_logos.json").read_text()).values()
    if url.startswith("/logos/")
})


@pytest.mark.parametrize("url", REGISTERED_LOGOS)
def test_registered_logos_have_enough_detail_for_retina_badges(url):
    asset = LOGO_ROOT / url.lstrip("/")
    assert asset.is_file(), url
    if asset.suffix == ".svg":
        return  # Vector artwork scales without a raster resolution limit.
    with Image.open(asset) as image:
        # The 56px badge has 12% padding: its mark is at most 42.56 CSS px.
        # 128 source pixels cover that mark at up to 3x device pixel density.
        assert max(image.size) >= 128, f"{url}: {image.size} is a favicon, not a high-density logo"


def test_catalog_overlays_current_logo_registry_on_read(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(securities_catalog, "DB_PATH", tmp_path / "securities.db")
    securities_catalog.sync_securities(
        [{
            "ticker": "KFSK",
            "isin": "UZ7001100005",
            "name": '"Kafolat sug\'urta kompaniyasi" AJ',
            "type": "stock",
            "share_type": "ordinary",
        }],
        {},
    )

    security = securities_catalog.get_securities_map()["KFSK"]

    assert security["logo_url"] == "/logos/KFSK_STATIC.svg"


def test_preferred_share_uses_the_same_issuer_logo() -> None:
    logos = {"KFSK": "/logos/KFSK.png"}

    assert securities_catalog.resolve_logo("KFSKP", logos) == "/logos/KFSK.png"


@pytest.mark.parametrize("ticker,registry,expected", [
    ("IPKY", {"IPKY": "/logos/IPKY_MARK.svg"}, "/logos/IPKY_MARK.svg"),
    ("IPTBP", {"IPTB": "/logos/IPTB_MARK.svg"}, "/logos/IPTB_MARK.svg"),
    ("NEW", {}, "/logos/imported-company.svg"),
])
def test_deployed_logo_survives_approved_metadata_overlay(
    tmp_path, monkeypatch, ticker, registry, expected,
):
    """Approved imports can retain the old favicon across a deployment."""
    monkeypatch.setattr(securities_catalog, "DB_PATH", tmp_path / "securities.db")
    registry_path = tmp_path / "logos.json"
    registry_path.write_text(json.dumps(registry))
    monkeypatch.setattr(securities_catalog, "_COMPANY_LOGOS_PATH", registry_path)
    imported_logo = "/logos/IPKY.jpg" if ticker == "IPKY" else "/logos/imported-company.svg"
    monkeypatch.setattr(company_imports, "approved_metadata_map", lambda: {
        ticker: {"logo_url": imported_logo, "company_name": "Reviewed company name"},
    })
    securities_catalog.sync_securities([
        {"ticker": ticker, "isin": "UZ0000000001", "name": "Feed name", "type": "stock"},
    ], {})

    security = securities_catalog.get_securities_map()[ticker]

    assert security["logo_url"] == expected
    assert security["company_name"] == "Reviewed company name"

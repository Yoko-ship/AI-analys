"""Company logos should follow the deployed registry, not stale DB rows."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

import securities_catalog


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

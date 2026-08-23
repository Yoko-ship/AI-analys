"""Company logos should follow the deployed registry, not stale DB rows."""
from __future__ import annotations

import securities_catalog


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

    assert security["logo_url"] == "/logos/KFSK_MARK.svg"


def test_preferred_share_uses_the_same_issuer_logo() -> None:
    logos = {"KFSK": "/logos/KFSK.png"}

    assert securities_catalog.resolve_logo("KFSKP", logos) == "/logos/KFSK.png"

from __future__ import annotations



from delisted import DELISTED_TICKERS
from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ТЗ §11.6: each change ships behind a flag so it can be turned off without a
# rollback. The interface reads them from /api/config rather than guessing.
FEATURE_FLAGS: dict[str, bool] = {
    key: os.getenv(f"FLAG_{key.upper()}", "1").strip().lower() not in {"0", "false", "no"}
    for key in ("catalog_v2", "metrics_v2", "tiers_v1", "multiples_v2",
                "market_validation_v1", "map_v2", "audit_v1")
}


_LOGOS_PATH = (PROJECT_ROOT / "company_logos.json")


def _load_logos() -> dict[str, str]:
    try:
        import json
        return json.loads(_LOGOS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


COMPANY_LOGOS: dict[str, str] = _load_logos()


UZSE_STOCK_API_BASE = os.getenv("UZSE_STOCK_API_BASE", "").strip().rstrip("/")


# Tickers suppressed from the market board. Display-only: the underlying
# financials/catalog data is left intact and each /company/<ticker> page stays
# reachable by direct link — which is the difference from DELISTED_TICKERS, whose
# rows are deleted outright and are folded in here so the board filter covers both.
# Extend at runtime via BOARD_DENYLIST_EXTRA (comma-separated) without a code change.
# KFSKP was suppressed here as a dormant registry line; it is not one — Kafolat's
# preferred share traded 39 times on 31.07 and closed +17.27%, third on the
# exchange's own top-gainers board. It was invisible because the /stocks mirror
# does not carry it, not because it is quiet.
BOARD_DENYLIST = DELISTED_TICKERS | frozenset(
    {t.strip().upper() for t in os.getenv("BOARD_DENYLIST_EXTRA", "").split(",") if t.strip()})

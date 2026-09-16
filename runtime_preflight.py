"""Startup dependency self-check for the scheduled collectors.

Both collectors run as Railway cron jobs off the shared server image, and both
have code paths that import a third-party package lazily inside the function
that needs it. When such a package is missing from ``requirements-server.txt``
the ImportError is swallowed by the per-item ``except Exception`` that keeps one
bad issuer from killing a whole run — so the job exits 0 while quietly doing
nothing. That is exactly how the news collector shipped six weeks of empty runs
(feedparser absent) and how the hand-verified PDF gap-fills regressed
(pdfplumber absent).

This module turns that class of failure from silent into loud: each entrypoint
declares the packages its pipeline actually needs, and anything missing is
logged at ERROR with the capability it disables. Import-only — it never
installs, never exits, and never blocks a run that can still do useful work.
"""
from __future__ import annotations

import importlib.util
import logging

logger = logging.getLogger(__name__)

# What each entrypoint's pipeline needs, and what silently stops working without
# it. Keys are import names (not PyPI names) because that is what fails.
COLLECTOR_REQUIREMENTS: dict[str, str] = {
    "pandas": "NSBU Excel statement parsing (all financials)",
    "openpyxl": "reading .xlsx report exports",
    "pdfplumber": "PDF gap-fill for issuers whose Excel export is broken",
    "bs4": "uzse.uz listing/board scraping (market caps, share counts)",
    "requests": "every outbound HTTP call",
}

NEWS_REQUIREMENTS: dict[str, str] = {
    "feedparser": "RSS/Atom ingestion — without it every run collects 0 items",
    "requests": "og:image extraction and the push to prod",
    "pydantic": "classifier response validation",
}


def missing_packages(requirements: dict[str, str]) -> dict[str, str]:
    """Subset of ``requirements`` that cannot be imported in this interpreter."""
    return {
        name: purpose
        for name, purpose in requirements.items()
        if importlib.util.find_spec(name) is None
    }


def preflight(requirements: dict[str, str], *, label: str) -> dict[str, str]:
    """Log any missing dependency at ERROR and return the missing mapping.

    Returns an empty dict when the environment is complete, so a caller can
    branch on it (``if preflight(...): ...``) without re-deriving the check.
    """
    missing = missing_packages(requirements)
    if not missing:
        logger.info("%s preflight: all %d required packages present", label, len(requirements))
        return {}
    for name, purpose in missing.items():
        logger.error(
            "%s preflight: %r is NOT installed — %s is disabled for this run. "
            "Add it to requirements-server.txt and redeploy.",
            label, name, purpose,
        )
    return missing

"""Financials retry operations with explicit dependencies."""
from __future__ import annotations

import collectors.financials.settings as collectors_financials_settings
import os


RETRY_ATTEMPTS = int(os.getenv("UZSE_RETRY_ATTEMPTS", "3"))


RETRY_WAIT_SECONDS = int(os.getenv("UZSE_RETRY_WAIT_SECONDS", "300"))


def _wait_and_retry(attempt: int, why: str) -> bool:
    """Sleep before another attempt; False when there are none left.

    Bounded on purpose: at the defaults the longest a step can spend waiting is
    two intervals, ten minutes, and Railway SKIPS a cron run whose predecessor is
    still going. The tightest gap in the schedule is 08:00 to 13:00.
    """
    import time

    if attempt >= RETRY_ATTEMPTS:
        return False
    collectors_financials_settings.log.warning("%s — waiting %ds, then attempt %d of %d",
                why, RETRY_WAIT_SECONDS, attempt + 1, RETRY_ATTEMPTS)
    time.sleep(RETRY_WAIT_SECONDS)
    return True

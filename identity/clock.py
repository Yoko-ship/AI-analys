"""Clock."""
from __future__ import annotations

from datetime import datetime
from datetime import timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

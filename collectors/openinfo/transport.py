"""Openinfo transport operations with explicit dependencies."""
from __future__ import annotations
from typing import Any
import requests

from openinfo_http import make_session as _make_paced_session
import collectors.openinfo.settings as collectors_openinfo_settings


def _make_session() -> requests.Session:
    return _make_paced_session()


def _fix_mojibake(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _fix_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_fix_mojibake(item) for item in value]
    if isinstance(value, str) and ("Ð" in value or "Ñ" in value):
        try:
            return value.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value
    return value


def _json_get(
    session: requests.Session,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    url = path if path.startswith("http") else f"{collectors_openinfo_settings.OPENINFO_API_BASE}{path}"
    response = session.get(url, params=params, timeout=collectors_openinfo_settings.REQUEST_TIMEOUT)
    response.raise_for_status()
    return _fix_mojibake(response.json())

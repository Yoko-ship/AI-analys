from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from typing import Any
import hashlib
import json
import logging


logger = logging.getLogger(__name__)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


# ---------------------------------------------------------------------------
# ТЗ v1.2 §7–§9, §4, §10.9 — one calc layer, one universe, cached by content.
# ---------------------------------------------------------------------------

def _etag_json(request: Request, payload: dict[str, Any], max_age: int) -> Response:
    """Serve a payload with a content ETag (ТЗ §10.9).

    The cache key is the data, not the clock: while the numbers have not changed
    the same response is valid however old it is. Before this, static bundles
    carried no cache header at all and the browser refetched an immutable file on
    every load.
    """
    body = _json_safe(payload)
    etag = '"%s"' % hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:32]
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={max_age}"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)

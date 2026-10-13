"""Response hardening: browser security headers and opaque server errors.

The app itself serves every response — API, SPA shell and static assets — so
these live here, versioned and tested, rather than in the nginx config the
deploy writes.

Why they matter here: the session token sits in web storage, so any script that
runs in the page can read it. The CSP narrows what can run to our own bundle
plus the one inline theme script (allowed by hash, not by 'unsafe-inline').
"""
from __future__ import annotations

import base64
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import server.http as http

# Interactive API docs (staging only) load their own CDN scripts; leave them be.
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc")

_INLINE_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.DOTALL)


def inline_script_hashes(index_html: Path) -> list[str]:
    """CSP hash sources for the attribute-less inline scripts in the SPA shell.

    Read from the built file at startup, so editing the theme script cannot
    silently fall out of step with a hash pasted into code.
    """
    try:
        text = index_html.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        "'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode("ascii") + "'"
        for body in _INLINE_SCRIPT_RE.findall(text)
    ]


def content_security_policy(script_hashes: list[str]) -> str:
    directives = {
        "default-src": ["'self'"],
        "script-src": ["'self'", *script_hashes],
        # React style={{…}} props render as style attributes, which CSP governs
        # through style-src; Google Fonts serves the @import-ed stylesheets.
        "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
        "font-src": ["'self'", "data:", "https://fonts.gstatic.com"],
        # News and issuer images come from many publishers.
        "img-src": ["'self'", "data:", "blob:", "https:"],
        "connect-src": ["'self'"],
        # The registry tab embeds a Google Maps pin.
        "frame-src": ["https://www.google.com", "https://maps.google.com"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
        "upgrade-insecure-requests": [],
    }
    return "; ".join(" ".join([name, *values]) for name, values in directives.items())


def security_headers(csp: str) -> list[tuple[bytes, bytes]]:
    return [
        (b"content-security-policy", csp.encode("ascii")),
        (b"strict-transport-security", b"max-age=31536000"),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    ]


class SecurityHeadersMiddleware:
    """Pure ASGI, so streaming responses and background tasks are untouched.

    A header a route already set (e.g. the stricter CSP on admin downloads) wins.
    """

    def __init__(self, app: Any, csp: str) -> None:
        self.app = app
        self.headers = security_headers(csp)
        self.headers_without_csp = [h for h in self.headers if h[0] != b"content-security-policy"]

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        exempt = scope.get("path", "").startswith(_CSP_EXEMPT_PREFIXES)
        extra = self.headers_without_csp if exempt else self.headers

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                existing = {name.lower() for name, _ in message.get("headers", [])}
                message["headers"] = [
                    *message.get("headers", []),
                    *(h for h in extra if h[0] not in existing),
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _opaque_server_error(request: Request, exc: StarletteHTTPException):
    """A 500's detail is an exception's text: SQL, hostnames, file paths.

    Log it under an id and hand the client only the id, which is enough to find
    the log line without telling a stranger anything about the internals.
    """
    if exc.status_code != 500:
        return await http_exception_handler(request, exc)
    error_id = uuid.uuid4().hex[:12]
    http.logger.error("500 %s %s [error_id=%s]: %s", request.method, request.url.path, error_id, exc.detail)
    return JSONResponse(
        {"detail": "Internal server error", "error_id": error_id},
        status_code=500,
        headers=getattr(exc, "headers", None),
    )


def install(app: FastAPI, index_html: Path) -> None:
    app.add_exception_handler(StarletteHTTPException, _opaque_server_error)
    app.add_middleware(SecurityHeadersMiddleware, csp=content_security_policy(inline_script_hashes(index_html)))

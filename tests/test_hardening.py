"""Browser security headers and opaque 500s (server/hardening.py)."""
from __future__ import annotations

import base64
import hashlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.testclient import TestClient

import api
import server.hardening as hardening


def _app(tmp_path) -> FastAPI:
    index = tmp_path / "index.html"
    index.write_text('<html><body><script>var t = 1;</script>'
                     '<script type="module" src="/assets/x.js"></script></body></html>', encoding="utf-8")
    app = FastAPI()

    @app.get("/ok")
    def ok() -> dict:
        return {"ok": True}

    @app.get("/boom")
    def boom() -> dict:
        raise HTTPException(status_code=500, detail="connection to server at 10.0.0.5 failed: password")

    @app.get("/missing")
    def missing() -> dict:
        raise HTTPException(status_code=404, detail="issuer not found")

    @app.get("/own-csp")
    def own_csp() -> Response:
        return Response("x", headers={"Content-Security-Policy": "default-src 'none'"})

    hardening.install(app, index)
    return app


def test_every_response_carries_the_security_headers(tmp_path):
    response = TestClient(_app(tmp_path)).get("/ok")
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert headers["strict-transport-security"].startswith("max-age=")
    csp = headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    script_src = next(d for d in csp.split("; ") if d.startswith("script-src "))
    assert "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src


def test_the_inline_theme_script_is_allowed_by_its_hash(tmp_path):
    expected = base64.b64encode(hashlib.sha256(b"var t = 1;").digest()).decode()
    csp = TestClient(_app(tmp_path)).get("/ok").headers["content-security-policy"]
    assert f"'sha256-{expected}'" in csp


def test_a_route_that_sets_its_own_policy_keeps_it(tmp_path):
    response = TestClient(_app(tmp_path)).get("/own-csp")
    assert response.headers.get_list("content-security-policy") == ["default-src 'none'"]


def test_a_500_hides_the_exception_text_behind_an_error_id(tmp_path, caplog):
    response = TestClient(_app(tmp_path)).get("/boom")
    body = response.json()
    assert response.status_code == 500
    assert body["detail"] == "Internal server error"
    assert "10.0.0.5" not in response.text
    assert body["error_id"] and body["error_id"] in caplog.text and "10.0.0.5" in caplog.text
    assert response.headers["x-content-type-options"] == "nosniff"


def test_client_errors_keep_their_detail(tmp_path):
    response = TestClient(_app(tmp_path)).get("/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "issuer not found"}


def test_the_real_app_is_hardened():
    response = TestClient(api.app).get("/health")
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"

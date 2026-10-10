"""Files from frontend/public sit in the dist root and have no mount of their own."""

from fastapi.testclient import TestClient

import api


def test_public_root_files_are_served_not_the_shell(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>shell</title>", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (tmp_path / "bank-logos").mkdir()
    (tmp_path / "bank-logos" / "002.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path.parent / "secret.txt").write_text("nope", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIR", tmp_path)
    client = TestClient(api.app)

    icon = client.get("/favicon.svg")
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/svg+xml")

    logo = client.get("/bank-logos/002.png")
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"

    # Client-side routes, directories and escapes still get the SPA shell.
    for path in ("/market", "/bank-logos/", "/..%2Fsecret.txt", "/%2e%2e/secret.txt"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "shell" in response.text, path
    assert client.get("/api/nope").status_code == 404

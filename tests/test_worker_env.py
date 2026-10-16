"""Scheduled workers get no web-only secret, and nothing they use is withheld."""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

import scripts.worker_env as worker_env

ROOT = Path(__file__).resolve().parent.parent


def _tracked_sources() -> dict[str, str]:
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return {f: (ROOT / f).read_text(encoding="utf-8", errors="replace")
            for f in files if not f.startswith(("tests/", "scripts/"))}


def _importers(sources: dict[str, str], module: str) -> set[str]:
    found = set()
    for path, text in sources.items():
        for node in ast.walk(ast.parse(text)):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            if module in names:
                found.add(path)
    return found


def _web_only(path: str, sources: dict[str, str]) -> bool:
    """HTTP route code, or a module that only HTTP route code imports."""
    if path.startswith("server/"):
        return True
    importers = _importers(sources, Path(path).with_suffix("").as_posix().replace("/", "."))
    return bool(importers) and all(p.startswith("server/") for p in importers)


@pytest.mark.parametrize("key", sorted(worker_env.WITHHELD))
def test_every_withheld_key_is_read_only_by_web_code(key) -> None:
    sources = _tracked_sources()
    readers = [p for p, text in sources.items() if key in text]
    assert readers, f"{key} is read nowhere; drop it from WITHHELD"
    assert all(_web_only(p, sources) for p in readers), f"{key} is read by worker-reachable code: {readers}"


def test_the_filter_drops_only_withheld_keys() -> None:
    env = ("DATABASE_URL=postgresql://x\nGOOGLE_CLIENT_SECRET=s\nexport SMTP_PASSWORD=p\n"
           "# GOOGLE_CLIENT_ID=commented\nADMIN_API_SECRET=a\nSOLIQ_API_KEY=k\n")
    out = worker_env.filtered(env)
    assert "GOOGLE_CLIENT_SECRET" not in out and "SMTP_PASSWORD" not in out
    for kept in ("DATABASE_URL=postgresql://x", "ADMIN_API_SECRET=a", "SOLIQ_API_KEY=k", "# GOOGLE_CLIENT_ID=commented"):
        assert kept in out


def test_the_worker_file_is_private(tmp_path) -> None:
    source = tmp_path / ".env"
    source.write_text("A=1\nGOOGLE_CLIENT_ID=x\n")
    target = tmp_path / "worker.env"
    worker_env.write(source, target)
    assert target.read_text() == "A=1\n"
    assert target.stat().st_mode & 0o777 == 0o600

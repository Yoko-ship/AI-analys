#!/usr/bin/env python3
"""Fail if a module that runs on the server image imports something it does not declare.

This exists because of a specific, repeated production failure: code imports a
third-party package lazily inside the function that needs it, the package is
absent from ``requirements-server.txt``, and the ImportError is swallowed by the
per-item ``except Exception`` that stops one bad issuer from killing a whole run.
The cron job then exits 0 having done nothing. That is how the news collector
shipped weeks of empty runs (feedparser missing) and how the hand-verified PDF
gap-fills silently regressed (pdfplumber missing).

Reviewing requirements by eye does not catch it — a lazy import inside a function
body 800 lines into a 3000-line module is invisible. Static analysis does.

Scope: the entrypoints that actually run on the built image, plus everything they
import transitively within this repo. Modules reachable only from dev tooling are
not checked.

A ``try: import x / except ImportError`` guard normally means "optional, there is
a fallback" and is skipped — EXCEPT when ``runtime_preflight`` names the package as
something a pipeline requires. That is the whole feedparser lesson: the import was
guarded and even logged an error, but the fallback was ``return []``, so the run
still reported success with nothing collected. A guard is not a substitute for
declaring a dependency the pipeline cannot work without.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# What the deployed image starts (see railway.json / railway.*.json).
ENTRYPOINTS = ("api.py", "bot.py", "collector_financials.py", "news_collector.py")

# Import name -> distribution name, where they differ.
IMPORT_TO_DIST = {
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "telegram": "python-telegram-bot",
    "PIL": "pillow",
    "psycopg": "psycopg",
    "yaml": "pyyaml",
    "sklearn": "scikit-learn",
    "dateutil": "python-dateutil",
    "docx": "python-docx",
    "fitz": "pymupdf",
}

# Installed as a transitive dependency of something already declared, and relied
# on as such. Listed explicitly so the exemption is a decision, not an oversight.
TRANSITIVE_OK = {
    "pydantic",    # fastapi
    "urllib3",     # requests
    "numpy",       # pandas
    "starlette",   # fastapi
    "anyio",       # fastapi / httpx
}


def _repo_modules() -> set[str]:
    return ({p.stem for p in REPO.glob("*.py")}
            | {p.parent.name for p in REPO.glob("*/__init__.py")})


def _imports_of(path: Path) -> tuple[set[str], set[str], set[str]]:
    """(local modules, hard third-party imports, optional third-party imports)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    local = _repo_modules()
    # Names imported inside a try/except ImportError have a real fallback path.
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        handles_import_error = any(
            handler.type is None
            or (isinstance(handler.type, ast.Name)
                and handler.type.id in {"ImportError", "ModuleNotFoundError", "Exception"})
            or (isinstance(handler.type, ast.Tuple)
                and any(isinstance(e, ast.Name)
                        and e.id in {"ImportError", "ModuleNotFoundError", "Exception"}
                        for e in handler.type.elts))
            for handler in node.handlers
        )
        if handles_import_error:
            for child in ast.walk(node):
                for name in _names_of(child):
                    guarded.add(name)

    local_hits: set[str] = set()
    third: set[str] = set()
    for node in ast.walk(tree):
        for name in _names_of(node):
            if name in local:
                local_hits.add(name)
            elif name not in sys.stdlib_module_names:
                third.add(name)
    return local_hits, third - guarded, third & guarded


def _names_of(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        return [node.module.split(".")[0]]
    return []


def _declared() -> set[str]:
    text = (REPO / "requirements-server.txt").read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        # "psycopg[binary]>=3.2,<4" -> "psycopg"
        names.add(re.split(r"[\[<>=!;~ ]", line, maxsplit=1)[0].strip().lower())
    return names


def _preflight_required() -> set[str]:
    """Packages the collectors declare as required, regardless of import guards."""
    sys.path.insert(0, str(REPO))
    try:
        from runtime_preflight import COLLECTOR_REQUIREMENTS, NEWS_REQUIREMENTS
    except Exception as exc:  # noqa: BLE001 — the check must still run
        print(f"warning: could not read runtime_preflight ({exc})")
        return set()
    return set(COLLECTOR_REQUIREMENTS) | set(NEWS_REQUIREMENTS)


def main() -> int:
    declared = _declared()
    pipeline_required = _preflight_required()
    seen: set[str] = set()
    queue = [REPO / name for name in ENTRYPOINTS]
    required: dict[str, set[str]] = {}
    optional: dict[str, set[str]] = {}

    while queue:
        path = queue.pop()
        identity = str(path.relative_to(REPO))
        if identity in seen or not path.exists():
            continue
        seen.add(identity)
        local, third, guarded = _imports_of(path)
        for name in third:
            required.setdefault(name, set()).add(path.name)
        for name in guarded:
            # A guard does not make a pipeline-critical package optional: the
            # fallback is "collect nothing and exit 0".
            if name in pipeline_required:
                required.setdefault(name, set()).add(path.name)
            else:
                optional.setdefault(name, set()).add(path.name)
        for module in local:
            package = REPO / module
            if (package / "__init__.py").is_file():
                # Include relative imports and siblings in each runtime package.
                queue.extend(package.rglob("*.py"))
            else:
                queue.append(REPO / f"{module}.py")

    missing: dict[str, set[str]] = {}
    for name, users in sorted(required.items()):
        if name in TRANSITIVE_OK:
            continue
        dist = IMPORT_TO_DIST.get(name, name).lower()
        if dist not in declared and name.lower() not in declared:
            missing[name] = users

    print(f"reachable modules from {len(ENTRYPOINTS)} entrypoints: {len(seen)}")
    print(f"third-party imports required: {len(required)}  optional (guarded): {len(optional)}")
    if optional:
        print("optional, not required to be declared: "
              + ", ".join(sorted(optional)))

    if missing:
        print("\nFAIL — imported on the server path but not in requirements-server.txt:")
        for name, users in missing.items():
            dist = IMPORT_TO_DIST.get(name, name)
            print(f"  {name!r} (install as {dist!r}) — imported by {', '.join(sorted(users))}")
        print("\nA missing package here does not crash the job: the ImportError is "
              "swallowed per item and the run exits 0 having collected nothing.")
        return 1

    print("\nOK — every server-path import is declared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

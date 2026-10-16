#!/usr/bin/env python3
"""The env file the scheduled workers get: the app's .env minus web-only secrets.

Every collector container used to receive the whole /root/uzstock/app/.env,
so a parser compromised by a hostile filing would also hold the Google sign-in
client secret and the mail account's password, which no worker ever uses.

A key is withheld only when the code reading it is web-only (checked by
tests/test_worker_env.py), because a worker missing something it needs fails
silently at 3 a.m. The import graph is too entangled to derive this per worker
(every entry point reaches ~300 modules), so the list is explicit and tested.

Run by each worker unit just before it starts (ExecStartPre), so a hand edit of
.env reaches the workers on their next run, not on the next deploy:

    python3 scripts/worker_env.py /root/uzstock/app/.env /root/uzstock/worker.env
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

WITHHELD = frozenset({
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
})


def _key(line: str) -> str:
    key = line.partition("=")[0].strip()
    return key[len("export "):].strip() if key.startswith("export ") else key


def filtered(text: str) -> str:
    kept = [line for line in text.splitlines() if _key(line) not in WITHHELD]
    return "\n".join(kept) + "\n"


def write(source: Path, target: Path) -> None:
    content = filtered(source.read_text(encoding="utf-8"))
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp, target)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: worker_env.py SOURCE_ENV TARGET_ENV")
    write(Path(sys.argv[1]), Path(sys.argv[2]))

#!/usr/bin/env python3
"""Show production output in CI without publishing it.

The repository is public, so every Actions log is too. The deploy printed
container logs and service journals there when something failed, and those
carry visitors' emails and addresses, tokens in request lines, and whatever an
exception happened to hold. Pipe such output through this instead:

    docker logs --tail 160 uzstock-web 2>&1 | python3 scripts/ci_log.py web-start

The full text is kept on the server (root-only, newest KEEP per name) and only
a redacted tail reaches the CI log, with the path to the full copy. What stays
readable is what a failure is diagnosed by: messages, tracebacks, private
addresses, git hashes and timestamps. Stdlib only: it runs on the host.
"""
from __future__ import annotations

import ipaddress
import os
import re
import sys
import time
from pathlib import Path

LOG_DIR = Path(os.environ.get("CI_LOG_DIR", "/root/uzstock/ci-logs"))
KEEP = 30
DEFAULT_TAIL = 120

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
_BEARER = re.compile(r"(?i)\b(bearer)(\s+)(\S+)")
# Only labelled values: systemd's "code=exited" and "exit code 1" stay readable.
_LABELLED = re.compile(
    r"(?i)(?<![a-z])(token|secret|password|passwd|api[_-]?key|authorization|cookie|otp)"
    r"(\"?\s*[:=]\s*\"?)([^\s\"',;&]+)")
# Session tokens and keys: long runs mixing cases and digits. Lowercase hex
# (git and image hashes) and plain words are left alone.
_OPAQUE = re.compile(r"[A-Za-z0-9_\-]{24,}")


def _public_ip(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    return address.is_global


def _opaque(match: re.Match) -> str:
    token = match.group(0)
    mixed = any(c.isupper() for c in token) and any(c.islower() for c in token) and any(c.isdigit() for c in token)
    return "[token]" if mixed else token


def redact(line: str) -> str:
    line = _EMAIL.sub("[email]", line)
    line = _BEARER.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
    line = _LABELLED.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
    line = _IPV4.sub(lambda m: "[ip]" if _public_ip(m.group(0)) else m.group(0), line)
    line = _IPV6.sub(lambda m: "[ip]" if _public_ip(m.group(0).strip("[]")) else m.group(0), line)
    return _OPAQUE.sub(_opaque, line)


def keep(name: str, text: str) -> Path:
    LOG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = LOG_DIR / f"{name}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.log"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    for old in sorted(LOG_DIR.glob(f"{name}-*.log"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


def main(argv: list[str]) -> int:
    if not argv or not re.fullmatch(r"[a-z0-9-]+", argv[0]):
        sys.exit("usage: ... | ci_log.py NAME [TAIL_LINES]")
    tail = int(argv[1]) if len(argv) > 1 else DEFAULT_TAIL
    text = sys.stdin.read()
    path = keep(argv[0], text)
    lines = text.splitlines()[-tail:]
    for line in lines:
        print(redact(line))
    print(f"[{len(lines)} redacted lines shown; full log on the server: {path}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

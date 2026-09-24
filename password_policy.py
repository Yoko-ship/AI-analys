"""password_policy.py — which new passwords the site accepts.

Follows NIST SP 800-63B: no «must contain a digit and a symbol» rules and no
forced rotation, which only produce predictable passwords like `Password1!`.
Instead a password is refused when it is too short or long, on the list of
the ~100k most common passwords (UK NCSC list via SecLists, MIT licence, plus
local words such as city names), a keyboard/number sequence or a repeat, the
site's own name, or built from the user's email or name.

`check_password` returns a reason code (or None); `validate_new_password`
raises `WeakPassword`, a ValueError, so existing «400 on ValueError» handling
applies unchanged.  The English messages are mapped to RU/UZ on the client.
"""
from __future__ import annotations

import gzip
import re
from functools import lru_cache
from pathlib import Path

MIN_LENGTH = 8
MAX_LENGTH = 128

MESSAGES = {
    "too_short": f"Password must be at least {MIN_LENGTH} characters long",
    "too_long": f"Password must be at most {MAX_LENGTH} characters long",
    "context": "The password must not contain the site name",
    "common": "This password is too common — choose a less predictable one",
    "sequence": "Avoid keyboard or number sequences and repeated characters",
    "personal": "The password must not contain your name or email",
}

_LIST_PATH = Path(__file__).parent / "config" / "common_passwords.txt.gz"
_SITE_WORDS = ("uzstock", "uz stock", "uz-stock")
_KEYBOARD_ROWS = (
    "1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm",
    "йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю",
)
_LEET = str.maketrans({"@": "a", "4": "a", "3": "e", "0": "o", "$": "s", "5": "s", "1": "i", "!": "i", "7": "t"})
_EDGE_NOISE = re.compile(r"^[\d\W_]+|[\d\W_]+$")


class WeakPassword(ValueError):
    def __init__(self, code: str):
        super().__init__(MESSAGES[code])
        self.code = code


@lru_cache(maxsize=1)
def _common() -> frozenset[str]:
    with gzip.open(_LIST_PATH, "rt", encoding="utf-8") as handle:
        return frozenset(line.strip() for line in handle if line.strip())


def common_password_count() -> int:
    return len(_common())


def _is_common(normalized: str) -> bool:
    common = _common()
    base = _EDGE_NOISE.sub("", normalized)  # «dragon12345», «2024tashkent!» → the word
    candidates = {normalized, base, normalized.translate(_LEET), base.translate(_LEET)}
    return any(len(item) >= 4 and item in common for item in candidates)


def _is_sequence(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    if len(set(compact)) < 4:
        return True  # «aaaaaaaa», «abababab», «q9q9q9q9q9»
    steps = {ord(b) - ord(a) for a, b in zip(compact, compact[1:])}
    if steps in ({1}, {-1}):
        return True  # «mnopqrstu», «87654321»
    return any(compact in row or compact in row[::-1] for row in _KEYBOARD_ROWS)


def _personal_fragments(email: str, full_name: str) -> set[str]:
    local = (email or "").split("@", 1)[0]
    words = re.split(r"[^\w]+|_|\d+", f"{local} {full_name or ''}".lower())
    fragments = {word for word in words if len(word) >= 4}
    compact_local = re.sub(r"[^\w]", "", local.lower())
    if len(compact_local) >= 4:
        fragments.add(compact_local)
    return fragments


def check_password(password: str, *, email: str = "", full_name: str = "") -> str | None:
    """Return the reason a new password is refused, or None when it is fine."""
    password = password or ""
    if len(password) < MIN_LENGTH:
        return "too_short"
    if len(password) > MAX_LENGTH:
        return "too_long"
    normalized = password.strip().lower()
    if any(word in normalized for word in _SITE_WORDS):
        return "context"
    if _is_common(normalized):
        return "common"
    if _is_sequence(normalized):
        return "sequence"
    if any(fragment in normalized for fragment in _personal_fragments(email, full_name)):
        return "personal"
    return None


def validate_new_password(password: str, *, email: str = "", full_name: str = "") -> None:
    reason = check_password(password, email=email, full_name=full_name)
    if reason:
        raise WeakPassword(reason)

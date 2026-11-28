"""Shared URL validation with no dependency on content or source workflows."""
from urllib.parse import urlparse


def public_url(value, *, uzstock=False):
    parsed = urlparse(value)
    return (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
            and not parsed.password and (not uzstock or parsed.hostname in {"uzstock.uz", "www.uzstock.uz"}))

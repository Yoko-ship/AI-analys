"""Fixed Graph API requests; only explicit rejection permits a public retry."""
import hashlib
import hmac
import json
from math import ceil
from email.utils import parsedate_to_datetime

import requests

from . import meta_identity
from .delivery import PermanentRejection, TemporaryRejection

RATE_CODES = {4, 17, 32, 613, 80001}


def retry_after(headers, now):
    delays = [60]
    header = headers.get("Retry-After", "")
    try:
        if header.isascii() and header.isdecimal():
            delays.append(int(header))
        else:
            until = parsedate_to_datetime(header)
            if until.tzinfo is not None:
                delays.append(ceil((until - now).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        pass
    try:
        usage = json.loads(headers.get("x-business-use-case-usage", "{}"))
        for rows in usage.values():
            for row in rows:
                wait = row.get("estimated_time_to_regain_access")
                if type(wait) is int and wait > 0:
                    delays.append(wait * 60)
    except (ValueError, TypeError, AttributeError):
        pass
    return max(delays)


def request(method, path, token, secret, now, *, data=None, files=None, public_write=False):
    """Paths are constructed from validated IDs; no provider URLs are followed."""
    params = {**(data or {}), "appsecret_proof": hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()}
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.request(method, "https://graph.facebook.com/" + meta_identity.API_VERSION + "/" + path,
                headers={"Authorization": "Bearer " + token}, timeout=(5, 30), allow_redirects=False,
                **({"params": params} if method == "GET" else {"data": params, "files": files}))
        if len(response.content) > 1_000_000:
            raise ValueError("Oversized response")
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid response")
    except Exception:
        if public_write:
            raise RuntimeError("Meta publication outcome is unknown") from None
        raise TemporaryRejection("Meta preparation or verification is unavailable", retry_after=60) from None
    error = value.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    # A server failure can occur after acceptance, regardless of its error code.
    if 400 <= response.status_code < 500 and (response.status_code == 429 or type(code) is int and code in RATE_CODES):
        raise TemporaryRejection("Meta explicitly rejected this request", retry_after=retry_after(response.headers, now))
    if (400 <= response.status_code < 500 and type(code) is int
            and (code in {3, 10, 100, 102, 104, 190, 368, 506} or 200 <= code <= 299)):
        raise PermanentRejection("Meta rejected this request")
    if response.status_code != 200 or error is not None:
        if public_write:
            raise RuntimeError("Meta publication outcome is unknown")
        raise TemporaryRejection("Meta preparation or verification is unavailable", retry_after=60)
    return value

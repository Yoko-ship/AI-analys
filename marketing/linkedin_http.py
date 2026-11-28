"""Fixed LinkedIn API protocol and safe failures before a post is created."""
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from math import ceil
import re

import requests

from .delivery import PermanentRejection, TemporaryRejection

# Supported through 2027-06-15; change deliberately with transport contracts.
API_VERSION = "202606"


def retry_delay(header, now):
    if isinstance(header, str) and re.fullmatch(r"[0-9]{1,20}", header) and int(header) > 0:
        return int(header)
    try:
        until = parsedate_to_datetime(header)
        if until.tzinfo is not None:
            return max(60, ceil((until - now).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        pass
    tomorrow = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return max(60, ceil((tomorrow - now).total_seconds()))


def headers(token):
    return {"Authorization": "Bearer " + token, "Linkedin-Version": API_VERSION, "X-Restli-Protocol-Version": "2.0.0"}


def preparation_request(method, url, now, *, expected, **kwargs):
    """Only registration, upload, finalization or reads. Never a post write."""
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.request(method, url, timeout=(5, 30), allow_redirects=False, **kwargs)
        if len(response.content) > 1_000_000:
            raise ValueError("Oversized response")
    except Exception:
        raise TemporaryRejection("LinkedIn media preparation is unavailable", retry_after=60) from None
    if response.status_code == 429:
        raise TemporaryRejection("LinkedIn rejected media preparation", retry_after=retry_delay(response.headers.get("Retry-After"), now))
    if response.status_code in expected:
        return response
    if response.status_code >= 500 or response.status_code == 408:
        raise TemporaryRejection("LinkedIn media preparation is unavailable", retry_after=60)
    raise PermanentRejection("LinkedIn rejected media preparation")


def preparation_json(method, path, token, now, data=None):
    response = preparation_request(method, "https://api.linkedin.com/rest/" + path, now,
                                   expected={200}, headers=headers(token), **({"json": data} if data is not None else {}))
    try:
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid response")
        return value
    except Exception:
        raise TemporaryRejection("LinkedIn media response is unavailable", retry_after=60) from None

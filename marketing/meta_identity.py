"""Fixed-host Meta code exchange, inspected grants and bounded Page discovery."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re

import requests

from .errors import MarketingError

API_VERSION = "v25.0"  # Graph API supported until 2028-07-29; upgrade deliberately.
SCOPES = {"facebook": {"pages_show_list", "pages_read_engagement", "pages_manage_posts"},
          "instagram": {"pages_show_list", "pages_read_engagement", "instagram_basic", "instagram_content_publish"}}


def invalid():
    return MarketingError("META_IDENTITY_INVALID", "Meta could not verify this account and its publishing permissions.")


def identifier(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,39}", value):
        raise invalid()
    return value


def _token(value):
    if not isinstance(value, str) or not re.fullmatch(r"[!-~]{1,8192}", value):
        raise invalid()
    return value


def request(path, *, token=None, secret=None, params=None):
    values = dict(params or {})
    if token and secret:
        values["appsecret_proof"] = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get("https://graph.facebook.com/" + API_VERSION + "/" + path,
                params=values, headers={"Authorization": "Bearer " + token} if token else {}, timeout=(5, 30), allow_redirects=False)
        if response.status_code != 200 or len(response.content) > 1_000_000:
            raise ValueError("Unusable response")
        result = response.json()
        if not isinstance(result, dict) or "error" in result:
            raise ValueError("Invalid response")
        return result
    except Exception:
        raise MarketingError("META_UNAVAILABLE", "Meta could not verify this login. Start the connection again.") from None


def inspect(config, token, platform, now, *, page_id=None):
    value = request("debug_token", token=config["app_id"] + "|" + config["app_secret"], params={"input_token": token}).get("data")
    if (not isinstance(value, dict) or value.get("is_valid") is not True
            or str(value.get("app_id")) != config["app_id"] or value.get("type") != ("PAGE" if page_id else "USER")
            or not isinstance(value.get("scopes"), list) or not all(isinstance(scope, str) for scope in value["scopes"])
            or not SCOPES[platform].issubset(set(value["scopes"]))):
        raise invalid()
    user_id = identifier(value.get("user_id"))
    if page_id and identifier(value.get("profile_id")) != page_id:
        raise invalid()
    expiries = []
    for field in ("expires_at", "data_access_expires_at"):
        stamp = value.get(field)
        if type(stamp) is not int or stamp < 0 or (field == "expires_at" and not page_id and stamp == 0):
            raise invalid()
        if stamp:
            try:
                expires = datetime.fromtimestamp(stamp, timezone.utc)
            except (ValueError, OverflowError, OSError):
                raise invalid() from None
            if expires <= now + timedelta(seconds=60):
                raise invalid()
            expiries.append(expires)
    return {"user_id": user_id, "expires_at": min(expiries).isoformat() if expiries else None}


def exchange(config, code, platform, now):
    short = request("oauth/access_token", params={"client_id": config["app_id"], "client_secret": config["app_secret"],
        "redirect_uri": config["redirect_uri"], "code": code})
    token = _token(short.get("access_token"))
    value = request("oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": config["app_id"],
        "client_secret": config["app_secret"], "fb_exchange_token": token})
    token, lifetime = _token(value.get("access_token")), value.get("expires_in")
    if not isinstance(value.get("token_type"), str) or value["token_type"].lower() != "bearer" or type(lifetime) is not int or not 60 < lifetime <= 366 * 86400:
        raise invalid()
    proof = inspect(config, token, platform, now)
    expiry = min(datetime.fromisoformat(proof["expires_at"]), now + timedelta(seconds=lifetime))
    return {"access_token": token, "user_id": proof["user_id"], "expires_at": expiry.isoformat()}


def discover(config, grant, platform, now):
    proof = inspect(config, grant["access_token"], platform, now)
    if proof["user_id"] != grant["user_id"]:
        raise invalid()
    fields = "id,name,tasks,access_token"
    if platform == "instagram":
        fields += ",instagram_business_account{id,username,name}"
    choices, after, seen, targets = [], None, set(), set()
    for _ in range(10):
        value = request("me/accounts", token=grant["access_token"], secret=config["app_secret"],
                        params={"fields": fields, "limit": 100, **({"after": after} if after else {})})
        pages = value.get("data")
        if not isinstance(pages, list) or len(pages) > 100:
            raise invalid()
        for page in pages:
            if not isinstance(page, dict) or not isinstance(page.get("tasks"), list):
                raise invalid()
            if "CREATE_CONTENT" not in page["tasks"]:
                continue
            profile = page if platform == "facebook" else page.get("instagram_business_account")
            if not profile:
                continue
            if not isinstance(profile, dict):
                raise invalid()
            target_id, page_id = identifier(profile.get("id")), identifier(page.get("id"))
            if target_id in targets:
                raise invalid()
            targets.add(target_id)
            title = profile.get("name") or profile.get("username") or page.get("name")
            choices.append({"target_id": target_id, "page_id": page_id, "title": str(title or target_id)[:200],
                            "page_title": str(page.get("name") or page_id)[:200], "access_token": _token(page.get("access_token"))})
        paging = value.get("paging") or {}
        if not isinstance(paging, dict):
            raise invalid()
        if not paging.get("next"):
            return {"choices": choices, "expires_at": min(grant["expires_at"], proof["expires_at"])}
        # Never follow a provider-supplied URL containing tokens or another host.
        cursors = paging.get("cursors")
        if not isinstance(cursors, dict):
            raise invalid()
        after = cursors.get("after")
        if not isinstance(after, str) or not re.fullmatch(r"[!-~]{1,4096}", after) or after in seen:
            raise invalid()
        seen.add(after)
    raise MarketingError("META_DISCOVERY_LIMIT", "Meta returned too many accounts. Limit the assets selected during login and try again.")


def verify_choice(config, grant, platform, choice, now):
    discovered = discover(config, grant, platform, now)
    current = next((row for row in discovered["choices"] if row["target_id"] == choice["target_id"] and row["page_id"] == choice["page_id"]), None)
    if not current:
        raise invalid()
    proof = inspect(config, current["access_token"], platform, now, page_id=current["page_id"])
    if proof["user_id"] != grant["user_id"]:
        raise invalid()
    expiry = min(discovered["expires_at"], proof["expires_at"]) if proof["expires_at"] else discovered["expires_at"]
    return current, expiry

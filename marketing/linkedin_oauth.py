"""Owner consent binds a personal profile; account release rules stay unchanged."""
from datetime import datetime, timedelta, timezone
import hmac
import os
import re
import secrets
from time import monotonic
from urllib.parse import urlencode, urlsplit

from . import credentials, linkedin_identity, store as s
from .errors import MarketingError, require_owner
from .permissions import timestamp

SETTINGS = ["MARKETING_LINKEDIN_CLIENT_ID", "MARKETING_LINKEDIN_CLIENT_SECRET", "MARKETING_LINKEDIN_REDIRECT_URI", credentials.KEY_ENV]
COOKIE = "marketing_linkedin_binding"
TTL = 600


def _config():
    values = [os.getenv(key, "").strip() for key in SETTINGS[:3]]
    try:
        url = urlsplit(values[2])
        valid = (url.scheme == "https" and url.hostname and not url.username and not url.password
                 and url.path == "/admin/ai-marketing" and not url.query and not url.fragment)
    except ValueError:
        valid = False
    if not all(values) or not valid or not credentials.configured():
        raise MarketingError("LINKEDIN_SETUP_REQUIRED", "Configure the private LinkedIn app, HTTPS callback and marketing credential encryption key.")
    return dict(zip(("client_id", "client_secret", "redirect_uri"), values))


def _fingerprint(config):
    return s.digest({**config, "key": os.getenv(credentials.KEY_ENV, "")})


def _personal(account):
    if (account["platform"] != "linkedin" or not account.get("personal_profile")
            or account["external_id"] and not re.fullmatch(r"urn:li:person:[A-Za-z0-9_-]{1,128}", account["external_id"])):
        raise MarketingError("LINKEDIN_PERSON_REQUIRED", "Authorize this personal LinkedIn profile separately before connecting it.")


def current_grant(account, now, c=None):
    config = _config()
    _personal(account)
    if c is None:
        with s.connection() as db:
            grant = credentials.read(db, account.get("id", ""), "linkedin")
    else:
        grant = credentials.read(c, account.get("id", ""), "linkedin")
    if (not grant or grant["config_fingerprint"] != _fingerprint(config)
            or grant["person"] != account["external_id"] or timestamp(grant["expires_at"]) <= now + timedelta(seconds=60)):
        raise MarketingError("LINKEDIN_LOGIN_REQUIRED", "Connect the current personal LinkedIn profile again.")
    return grant


def setup(account, now=None, c=None):
    now = now or datetime.now(timezone.utc)
    try:
        config, configured = _config(), True
    except MarketingError:
        config, configured = {}, False
    result = {"implemented": True, "configured": configured, "ready": False, "oauth": True,
              "required_settings": SETTINGS, "callback_url": config.get("redirect_uri"), "formats": ["post", "image", "carousel", "video"],
              "reason": "Connect the current personal LinkedIn profile again." if configured else
              "Configure the private LinkedIn app, HTTPS callback and marketing credential encryption key."}
    if account.get("id") and configured:
        try:
            grant = current_grant(account, now, c)
            ready = account.get("connection_status") == "connected" and account.get("connection_fingerprint") == grant["id"]
            result.update(ready=ready, expires_at=grant["expires_at"], has_credential=True)
            if ready:
                result["reason"] = "Connection verified"
        except MarketingError:
            pass
    return result


def begin(actor, account_id, expected_version, now):
    require_owner(actor)
    config = _config()
    state, binding = "li_" + secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with s.connection(write=True) as c:
        account = s.get(c, "account", account_id)
        _personal(account)
        if account["version"] != expected_version:
            raise MarketingError("ACCOUNT_CHANGED", "The account changed. Reload before connecting.")
        credentials.remember(c, state, {"owner_id": actor["id"], "account_id": account_id,
            "account_version": expected_version, "binding_hash": s.digest(binding),
            "config_fingerprint": _fingerprint(config), "started_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=TTL)).isoformat()})
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urlencode({"response_type": "code",
        "client_id": config["client_id"], "redirect_uri": config["redirect_uri"],
        "scope": " ".join(sorted(linkedin_identity.SCOPES)), "state": state})
    return {"authorization_url": url, "binding": binding}


def finish(actor, *, state, code, binding, now, error=None):
    require_owner(actor)
    started = monotonic()
    config = _config()
    with s.connection(write=True) as c:
        intent = credentials.intent(c, state)
        if (not intent or intent["owner_id"] != actor["id"] or not binding
                or not hmac.compare_digest(intent["binding_hash"], s.digest(binding))
                or timestamp(intent["expires_at"]) <= now):
            raise MarketingError("LINKEDIN_STATE_INVALID", "This LinkedIn login expired, was used, or belongs to another browser. Start again.")
        account = s.get(c, "account", intent["account_id"])
        if account["version"] != intent["account_version"] or intent["config_fingerprint"] != _fingerprint(config):
            raise MarketingError("LINKEDIN_LOGIN_CHANGED", "Account or app settings changed during login. Start again.")
        _personal(account)
        credentials.consume(c, state)  # Commit single-use claim before network I/O.
    if error or not code:
        raise MarketingError("LINKEDIN_CANCELLED", "LinkedIn login was cancelled. No connection was changed.")
    token, identity = linkedin_identity.exchange(config, code)
    if account["external_id"] and account["external_id"] != identity["target_id"]:
        raise MarketingError("LINKEDIN_PROFILE_MISMATCH", "The signed-in LinkedIn profile differs from the authorized personal profile.")
    grant = {"id": s.uid("grant"), "access_token": token["access_token"], "scopes": token["scopes"],
             "person": identity["target_id"], "config_fingerprint": _fingerprint(config),
             "expires_at": (now + timedelta(seconds=token["expires_in"])).isoformat()}
    with s.connection(write=True) as c:
        current = s.get(c, "account", account["id"])
        completed = now + timedelta(seconds=monotonic() - started)
        if (current["version"] != account["version"] or grant["config_fingerprint"] != _fingerprint(_config())
                or timestamp(intent["expires_at"]) <= completed or timestamp(grant["expires_at"]) <= completed + timedelta(seconds=60)):
            raise MarketingError("LINKEDIN_LOGIN_CHANGED", "Account or app settings changed during login. Start again.")
        credentials.save(c, account["id"], "linkedin", grant)
        return s.put(c, "account", {**current, "external_id": identity["target_id"],
            "connection_status": "connected", "connection_checked_at": completed.isoformat(),
            "connection_fingerprint": grant["id"], "connection_identity": identity, "connection_reason": "Connection verified"},
            actor=actor, action="linkedin_profile_connected", expected_version=current["version"])


def disconnect(actor, account_id, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        current = s.get(c, "account", account_id)
        if current["platform"] != "linkedin":
            raise MarketingError("LINKEDIN_PERSON_REQUIRED", "Choose a personal LinkedIn account.")
        result = s.put(c, "account", {**current, "connection_status": "not_connected", "connection_fingerprint": None,
            "connection_identity": None, "connection_checked_at": None, "connection_reason": "LinkedIn disconnected locally."},
            actor=actor, action="linkedin_profile_disconnected", expected_version=expected_version)
        credentials.delete(c, account_id, "linkedin")
        return result


def probe(actor, account_id, expected_version, now):
    require_owner(actor)
    with s.connection() as c:
        account = s.get(c, "account", account_id)
        grant = current_grant(account, now, c)
    if account["version"] != expected_version:
        raise MarketingError("ACCOUNT_CHANGED", "The account changed. Reload before connecting.")
    from .linkedin_transport import LinkedIn
    try:
        identity = LinkedIn(grant).probe(account)
        status, reason = "connected", "Connection verified"
    except MarketingError:
        identity, status, reason = None, "error", "LinkedIn could not verify the authorized personal profile before sending"
    with s.connection(write=True) as c:
        current = s.get(c, "account", account_id)
        if current_grant(current, now, c)["id"] != grant["id"]:
            raise MarketingError("LINKEDIN_LOGIN_CHANGED", "Account or app settings changed during login. Start again.")
        return s.put(c, "account", {**current, "connection_status": status, "connection_identity": identity,
            "connection_fingerprint": grant["id"] if identity else None, "connection_reason": reason,
            "connection_checked_at": now.isoformat()}, actor=actor, action="linkedin_connection_checked", expected_version=expected_version)

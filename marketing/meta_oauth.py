"""Owner login and explicit selection of a verified Page or linked Instagram."""
from datetime import datetime, timedelta, timezone
import hmac
import os
import secrets
from time import monotonic
from urllib.parse import urlencode, urlsplit

from . import credentials, meta_identity as identity, store as s
from .errors import MarketingError, require_owner
from .permissions import timestamp

COOKIE, TTL = "marketing_meta_binding", 600
SETTINGS = ["MARKETING_META_APP_ID", "MARKETING_META_APP_SECRET", "MARKETING_META_REDIRECT_URI"]


def _settings(platform):
    return [*SETTINGS, "MARKETING_META_" + platform.upper() + "_CONFIG_ID", credentials.KEY_ENV]


def _config(platform):
    if platform not in identity.SCOPES:
        raise MarketingError("META_ACCOUNT_REQUIRED", "Choose a Facebook Page or a linked professional Instagram account.")
    values = [os.getenv(key, "").strip() for key in _settings(platform)[:4]]
    try:
        url = urlsplit(values[2])
        valid = (url.scheme == "https" and url.hostname and not url.username and not url.password
                 and url.path == "/admin/ai-marketing" and not url.query and not url.fragment)
        identity.identifier(values[0])
        identity.identifier(values[3])
    except (ValueError, MarketingError):
        valid = False
    if not all(values) or not valid or not credentials.configured():
        raise MarketingError("META_SETUP_REQUIRED", "Configure the private Meta app, login configuration, HTTPS callback and credential encryption key.")
    return dict(zip(("app_id", "app_secret", "redirect_uri", "config_id"), values))


def _fingerprint(config):
    return s.digest({**config, "key": os.getenv(credentials.KEY_ENV, "")})


def _changed():
    return MarketingError("META_LOGIN_CHANGED", "Meta login, account or app settings changed. Start the connection again.")


def _pending(c, account, config, now):
    pending = credentials.read(c, account["id"], "meta_pending")
    if (not pending or pending["account_version"] != account["version"]
            or pending["config_fingerprint"] != _fingerprint(config) or timestamp(pending["expires_at"]) <= now):
        raise _changed()
    return pending


def _public(pending):
    return {"selection_id": pending["id"], "expires_at": pending["expires_at"],
            "choices": [{key: row[key] for key in ("target_id", "page_id", "title", "page_title")} for row in pending["choices"]]}


def current_grant(account, now, c=None):
    config = _config(account["platform"])
    if c is None:
        with s.connection() as db:
            grant = credentials.read(db, account.get("id", ""), "meta")
    else:
        grant = credentials.read(c, account.get("id", ""), "meta")
    if (not grant or grant["config_fingerprint"] != _fingerprint(config) or grant["platform"] != account["platform"]
            or grant["choice"]["target_id"] != account["external_id"] or timestamp(grant["expires_at"]) <= now + timedelta(seconds=60)):
        raise MarketingError("META_LOGIN_REQUIRED", "Connect the current Meta account again.")
    return grant


def setup(account, now=None, c=None):
    now = now or datetime.now(timezone.utc)
    try:
        config, configured = _config(account["platform"]), True
    except MarketingError:
        config, configured = {}, False
    result = {"implemented": True, "configured": configured, "ready": False, "oauth": True,
              "formats": ["post", "image", "carousel", "video"] if account["platform"] == "facebook" else ["image", "carousel", "video", "story"],
              "publishing_implemented": True, "required_settings": _settings(account["platform"]),
              "callback_url": config.get("redirect_uri"), "reason": "Connect the current Meta account again." if configured else
              "Configure the private Meta app, login configuration, HTTPS callback and credential encryption key."}
    if not account.get("id") or not configured:
        return result
    if c is None:
        with s.connection() as db:
            return setup(account, now, db)
    try:
        grant = current_grant(account, now, c)
        ready = account.get("connection_status") == "connected" and account.get("connection_fingerprint") == grant["id"]
        result.update(ready=ready, has_credential=True, expires_at=grant["expires_at"])
        if ready:
            result["reason"] = "Connection verified"
    except MarketingError:
        pass
    try:
        pending = _pending(c, account, config, now)
        if pending["phase"] == "selection":
            result["selection"] = _public(pending)
    except MarketingError:
        pass
    return result


def begin(actor, account_id, expected_version, now):
    require_owner(actor)
    state, binding = "meta_" + secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with s.connection(write=True) as c:
        account = s.get(c, "account", account_id)
        config = _config(account["platform"])
        if account["version"] != expected_version:
            raise _changed()
        if account["external_id"]:
            identity.identifier(account["external_id"])
        pending = {"id": s.uid("selection"), "phase": "login", "owner_id": actor["id"], "account_id": account_id,
                   "account_version": expected_version, "config_fingerprint": _fingerprint(config),
                   "expires_at": (now + timedelta(seconds=TTL)).isoformat()}
        credentials.save(c, account_id, "meta_pending", pending)
        credentials.remember(c, state, {**pending, "binding_hash": s.digest(binding), "started_at": now.isoformat()})
    url = "https://www.facebook.com/" + identity.API_VERSION + "/dialog/oauth?" + urlencode({"client_id": config["app_id"],
        "config_id": config["config_id"], "redirect_uri": config["redirect_uri"], "state": state,
        "response_type": "code", "override_default_response_type": "true"})
    return {"authorization_url": url, "binding": binding}


def finish(actor, *, state, code, binding, now, error=None):
    require_owner(actor)
    started = monotonic()
    with s.connection(write=True) as c:
        intent = credentials.intent(c, state)
        if (not state.startswith("meta_") or not intent or intent["owner_id"] != actor["id"] or not binding
                or not hmac.compare_digest(intent["binding_hash"], s.digest(binding)) or timestamp(intent["expires_at"]) <= now):
            raise MarketingError("META_STATE_INVALID", "This Meta login expired, was used, or belongs to another browser. Start again.")
        account = s.get(c, "account", intent["account_id"])
        config = _config(account["platform"])
        pending = _pending(c, account, config, now)
        if pending["id"] != intent["id"]:
            raise _changed()
        credentials.consume(c, state)
    if error or not code:
        raise MarketingError("META_CANCELLED", "Meta login was cancelled. No connection was changed.")
    grant = identity.exchange(config, code, account["platform"], now)
    discovered = identity.discover(config, grant, account["platform"], now)
    grant = {**grant, "expires_at": discovered["expires_at"]}
    choices = [row for row in discovered["choices"] if not account["external_id"] or row["target_id"] == account["external_id"]]
    if not choices:
        raise MarketingError("META_NO_ACCOUNT", "Meta returned no matching account with permission to create content.")
    with s.connection(write=True) as c:
        completed = now + timedelta(seconds=monotonic() - started)
        if timestamp(grant["expires_at"]) <= completed + timedelta(seconds=60):
            raise _changed()
        current = s.get(c, "account", account["id"])
        existing = _pending(c, current, _config(current["platform"]), completed)
        if existing["id"] != pending["id"]:
            raise _changed()
        pending = {**pending, "phase": "selection", "grant": grant, "choices": choices}
        credentials.save(c, account["id"], "meta_pending", pending)
        return _public(pending)


def select(actor, account_id, expected_version, selection_id, target_id, now):
    require_owner(actor)
    started = monotonic()
    with s.connection() as c:
        account = s.get(c, "account", account_id)
        config = _config(account["platform"])
        pending = _pending(c, account, config, now)
        if (pending["phase"] != "selection" or pending["owner_id"] != actor["id"]
                or pending["id"] != selection_id or expected_version != account["version"]):
            raise _changed()
        choice = next((row for row in pending["choices"] if row["target_id"] == target_id), None)
        if not choice:
            raise _changed()
    choice, expires = identity.verify_choice(config, pending["grant"], account["platform"], choice, now)
    grant = {"id": s.uid("grant"), "platform": account["platform"], "user": pending["grant"], "choice": choice,
             "config_fingerprint": _fingerprint(config), "expires_at": expires}
    with s.connection(write=True) as c:
        completed = now + timedelta(seconds=monotonic() - started)
        if timestamp(expires) <= completed + timedelta(seconds=60):
            raise _changed()
        current = s.get(c, "account", account_id)
        existing = _pending(c, current, _config(current["platform"]), completed)
        if existing["id"] != pending["id"] or current["version"] != expected_version:
            raise _changed()
        credentials.save(c, account_id, "meta", grant)
        credentials.delete(c, account_id, "meta_pending")
        return s.put(c, "account", {**current, "external_id": target_id, "connection_status": "connected",
            "connection_checked_at": completed.isoformat(), "connection_fingerprint": grant["id"], "connection_reason": "Connection verified",
            "connection_identity": {key: choice[key] for key in ("target_id", "page_id", "title", "page_title")}},
            actor=actor, action="meta_account_selected", expected_version=expected_version)


def probe(actor, account_id, expected_version, now):
    require_owner(actor)
    with s.connection() as c:
        account = s.get(c, "account", account_id)
        grant = current_grant(account, now, c)
    if account["version"] != expected_version:
        raise _changed()
    try:
        choice, expires = identity.verify_choice(_config(account["platform"]), grant["user"], account["platform"], grant["choice"], now)
        status, reason = "connected", "Connection verified"
    except MarketingError:
        choice, expires, status, reason = None, grant["expires_at"], "error", "Meta could not verify this account and its publishing permissions."
    with s.connection(write=True) as c:
        current = s.get(c, "account", account_id)
        if current_grant(current, now, c)["id"] != grant["id"]:
            raise _changed()
        if choice:
            credentials.save(c, account_id, "meta", {**grant, "choice": choice, "expires_at": expires})
        return s.put(c, "account", {**current, "connection_status": status, "connection_reason": reason,
            "connection_fingerprint": grant["id"] if choice else None, "connection_checked_at": now.isoformat(),
            "connection_identity": {key: choice[key] for key in ("target_id", "page_id", "title", "page_title")} if choice else None},
            actor=actor, action="meta_connection_checked", expected_version=expected_version)


def disconnect(actor, account_id, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        current = s.get(c, "account", account_id)
        if current["platform"] not in identity.SCOPES:
            raise MarketingError("META_ACCOUNT_REQUIRED", "Choose a Facebook Page or a linked professional Instagram account.")
        saved = s.put(c, "account", {**current, "connection_status": "not_connected", "connection_fingerprint": None,
            "connection_checked_at": None, "connection_identity": None, "connection_reason": "Meta disconnected locally."},
            actor=actor, action="meta_disconnected", expected_version=expected_version)
        credentials.delete(c, account_id, "meta")
        credentials.delete(c, account_id, "meta_pending")
        return saved

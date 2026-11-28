"""Provider setup and read-only probes are separate from account permissions."""
import hashlib
import os
import time
from datetime import datetime, timedelta, timezone

from . import store as s
from .errors import MarketingError, require_owner

TELEGRAM_ENV = "MARKETING_TELEGRAM_BOT_TOKEN"
PROBE = {"id": "channel_probe", "role": "connection_verifier"}


def _credential():
    return os.getenv(TELEGRAM_ENV, "").strip()


def _fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def setup(account, now=None, c=None):
    platform = account["platform"]
    if platform in {"facebook", "instagram"}:
        from . import meta_oauth
        return meta_oauth.setup(account, now, c)
    if platform == "linkedin":
        from . import linkedin_oauth
        return linkedin_oauth.setup(account, now, c)
    implemented = platform == "telegram"
    credential = _credential() if implemented else ""
    ready = bool(credential and account.get("connection_status") == "connected"
                 and account.get("connection_fingerprint") == _fingerprint(credential))
    return {"implemented": implemented, "configured": bool(credential), "ready": ready,
            "credential_setting": TELEGRAM_ENV if implemented else None,
            "formats": ["post", "image", "carousel", "video"] if implemented else [],
            "reason": "Connection verified" if ready else "Verify the current channel credentials" if credential
            else "Dedicated Telegram credentials are not configured" if implemented else "This platform adapter is not implemented yet"}


def _adapter(account, now=None):
    if account["platform"] == "instagram":
        from .meta_oauth import current_grant
        from .instagram_transport import Instagram
        return Instagram(current_grant(account, now or datetime.now(timezone.utc)), now)
    if account["platform"] == "facebook":
        from .meta_oauth import current_grant
        from .facebook_transport import Facebook
        return Facebook(current_grant(account, now or datetime.now(timezone.utc)), now)
    if account["platform"] == "linkedin":
        from .linkedin_oauth import current_grant
        from .linkedin_transport import LinkedIn
        return LinkedIn(current_grant(account, now or datetime.now(timezone.utc)), now)
    if account["platform"] != "telegram":
        raise MarketingError("CHANNEL_NOT_IMPLEMENTED", "This platform adapter is not implemented yet.")
    token = _credential()
    if not token:
        raise MarketingError("CHANNEL_SETUP_REQUIRED", "Dedicated Telegram credentials are not configured.")
    from .telegram_transport import Telegram
    return Telegram(token)


def probe(actor, account_id, expected_version, now):
    require_owner(actor)
    with s.connection() as c:
        account = s.get(c, "account", account_id)
    if account["platform"] in {"facebook", "instagram"}:
        from . import meta_oauth
        return meta_oauth.probe(actor, account_id, expected_version, now)
    if account["platform"] == "linkedin":
        from . import linkedin_oauth
        return linkedin_oauth.probe(actor, account_id, expected_version, now)
    if account["version"] != expected_version:
        raise MarketingError("ACCOUNT_CHANGED", "The account changed. Reload before checking its connection.")
    credential = _credential()
    if not setup(account)["configured"]:
        _adapter(account)  # Return a precise setup error without exposing secrets.
    try:
        identity = _adapter(account).probe(account)
        status, reason = "connected", "Connection verified"
    except Exception:
        identity, status = None, "error"
        reason = "Connection could not be verified. Check the credential, numeric channel ID and bot posting rights."
    if credential != _credential():
        raise MarketingError("CREDENTIAL_CHANGED", "Credentials changed during the connection check. Check again.")
    with s.connection(write=True) as c:
        current = s.get(c, "account", account_id)
        return s.put(c, "account", {**current, "connection_status": status, "connection_checked_at": now.isoformat(),
                     "connection_fingerprint": _fingerprint(credential) if identity else None,
                     "connection_identity": identity, "connection_reason": reason}, actor=PROBE,
                     action="provider_connection_checked", expected_version=expected_version)


class Transport:
    def __init__(self, now=None):
        self.started_at = now or datetime.now(timezone.utc)
        self.started_clock = time.monotonic()

    def ready(self, account, item):
        state = setup(account, self.started_at)
        if state.get("publishing_implemented") is False:
            return False, "This platform adapter is not implemented yet"
        return state["ready"], state["reason"]

    def publish_claimed(self, account, item, job):
        from . import delivery
        release_key = job["id"]
        def verify(prepared=None):
            at = self.started_at + timedelta(seconds=time.monotonic() - self.started_clock)
            current = delivery.verify_before_send(release_key, account, item, at, prepared, claim_token=job["claim_token"])
            if not setup(current, at)["ready"]:
                raise delivery.StoppedBeforeSend("Verify the current channel credentials")
            if current["platform"] in {"linkedin", "facebook", "instagram"} and current.get("connection_fingerprint") != account.get("connection_fingerprint"):
                raise delivery.StoppedBeforeSend("The authorized social account connection changed before sending")
        verify()
        try:
            adapter = _adapter(account, self.started_at)
        except MarketingError:
            raise delivery.StoppedBeforeSend("Verify the current channel credentials") from None
        return adapter.publish(account, item, release_key, before_send=verify, claim_token=job["claim_token"])

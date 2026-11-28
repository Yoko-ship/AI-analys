"""Current encrypted grants and short-lived OAuth intents; never portable history.

The encryption key belongs in the service environment. Ciphertexts are bound to
the environment, provider and account so copying a row cannot retarget a grant.
"""
import json
import os

from cryptography.fernet import Fernet, InvalidToken

from . import store as s
from .errors import MarketingError

KEY_ENV = "MARKETING_CREDENTIAL_KEY"


def cipher():
    try:
        return Fernet(os.environ[KEY_ENV].strip().encode())
    except (KeyError, ValueError):
        raise MarketingError("CREDENTIAL_KEY_REQUIRED", "Configure the private marketing credential encryption key.") from None


def configured():
    try:
        cipher()
        return True
    except MarketingError:
        return False


def save(c, account_id, provider, grant):
    value = {"environment": s.environment(), "account_id": account_id, "provider": provider, "grant": grant}
    encrypted = cipher().encrypt(s.encode(value).encode()).decode()
    c.execute("INSERT INTO marketing_credentials(environment,account_id,provider,ciphertext) VALUES (?,?,?,?) "
              "ON CONFLICT(environment,account_id,provider) DO UPDATE SET ciphertext=excluded.ciphertext",
              (s.environment(), account_id, provider, encrypted))


def read(c, account_id, provider):
    row = c.execute("SELECT ciphertext FROM marketing_credentials WHERE environment=? AND account_id=? AND provider=?",
                    (s.environment(), account_id, provider)).fetchone()
    if not row:
        return None
    try:
        value = json.loads(cipher().decrypt(row["ciphertext"].encode()))
    except (InvalidToken, ValueError, MarketingError):
        return None
    if (value.get("environment"), value.get("account_id"), value.get("provider")) != (s.environment(), account_id, provider):
        return None
    return value.get("grant")


def delete(c, account_id, provider):
    c.execute("DELETE FROM marketing_credentials WHERE environment=? AND account_id=? AND provider=?",
              (s.environment(), account_id, provider))


def remember(c, state, intent):
    c.execute("DELETE FROM marketing_oauth_states WHERE environment=? AND expires_at<=?",
              (s.environment(), intent["started_at"]))
    c.execute("INSERT INTO marketing_oauth_states(environment,state_hash,expires_at,payload) VALUES (?,?,?,?)",
              (s.environment(), s.digest(state), intent["expires_at"], s.encode(intent)))


def intent(c, state):
    row = c.execute("SELECT payload FROM marketing_oauth_states WHERE environment=? AND state_hash=?",
                    (s.environment(), s.digest(state))).fetchone()
    return json.loads(row["payload"]) if row else None


def consume(c, state):
    c.execute("DELETE FROM marketing_oauth_states WHERE environment=? AND state_hash=?", (s.environment(), s.digest(state)))

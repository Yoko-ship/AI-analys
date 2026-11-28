"""Small fixed-host LinkedIn OAuth client; provider responses never become errors."""
import re

import requests

from .errors import MarketingError

SCOPES = {"openid", "profile", "w_member_social"}


def request(method, url, **kwargs):
    try:
        with requests.Session() as session:
            response = session.request(method, url, timeout=(5, 30), allow_redirects=False, **kwargs)
        if response.status_code != 200 or len(response.content) > 1_000_000:
            raise ValueError("Unusable response")
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("Invalid response")
        return value
    except Exception:
        raise MarketingError("LINKEDIN_UNAVAILABLE", "LinkedIn could not verify this login. Start the connection again.") from None


def profile(token):
    value = request("GET", "https://api.linkedin.com/v2/userinfo", headers={"Authorization": "Bearer " + token})
    subject = value.get("sub")
    if not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", subject):
        raise MarketingError("LINKEDIN_PROFILE_INVALID", "LinkedIn did not identify a personal profile.")
    name = value.get("name")
    return {"target_id": "urn:li:person:" + subject, "title": name[:200] if isinstance(name, str) else "LinkedIn member"}


def exchange(config, code):
    value = request("POST", "https://www.linkedin.com/oauth/v2/accessToken", data={
        "grant_type": "authorization_code", "code": code, "client_id": config["client_id"],
        "client_secret": config["client_secret"], "redirect_uri": config["redirect_uri"]})
    token, lifetime, scopes = value.get("access_token"), value.get("expires_in"), value.get("scope")
    if (not isinstance(token, str) or not re.fullmatch(r"[!-~]{1,8192}", token)
            or type(lifetime) is not int or not 60 < lifetime <= 366 * 86400
            or not isinstance(scopes, str) or not SCOPES.issubset(set(scopes.replace(",", " ").split()))):
        raise MarketingError("LINKEDIN_GRANT_INVALID", "LinkedIn did not grant the required profile and posting permissions.")
    return {"access_token": token, "expires_in": lifetime, "scopes": sorted(SCOPES)}, profile(token)

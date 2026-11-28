"""Personal organic posts through the versioned LinkedIn Posts API."""
import hashlib
import re
from datetime import datetime, timezone

import requests

from . import linkedin_identity, publishing, sources, store as s
from .delivery import PermanentRejection, StoppedBeforeSend, TemporaryRejection
from .errors import MarketingError
from .linkedin_http import headers, retry_delay


def little_text(text):
    """Encode plain copy, preventing reserved punctuation from becoming markup."""
    return "".join("\\" + char if char in "|{}@[]()<>#\\*_~" else char for char in text)


class LinkedIn:
    def __init__(self, grant, now=None):
        self.grant = grant
        self.now = now or datetime.now(timezone.utc)

    def probe(self, account):
        identity = linkedin_identity.profile(self.grant["access_token"])
        if identity["target_id"] != account["external_id"] or identity["target_id"] != self.grant["person"]:
            raise MarketingError("LINKEDIN_PROFILE_MISMATCH", "The signed-in LinkedIn profile differs from the authorized personal profile.")
        return identity

    def publish(self, account, item, release_key, *, before_send, claim_token):
        with s.connection() as c:
            evidence = {key: sources.current_evidence(c, key) for key in item["evidence_ids"]}
        if (item["format"] == "post" and item["assets"]) or publishing.check(account, item, evidence):
            raise PermanentRejection("LinkedIn content limits require a revision")
        copy = publishing.text(item, evidence)
        try:
            self.probe(account)
        except MarketingError:
            raise StoppedBeforeSend("LinkedIn could not verify the authorized personal profile before sending") from None
        payload = {"author": account["external_id"], "commentary": little_text(copy), "visibility": "PUBLIC",
                   "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                   "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
        if item["format"] != "post":
            from .linkedin_media import LinkedInMedia
            payload["content"] = LinkedInMedia(self.grant, self.now, before_send).prepare(account, item, release_key, claim_token)
            try:
                self.probe(account)
            except MarketingError:
                raise StoppedBeforeSend("LinkedIn could not verify the authorized personal profile before sending") from None
        before_send({"text": copy, "format": item["format"], "media_count": len(item["assets"]),
                     "assets": [{"id": ref["id"], **item["check"]["asset_versions"][ref["id"]]} for ref in item["assets"]]})
        # Default requests sessions do not retry; never redirect a bearer token.
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.post("https://api.linkedin.com/rest/posts", json=payload, timeout=(5, 30), allow_redirects=False,
                    headers=headers(self.grant["access_token"]))
        except Exception:
            raise RuntimeError("LinkedIn publication outcome is unknown") from None
        if response.status_code == 429:
            raise TemporaryRejection("LinkedIn explicitly rejected this request", retry_after=retry_delay(response.headers.get("Retry-After"), self.now))
        if response.status_code in {400, 401, 403, 404, 405, 413, 415, 422}:
            raise PermanentRejection("LinkedIn rejected this request")
        identifier = response.headers.get("x-restli-id", "")
        if response.status_code != 201 or not re.fullmatch(r"urn:li:(?:share|ugcPost):[1-9][0-9]{0,30}", identifier):
            raise RuntimeError("LinkedIn did not confirm a created post ID")
        return {"provider": "linkedin", "publication_status": "submitted", "external_id": identifier, "external_ids": [identifier],
                "url": "https://www.linkedin.com/feed/update/" + identifier + "/",
                "payload_digest": hashlib.sha256(copy.encode()).hexdigest()}

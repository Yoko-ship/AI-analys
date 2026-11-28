"""Fenced upload checkpoints: public progress, encrypted provider upload tickets."""
from . import content, credentials, store as s
from .delivery import StoppedBeforeSend

ACTOR = {"id": "linkedin_media", "role": "publisher"}


class UploadJournal:
    def __init__(self, account, item, grant, asset, release_key, claim_token, now, *, provider="linkedin"):
        self.key = s.digest([account["id"], account["external_id"], grant["id"], release_key,
                             content.content_digest(item), asset["id"], asset["sha256"]])
        self.job_id, self.claim_token, self.now = release_key, claim_token, now
        self.provider = provider
        self.public = {"id": self.key, "candidate_id": item["id"], "account_id": account["id"], "provider": provider,
                       "asset_id": asset["id"], "sha256": asset["sha256"], "format": item["format"]}

    def _fence(self, c):
        job = s.get(c, "delivery", self.job_id)
        if job["status"] != "sending" or job.get("claim_token") != self.claim_token or job.get("dispatch_phase") != "preparing":
            raise StoppedBeforeSend("The dispatch claim is no longer active")

    def load(self):
        with s.connection() as c:
            self._fence(c)
            return credentials.read(c, self.key, self.provider + "_upload")

    def save(self, state):
        with s.connection(write=True) as c:
            self._fence(c)
            previous = s.get(c, "provider_upload", self.key, required=False)
            credentials.save(c, self.key, self.provider + "_upload", state)
            s.put(c, "provider_upload", {**self.public, "remote_id": state["remote_id"], "status": state["phase"],
                  "parts_completed": len(state.get("completed", [])), "part_count": len(state["parts"]),
                  "checked_at": self.now.isoformat()}, actor={**ACTOR, "id": self.provider + "_media"}, action="provider_upload_checkpoint",
                  expected_version=previous["version"] if previous else 0)
        return state

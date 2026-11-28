"""Upload verified local media and resume confirmed parts without creating posts."""
import io
import re
from urllib.parse import quote, urlsplit

from PIL import Image

from . import linkedin_http as http, media, store as s
from .delivery import PermanentRejection, PreparationPending
from .upload_journal import UploadJournal


def _invalid():
    return PermanentRejection("LinkedIn media or upload instructions require attention")


def _urn(value, kind):
    if not isinstance(value, str) or not re.fullmatch(r"urn:li:" + kind + r":[A-Za-z0-9_-]{1,200}", value):
        raise _invalid()
    return value


def _url(value, remote_id, kind):
    try:
        url = urlsplit(value)
        suffix = r"/uploaded-image/[0-9]+" if kind == "image" else r"/uploadedVideo(?:/[0-9]+)?"
        valid = (len(value) <= 8192 and url.scheme == "https" and url.hostname == "www.linkedin.com"
                 and url.port in {None, 443} and not url.username and not url.password and not url.fragment
                 and re.fullmatch(r"/dms-uploads/" + re.escape(remote_id.rsplit(":", 1)[-1]) + suffix, url.path))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise _invalid()
    return value


def _expires(value, now):
    if type(value) is not int or value <= int(now.timestamp() * 1000):
        raise _invalid()
    return value


def _local_files(item):
    with s.connection() as c:
        assets = [s.get(c, "asset", ref["id"]) for ref in item["assets"]]
    expected = 2 <= len(assets) <= 20 if item["format"] == "carousel" else len(assets) == 1
    if not expected or len({asset["id"] for asset in assets}) != len(assets):
        raise _invalid()
    files = []
    for asset in assets:
        try:
            raw = media.read_asset(asset)
            alt = asset.get("alt_text", "")
            if not isinstance(alt, str) or not alt or len(alt.encode("utf-16-le")) // 2 > 4086:
                raise ValueError("Invalid alternate text")
            if item["format"] == "video":
                if (asset["mime"] != "video/mp4" or not 75000 <= len(raw) <= 30_000_000
                        or not 3 <= asset.get("duration_seconds", 0) <= 1800 or raw[4:8] != b"ftyp"):
                    raise ValueError("Invalid video")
            else:
                with Image.open(io.BytesIO(raw)) as picture:
                    if picture.format not in {"PNG", "JPEG"} or picture.width * picture.height >= 36_152_320:
                        raise ValueError("Invalid image")
                    if asset["mime"] != {"PNG": "image/png", "JPEG": "image/jpeg"}[picture.format]:
                        raise ValueError("Image type mismatch")
                    picture.verify()
        except Exception:
            raise _invalid() from None
        files.append((asset, raw))
    return files


class LinkedInMedia:
    def __init__(self, grant, now, check):
        self.grant, self.now, self.check = grant, now, check

    def _register(self, owner, raw, kind):
        value = {"owner": owner}
        if kind == "video":
            value.update(fileSizeBytes=len(raw), uploadCaptions=False, uploadThumbnail=False)
        self.check()
        response = http.preparation_json("POST", kind + "s?action=initializeUpload", self.grant["access_token"], self.now,
                                         {"initializeUploadRequest": value}).get("value")
        if not isinstance(response, dict):
            raise _invalid()
        remote_id = _urn(response.get(kind), kind)
        if kind == "image":
            expires = _expires(response.get("uploadUrlExpiresAt"), self.now)
            parts = [{"firstByte": 0, "lastByte": len(raw) - 1, "uploadUrl": _url(response.get("uploadUrl"), remote_id, kind)}]
            upload_token = None
        else:
            expires = _expires(response.get("uploadUrlsExpireAt"), self.now)
            parts, upload_token = response.get("uploadInstructions"), response.get("uploadToken")
            if (not isinstance(parts, list) or not 1 <= len(parts) <= 100
                    or not isinstance(upload_token, str) or len(upload_token) > 8192):
                raise _invalid()
            expected = 0
            for part in parts:
                if (not isinstance(part, dict) or type(part.get("firstByte")) is not int or type(part.get("lastByte")) is not int
                        or part["firstByte"] != expected or not expected <= part["lastByte"] < len(raw)
                        or part["lastByte"] - expected + 1 > 4_194_304):
                    raise _invalid()
                _url(part.get("uploadUrl"), remote_id, kind)
                expected = part["lastByte"] + 1
            if expected != len(raw):
                raise _invalid()
        return {"phase": "registered", "remote_id": remote_id, "parts": parts, "completed": [],
                "expires_at": expires, "upload_token": upload_token, "waits": 0}

    def _video_status(self, state, owner):
        self.check()
        result = http.preparation_json("GET", "videos/" + quote(state["remote_id"], safe=""), self.grant["access_token"], self.now)
        if result.get("id") != state["remote_id"] or result.get("owner") != owner:
            raise _invalid()
        status = result.get("status")
        if status not in {"WAITING_UPLOAD", "PROCESSING", "PROCESSING_FAILED", "AVAILABLE"}:
            raise _invalid()
        return status

    def _upload(self, journal, state, raw, kind, owner):
        if state["phase"] == "failed":
            raise PermanentRejection("LinkedIn could not process the video; no post has been created")
        if state["phase"] in {"registered", "uploading"}:
            _expires(state["expires_at"], self.now)
            for part in state["parts"][len(state["completed"]):]:
                self.check()
                headers = {"Content-Type": "application/octet-stream"}
                if kind == "image":
                    headers["Authorization"] = "Bearer " + self.grant["access_token"]
                response = http.preparation_request("PUT", _url(part["uploadUrl"], state["remote_id"], kind), self.now,
                    expected={200, 201} if kind == "image" else {200}, headers=headers, data=raw[part["firstByte"]:part["lastByte"] + 1])
                receipt = response.headers.get("ETag", "").strip('"') if kind == "video" else "uploaded"
                if not receipt or len(receipt) > 8192 or not re.fullmatch(r'[!-~]+', receipt) or '"' in receipt:
                    raise _invalid()
                state = journal.save({**state, "phase": "uploading", "completed": [*state["completed"], receipt]})
            state = journal.save({**state, "phase": "uploaded"})
        if kind == "image":
            return state
        # A lost finalize response is reconciled by reading this exact video's
        # owner/status. It cannot justify repeating any public post request.
        status = self._video_status(state, owner) if state["phase"] in {"finalizing", "processing", "ready"} else "WAITING_UPLOAD"
        if state["phase"] == "uploaded" or status == "WAITING_UPLOAD":
            self.check()
            state = journal.save({**state, "phase": "finalizing"})
            http.preparation_request("POST", "https://api.linkedin.com/rest/videos?action=finalizeUpload", self.now, expected={200},
                headers=http.headers(self.grant["access_token"]), json={"finalizeUploadRequest": {"video": state["remote_id"],
                    "uploadToken": state["upload_token"], "uploadedPartIds": state["completed"]}})
            state = journal.save({**state, "phase": "processing"})
            status = self._video_status(state, owner)
        if status == "PROCESSING_FAILED":
            journal.save({**state, "phase": "failed"})
            raise PermanentRejection("LinkedIn could not process the video; no post has been created")
        if status != "AVAILABLE":
            delay = min(600, 60 * 2 ** min(state["waits"], 4))
            journal.save({**state, "phase": "processing", "waits": state["waits"] + 1})
            raise PreparationPending("LinkedIn video is processing; no post has been created", delay)
        return journal.save({**state, "phase": "ready"})

    def prepare(self, account, item, release_key, claim_token):
        files = _local_files(item)  # Validate every local file before the first remote write.
        entries = []
        for asset, raw in files:
            kind = "video" if item["format"] == "video" else "image"
            journal = UploadJournal(account, item, self.grant, asset, release_key, claim_token, self.now)
            state = journal.load()
            if state is None:
                state = journal.save(self._register(account["external_id"], raw, kind))
            state = self._upload(journal, state, raw, kind, account["external_id"])
            entries.append({"id": state["remote_id"], **({"altText": asset["alt_text"]} if kind == "image" else {"title": item["title"]})})
        if len({entry["id"] for entry in entries}) != len(entries):
            raise _invalid()
        return {"multiImage": {"images": entries}} if item["format"] == "carousel" else {"media": entries[0]}

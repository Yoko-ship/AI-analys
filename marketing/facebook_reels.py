"""Unpublished Reel uploads resume only from provider-confirmed byte offsets."""
from fractions import Fraction
import json
import re
import shutil
import subprocess
from urllib.parse import urlsplit

import requests

from . import media, meta_http as http, meta_identity, store as s
from .delivery import PermanentRejection, PreparationPending, TemporaryRejection
from .upload_journal import UploadJournal


def invalid():
    return PermanentRejection("Facebook Reel media or upload status requires attention")


class UploadExpired(Exception):
    """Only an unpublished upload may be replaced with a new session."""


def local_video(item):
    if len(item["assets"]) != 1:
        raise invalid()
    with s.connection() as c:
        asset = s.get(c, "asset", item["assets"][0]["id"])
    try:
        raw = media.read_asset(asset)
        executable = shutil.which("ffprobe")
        if not executable or asset["mime"] != "video/mp4" or raw[4:8] != b"ftyp":
            raise ValueError("Invalid video file")
        response = subprocess.run([executable, "-v", "error", "-show_streams", "-show_format", "-of", "json",
            str(media.asset_path(asset))], check=True, capture_output=True, timeout=30)
        if len(response.stdout) > 1_000_000:
            raise ValueError("Oversized media metadata")
        info = json.loads(response.stdout)
        streams = info["streams"]
        video = [row for row in streams if row["codec_type"] == "video"]
        if len(video) != 1 or any(row["codec_type"] not in {"video", "audio"} for row in streams):
            raise ValueError("Unexpected media streams")
        video = video[0]
        if (video["codec_name"] != "h264" or video["pix_fmt"] != "yuv420p" or video["field_order"] != "progressive"
                or video["width"] < 540 or video["height"] < 960 or video["width"] * 16 != video["height"] * 9
                or not 24 <= Fraction(video["avg_frame_rate"]) == Fraction(video["r_frame_rate"]) <= 60
                or not 3 <= float(info["format"]["duration"]) <= 90):
            raise ValueError("Unsupported Reel video")
        for audio in (row for row in streams if row["codec_type"] == "audio"):
            if (audio["codec_name"] != "aac" or audio.get("profile") != "LC" or int(audio["sample_rate"]) != 48000
                    or audio["channels"] != 2 or int(audio.get("bit_rate", 0)) < 128000):
                raise ValueError("Unsupported Reel audio")
    except Exception:
        raise invalid() from None
    return asset, raw


def upload_url(value, identifier):
    try:
        url = urlsplit(value)
        valid = (len(value) <= 8192 and url.scheme == "https" and url.hostname == "rupload.facebook.com"
            and url.port in {None, 443} and not url.username and not url.password and not url.fragment
            and re.fullmatch(r"/video-upload/(?:" + re.escape(meta_identity.API_VERSION) + r"/)?" + re.escape(identifier), url.path))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise invalid()
    return value


def status(value, identifier, size):
    if value.get("id") != identifier or not isinstance(value.get("status"), dict):
        raise invalid()
    result = value["status"]
    phases = [result.get(name) for name in ("uploading_phase", "processing_phase", "publishing_phase")]
    if any(not isinstance(phase, dict) for phase in phases):
        raise invalid()
    upload, process, publication = phases
    if any(phase.get("error") or phase.get("errors") or phase.get("status") == "error" for phase in (process, publication)):
        raise invalid()
    if publication.get("publish_status") in {"published", "scheduled", "error"} or publication.get("status") == "completed":
        raise invalid()
    if result.get("video_status") == "expired":
        raise UploadExpired()
    resumable = result.get("video_status") == "upload_failed"
    if result.get("video_status") == "error" or not resumable and (upload.get("error") or upload.get("errors")):
        raise invalid()
    if upload.get("status") not in {"completed", "complete", "in_progress", "not_started"} and not (resumable and upload.get("status") == "error"):
        raise invalid()
    offset = upload.get("bytes_transfered", size if upload["status"] in {"completed", "complete"} else None)
    reported = upload.get("source_file_size")
    if (type(offset) is not int or not 0 <= offset <= size
            or reported is not None and (type(reported) is not int or reported != size)
            or upload["status"] in {"completed", "complete"} and offset != size):
        raise invalid()
    if resumable and offset == size:
        raise invalid()
    ready = offset == size and upload["status"] in {"completed", "complete"} and process.get("status") == "completed" and result.get("video_status") == "ready"
    return offset, ready


class ReelUpload:
    def __init__(self, grant, config, at, check):
        self.grant, self.config, self.at, self.check = grant, config, at, check

    def graph(self, method, path, data):
        self.check()
        return http.request(method, path, self.grant["choice"]["access_token"], self.config["app_secret"], self.at(), data=data)

    def _upload(self, state, raw, offset):
        self.check()
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(upload_url(state["upload_url"], state["remote_id"]), data=raw[offset:], timeout=(5, 30), allow_redirects=False,
                    headers={"Authorization": "OAuth " + self.grant["choice"]["access_token"], "Content-Type": "application/octet-stream",
                             "offset": str(offset), "file_size": str(len(raw))})
            if response.status_code == 429:
                raise TemporaryRejection("Facebook Reel upload is rate limited", retry_after=http.retry_after(response.headers, self.at()))
            if len(response.content) > 1_000_000 or response.status_code != 200 or response.json().get("success") is not True:
                raise ValueError("Upload not confirmed")
        except TemporaryRejection:
            raise
        except Exception:
            # Only unpublished bytes were sent. Read the offset before resuming.
            raise TemporaryRejection("Facebook Reel upload is unconfirmed", retry_after=60) from None

    def prepare(self, account, item, file, release_key, claim_token):
        asset, raw = file
        journal = UploadJournal(account, item, self.grant, asset, release_key, claim_token, self.at(), provider="facebook")
        saved = journal.load()
        if not saved or saved["phase"] == "expired":
            retired = [*(saved.get("retired_ids", []) if saved else []), *([saved["remote_id"]] if saved else [])]
            if len(retired) >= 3:
                raise invalid()
            value = self.graph("POST", account["external_id"] + "/video_reels", {"upload_phase": "start"})
            identifier = meta_identity.identifier(value.get("video_id"))
            if identifier in retired:
                raise invalid()
            saved = journal.save({"remote_id": identifier, "upload_url": upload_url(value.get("upload_url"), identifier), "phase": "registered",
                "parts": [{"firstByte": 0, "lastByte": len(raw) - 1}], "completed": [], "polls": 0, "retired_ids": retired})
        if saved["phase"] == "failed":
            raise invalid()
        try:
            offset, ready = (0, False) if saved["phase"] == "registered" else status(
                self.graph("GET", saved["remote_id"], {"fields": "status"}), saved["remote_id"], len(raw))
            if offset < len(raw):
                saved = journal.save({**saved, "phase": "uploading"})
                self._upload(saved, raw, offset)
                saved = journal.save({**saved, "phase": "uploaded", "completed": [0]})
                offset, ready = status(self.graph("GET", saved["remote_id"], {"fields": "status"}), saved["remote_id"], len(raw))
            if not ready:
                polls = saved.get("polls", 0) + 1
                journal.save({**saved, "phase": "processing", "completed": [0] if offset == len(raw) else [], "polls": polls})
                raise PreparationPending("Facebook is processing the Reel; no post has been created", retry_after=min(600, 60 * 2 ** min(polls - 1, 4)))
            journal.save({**saved, "phase": "ready", "completed": [0]})
            return saved["remote_id"]
        except UploadExpired:
            journal.save({**saved, "phase": "expired", "completed": []})
            raise PreparationPending("Facebook Reel upload expired; a new upload is scheduled", retry_after=60) from None
        except PermanentRejection:
            journal.save({**saved, "phase": "failed"})
            raise

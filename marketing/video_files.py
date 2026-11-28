"""Verify narrated MP4 exports before marking an independent project complete."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from . import media, store as s, video_studio as studio
from .errors import MarketingError

MAX_BYTES = 80_000_000


def upload_path(identifier, token):
    return media.directory() / (s.digest([identifier, token]) + ".upload.mp4")


def append(identifier, token, offset, chunk, now):
    if not 0 < len(chunk) <= 512000 or offset < 0 or offset + len(chunk) > MAX_BYTES:
        raise MarketingError("INVALID_VIDEO_CHUNK", "Invalid upload chunk", 413)
    with s.connection(write=True) as c:
        studio.leased(c, identifier, token, now)
        target = upload_path(identifier, token)
        size = target.stat().st_size if target.exists() else 0
        if offset < size and offset + len(chunk) <= size:
            with target.open("rb") as stream:
                stream.seek(offset)
                if stream.read(len(chunk)) == chunk:
                    return size
        if offset != size:
            raise MarketingError("VIDEO_UPLOAD_OFFSET", "Upload offset changed")
        with target.open("ab") as output:
            output.write(chunk)
        return size + len(chunk)


def inspect_video(path):
    if not 0 < path.stat().st_size <= MAX_BYTES or path.read_bytes()[4:8] != b"ftyp":
        raise ValueError("Invalid MP4")
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            check=True, capture_output=True, timeout=30)
    info = json.loads(result.stdout)
    video = [row for row in info["streams"] if row["codec_type"] == "video"]
    audio = [row for row in info["streams"] if row["codec_type"] == "audio"]
    if len(video) != 1 or len(audio) != 1 or len(info["streams"]) != 2:
        raise ValueError("Video and narration required")
    v, a = video[0], audio[0]
    duration = float(info["format"]["duration"])
    if (v["codec_name"] != "h264" or v["pix_fmt"] != "yuv420p" or v["width"] != 1080 or v["height"] != 1920
            or Fraction(v["avg_frame_rate"]) != 30 or a["codec_name"] != "aac" or int(a["sample_rate"]) != 48000
            or not 8 <= duration <= 120 or abs(float(a["duration"]) - duration) > 1):
        raise ValueError("Unsupported export format")
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
                   check=True, capture_output=True, timeout=120)
    return {"duration_seconds": duration, "width": 1080, "height": 1920, "fps": 30, "voice": "uzstock-male-v1"}


def path(item):
    name = item.get("file_name", "")
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise MarketingError("VIDEO_UNAVAILABLE", "Файл видео недоступен.", 404)
    return media.directory() / name


def finish(identifier, token, uploaded, now):
    with s.connection() as c:
        studio.leased(c, identifier, token, now)
    try:
        metadata = inspect_video(uploaded)
    except Exception:
        raise MarketingError("INVALID_VIDEO", "MP4 не прошёл проверку изображения, звука или длительности.", 422) from None
    name = s.uid("video_export") + ".mp4"
    destination = media.directory() / name
    shutil.copyfile(uploaded, destination)
    try:
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        with s.connection(write=True) as c:
            item = studio.leased(c, identifier, token, now)
            return studio._save(c, item, status="complete", stage="complete", lease_token=None,
                                file_name=name, sha256=digest, metadata=metadata)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def read(item):
    try:
        target = path(item)
        if item["status"] == "complete" and 0 < target.stat().st_size <= MAX_BYTES:
            raw = target.read_bytes()
            if hashlib.sha256(raw).hexdigest() == item["sha256"]:
                return raw
    except OSError:
        pass
    raise MarketingError("VIDEO_UNAVAILABLE", "Файл видео недоступен или повреждён.", 404)

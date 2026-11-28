"""Validate the actual reviewed MP4 before Instagram fetches it."""
from fractions import Fraction
import json
import shutil
import subprocess

from . import media
from .delivery import PermanentRejection


def _boxes(raw, start, end):
    count = 0
    while start < end:
        if end - start < 8 or count >= 1000:
            raise ValueError("Invalid MP4 box table")
        size, name, header = int.from_bytes(raw[start:start + 4], "big"), raw[start + 4:start + 8], 8
        if size == 1:
            if end - start < 16:
                raise ValueError("Invalid MP4 extended size")
            size, header = int.from_bytes(raw[start + 8:start + 16], "big"), 16
        elif size == 0:
            size = end - start
        if not header <= size <= end - start:
            raise ValueError("Invalid MP4 box bounds")
        yield name, start + header, start + size
        start += size
        count += 1


def _layout(raw):
    boxes = list(_boxes(raw, 0, len(raw)))
    names = [box[0] for box in boxes]
    if not names or names[0] != b"ftyp" or names.count(b"moov") != 1 or b"mdat" not in names or names.index(b"moov") > names.index(b"mdat"):
        raise ValueError("Instagram needs an MP4 with metadata before its media")
    _, start, end = boxes[names.index(b"moov")]
    for name, first, last in _boxes(raw, start, end):
        if name == b"trak":
            if any(child[0] in {b"edts", b"elst"} for child in _boxes(raw, first, last)):
                raise ValueError("Instagram does not support MP4 edit lists")


def validate(asset):
    try:
        raw = media.read_asset(asset)
        executable = shutil.which("ffprobe")
        if not executable or asset["mime"] != "video/mp4":
            raise ValueError("MP4 probing is unavailable")
        _layout(raw)
        response = subprocess.run([executable, "-v", "error", "-show_streams", "-show_format", "-of", "json",
            str(media.asset_path(asset))], check=True, capture_output=True, timeout=30)
        if len(response.stdout) > 1_000_000:
            raise ValueError("Oversized video metadata")
        info = json.loads(response.stdout)
        streams = info["streams"]
        videos = [row for row in streams if row["codec_type"] == "video"]
        if len(videos) != 1 or any(row["codec_type"] not in {"video", "audio"} for row in streams):
            raise ValueError("Unexpected MP4 streams")
        video = videos[0]
        if (video["codec_name"] not in {"h264", "hevc"} or video["pix_fmt"] != "yuv420p" or video["field_order"] != "progressive"
                or not 1 <= video["width"] <= 1920 or not .01 <= video["width"] / video["height"] <= 10
                or not all(23 <= Fraction(video[key]) <= 60 for key in ("avg_frame_rate", "r_frame_rate"))
                or not 3 <= float(info["format"]["duration"]) <= 900 or not 0 < int(video["bit_rate"]) <= 25_000_000):
            raise ValueError("Video exceeds Instagram Reel limits")
        for audio in (row for row in streams if row["codec_type"] == "audio"):
            if audio["codec_name"] != "aac" or audio["channels"] not in {1, 2} or not 0 < int(audio["sample_rate"]) <= 48000:
                raise ValueError("Audio exceeds Instagram Reel limits")
    except Exception:
        raise PermanentRejection("Instagram needs a verified MP4 within its Reel limits and without edit lists") from None

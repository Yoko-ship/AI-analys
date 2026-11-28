"""Deterministic UZStock cards/charts and silent captioned MP4 slideshows."""
from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path
import shutil
import subprocess
import struct
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from . import instagram_links

BG, PANEL, TEXT, MUTED, GREEN = "#10251f", "#1b372c", "#f5f8f0", "#bed0c1", "#b3df80"
LABELS = {
    "dividend": ("Дивиденд на акцию", "Bir aksiyaga dividend"),
    "net_income": ("Чистая прибыль", "Sof foyda"), "total_assets": ("Активы", "Aktivlar"),
    "revenue": ("Выручка", "Tushum"), "turnover": ("Оборот", "Aylanma"),
    "trades": ("Количество сделок", "Bitimlar soni"), "close": ("Цена закрытия", "Yopilish narxi"),
}


def _font(size):
    root = Path(__file__).resolve().parents[1]
    paths = [root / "marketing/assets/Manrope.ttf", root / "frontend/src/assets/landing/Manrope.ttf",
             Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for path in paths:
        if path.is_file():
            font = ImageFont.truetype(str(path), size)
            if path.name == "Manrope.ttf":
                font.set_variation_by_axes([600])
            return font
    raise ValueError("A font supporting the publication language is required")


def _lines(draw, text, font, width):
    lines = []
    for paragraph in str(text).splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            if line and draw.textlength(line + " " + word, font=font) > width:
                lines.append(line)
                line = ""
            for letter in word:
                if draw.textlength(line + letter, font=font) > width:
                    lines.append(line)
                    line = ""
                line += letter
            line += " "
        lines.append(line.rstrip())
    return lines


def _text(draw, text, xy, width, height, *, size=38, color=TEXT, minimum=None):
    minimum = minimum or size
    for scale in range(size, minimum - 1, -2):
        font = _font(scale)
        lines = _lines(draw, text, font, width)
        line_height = int(scale * 1.4)
        if len(lines) * line_height <= height:
            for index, line in enumerate(lines):
                draw.text((xy[0], xy[1] + index * line_height), line, font=font, fill=color)
            return len(lines) * line_height
    raise ValueError("Media text does not fit at a readable size")


def _label(claim, language):
    labels = LABELS.get(claim["field"])
    return labels[1 if language == "uz" else 0] if labels else {"ru": "Факт", "uz": "Ma’lumot", "en": "Fact"}[language]


def _number(value):
    if not isinstance(value, (float, int)):
        return str(value)
    number = format(Decimal(str(value)), "f")
    return number.rstrip("0").rstrip(".") if "." in number else number


def _dividend_context(snapshot):
    item = snapshot["item"]
    claim = next((claim for claim in item["claims"] if claim["field"] == "dividend"), None)
    if not claim:
        return ""
    # Rendering has already verified one unambiguous original. Keep its state
    # and class visible on every frame, including a standalone story/fact slide.
    data = snapshot["evidence"][claim["evidence_id"]]["data"]
    language = {"ru": 0, "uz": 1, "en": 2}[item["language"]]
    state = {"proposed": ("Предложено", "Taklif qilingan", "Proposed"),
             "approved": ("Утверждено", "Tasdiqlangan", "Approved"),
             "paid": ("Выплачено", "To‘langan", "Paid")}[data["dividend_state"]][language]
    share_class = {"ordinary": ("Простая акция", "Oddiy aksiya", "Ordinary share"),
                   "preferred": ("Привилегированная акция", "Imtiyozli aksiya", "Preferred share")}[data["share_class"]][language]
    return state + " · " + share_class


def _canvas(snapshot, height):
    item = snapshot["item"]
    image = Image.new("RGB", (1080, height), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((72, 64, 128, 120), radius=14, fill=GREEN)
    draw.text((86, 68), "U", font=_font(34), fill=BG)
    draw.text((148, 66), "UZStock", font=_font(36), fill=TEXT)
    draw.line((72, 150, 1008, 150), fill=PANEL, width=3)
    _text(draw, item["title"], (72, 195), 936, 290, size=66, minimum=44)
    period = item.get("period") or next((row.get("period") for row in snapshot["evidence"].values() if row and row.get("period")), "")
    if item.get("entity") or period:
        draw.text((72, 465), " · ".join(value for value in (item.get("entity"), period) if value), font=_font(30), fill=MUTED)
    if context := _dividend_context(snapshot):
        _text(draw, context, (72, 508), 936, 38, size=26, color=GREEN)
    urls = list(dict.fromkeys(row["url"] for row in snapshot["evidence"].values() if row))
    domains = " · ".join(dict.fromkeys(urlsplit(url).hostname for url in urls))
    draw.line((72, height - 182, 1008, height - 182), fill=PANEL, width=3)
    source_label = "Manba" if item["language"] == "uz" else "Источник"
    _text(draw, f"{source_label}: {domains}", (72, height - 150), 936, 94, size=30, color=MUTED)
    draw.text((72, height - 55), "uzstock.uz", font=_font(27), fill=GREEN)
    if cta := instagram_links.caption(item):
        _text(draw, cta, (72, height - 240), 936, 52, size=36, color=GREEN)
    return image, draw


def _card(snapshot, claims, height, *, cover=False):
    image, draw = _canvas(snapshot, height)
    item = snapshot["item"]
    if cover or not claims:
        _text(draw, item["body"], (72, 565), 936, height - 810, size=40, minimum=34)
    else:
        if len(claims) > 3:
            raise ValueError("Use a carousel for more than three displayed facts")
        single = len(claims) == 1
        block = min(370 if single else 260, (height - (800 if instagram_links.caption(item) else 730)) // len(claims))
        compact = not single and block < 200
        for index, claim in enumerate(claims):
            top = 550 + index * block
            draw.rounded_rectangle((72, top, 1008, top + block - 20), radius=22, fill=PANEL)
            _text(draw, _label(claim, item["language"]), (100, top + 18), 870, 60 if single else 45, size=28 if compact else 40 if single else 32, minimum=28, color=MUTED)
            _text(draw, _number(claim["value"]), (100, top + (96 if single else 58)), 870, 64 if compact else 170 if single else 82, size=46 if compact else 120 if single else 58, minimum=44, color=GREEN)
            if claim["unit"]:
                _text(draw, claim["unit"], (100, top + (124 if compact else 280 if single else 139)), 870, 39 if compact else 58 if single else 45, size=28 if compact else 38 if single else 30, minimum=28)
        if item["format"] == "story":
            body_top = 550 + len(claims) * block + 32
            _text(draw, item["body"], (72, body_top), 936, height - 242 - body_top, size=40, minimum=34)
    return image


def _chart_data(snapshot):
    from .chart_series import measured
    from .permissions import timestamp
    ref = snapshot["chart"]
    if not isinstance(ref, dict) or set(ref) != {"evidence_id", "field"}:
        raise ValueError("Choose a source series by evidence id and field")
    source = snapshot["evidence"].get(ref["evidence_id"])
    return measured(ref['evidence_id'], ref['field'], source, timestamp(snapshot['rendered_at']))


def _chart(snapshot, chart, height):
    image, draw = _canvas(snapshot, height)
    story = snapshot["item"]["format"] == "story"
    left, top, right, bottom = 210, 590, 990, height - (600 if story else 300)
    lo, hi = chart["axis_min"], chart["axis_max"]
    scale = 1_000_000 if max(abs(lo), abs(hi)) >= 1_000_000 else 1000 if max(abs(lo), abs(hi)) >= 1000 else 1
    axis_unit = chart["unit"] + (f" · × {_number(scale)}" if scale != 1 else "")
    draw.text((72, 520), axis_unit, font=_font(32), fill=MUTED)
    for index in range(5):
        value = lo + (hi - lo) * index / 4
        y = bottom - (bottom - top) * index / 4
        draw.line((left, y, right, y), fill=PANEL, width=3)
        label = f"{value / scale:.2f}".rstrip("0").rstrip(".")
        draw.text((left - 18, y - 18), label, font=_font(27), fill=MUTED, anchor="ra")
    values = chart["series"]
    times = [date.fromisoformat(point["date"]).toordinal() for point in values]
    points = [(left + (right - left) * (day - times[0]) / (times[-1] - times[0]),
               bottom - (bottom - top) * (point["value"] - lo) / (hi - lo)) for day, point in zip(times, values)]
    draw.line(points, fill=GREEN, width=7)
    for index in sorted({0, len(values) // 2, len(values) - 1}):
        x, y = points[index]
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=GREEN)
        anchor = "la" if index == 0 else "ra" if index == len(values) - 1 else "ma"
        draw.text((x, bottom + 25), values[index]["date"], font=_font(27), fill=MUTED, anchor=anchor)
    if story:
        _text(draw, snapshot["item"]["body"], (72, bottom + 95), 936, height - 337 - bottom, size=40, minimum=34)
    return image


def _alt(snapshot, chart=None):
    item = snapshot["item"]
    facts = "; ".join(f"{_label(claim, item['language'])}: {_number(claim['value'])} {claim['unit']}" for claim in item["claims"])
    description = ". ".join(part.rstrip(".") for part in ["UZStock", item["title"], _dividend_context(snapshot), facts, item.get("period", ""), item["body"]] if part) + "."
    if chart:
        series_label, axis_label = ("Qator", "Shkala") if item["language"] == "uz" else ("Ряд", "Шкала")
        description += f" {series_label}: {chart['field']}, {chart['unit']}, {chart['series'][0]['date']} – {chart['series'][-1]['date']}. {axis_label}: {chart['axis_min']} – {chart['axis_max']}."
    if cta := instagram_links.caption(item):
        description += " " + cta
    return description


def render(snapshot, directory, key):
    item = snapshot["item"]
    height = 1920 if item["format"] in {"story", "video"} else 1350
    chart = _chart_data(snapshot) if snapshot.get("chart") else None
    claims = item["claims"]
    if chart:
        images = [_chart(snapshot, chart, height)]
        if item['format'] == 'carousel':
            images.insert(0, _card(snapshot, [], height, cover=True))
    elif item["format"] == "carousel":
        images = [_card(snapshot, claims[i:i + 3], height) for i in range(0, max(1, len(claims)), 3)]
        if len(images) == 1:
            images.insert(0, _card(snapshot, [], height, cover=True))
        if len(images) > 8:
            raise ValueError("A carousel is limited to eight readable slides")
    elif item["format"] == "video":
        if len(claims) > 24:
            raise ValueError("A short video is limited to eight readable fact slides")
        images = [_card(snapshot, [], height, cover=True)] + [_card(snapshot, claims[i:i + 3], height) for i in range(0, max(1, len(claims)), 3)]
    else:
        images = [_card(snapshot, claims, height)]
    description = _alt(snapshot, chart)
    files = []
    paths = []
    for index, image in enumerate(images):
        video = item["format"] == "video"
        path = directory / f"{key}-{index}.{'png' if video else 'jpg'}"
        if video:
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("Description", description)
            image.save(path, format="PNG", pnginfo=metadata, optimize=True)
        else:
            profile = Path(__file__).with_name("assets").joinpath("sRGB.icc").read_bytes()
            image.convert("RGB").save(path, format="JPEG", quality=95, subsampling=0, optimize=True, icc_profile=profile)
        paths.append(path)
        slide = (f"Карточка {index + 1}/{len(images)}. " if item["language"] == "ru" else f"Karta {index + 1}/{len(images)}. ") if item["format"] == "carousel" else ""
        cover = chart and item['format'] == 'carousel' and index == 0
        files.append({"file_name": path.name, "mime": "image/png" if video else "image/jpeg", "width": 1080, "height": height,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "alt_text": slide + (_alt(snapshot) if cover else description),
                      "chart": None if cover else chart})
    if item["format"] == "video":
        executable = shutil.which("ffmpeg")
        if not executable:
            raise ValueError("Video renderer is unavailable; a storyboard is not a video")
        manifest = directory / f"{key}.concat"
        quoted = [str(path).replace("\\", "/").replace("'", "'\\''") for path in paths]
        manifest.write_text("".join(f"file '{path}'\nduration 3\n" for path in quoted) + f"file '{quoted[-1]}'\n", encoding="utf-8")
        target = directory / f"{key}.mp4"
        subprocess.run([executable, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(manifest),
                        "-r", "25", "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                        "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-flags", "+cgop", "-x264-params", "open-gop=0", "-bf", "0",
                        "-movflags", "+faststart", "-use_editlist", "0", "-an", "-t", str(len(images) * 3), str(target)], check=True, capture_output=True, timeout=90)
        # Static slideshows can compress below LinkedIn's 75 kB minimum. A
        # standard MP4 free-space box preserves the encoded frames and timing.
        missing = 75000 - target.stat().st_size
        if missing > 0:
            padding = max(8, missing)
            with target.open("ab") as output:
                output.write(struct.pack(">I4s", padding, b"free") + bytes(padding - 8))
        return [{"file_name": target.name, "mime": "video/mp4", "width": 1080, "height": height,
                 "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "alt_text": description, "chart": chart,
                 "audio": "none", "captions": "burned_in", "frames": len(images), "duration_seconds": len(images) * 3}]
    return files

"""Vertical website films with recorded motion, narration and phrase captions."""
import json
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def command(args, *, cwd=None, timeout=300):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-2500:])
    return result


def duration(path):
    result = command(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(result.stdout)["format"]["duration"])


def caption_events(text, seconds):
    words = re.sub(r"[{}\\\r\n]", " ", text).split()
    groups, group = [], []
    for word in words:
        if group and (len(" ".join([*group, word])) > 58 or len(group) >= 8):
            groups.append(" ".join(group)); group = []
        group.append(word)
    if group:
        groups.append(" ".join(group))
    total = sum(len(value) for value in groups)
    at, events = 0., []
    for value in groups:
        end = at + seconds * len(value) / total
        events.append((at, end, value))
        at = end
    return events


def _stamp(seconds):
    centiseconds = round(seconds * 100)
    return f"{centiseconds // 360000}:{centiseconds // 6000 % 60:02}:{centiseconds // 100 % 60:02}.{centiseconds % 100:02}"


def _font(size):
    for path in [ROOT / "frontend/src/assets/landing/Manrope.ttf", ROOT / "marketing/assets/Manrope.ttf",
                 Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]:
        if path.exists():
            font = ImageFont.truetype(str(path), size)
            if path.name == "Manrope.ttf":
                font.set_variation_by_axes([600])
            return font
    raise RuntimeError("Install the project brand font")


def _heading(draw, text, y):
    font = _font(82)
    words, lines, line = text.split(), [], ""
    for word in words:
        test = f"{line} {word}".strip()
        if line and draw.textlength(test, font=font) > 920:
            lines.append(line); line = word
        else:
            line = test
    lines.append(line)
    if len(lines) > 3:
        raise ValueError("Headline does not fit the video frame")
    for line in lines:
        draw.text((80, y), line, font=font, fill="#f3f4e9")
        y += 104


def render_scene(scene, audio, footage, folder, index, count):
    folder = Path(folder).resolve()
    seconds = duration(audio) + .35
    if not 2 <= seconds <= 40:
        raise ValueError("Narration scene duration is outside its useful range")
    base = Image.new("RGB", (1080, 1920), "#101e19")
    draw = ImageDraw.Draw(base)
    for x in range(0, 1080, 90):
        draw.line((x, 0, x, 1920), fill="#172a22")
    draw.text((865, 84), f"{index + 1:02} / {count:02}", font=_font(26), fill="#a8b9ad")
    _heading(draw, scene["headline"], 158)
    logo = ROOT / "frontend/public/favicon-96x96.png"
    if logo.exists():
        with Image.open(logo) as icon:
            icon = icon.convert("RGBA").resize((56, 56), Image.Resampling.LANCZOS)
            base.paste(icon, (80, 70), icon)
    draw.text((152 if logo.exists() else 80, 76), "UZStock", font=_font(38), fill="#b5e479")
    draw.rounded_rectangle((66, 518, 1014, 1582), radius=26, fill="#e9eee5")
    draw.text((88, 535), "uzstock.uz", font=_font(22), fill="#244431")
    draw.text((80, 1824), "Откройте uzstock.uz", font=_font(34), fill="#b5e479")
    background = folder / f"background-{index}.png"
    base.save(background)
    captions = folder / f"captions-{index}.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Manrope,44,&H00F3F4E9,&H00F3F4E9,&H00101E19,&H00101E19,0,0,0,0,100,100,0,0,1,2,0,2,90,90,188,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = caption_events(scene["narration"], seconds - .35)
    captions.write_text(header + "\n".join(f"Dialogue: 0,{_stamp(start)},{_stamp(end)},Default,,0,0,0,,{{\\fad(90,90)}}{line}"
                                          for start, end, line in events), encoding="utf-8")
    output = folder / f"scene-{index}.mp4"
    filters = (f"[1:v]scale=916:988:force_original_aspect_ratio=increase,crop=916:988,setsar=1[site];"
               f"[0:v][site]overlay=82:580:shortest=1,ass={captions.name},"
               f"drawbox=x=80:y=1790:w='920':h=3:color=0x344b3d:t=fill,"
               f"fade=t=in:d=0.15,fade=t=out:st={seconds - .15}:d=0.15,fps=30[v]")
    command(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "30", "-i", str(background),
             "-stream_loop", "-1", "-i", str(footage), "-i", str(audio), "-filter_complex_threads", "2",
             "-filter_complex", filters, "-map", "[v]", "-map", "2:a", "-af", "apad=pad_dur=0.35,loudnorm=I=-16:TP=-1.5:LRA=11",
             "-t", str(seconds), "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-threads", "2", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", str(output)], cwd=folder)
    return output


def assemble(storyboard, folder, progress):
    folder = Path(folder).resolve()
    scenes = storyboard["scenes"]
    clips = []
    for index, scene in enumerate(scenes):
        progress("encoding")
        clips.append(render_scene(scene, folder / f"voice-{index}.wav", folder / f"site-{index}.webm", folder, index, len(scenes)))
    manifest = folder / "clips.txt"
    manifest.write_text("\n".join(f"file '{path.name}'" for path in clips), encoding="utf-8")
    output = folder / "uzstock-video.mp4"
    command(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "1", "-i", str(manifest), "-c", "copy",
             "-movflags", "+faststart", str(output)], cwd=folder)
    return output

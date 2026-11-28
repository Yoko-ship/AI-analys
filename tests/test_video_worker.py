"""Local render contract: real motion, narration, readable captions and exports."""
import json
import shutil
import subprocess

import pytest


def test_captions_preserve_text_and_cannot_inject_ass_commands():
    from video_worker.render import caption_events
    text = r"Откройте UZStock. {\\pos(0,0)} Выберите новости и прочитайте материал на сайте."
    events = caption_events(text, 9)
    assert events and events[-1][1] == pytest.approx(9)
    assert all(len(line) <= 90 for _, _, line in events)
    assert "{" not in " ".join(line for _, _, line in events)
    assert "UZStock" in " ".join(line for _, _, line in events)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="Requires local media tools")
def test_render_encodes_full_duration_with_motion_and_audible_narration(tmp_path):
    from video_worker.render import render_scene
    audio, footage = tmp_path / "voice.wav", tmp_path / "site.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=4",
                    str(audio)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=900x1000:rate=30:duration=4",
                    "-c:v", "libx264", "-preset", "ultrafast", str(footage)], check=True)
    output = render_scene({"headline": "Как читать новости?", "narration": "Откройте UZStock и выберите интересующий вас материал."},
                          audio, footage, tmp_path, 0, 3)
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
                            capture_output=True, check=True)
    data = json.loads(result.stdout)
    assert float(data["format"]["duration"]) == pytest.approx(4.35, abs=.08)
    video = next(row for row in data["streams"] if row["codec_type"] == "video")
    assert (video["width"], video["height"], video["avg_frame_rate"]) == (1080, 1920, "30/1")
    assert any(row["codec_type"] == "audio" and row["codec_name"] == "aac" for row in data["streams"])

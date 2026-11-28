"""Media acceptance checks real files and provenance, not a model's filename."""
from datetime import timedelta
import hashlib
import shutil
import subprocess
import json

import pytest
from PIL import Image, ImageDraw

from marketing import content, store
from test_marketing_core import OWNER, NOW, account, candidate, evidence, isolated  # noqa: F401


def test_production_runtime_packages_the_renderer_tools_and_brand_font():
    from pathlib import Path
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split("FROM python:", 1)[1]
    assert "ffmpeg" in runtime
    assert "/app/marketing/assets/Manrope.ttf" in runtime


def media_candidate(**changes):
    account(formats=["image", "carousel", "video", "story"], mode="manual", languages=["ru", "uz"])
    evidence()
    return candidate(format="image", mode="manual", **changes)


@pytest.mark.parametrize("language,body,context", [
    ("ru", "Утверждено 120 сум на простую акцию.", "Утверждено · Простая акция"),
    ("uz", "Oddiy aksiya uchun 120 so‘m dividend tasdiqlandi.", "Tasdiqlangan · Oddiy aksiya"),
])
@pytest.mark.parametrize("format", ["image", "carousel", "story"])
def test_fact_card_is_a_real_readable_file_bound_to_text_and_original_versions(monkeypatch, language, body, context, format):
    from marketing import media
    drawn = []
    original = ImageDraw.ImageDraw.text
    def capture(draw, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original(draw, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    account(formats=[format], mode="manual", languages=["ru", "uz"], platform="instagram" if format == "story" else "telegram")
    evidence()
    item = candidate(format=format, mode="manual", language=language, body=body)
    job = media.request_candidate(OWNER, item["id"], item["version"])
    assert job["status"] == "queued"
    assert media.run_one(NOW)
    with store.connection() as c:
        rendered = store.get(c, "candidate", item["id"])
        asset = store.get(c, "asset", rendered["assets"][0]["id"])
        assert asset["status"] == "ready" and asset["source_versions"] == {"decision": 1}
        assert "120" in asset["alt_text"] and "UZS/share" in asset["alt_text"]
        assert context in asset["alt_text"]
    # The reviewed JPEG must contain the source caption before any upload.
    assert context in drawn
    if format == "story":
        assert body in " ".join(" ".join(drawn).split())
    path = media.asset_path(asset)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
    for ref in rendered["assets"]:
        with store.connection() as c:
            card = store.get(c, "asset", ref["id"])
        assert card["mime"] == "image/jpeg"
        with Image.open(media.asset_path(card)) as image:
            assert image.format == "JPEG" and image.size == (1080, 1920 if format == "story" else 1350)
            assert image.mode == "RGB" and image.info.get("icc_profile")
            image.verify()
    assert content.check_candidate(item["id"], NOW)["status"] == "awaiting_approval"


def test_a_previous_render_contract_is_replaced_before_media_can_be_released(monkeypatch):
    from marketing import media
    item = media_candidate()
    with monkeypatch.context() as previous:
        previous.setattr(media, "RENDER_VERSION", "previous-test-contract", raising=False)
        old = media.request_candidate(OWNER, item["id"], item["version"])
        media.run_one(NOW)
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "needs_revision"
    new = media.request_candidate(OWNER, item["id"], checked["version"])
    assert new["id"] != old["id"]
    media.run_one(NOW)
    assert content.check_candidate(item["id"], NOW)["status"] == "awaiting_approval"


def test_rendered_financial_value_never_rounds_to_six_significant_digits():
    from marketing import media
    account(formats=["image"], mode="draft")
    evidence(data={"dividend": 1234567.89, "dividend_state": "approved", "share_class": "ordinary"})
    item = candidate(format="image", mode="draft", body="Утверждено 1 234 567,89 сум на простую акцию.",
        claims=[{"evidence_id": "decision", "field": "dividend", "value": 1234567.89, "unit": "UZS/share"}])
    media.request_candidate(OWNER, item["id"], item["version"])
    media.run_one(NOW)
    with store.connection() as c:
        asset = store.list_items(c, "asset")[0]
    assert "1234567.89 UZS/share" in asset["alt_text"]


def test_editing_text_or_corrupting_a_file_invalidates_the_media_proof():
    from marketing import media
    item = media_candidate()
    media.request_candidate(OWNER, item["id"], item["version"])
    media.run_one(NOW)
    with store.connection() as c:
        current = store.get(c, "candidate", item["id"])
        asset = store.get(c, "asset", current["assets"][0]["id"])
    content.revise_candidate(OWNER, item["id"], {"body": "Подтверждено 120 сум на простую акцию. Изменён текст."}, current["version"])
    checked = content.check_candidate(item["id"], NOW)
    assert checked["status"] == "needs_revision" and "media" in checked["check"]["reason"].lower()
    media.asset_path(asset).write_bytes(b'not an image')
    assert not media.valid_asset(asset)


def test_renderer_failure_preserves_inputs_and_does_not_create_a_fake_asset():
    from marketing import media
    item = media_candidate()
    job = media.request_candidate(OWNER, item["id"], item["version"])
    def fail(*args, **kwargs):
        raise OSError("private filesystem path must not leak")
    assert media.run_one(NOW, renderer=fail)
    with store.connection() as c:
        failed = store.get(c, "render", job["id"])
        assert failed["status"] == "error" and "private filesystem" not in str(failed)
        assert store.list_items(c, "asset") == []
        assert store.get(c, "candidate", item["id"])["assets"] == []
    media.retry(OWNER, job["id"], failed["version"])
    assert media.run_one(NOW)
    with store.connection() as c:
        assert store.get(c, "render", job["id"])["status"] == "complete"


def test_owner_can_repair_a_missing_file_without_changing_text_or_duplicating_assets():
    from marketing import media
    item = media_candidate()
    media.request_candidate(OWNER, item["id"], item["version"])
    media.run_one(NOW)
    with store.connection() as c:
        current = store.get(c, "candidate", item["id"])
        asset = store.list_items(c, "asset")[0]
    media.asset_path(asset).unlink()
    repaired = media.request_candidate(OWNER, current["id"], current["version"])
    assert repaired["status"] == "queued"
    media.run_one(NOW)
    with store.connection() as c:
        assets = store.list_items(c, "asset")
        assert len(assets) == 1 and media.valid_asset(assets[0])


def test_jpeg_repair_preserves_exact_bytes_when_the_colour_profile_clock_changes(monkeypatch):
    from PIL import ImageCms
    import struct
    from marketing import media
    original = ImageCms.ImageCmsProfile.tobytes
    clock = iter([1, 2, 3, 4])
    def later_profile(profile):
        value = bytearray(original(profile))
        # LittleCMS embeds the creation timestamp at bytes 24..35 of the ICC header.
        value[24:36] = struct.pack(">6H", 2026, 11, 26, 8, 0, next(clock))
        return bytes(value)
    monkeypatch.setattr(ImageCms.ImageCmsProfile, "tobytes", later_profile)
    item = media_candidate()
    media.request_candidate(OWNER, item["id"], item["version"])
    media.run_one(NOW)
    with store.connection() as c:
        current = store.get(c, "candidate", item["id"])
        asset = store.get(c, "asset", current["assets"][0]["id"])
    original_bytes = media.read_asset(asset)
    media.asset_path(asset).unlink()
    media.request_candidate(OWNER, item["id"], current["version"])
    media.run_one(NOW + timedelta(minutes=2))
    with store.connection() as c:
        repaired = store.get(c, "asset", asset["id"])
    assert media.read_asset(repaired) == original_bytes


@pytest.mark.parametrize("language,label", [("ru", "Факт"), ("uz", "Ma’lumot")])
@pytest.mark.parametrize("field", ["feature", "future_source_property"])
def test_unknown_source_keys_do_not_leak_into_visible_or_accessible_card_labels(monkeypatch, language, label, field):
    from marketing import media
    drawn = []
    original = ImageDraw.ImageDraw.text
    def capture(draw, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original(draw, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    account(formats=["image"], mode="draft", languages=[language])
    evidence(data={field: "Сравнение компаний"}, units={})
    item = candidate(format="image", mode="draft", language=language, title="Сравнение компаний", body="Доступно сравнение компаний.",
                     claims=[{"evidence_id": "decision", "field": field, "value": "Сравнение компаний", "unit": ""}])
    media.request_candidate(OWNER, item["id"], item["version"])
    media.run_one(NOW)
    with store.connection() as c:
        rendered = store.get(c, "candidate", item["id"])
        asset = store.get(c, "asset", rendered["assets"][0]["id"])
    assert label in drawn and field not in drawn
    assert label + ":" in asset["alt_text"] and field not in asset["alt_text"]
    assert media.valid_asset(asset)


def test_inflight_render_is_discarded_if_the_owner_changes_the_material():
    from marketing import media, media_renderer
    item = media_candidate()
    job = media.request_candidate(OWNER, item["id"], item["version"])
    def edit_during_render(snapshot, directory, key):
        result = media_renderer.render(snapshot, directory, key)
        with store.connection() as c:
            current = store.get(c, "candidate", item["id"])
        content.revise_candidate(OWNER, item["id"], {"title": "Изменённый заголовок"}, current["version"])
        return result
    media.run_one(NOW, renderer=edit_during_render)
    with store.connection() as c:
        assert store.get(c, "render", job["id"])["status"] == "cancelled"
        assert store.get(c, "candidate", item["id"])["assets"] == []


def test_interrupted_render_recovers_from_saved_inputs_without_duplicate_assets():
    from marketing import media
    item = media_candidate()
    job = media.request_candidate(OWNER, item["id"], item["version"])
    with store.connection(write=True) as c:
        store.put(c, "render", {**job, "status": "running", "claimed_at": NOW.isoformat(), "attempts": 1}, actor=OWNER, action="test_interruption", expected_version=job["version"])
    assert media.recover(NOW + timedelta(minutes=20)) == 1
    assert media.run_one(NOW + timedelta(minutes=20))
    assert not media.run_one(NOW + timedelta(minutes=21))
    with store.connection() as c:
        assert len(store.list_items(c, "asset")) == 1


@pytest.mark.parametrize("format", ["image", "story", "carousel"])
def test_chart_keeps_the_exact_exported_series_and_labels_a_zero_based_scale(monkeypatch, format):
    from marketing import media
    drawn = []
    original = ImageDraw.ImageDraw.text
    def capture(draw, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original(draw, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    account(formats=[format], mode="draft", rubrics=["chart"], platform='instagram' if format == 'story' else 'telegram')
    series = [{"date": "2026-11-19", "value": 120}, {"date": "2026-11-20", "value": 100}, {"date": "2026-11-21", "value": 110}]
    evidence(data={"close": series}, units={"close": "UZS/share"})
    item = candidate(rubric="chart", format=format, mode="draft", title="Как менялась цена?", body="Цена за выбранные даты, без прогноза.", claims=[])
    job = media.request_candidate(OWNER, item["id"], item["version"], chart={"evidence_id": "decision", "field": "close"})
    media.run_one(NOW)
    with store.connection() as c:
        assets = store.list_items(c, "asset")
    assert len(assets) == (2 if format == 'carousel' else 1)
    chart_assets = [asset for asset in assets if asset.get('chart')]
    assert len(chart_assets) == 1
    asset = chart_assets[0]
    if format == 'carousel':
        cover, = [asset for asset in assets if not asset.get('chart')]
        assert 'Шкала:' not in cover['alt_text']
    assert asset["chart"]["series"] == series
    assert asset["chart"]["axis_min"] == 0 and asset["chart"]["unit"] == "UZS/share"
    assert "2026-11-20,100" in media.asset_csv(asset)
    checked = content.check_candidate(item['id'], NOW)
    assert checked['check']['passed'], checked['check']['reason']
    if format == "story":
        assert item["body"] in " ".join(" ".join(drawn).split())


def test_a_generic_fact_card_cannot_substitute_for_a_chart_but_the_owner_can_render_the_source_series():
    from marketing import media
    account(formats=['image'], mode='manual', rubrics=['news', 'chart'])
    series = [{'date': '2026-11-19', 'value': 120}, {'date': '2026-11-20', 'value': 100}]
    evidence(data={'close': series}, units={'close': 'UZS/share'})
    copy = dict(format='image', mode='manual', title='Как менялась цена?', body='Цена за выбранные даты, без прогноза.', claims=[])
    card = candidate('plain-card', **copy)
    media.request_candidate(OWNER, card['id'], card['version'])
    media.run_one(NOW)
    with store.connection() as c:
        rendered = store.get(c, 'candidate', card['id'])
    chart = candidate('chart-with-generic-card', rubric='chart', assets=rendered['assets'], **copy)
    checked = content.check_candidate(chart['id'], NOW)
    assert not checked['check']['passed']
    assert 'chart' in checked['check']['reason'].lower()
    media.request_candidate(OWNER, chart['id'], checked['version'], chart={'evidence_id': 'decision', 'field': 'close'})
    assert media.run_one(NOW)
    repaired = content.check_candidate(chart['id'], NOW)
    assert repaired['check']['passed'], repaired['check']['reason']
    assert repaired['status'] == 'awaiting_approval'


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="Video tool is not installed")
def test_video_render_creates_a_real_mp4_with_burned_in_source_captions():
    from marketing import media
    account(formats=["video"], mode="draft")
    facts = {"dividend": 120, "revenue": 1234567.89, "net_income": 150000, "total_assets": 6543210}
    units = {key: "UZS/share" if key == "dividend" else "UZS" for key in facts}
    evidence(data={**facts, "dividend_state": "approved", "share_class": "ordinary"}, units=units)
    item = candidate(format="video", mode="draft", body="Утверждён дивиденд 120 UZS на простую акцию. Выручка 1234567.89 UZS, прибыль 150000 UZS, активы 6543210 UZS.",
                     claims=[{"evidence_id": "decision", "field": key, "value": value, "unit": units[key]} for key, value in facts.items()])
    media.request_candidate(OWNER, item["id"], item["version"])
    media.run_one(NOW)
    with store.connection() as c:
        asset = store.list_items(c, "asset")[0]
    assert asset["mime"] == "video/mp4" and "120" in asset["alt_text"]
    assert len(media.read_asset(asset)) >= 75000  # LinkedIn's minimum MP4 size also applies to static slideshows.
    result = subprocess.run([shutil.which("ffprobe"), "-v", "trace", "-show_streams", "-show_format", "-of", "json", str(media.asset_path(asset))], check=True, capture_output=True, text=True)
    assert "type:'edts'" not in result.stderr and "type:'elst'" not in result.stderr
    assert 0 <= result.stderr.index("type:'moov'") < result.stderr.index("type:'mdat'")
    metadata = json.loads(result.stdout)
    assert asset["frames"] == 3  # cover + two fact slides, including the fourth metric
    assert float(metadata["format"]["duration"]) == pytest.approx(9, abs=0.05)
    assert metadata["streams"][0]["width"] == 1080 and metadata["streams"][0]["height"] == 1920
    stream = metadata["streams"][0]
    assert stream["codec_name"] == "h264" and stream["pix_fmt"] == "yuv420p" and stream["field_order"] == "progressive"
    assert stream["avg_frame_rate"] == stream["r_frame_rate"] == "25/1"
    frames = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
        "-show_frames", "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(media.asset_path(asset))],
        check=True, capture_output=True, text=True)
    keys = [float(frame["best_effort_timestamp_time"]) for frame in json.loads(frames.stdout)["frames"]]
    assert keys[0] == 0 and all(2 <= right - left <= 5 for left, right in zip(keys, keys[1:]))
    assert max(right - left for left, right in zip(keys, keys[1:] + [float(metadata["format"]["duration"])])) <= 5


def test_chart_rejects_future_observations_instead_of_rendering_a_forecast_as_fact():
    from marketing import media
    account(formats=["image"], mode="draft")
    evidence(data={"close": [{"date": "2026-11-22", "value": 100}, {"date": "2026-12-01", "value": 120}]}, units={"close": "UZS/share"})
    item = candidate(format="image", mode="draft", body="Цена за выбранный период.", claims=[])
    job = media.request_candidate(OWNER, item["id"], item["version"], chart={"evidence_id": "decision", "field": "close"})
    media.run_one(NOW)
    with store.connection() as c:
        assert store.get(c, "render", job["id"])["status"] == "error"
        assert not store.list_items(c, "asset")

"""A feed's thumbnail is not the picture — take the original the CMS keeps one name away.

uza.uz ships `…_small.jpg` at 320×213 in its RSS and serves `…_normal.jpg` at 1024×682 from
the same path; spot.uz ships `…_b.jpg` at 680×453 against `…_l.jpg` at 1200×800. Stretched
across a ~950px article column the 320px one is visibly soft, which is what a reader sees.

The rewrite is a per-source rule, and the point of these is that it is never trusted: the
candidate has to exist and be an image before it replaces anything, so the day a CMS renames
its derivatives we fall back to the thumbnail instead of serving a 404.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import news_collector as nc
import collectors.news.images as collectors_news_images


UZA = {"id": "uza", "image_upgrade": {"from": r"_small(\.[a-z]{3,4})$", "to": r"_normal\1"}}
SMALL = "https://cdn.uza.uz/2026/08/07/15/14/BHsTYKW_small.jpg"
BIG = "https://cdn.uza.uz/2026/08/07/15/14/BHsTYKW_normal.jpg"


class _Resp:
    def __init__(self, status=200, ctype="image/jpeg"):
        self.status_code = status
        self.headers = {"content-type": ctype}

    def close(self):
        pass


@pytest.fixture()
def head(monkeypatch):
    """Serve one verification response, and record what was asked for."""
    asked: list[str] = []

    def _serve(resp):
        def _head(self, url, **kw):
            asked.append(url)
            return resp
        monkeypatch.setattr(nc.requests.Session, "head", _head)
        return asked
    return _serve


def test_the_thumbnail_is_replaced_by_the_original(head):
    asked = head(_Resp())
    assert collectors_news_images._upgrade_image(nc.requests.Session(), SMALL, UZA) == BIG
    assert asked == [BIG]


def test_a_missing_original_leaves_the_thumbnail_alone(head):
    head(_Resp(status=404, ctype="text/html"))
    assert collectors_news_images._upgrade_image(nc.requests.Session(), SMALL, UZA) == SMALL


def test_an_html_error_page_answering_200_is_not_an_image(head):
    """A CMS that serves its 'not found' page at 200 must not become the article's picture."""
    head(_Resp(status=200, ctype="text/html; charset=utf-8"))
    assert collectors_news_images._upgrade_image(nc.requests.Session(), SMALL, UZA) == SMALL


def test_a_url_the_rule_does_not_match_is_never_verified(head):
    asked = head(_Resp())
    other = "https://cdn.uza.uz/2026/08/07/x_normal.jpg"

    assert collectors_news_images._upgrade_image(nc.requests.Session(), other, UZA) == other
    assert asked == [], "no request should be made when the rewrite is a no-op"


def test_a_source_with_no_rule_is_left_alone(head):
    asked = head(_Resp())
    assert collectors_news_images._upgrade_image(nc.requests.Session(), SMALL, {"id": "kursiv"}) == SMALL
    assert asked == []


def test_a_network_failure_keeps_the_thumbnail(monkeypatch):
    def _boom(self, url, **kw):
        raise nc.requests.ConnectionError("down")

    monkeypatch.setattr(nc.requests.Session, "head", _boom)
    assert collectors_news_images._upgrade_image(nc.requests.Session(), SMALL, UZA) == SMALL


def test_the_pass_rewrites_in_place_and_counts(monkeypatch):
    monkeypatch.setattr(collectors_news_images, "_upgrade_image",
                        lambda s, url, src: url.replace("_small.", "_normal."))
    items = [{"source_id": "uza", "image_url": SMALL},
             {"source_id": "uza", "image_url": BIG},          # already upgraded
             {"source_id": "kursiv", "image_url": SMALL},     # no rule for this source
             {"source_id": "uza", "image_url": None}]         # nothing to upgrade

    n = collectors_news_images.upgrade_images(items, {"uza": UZA, "kursiv": {"id": "kursiv"}})

    assert n == 1
    assert items[0]["image_url"] == BIG
    assert items[2]["image_url"] == SMALL


class TestTheRulesInTheRegistry:
    REGISTRY = json.loads((Path(nc.__file__).resolve().parent / "news_sources.json")
                          .read_text(encoding="utf-8"))["sources"]

    @pytest.mark.parametrize("source_id, before, after", [
        ("uza", "https://cdn.uza.uz/a/b/XYZ_small.jpg", "https://cdn.uza.uz/a/b/XYZ_normal.jpg"),
        ("spot", "https://www.spot.uz/media/img/2026/08/aB1_b.jpg",
         "https://www.spot.uz/media/img/2026/08/aB1_l.jpg"),
        # spot serves webp too, and the rule has to carry the extension across.
        ("spot", "https://www.spot.uz/media/img/2026/08/aB1_b.webp",
         "https://www.spot.uz/media/img/2026/08/aB1_l.webp"),
    ])
    def test_the_declared_rewrites_produce_the_measured_urls(self, source_id, before, after):
        import re
        rule = next(s for s in self.REGISTRY if s["id"] == source_id)["image_upgrade"]
        assert re.sub(rule["from"], rule["to"], before) == after

    def test_a_rule_never_fires_twice(self):
        """Re-running the pass over an already-upgraded row must be a no-op, not a mangle."""
        import re
        for source_id, upgraded in (("uza", "https://cdn.uza.uz/a/XYZ_normal.jpg"),
                                    ("spot", "https://www.spot.uz/media/img/a_l.jpg")):
            rule = next(s for s in self.REGISTRY if s["id"] == source_id)["image_upgrade"]
            assert re.sub(rule["from"], rule["to"], upgraded) == upgraded

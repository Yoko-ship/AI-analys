"""The server never fetches a URL it did not write from an address nobody outside may reach.

Article pages and images come from feeds and search results; a hostile one (or a redirect
from it) could name 127.0.0.1, the Docker network or the metadata address 169.254.169.254.
The news collector followed such URLs blindly and read whole bodies before cutting them;
admin documents and issuer registration each had a check of their own. public_fetch is the
one rule, and these hold it to the addresses it must refuse and the ones it must let through.
No test resolves or connects for real: resolvers and sessions are injected.
"""
from __future__ import annotations

import socket

import pytest

import public_fetch
import collectors.news.articles as news_articles
import collectors.news.images as news_images
from admin_control import documents as admin_documents
from admin_control.store import ControlError

PUBLIC = "93.184.216.34"


def _resolver(table: dict[str, list[str]]):
    def resolve(host, port, **kw):
        if host not in table:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
                for a in table[host]]
    return resolve


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "172.17.0.1", "192.168.1.1", "100.64.0.1",  # loopback, private, CGNAT
    "169.254.169.254",                                                  # cloud metadata
    "0.0.0.0", "224.0.0.1", "::1", "fd00::1", "fe80::1",                 # unspecified, multicast, v6
    "::ffff:10.0.0.5", "2002:0a00:0005::1",                             # private v4 inside v6
])
def test_non_public_addresses_are_refused(address) -> None:
    with pytest.raises(public_fetch.FetchRefused) as refused:
        public_fetch.check_url("https://news.example/a", resolver=_resolver({"news.example": [address]}))
    assert refused.value.code == "NOT_PUBLIC"


def test_one_private_answer_among_public_ones_is_enough_to_refuse() -> None:
    resolver = _resolver({"news.example": [PUBLIC, "10.0.0.5"]})
    with pytest.raises(public_fetch.FetchRefused):
        public_fetch.check_url("https://news.example/a", resolver=resolver)


@pytest.mark.parametrize("url", ["https://news.example/a", "http://news.example:8080/a"])
def test_a_public_host_passes(url) -> None:
    public_fetch.check_url(url, resolver=_resolver({"news.example": [PUBLIC, "2606:2800:220:1::248"]}))


@pytest.mark.parametrize("url,code", [
    ("file:///etc/passwd", "SCHEME_NOT_ALLOWED"), ("gopher://news.example/", "SCHEME_NOT_ALLOWED"),
    ("https://user:pw@news.example/", "CREDENTIALS_IN_URL"), ("https://nowhere.invalid/", "UNRESOLVED"),
])
def test_other_urls_that_must_not_be_fetched(url, code) -> None:
    with pytest.raises(public_fetch.FetchRefused) as refused:
        public_fetch.check_url(url, resolver=_resolver({"news.example": [PUBLIC]}))
    assert refused.value.code == code


class _Response:
    def __init__(self, status=200, body=b"", location=None):
        self.status_code = status
        self.is_redirect = location is not None
        self.headers = {"Location": location} if location else {}
        self.encoding = "utf-8"
        self._body = body
        self.closed = False

    def iter_content(self, size):
        for start in range(0, len(self._body), size):
            yield self._body[start:start + size]

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, routes):
        self.routes, self.asked = routes, []

    def request(self, method, url, **kw):
        self.asked.append(url)
        return self.routes[url]


RESOLVE = _resolver({"news.example": [PUBLIC], "cdn.example": [PUBLIC], "internal.example": ["10.0.0.5"]})


def _check(url):
    public_fetch.check_url(url, resolver=RESOLVE)


def test_a_redirect_into_a_private_address_is_refused_before_it_is_followed() -> None:
    session = _Session({"https://news.example/a": _Response(302, location="http://internal.example/admin")})
    with pytest.raises(public_fetch.FetchRefused):
        public_fetch.fetch(session, "https://news.example/a", max_bytes=1000, timeout=5, check=_check)
    assert session.asked == ["https://news.example/a"]


def test_a_redirect_to_a_public_host_is_followed() -> None:
    session = _Session({"https://news.example/a": _Response(301, location="https://cdn.example/b"),
                        "https://cdn.example/b": _Response(200, b"<p>story</p>")})
    got = public_fetch.fetch(session, "https://news.example/a", max_bytes=1000, timeout=5, check=_check)
    assert got.content == b"<p>story</p>" and got.url == "https://cdn.example/b"


def test_endless_redirects_stop() -> None:
    session = _Session({"https://news.example/a": _Response(302, location="https://news.example/a")})
    with pytest.raises(public_fetch.FetchRefused) as refused:
        public_fetch.fetch(session, "https://news.example/a", max_bytes=1000, timeout=5, check=_check)
    assert refused.value.code == "TOO_MANY_REDIRECTS"


def test_an_oversized_body_stops_at_the_cap() -> None:
    big = _Response(200, b"x" * 300_000)
    with pytest.raises(public_fetch.BodyTooLarge):
        public_fetch.fetch(_Session({"https://news.example/a": big}), "https://news.example/a",
                           max_bytes=100_000, timeout=5, check=_check)
    assert big.closed
    kept = public_fetch.fetch(_Session({"https://news.example/a": _Response(200, b"x" * 300_000)}),
                              "https://news.example/a", max_bytes=100_000, timeout=5, truncate=True, check=_check)
    assert len(kept.content) == 100_000 and kept.truncated


class TestNewsCollector:
    @pytest.fixture(autouse=True)
    def dns(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", RESOLVE)

    def test_an_article_url_naming_a_private_host_is_never_requested(self) -> None:
        session = _Session({})
        assert news_articles._article_text(session, "http://internal.example/latest") == ""
        assert session.asked == []

    def test_a_page_image_redirecting_inside_is_refused(self) -> None:
        session = _Session({"https://news.example/a": _Response(302, location="http://internal.example/")})
        assert news_images._og_image(session, "https://news.example/a") is None
        assert session.asked == ["https://news.example/a"]

    def test_a_public_page_still_yields_its_image(self) -> None:
        head = b'<html><head><meta property="og:image" content="https://cdn.example/photo.jpg"></head>'
        session = _Session({"https://news.example/a": _Response(200, head + b"<body>" + b"x" * 500_000)})
        assert news_images._og_image(session, "https://news.example/a") == "https://cdn.example/photo.jpg"


class TestAdminDocuments:
    def test_an_approved_host_resolving_privately_is_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _resolver({"openinfo.uz": ["10.0.0.5"]}))
        with pytest.raises(ControlError) as refused:
            admin_documents.validate_source_url("https://openinfo.uz/doc.pdf")
        assert (refused.value.code, refused.value.status) == ("SOURCE_NOT_ALLOWED", 422)

    def test_an_unresolvable_host_is_unavailable_not_forbidden(self, monkeypatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _resolver({}))
        with pytest.raises(ControlError) as refused:
            admin_documents.validate_source_url("https://openinfo.uz/doc.pdf")
        assert (refused.value.code, refused.value.status) == ("SOURCE_UNAVAILABLE", 503)

    def test_a_public_approved_host_passes(self, monkeypatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _resolver({"openinfo.uz": [PUBLIC]}))
        admin_documents.validate_source_url("https://openinfo.uz/doc.pdf")

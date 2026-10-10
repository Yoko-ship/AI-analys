"""The offline IP → place lookup: placing, refusing, and keeping the file current."""
import time
from datetime import date

import geoip


class _Reader:
    def __init__(self, records):
        self.records = records

    def get(self, ip):
        return self.records.get(ip)

    def close(self):
        pass


RECORD = {
    "country": {"iso_code": "uz", "names": {"en": "Uzbekistan"}},
    "subdivisions": [{"names": {"en": "Samarqand Region"}}],
    "city": {"names": {"en": "Samarkand"}},
}


def test_a_public_ip_is_placed(monkeypatch):
    monkeypatch.setattr(geoip, "_current_reader", lambda: _Reader({"84.54.70.1": RECORD}))
    assert geoip.lookup("84.54.70.1") == {"country": "UZ", "region": "Samarqand Region", "city": "Samarkand"}


def test_private_unknown_and_missing_database_answer_none(monkeypatch):
    monkeypatch.setattr(geoip, "_current_reader", lambda: _Reader({}))
    assert geoip.lookup("10.0.0.7") is None          # private: never looked up
    assert geoip.lookup("172.18.0.1") is None        # docker bridge
    assert geoip.lookup("not an ip") is None
    assert geoip.lookup("8.8.8.8") is None           # not in the file
    monkeypatch.setattr(geoip, "_current_reader", lambda: None)
    assert geoip.lookup("84.54.70.1") is None        # no file yet


def test_a_partial_record_keeps_what_it_has(monkeypatch):
    monkeypatch.setattr(geoip, "_current_reader",
                        lambda: _Reader({"84.54.70.1": {"country": {"iso_code": "UZ"}}}))
    assert geoip.lookup("84.54.70.1") == {"country": "UZ", "region": None, "city": None}


def test_refresh_downloads_when_missing_and_falls_back_a_month(tmp_path):
    target = tmp_path / "geoip" / "city.mmdb"
    tried = []

    def download(url, path):
        tried.append(url)
        if "2026-10" in url:
            raise RuntimeError("not published yet")
        path.write_bytes(b"db")

    assert geoip.ensure_database(target, today=date(2026, 10, 1), download=download) is True
    assert [u.rsplit("-", 2)[-2:] for u in tried] == [["2026", "10.mmdb.gz"], ["2026", "09.mmdb.gz"]]
    assert target.read_bytes() == b"db"
    assert not target.with_name("city.mmdb.lock").exists()


def test_a_fresh_file_is_not_downloaded_again(tmp_path):
    target = tmp_path / "city.mmdb"
    target.write_bytes(b"db")
    called = []
    assert geoip.ensure_database(target, download=lambda url, path: called.append(url)) is True
    assert not called
    assert geoip.needs_refresh(target, now=time.time() + 40 * 86400) is True


def test_another_worker_holding_the_lock_is_left_alone(tmp_path):
    target = tmp_path / "city.mmdb"
    target.with_name("city.mmdb.lock").write_text("")
    called = []
    assert geoip.ensure_database(target, download=lambda url, path: called.append(url)) is False
    assert not called


def test_january_falls_back_to_last_december():
    assert geoip._months_to_try(date(2027, 1, 1)) == ["2027-01", "2026-12"]

"""Bounded, read-only UZSE connection checks; never print credentials."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.request


BASE = "https://uzse.uz"
FEED = "/trade_results/?page=1"
QUOTE = "/isu_infos/STK?isu_cd=UZ7001100005&locale=ru"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def probe(name: str, url: str, *, direct: bool = False) -> dict:
    started = time.monotonic()
    result = {"name": name, "direct": direct}
    headers = {"User-Agent": UA,
               "Accept": "application/json" if "trade_results" in url else "text/html,application/xhtml+xml"}
    try:
        try:
            import requests
        except ImportError:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}) if direct
                                                else urllib.request.ProxyHandler())
            try:
                response = opener.open(urllib.request.Request(url, headers=headers), timeout=15)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status, response_headers = response.code, response.headers
                body = response.read(1024 * 1024)
            result["client"] = "urllib"
        else:
            with requests.Session() as session:
                session.trust_env = not direct
                response = session.get(url, headers=headers, timeout=15)
                status, response_headers, body = response.status_code, response.headers, response.content
            result["client"] = "requests"
        result.update(status=status, server=response_headers.get("Server"),
                      content_type=response_headers.get("Content-Type"), bytes=len(body),
                      body_sha256=hashlib.sha256(body).hexdigest(),
                      gateway_headers=[key for key in response_headers
                                       if key.lower().startswith(("x-", "via"))])
        if status == 200 and "trade_results" in url:
            payload = json.loads(body)
            rows = payload.get("results") if isinstance(payload, dict) else None
            result.update(feed_valid=isinstance(rows, list), rows=len(rows or []),
                          days=sorted({str(row.get("trade_date")) for row in (rows or [])}))
        elif status == 200 and "isu_infos" in url:
            result["security_present"] = b"UZ7001100005" in body
            result["history_present"] = "Цена закрытия".encode() in body
        elif status != 200:
            title = re.search(rb"<title[^>]*>([^<]*)</title>", body, re.I)
            if title:
                result["error_title"] = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[address]",
                                               title[1].decode("utf-8", "replace")[:120])
    except Exception as error:
        # Exception messages can contain authenticated proxy URLs. Type only.
        result["error_type"] = type(error).__name__
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    print(json.dumps(result, ensure_ascii=True), flush=True)
    time.sleep(1)
    return result


def main() -> None:
    proxy_keys = [key for key in os.environ if key.lower() in
                  {"http_proxy", "https_proxy", "all_proxy", "no_proxy"} and os.environ[key]]
    dns = {}
    for host in ("uzse.uz", "www.uzse.uz"):
        try:
            dns[host] = sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443)})
        except OSError:
            dns[host] = "resolution_failed"
    hosts = Path("/etc/hosts")
    print(json.dumps({"proxy_setting_names": proxy_keys, "source_dns": dns,
                      "source_hosts_override": bool(hosts.exists() and
                                                     re.search(r"\buzse\.uz\b", hosts.read_text()))}), flush=True)
    feed = probe("configured_feed", BASE + FEED)
    probe("configured_quote", BASE + QUOTE)
    if not feed.get("feed_valid"):
        probe("direct_feed", BASE + FEED, direct=True)
        probe("canonical_www_feed", "https://www.uzse.uz" + FEED, direct=True)
        probe("direct_home", BASE + "/", direct=True)


if __name__ == "__main__":
    main()

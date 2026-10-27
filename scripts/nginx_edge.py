#!/usr/bin/env python3
"""The edge of uzstock.uz as the VPS's nginx sees it: who the client is, and how
fast one client may go.

Topology: browser → the hosting provider's OpenResty (TLS, outside the VPS) →
nginx on the VPS → uvicorn (one worker). Every request therefore reaches nginx
from the provider's proxy, so ``$remote_addr`` is the proxy, not the visitor.
A per-client limit keyed on that address would be one bucket for the whole
site — the first busy minute would throttle everyone. So this module owns both
halves and refuses to switch the limit on until it has seen them work:

* realip: trust ``X-Forwarded-For`` only from ``TRUSTED_EDGE`` (our side of the
  provider's network), walking it from the right, so ``$remote_addr`` becomes
  the visitor. Entries a client wrote itself are never reached: the edge
  appends the real address after them.
* limit_req: ``RATE_PER_SECOND`` with a ``BURST`` allowance per visitor address,
  answered with 429. Loopback (the deploy's own probes, the SSH-tunnelled smoke
  test) is never limited.
* the probe: after a reload, the deploy asks the live site — over the public
  route, through the provider's proxy — what nginx saw. Only when nginx resolved
  a visitor address different from the proxy's does the limit get a key. If the
  proxy's address is outside ``TRUSTED_EDGE`` the limit stays keyless (off) and
  the deploy warns with the address to add.
* canonical host: the provider must enable public TLS for ``www.uzstock.uz``
  and forward it to this origin over HTTP, preserving the Host header. The
  origin redirects that alias to the primary HTTPS domain, retaining the path
  and query. A public TLS rejection must be fixed at the provider, not here.

The rate and burst are held to real browser traffic in
``tests/test_nginx_edge.py`` (recorded page loads in
``tests/fixtures/browser_request_bursts.json``): a cold mobile load of /market
issues 81 requests in one second. Several visitors behind one mobile-carrier
NAT share an address, so the allowance covers three such loads at once.

Run on the VPS by the deploy (stdlib only — it runs on the host, not the image):

    python3 scripts/nginx_edge.py write    # render, nginx -t, restore on failure
    python3 scripts/nginx_edge.py probe    # after reload: verify, switch the limit
    python3 scripts/nginx_edge.py render DIR   # CI: write both files for nginx -t
"""
from __future__ import annotations

import ipaddress
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Addresses only something inside the provider's network can connect from. The
# provider's proxy reaches the VPS from one of these (the public address is the
# provider's, NATed: SSH and HTTPS share it). If the probe reports the proxy
# from a public address, add exactly that address here, not a wider range.
TRUSTED_EDGE = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "::1/128",
    "fc00::/7",
)

RATE_PER_SECOND = 30
BURST = 400
ZONE = "uzstock_per_client"

PUBLIC_ORIGIN = "https://uzstock.uz"
PROBE_PATH = "/__uzstock/edge-probe"
PROBE_HEADER = "X-UZStock-Edge-Probe"

HTTP_CONF = Path("/etc/nginx/conf.d/uzstock-edge.conf")
# Keeps the Netdata-era name: the live site config includes it by that name.
SERVER_SNIPPET = Path("/etc/nginx/snippets/uzstock-monitor.conf")
STATE_FILE = Path("/root/uzstock/nginx-edge.json")
TOKEN_FILE = Path("/root/uzstock/.nginx-edge-probe-token")

_HEADER = "# Managed by scripts/nginx_edge.py and rewritten on every deploy. Edit it there.\n"


def http_conf(limited: bool, trusted: tuple[str, ...] = TRUSTED_EDGE) -> str:
    """The http-context half: realip, and the zone the limit counts in."""
    for cidr in trusted:
        ipaddress.ip_network(cidr)  # a typo must fail here, not as a live nginx error
    realip = "".join(f"set_real_ip_from {cidr};\n" for cidr in trusted)
    # An empty key is never counted, so "not limited" is the same zone with no key.
    key = "$binary_remote_addr" if limited else '""'
    return (
        _HEADER
        + realip
        + "real_ip_header X-Forwarded-For;\n"
        + "real_ip_recursive on;\n\n"
        + "geo $uzstock_limit_exempt {\n    default 0;\n    127.0.0.0/8 1;\n    ::1 1;\n}\n"
        + "map $uzstock_limit_exempt $uzstock_limit_key {\n"
        + f'    1 "";\n    default {key};\n}}\n'
        + f"limit_req_zone $uzstock_limit_key zone={ZONE}:10m rate={RATE_PER_SECOND}r/s;\n"
        + "\n# The provider owns public TLS; this is its HTTP origin.\n"
        + "server {\n    listen 80;\n    listen [::]:80;\n"
        + "    server_name www.uzstock.uz;\n"
        + f"    return 301 {PUBLIC_ORIGIN}$request_uri;\n}}\n"
    )


def server_snippet(probe_token: str) -> str:
    """The server-block half: compression, the limit, and the probe location."""
    if not probe_token.isalnum():
        raise ValueError("probe token must be alphanumeric")
    return (
        _HEADER
        + "# The provider's proxy passes compressed responses through\n"
        + "# (verified 2026-09-23: 40/40 gzip requests returned 200), so compress here.\n"
        + "gzip on;\ngzip_vary on;\ngzip_proxied any;\ngzip_comp_level 5;\ngzip_min_length 1024;\n"
        + "gzip_types text/plain text/css text/javascript application/javascript"
        + " application/json application/xml image/svg+xml;\n\n"
        + f"limit_req zone={ZONE} burst={BURST} nodelay;\n"
        + "limit_req_status 429;\nlimit_req_log_level warn;\n\n"
        + f"location = {PROBE_PATH} {{\n"
        + f'    if ($http_{PROBE_HEADER.lower().replace("-", "_")} != "{probe_token}") {{\n'
        + "        return 404;\n    }\n"
        + "    default_type text/plain;\n"
        + '    return 200 "$realip_remote_addr $remote_addr\\n";\n'
        + "}\n"
    )


def judge_probe(body: str | None) -> tuple[str, str]:
    """``(verdict, peer)`` from the probe's ``"<peer> <client>"`` answer.

    verified      nginx replaced the proxy's address with the visitor's
    unresolved    nginx still sees the proxy as the client — limiting would be
                  one shared bucket; the proxy's address is not trusted
    inconclusive  no answer, or it did not come through the proxy at all
    """
    parts = (body or "").split()
    if len(parts) != 2:
        return "inconclusive", ""
    peer, client = parts
    try:
        if ipaddress.ip_address(peer).is_loopback:
            return "inconclusive", peer  # resolved to this host, skipping the edge
    except ValueError:
        return "inconclusive", ""
    return ("unresolved" if peer == client else "verified"), peer


def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _token() -> str:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token.isalnum():
            return token
    except OSError:
        pass
    token = secrets.token_hex(24)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    TOKEN_FILE.chmod(0o600)
    return token


def _nginx_test() -> tuple[bool, str]:
    run = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    return run.returncode == 0, (run.stderr or run.stdout).strip()


def _install(limited: bool) -> bool:
    """Write both files and prove nginx accepts them; restore the old ones if not."""
    previous = {path: path.read_text(encoding="utf-8") if path.exists() else None
                for path in (HTTP_CONF, SERVER_SNIPPET)}
    HTTP_CONF.write_text(http_conf(limited), encoding="utf-8")
    SERVER_SNIPPET.write_text(server_snippet(_token()), encoding="utf-8")
    ok, output = _nginx_test()
    if ok:
        return True
    for path, text in previous.items():
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text, encoding="utf-8")
    print(f"::warning::nginx rejected the edge configuration; the previous one is restored. {output}")
    return False


def _reload() -> None:
    subprocess.run(["systemctl", "reload", "nginx"], check=True)


def _probe_once(token: str) -> str | None:
    request = urllib.request.Request(PUBLIC_ORIGIN + PROBE_PATH, headers={PROBE_HEADER: token})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read(200).decode("ascii", "replace")
    except Exception as exc:  # the public route is known to stall; that is "no answer"
        print(f"edge probe: no answer ({exc.__class__.__name__}: {exc})")
        return None


def write() -> int:
    return 0 if _install(bool(_read_state().get("limited"))) else 1


def probe() -> int:
    state = _read_state()
    was_limited = bool(state.get("limited"))
    verdict, peer = "inconclusive", ""
    for attempt in range(3):
        if attempt:
            time.sleep(5)
        verdict, peer = judge_probe(_probe_once(_token()))
        if verdict != "inconclusive":
            break
    limited = {"verified": True, "unresolved": False}.get(verdict, was_limited)
    print(f"edge probe: {verdict} (proxy {peer or 'unknown'}); per-client limit "
          f"{'on' if limited else 'off'}, {RATE_PER_SECOND} r/s, burst {BURST}")
    if verdict == "unresolved":
        print(f"::warning::nginx sees the provider's proxy ({peer}) as the client, so the "
              f"per-client limit is off. Add {peer} to TRUSTED_EDGE in scripts/nginx_edge.py.")
    elif verdict == "inconclusive":
        print("::warning::The edge probe got no answer over the public route; the per-client "
              f"limit keeps its previous state ({'on' if limited else 'off'}).")
    if limited != was_limited:
        if not _install(limited):
            return 1
        _reload()
    STATE_FILE.write_text(json.dumps({"limited": limited, "verdict": verdict, "proxy": peer,
                                      "checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}),
                          encoding="utf-8")
    return 0


def render(directory: str) -> int:
    out = Path(directory)
    (out / "uzstock-edge.conf").write_text(http_conf(limited=True), encoding="utf-8")
    (out / "uzstock-monitor.conf").write_text(server_snippet(os.environ.get("PROBE_TOKEN", "ci")),
                                              encoding="utf-8")
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "write":
        sys.exit(write())
    if command == "probe":
        sys.exit(probe())
    if command == "render" and len(sys.argv) == 3:
        sys.exit(render(sys.argv[2]))
    sys.exit("usage: nginx_edge.py write | probe | render DIR")

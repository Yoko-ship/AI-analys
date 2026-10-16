"""Fetching a URL somebody else chose, without reaching anything private.

The server fetches URLs it did not write: article pages and images named by news
feeds and search results, issuer documents an operator pasted in. Followed
blindly, such a URL (or a redirect from it) can point at 127.0.0.1, the Docker
network, or the cloud metadata address 169.254.169.254, and the server would
fetch from inside what nobody outside may reach. Three places guarded this on
their own (admin documents, issuer registration) or not at all (the news
collector), so this module is the one rule:

* only http(s), no credentials in the URL, a host name present;
* every address the host resolves to (IPv4 and IPv6) must be globally routable:
  no private, loopback, link-local (the metadata address), shared, reserved or
  multicast range, and no IPv4 hidden inside an IPv6 address;
* redirects are followed by hand, and each hop is checked again;
* the body is streamed and stops at a byte ceiling instead of being read whole.

Known limit: the address is checked before requests resolves the host again to
connect, so a host that changes its DNS answer between the two (DNS rebinding)
is not caught. Closing that needs a connection pinned to the checked address.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlsplit


class FetchRefused(ValueError):
    """The URL, or a redirect it led to, is not one the server may fetch."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BodyTooLarge(FetchRefused):
    pass


Resolver = Callable[..., Iterable[Any]]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is not None and not _is_public(str(embedded)):
            return False
    return ip.is_global and not ip.is_multicast


def require_public_host(host: str, port: int, resolver: Resolver | None = None) -> None:
    """Every address ``host`` resolves to is public, or FetchRefused."""
    if not host:
        raise FetchRefused("NO_HOST", "The URL names no host.")
    try:
        records = list((resolver or socket.getaddrinfo)(host, port, type=socket.SOCK_STREAM))
    except (socket.gaierror, UnicodeError):
        raise FetchRefused("UNRESOLVED", "The source hostname could not be resolved.") from None
    if not records or not all(_is_public(record[4][0]) for record in records):
        raise FetchRefused("NOT_PUBLIC", "The source resolves to a non-public address.")


def check_url(url: str, *, schemes: tuple[str, ...] = ("http", "https"),
              resolver: Resolver | None = None) -> None:
    """The URL may be fetched: an allowed scheme, no credentials, a public host."""
    parts = urlsplit(url)
    if parts.scheme not in schemes:
        raise FetchRefused("SCHEME_NOT_ALLOWED", f"Only {'/'.join(schemes)} URLs may be fetched.")
    if parts.username or parts.password:
        raise FetchRefused("CREDENTIALS_IN_URL", "URLs with credentials may not be fetched.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise FetchRefused("BAD_PORT", "The URL's port is not valid.") from None
    require_public_host(parts.hostname or "", port, resolver)


@dataclass
class Fetched:
    url: str
    status_code: int
    headers: Any
    content: bytes
    encoding: str | None
    truncated: bool = False


def fetch(session: Any, url: str, *, method: str = "GET", max_bytes: int, timeout: Any,
          headers: dict[str, str] | None = None, max_redirects: int = 4, truncate: bool = False,
          stop: Callable[[bytearray], bool] | None = None,
          check: Callable[[str], None] = check_url) -> Fetched:
    """Fetch ``url`` through ``session``, checking it and every redirect hop.

    The body is read in chunks up to ``max_bytes``: past it, ``truncate`` keeps
    what fits, otherwise BodyTooLarge. ``stop(buffer)`` ends the read early once
    the caller has what it needs (a page's <head>). A non-2xx answer is returned
    with an empty body; deciding what it means is the caller's business.
    """
    for _ in range(max_redirects + 1):
        check(url)
        response = session.request(method, url, headers=headers, timeout=timeout,
                                   stream=True, allow_redirects=False)
        try:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            body, truncated = bytearray(), False
            if 200 <= response.status_code < 300 and method != "HEAD":
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        if not truncate:
                            raise BodyTooLarge("BODY_TOO_LARGE", f"The response exceeds {max_bytes} bytes.")
                        del body[max_bytes:]
                        truncated = True
                        break
                    if stop is not None and stop(body):
                        break
            return Fetched(url=url, status_code=response.status_code, headers=response.headers,
                           content=bytes(body), encoding=response.encoding, truncated=truncated)
        finally:
            response.close()
    raise FetchRefused("TOO_MANY_REDIRECTS", "The source redirected too many times.")

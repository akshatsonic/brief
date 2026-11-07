from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe to fetch."""


TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"}:
        raise UnsafeUrlError("only HTTP(S) URLs are supported")
    if not parts.hostname:
        raise UnsafeUrlError("URL must include a hostname")
    if parts.username or parts.password:
        raise UnsafeUrlError("URLs containing credentials are not allowed")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    port = parts.port
    default_port = (parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)
    if port and not default_port:
        host = f"{host}:{port}"
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(sorted(query)), ""))


def validate_public_url(
    url: str,
    resolver: Callable[[str], Iterable[str]] | None = None,
) -> str:
    canonical = canonicalize_url(url)
    host = urlsplit(canonical).hostname
    assert host is not None
    addresses = list((resolver or _resolve)(host))
    if not addresses:
        raise UnsafeUrlError(f"hostname did not resolve: {host}")
    for raw_address in addresses:
        address = ipaddress.ip_address(raw_address)
        if not address.is_global:
            raise UnsafeUrlError(f"destination resolves to a non-public address: {address}")
    return canonical


def _resolve(host: str) -> set[str]:
    try:
        return {result[4][0] for result in socket.getaddrinfo(host, None)}
    except socket.gaierror as error:
        raise UnsafeUrlError(f"could not resolve hostname: {host}") from error

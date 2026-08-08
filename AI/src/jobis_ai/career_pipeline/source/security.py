from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from collections.abc import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UnsafeSourceUrl(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedPublicUrl:
    canonical_url: str
    hostname: str
    addresses: tuple[str, ...]


def canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeSourceUrl("source URL must use http or https")
    if not parsed.hostname:
        raise UnsafeSourceUrl("source URL must include a hostname")

    host = parsed.hostname.encode("idna").decode("ascii").lower()
    port = parsed.port
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    if parsed.username or parsed.password:
        raise UnsafeSourceUrl("source URL must not contain credentials")

    path = parsed.path or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def _system_resolver(host: str) -> Iterable[str]:
    return {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}


class UrlSafetyPolicy:
    def __init__(self, resolver: Callable[[str], Iterable[str]] | None = None) -> None:
        self._resolver = resolver or _system_resolver

    def validate(self, value: str) -> str:
        return self.resolve(value).canonical_url

    def resolve(self, value: str) -> ResolvedPublicUrl:
        canonical = canonicalize_url(value)
        hostname = urlsplit(canonical).hostname
        assert hostname is not None
        try:
            addresses = list(self._resolver(hostname))
        except OSError as exc:
            raise UnsafeSourceUrl(f"source hostname could not be resolved: {hostname}") from exc
        if not addresses:
            raise UnsafeSourceUrl(f"source hostname could not be resolved: {hostname}")
        normalized: list[str] = []
        for raw in addresses:
            address = ipaddress.ip_address(raw)
            if not address.is_global:
                raise UnsafeSourceUrl("source URL resolves to a non-public network address")
            normalized.append(address.compressed)
        # The HTTP client connects to this validated address instead of doing a
        # second DNS lookup. IPv4 is preferred where local IPv6 routing is absent.
        normalized.sort(key=lambda item: (ipaddress.ip_address(item).version != 4, item))
        return ResolvedPublicUrl(canonical, hostname, tuple(normalized))

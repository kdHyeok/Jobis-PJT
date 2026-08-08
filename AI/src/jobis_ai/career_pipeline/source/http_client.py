from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .security import UrlSafetyPolicy


@dataclass(frozen=True, slots=True)
class FetchedResource:
    data: bytes
    content_type: str
    final_url: str

    def text(self) -> str:
        charset = "utf-8"
        for item in self.content_type.split(";")[1:]:
            key, _, value = item.strip().partition("=")
            if key.lower() == "charset" and value:
                charset = value.strip('"')
        try:
            return self.data.decode(charset, errors="replace")
        except LookupError:
            return self.data.decode("utf-8", errors="replace")


class SourceHttpClient:
    def __init__(
        self,
        *,
        safety: UrlSafetyPolicy,
        timeout_seconds: float,
        user_agent: str = "JOBIS/1.0 source-verification",
    ) -> None:
        self._safety = safety
        self._timeout = timeout_seconds
        self._user_agent = user_agent

    def get(
        self,
        url: str,
        *,
        max_bytes: int,
        headers: dict[str, str] | None = None,
    ) -> FetchedResource:
        current = self._safety.validate(url)
        request_headers = {"User-Agent": self._user_agent, **(headers or {})}
        with httpx.Client(timeout=self._timeout, follow_redirects=False) as client:
            for _redirect in range(6):
                resolved = self._safety.resolve(current)
                parsed = urlsplit(resolved.canonical_url)
                pinned_address = resolved.addresses[0]
                host = f"[{pinned_address}]" if ipaddress.ip_address(pinned_address).version == 6 else pinned_address
                pinned_netloc = host if parsed.port is None else f"{host}:{parsed.port}"
                pinned_url = urlunsplit((parsed.scheme, pinned_netloc, parsed.path, parsed.query, ""))
                pinned_headers = {"Host": parsed.netloc, **request_headers}
                with client.stream(
                    "GET",
                    pinned_url,
                    headers=pinned_headers,
                    extensions={"sni_hostname": resolved.hostname},
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise httpx.HTTPStatusError(
                                "redirect response omitted Location",
                                request=response.request,
                                response=response,
                            )
                        current = self._safety.validate(urljoin(current, location))
                        continue
                    response.raise_for_status()
                    declared = response.headers.get("content-length")
                    if declared and int(declared) > max_bytes:
                        raise ValueError(f"source exceeds the {max_bytes} byte safety limit")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError(f"source exceeds the {max_bytes} byte safety limit")
                        chunks.append(chunk)
                    return FetchedResource(
                        data=b"".join(chunks),
                        content_type=response.headers.get("content-type", "application/octet-stream"),
                        final_url=current,
                    )
        raise httpx.TooManyRedirects("source exceeded five redirects")

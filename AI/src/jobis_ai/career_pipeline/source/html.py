from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin


_JUNK_TAGS = {"script", "style", "noscript", "svg"}


class ExtractedHtml:
    def __init__(self, html: str, base_url: str) -> None:
        parser = _VisibleHtmlParser(base_url)
        parser.feed(html)
        self.text = re.sub(r"\n{3,}", "\n\n", "\n".join(parser.parts)).strip()
        self.meta_description = parser.meta_description
        self.title = parser.title
        self.iframe_urls = list(dict.fromkeys(parser.iframe_urls + _script_iframe_urls(html, base_url)))
        self.image_urls = list(dict.fromkeys(parser.image_urls))


class _VisibleHtmlParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._ignored_depth = 0
        self._in_title = False
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.meta_description = ""
        self.iframe_urls: list[str] = []
        self.image_urls: list[str] = []

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = dict(attrs)
        if tag in _JUNK_TAGS:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta" and not self.meta_description:
            if values.get("name") == "description" or values.get("property") == "og:description":
                self.meta_description = (values.get("content") or "").strip()
        if tag == "iframe" and values.get("src"):
            self.iframe_urls.append(urljoin(self._base_url, values["src"] or ""))
        if tag == "img" and values.get("src"):
            self.image_urls.append(urljoin(self._base_url, values["src"] or ""))
        if tag in {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _JUNK_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        if not self._ignored_depth:
            self.parts.append(value)


_SCRIPT_IFRAME_PATTERNS = (
    re.compile(r"/Recruit/GI_Read_Comt_Ifrm\?[^\s\"'<]+"),
)


def _script_iframe_urls(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    for pattern in _SCRIPT_IFRAME_PATTERNS:
        for match in pattern.findall(html):
            url = urljoin(base_url, match.replace("\\u0026", "&").rstrip("\\"))
            if url not in urls:
                urls.append(url)
    return urls


def derived_iframe_urls(page_url: str) -> list[str]:
    match = re.search(r"saramin\.co\.kr/zf_user/jobs/relay/view\?[^#]*?rec_idx=(\d+)", page_url)
    if not match:
        return []
    return [
        "https://www.saramin.co.kr/zf_user/jobs/relay/view-detail"
        f"?rec_idx={match.group(1)}&rec_seq=0"
    ]

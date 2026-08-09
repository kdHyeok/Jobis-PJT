from __future__ import annotations

import base64
import io
from dataclasses import replace

import pytest
from PIL import Image

from jobis_ai.career_pipeline.config import Settings
from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.contracts.source import (
    CorrectionReason,
    PostingCorrection,
    SourceAcquisitionRequest,
    SourceEntryPoint,
    SourceInputType,
    SourceStatus,
    SourceVerificationRequest,
    VerifiedBy,
)
from jobis_ai.career_pipeline.source.http_client import FetchedResource
from jobis_ai.career_pipeline.source.image import ImageTile, RecognizedTile
from jobis_ai.career_pipeline.source.service import (
    SourceAcquisitionFailure,
    SourceAcquisitionService,
    require_verified_snapshot,
)
from jobis_ai.career_pipeline.source.security import UnsafeSourceUrl, UrlSafetyPolicy, canonicalize_url


SETTINGS = Settings(
    environment="test",
    shared_secret="test-ai-secret-123",
    host="127.0.0.1",
    port=8300,
)


def test_firecrawl_settings_are_loaded_without_exposing_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JOBIS_FIRECRAWL_ENABLED", "true")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "firecrawl-secret")

    settings = Settings.from_env()

    assert settings.firecrawl_enabled is True
    assert settings.firecrawl_api_key == "firecrawl-secret"


def test_url_safety_resolution_returns_only_pinned_public_addresses() -> None:
    policy = UrlSafetyPolicy(resolver=lambda host: ["93.184.216.34"])

    resolved = policy.resolve("https://example.com/jobs/1")

    assert resolved.canonical_url == "https://example.com/jobs/1"
    assert resolved.hostname == "example.com"
    assert resolved.addresses == ("93.184.216.34",)


def test_url_safety_rejects_mixed_public_and_private_dns_answers() -> None:
    policy = UrlSafetyPolicy(resolver=lambda host: ["93.184.216.34", "127.0.0.1"])

    with pytest.raises(UnsafeSourceUrl, match="non-public"):
        policy.resolve("https://example.com/jobs/1")


class FakeHttpClient:
    def __init__(self, resources: dict[str, FetchedResource | Exception]) -> None:
        self.resources = resources
        self.calls: list[str] = []
        self.headers: dict[str, dict[str, str]] = {}

    def get(self, url: str, *, max_bytes: int, headers: dict[str, str] | None = None) -> FetchedResource:
        self.calls.append(url)
        self.headers[url] = headers or {}
        resource = self.resources[url]
        if isinstance(resource, Exception):
            raise resource
        return resource


class FakeImageRecognizer:
    def __init__(self, texts: list[str], confidence: float | None = None) -> None:
        self._texts = texts
        self._confidence = confidence

    def recognize(self, tile: ImageTile) -> RecognizedTile:
        text = self._texts[min(tile.index, len(self._texts) - 1)]
        return RecognizedTile(tile=tile, text=text, confidence=self._confidence)


def _image_base64(*, width: int = 100, height: int = 100) -> str:
    image = Image.new("RGB", (width, height), "white")
    output = io.BytesIO()
    image.save(output, "PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def test_text_source_waits_for_verification() -> None:
    service = SourceAcquisitionService(settings=SETTINGS)

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.TEXT,
        entry_point=SourceEntryPoint.CHAT,
        text="백엔드 개발자 채용\n지원 자격: 신입\nJava 경험 필수",
    ))

    assert source.status is SourceStatus.AWAITING_VERIFICATION
    assert source.segments[0].method.value == "USER_PASTE"
    assert source.extractor_version == "source-extractor-3.2.0"


def test_chat_and_postings_page_share_canonical_input_and_adapter() -> None:
    url = "https://example.invalid/posting/123?b=2&a=1"
    final_url = "https://example.invalid/posting/123?a=1&b=2"
    html = (
        "<html><head><title>백엔드 개발자 채용</title></head>"
        "<body><h1>백엔드 개발자 모집</h1><h2>지원 자격</h2>"
        f"<p>{'Java와 Spring을 사용한 API 개발 경험이 필요합니다. ' * 10}</p>"
        "</body></html>"
    )
    client = FakeHttpClient({
        final_url: FetchedResource(
            data=html.encode(),
            content_type="text/html; charset=utf-8",
            final_url=final_url,
        )
    })
    service = SourceAcquisitionService(settings=SETTINGS, http_client=client)

    chat = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=url,
    ))
    postings = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.POSTINGS_PAGE,
        url=url,
    ))

    assert chat.canonical_input_hash == postings.canonical_input_hash
    assert chat.raw_text == postings.raw_text
    assert client.calls == [final_url, final_url]


def test_direct_jobkorea_text_is_preferred_and_skips_external_collectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/123"
    html = (
        "<html><body><h1>백엔드 개발자 채용</h1><h2>지원 자격</h2>"
        f"<p>{'Java Spring 개발과 운영 경험을 확인합니다. ' * 10}</p></body></html>"
    )
    client = FakeHttpClient({
        url: FetchedResource(
            data=html.encode(),
            content_type="text/html; charset=utf-8",
            final_url=url,
        ),
    })
    service = SourceAcquisitionService(
        settings=replace(
            SETTINGS,
            jina_enabled=True,
            jina_api_key="secret",
            firecrawl_enabled=True,
            firecrawl_api_key="test-key",
            tavily_enabled=True,
            tavily_api_key="test-key",
        ),
        http_client=client,
    )
    monkeypatch.setattr(
        service,
        "_extract_with_firecrawl",
        lambda _url: pytest.fail("Firecrawl must not be called"),
    )
    monkeypatch.setattr(
        service,
        "_extract_with_tavily",
        lambda _url: pytest.fail("Tavily must not be called"),
    )

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=url,
    ))

    assert "지원 자격" in source.raw_text
    assert client.calls == [url]
    assert not any(item.code == "JINA_FETCH_FAILED" for item in source.warnings)


def test_fragment_career_page_runs_bounded_dynamic_collectors_before_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://example.com/career-book#backend"
    canonical_url = "https://example.com/career-book"
    reader_url = f"https://r.jina.ai/{canonical_url}%23backend"
    generic_page = (
        "회사 소개 채용 문화 모집 분야 경력 이야기 인재상 복리후생 " * 20
    )
    client = FakeHttpClient({
        canonical_url: FetchedResource(
            data=f"<html><body>{generic_page}</body></html>".encode(),
            content_type="text/html; charset=utf-8",
            final_url=url,
        ),
        reader_url: FetchedResource(
            data=generic_page.encode(),
            content_type="text/plain; charset=utf-8",
            final_url=reader_url,
        ),
    })
    firecrawl_calls: list[str] = []
    tavily_calls: list[str] = []
    service = SourceAcquisitionService(
        settings=replace(
            SETTINGS,
            jina_enabled=True,
            firecrawl_enabled=True,
            firecrawl_api_key="firecrawl-key",
            tavily_enabled=True,
            tavily_api_key="tavily-key",
        ),
        http_client=client,
    )

    def firecrawl_extract(target_url: str) -> str:
        firecrawl_calls.append(target_url)
        return (
            "백엔드 개발자 채용\n주요 업무\nJava API를 개발하고 운영합니다.\n"
            "자격요건\nSpring 개발 경험과 SQL 활용 경험이 필요합니다.\n" * 6
        )

    def tavily_extract(target_url: str) -> str:
        tavily_calls.append(target_url)
        return (
            "Backend Platform Engineer\n지원 자격\n"
            "Java Spring API 개발 경험과 Linux 운영 경험이 필요합니다.\n" * 6
        )

    monkeypatch.setattr(service, "_extract_with_firecrawl", firecrawl_extract)
    monkeypatch.setattr(service, "_extract_with_tavily", tavily_extract)

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=url,
    ))

    assert client.calls == [canonical_url, reader_url]
    assert firecrawl_calls == [url]
    assert tavily_calls == [url]
    assert "주요 업무" in source.raw_text
    assert "자격요건" in source.raw_text
    assert "Backend Platform Engineer" in source.raw_text
    assert source.canonical_url == url


def test_spa_fragments_have_distinct_source_identity() -> None:
    base_url = "https://example.com/career-book"
    posting = (
        "백엔드 개발자 채용\n주요 업무\nJava API를 개발하고 운영합니다.\n"
        "지원 자격\nSpring 개발 경험과 SQL 활용 경험이 필요합니다.\n" * 6
    )
    client = FakeHttpClient({
        base_url: FetchedResource(
            data=f"<html><body>{posting}</body></html>".encode(),
            content_type="text/html; charset=utf-8",
            final_url=base_url,
        ),
    })
    service = SourceAcquisitionService(settings=SETTINGS, http_client=client)

    backend = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=f"{base_url}#backend",
    ))
    data = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=f"{base_url}#data",
    ))

    assert backend.canonical_url == f"{base_url}#backend"
    assert data.canonical_url == f"{base_url}#data"
    assert backend.canonical_input_hash != data.canonical_input_hash


def test_all_nonempty_collectors_are_rejected_when_posting_signals_never_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://example.com/career-book#role"
    canonical_url = "https://example.com/career-book"
    reader_url = f"https://r.jina.ai/{canonical_url}%23role"
    generic_page = "회사 소개 채용 문화 모집 분야 경력 이야기 " * 30
    client = FakeHttpClient({
        canonical_url: FetchedResource(
            data=f"<html><body>{generic_page}</body></html>".encode(),
            content_type="text/html; charset=utf-8",
            final_url=url,
        ),
        reader_url: FetchedResource(
            data=generic_page.encode(),
            content_type="text/plain; charset=utf-8",
            final_url=reader_url,
        ),
    })
    service = SourceAcquisitionService(
        settings=replace(
            SETTINGS,
            jina_enabled=True,
            firecrawl_enabled=True,
            firecrawl_api_key="firecrawl-key",
            tavily_enabled=True,
            tavily_api_key="tavily-key",
        ),
        http_client=client,
    )
    monkeypatch.setattr(service, "_extract_with_firecrawl", lambda _url: generic_page)
    monkeypatch.setattr(service, "_extract_with_tavily", lambda _url: generic_page)

    with pytest.raises(SourceAcquisitionFailure, match="담당 업무와 지원 조건"):
        service.acquire(SourceAcquisitionRequest(
            input_type=SourceInputType.URL,
            entry_point=SourceEntryPoint.CHAT,
            url=url,
        ))

    assert client.calls == [canonical_url, reader_url]


def test_thin_direct_text_uses_jina_with_api_key() -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/124"
    reader_url = f"https://r.jina.ai/{url}"
    reader_text = "백엔드 개발자 채용\n지원 자격\n" + "Java Spring 개발 경험 필수\n" * 15
    client = FakeHttpClient({
        url: FetchedResource(
            data="<html><body>채용</body></html>".encode(),
            content_type="text/html; charset=utf-8",
            final_url=url,
        ),
        reader_url: FetchedResource(
            data=reader_text.encode(),
            content_type="text/plain; charset=utf-8",
            final_url=reader_url,
        ),
    })
    service = SourceAcquisitionService(
        settings=replace(SETTINGS, jina_enabled=True, jina_api_key="secret"),
        http_client=client,
    )

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=url,
    ))

    assert source.raw_text.endswith("Java Spring 개발 경험 필수")
    assert client.calls == [url, reader_url]
    assert client.headers[reader_url]["Authorization"] == "Bearer secret"


def test_direct_failure_is_suppressed_when_jina_recovers() -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/125"
    reader_url = f"https://r.jina.ai/{url}"
    reader_text = "백엔드 개발자 채용\n지원 자격\n" + "Python API 개발 경험 필수\n" * 15
    client = FakeHttpClient({
        url: OSError("direct blocked"),
        reader_url: FetchedResource(
            data=reader_text.encode(),
            content_type="text/plain; charset=utf-8",
            final_url=reader_url,
        ),
    })
    service = SourceAcquisitionService(
        settings=replace(SETTINGS, jina_enabled=True),
        http_client=client,
    )

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=url,
    ))

    assert "Python API 개발 경험 필수" in source.raw_text
    assert not source.warnings


def test_jina_failure_rejects_source_when_direct_text_is_insufficient() -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/126"
    reader_url = f"https://r.jina.ai/{url}"
    client = FakeHttpClient({
        url: FetchedResource(
            data="<html><body>지원 자격: Java</body></html>".encode(),
            content_type="text/html; charset=utf-8",
            final_url=url,
        ),
        reader_url: OSError("403 Forbidden"),
    })
    service = SourceAcquisitionService(
        settings=replace(SETTINGS, jina_enabled=True),
        http_client=client,
    )

    with pytest.raises(SourceAcquisitionFailure, match="담당 업무와 지원 조건"):
        service.acquire(SourceAcquisitionRequest(
            input_type=SourceInputType.URL,
            entry_point=SourceEntryPoint.CHAT,
            url=url,
        ))


def test_firecrawl_recovers_exact_url_after_jina_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/1260"
    reader_url = f"https://r.jina.ai/{url}"
    firecrawl_calls: list[str] = []
    client = FakeHttpClient({
        url: FetchedResource(
            data=b"<html><body>Backend job</body></html>",
            content_type="text/html; charset=utf-8",
            final_url=url,
        ),
        reader_url: OSError("403 Forbidden"),
    })

    def firecrawl_extract(target_url: str) -> str:
        firecrawl_calls.append(target_url)
        return "Backend Engineer\nRequirements\n" + "Python API experience\n" * 10

    service = SourceAcquisitionService(
        settings=replace(
            SETTINGS,
            jina_enabled=True,
            firecrawl_enabled=True,
            firecrawl_api_key="test-key",
            tavily_enabled=True,
            tavily_api_key="test-key",
        ),
        http_client=client,
    )
    monkeypatch.setattr(service, "_extract_with_firecrawl", firecrawl_extract)
    monkeypatch.setattr(
        service,
        "_extract_with_tavily",
        lambda _url: pytest.fail("Tavily must not run after Firecrawl recovers"),
    )

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=url,
    ))

    assert "Python API experience" in source.raw_text
    assert client.calls == [url, reader_url]
    assert firecrawl_calls == [url]
    assert not any(item.code.endswith("FETCH_FAILED") for item in source.warnings)


def test_firecrawl_failure_falls_through_to_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/12601"
    reader_url = f"https://r.jina.ai/{url}"
    tavily_calls: list[str] = []
    client = FakeHttpClient({
        url: OSError("direct blocked"),
        reader_url: OSError("Jina blocked"),
    })
    service = SourceAcquisitionService(
        settings=replace(
            SETTINGS,
            jina_enabled=True,
            firecrawl_enabled=True,
            firecrawl_api_key="firecrawl-key",
            tavily_enabled=True,
            tavily_api_key="tavily-key",
        ),
        http_client=client,
    )

    def firecrawl_fails(_url: str) -> str:
        raise OSError("Firecrawl blocked")

    monkeypatch.setattr(
        service,
        "_extract_with_firecrawl",
        firecrawl_fails,
    )

    def tavily_extract(target_url: str) -> str:
        tavily_calls.append(target_url)
        return "Backend Engineer\nRequirements\n" + "Python API experience\n" * 10

    monkeypatch.setattr(service, "_extract_with_tavily", tavily_extract)

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=url,
    ))

    assert "Python API experience" in source.raw_text
    assert tavily_calls == [url]
    assert not any(item.code.endswith("FETCH_FAILED") for item in source.warnings)


def test_tavily_recovers_exact_url_after_jina_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/1261"
    reader_url = f"https://r.jina.ai/{url}"
    tavily_calls: list[str] = []
    client = FakeHttpClient({
        url: FetchedResource(
            data=b"<html><body>Backend job</body></html>",
            content_type="text/html; charset=utf-8",
            final_url=url,
        ),
        reader_url: OSError("403 Forbidden"),
    })

    def tavily_extract(target_url: str) -> str:
        tavily_calls.append(target_url)
        return "Backend Engineer\nRequirements\n" + "Python API development experience\n" * 10

    service = SourceAcquisitionService(
        settings=replace(
            SETTINGS,
            jina_enabled=True,
            tavily_enabled=True,
            tavily_api_key="test-key",
        ),
        http_client=client,
    )
    monkeypatch.setattr(service, "_extract_with_tavily", tavily_extract)

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=url,
    ))

    assert "Python API development experience" in source.raw_text
    assert client.calls == [url, reader_url]
    assert tavily_calls == [url]
    assert not any(item.code.endswith("FETCH_FAILED") for item in source.warnings)


def test_all_url_collection_paths_must_fail_before_requesting_manual_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/127"
    reader_url = f"https://r.jina.ai/{url}"
    client = FakeHttpClient({
        url: OSError("direct blocked"),
        reader_url: OSError("403 Forbidden"),
    })
    def tavily_fails(_url: str) -> str:
        raise OSError("Tavily blocked")

    def firecrawl_fails(_url: str) -> str:
        raise OSError("Firecrawl blocked")

    service = SourceAcquisitionService(
        settings=replace(
            SETTINGS,
            jina_enabled=True,
            firecrawl_enabled=True,
            firecrawl_api_key="firecrawl-key",
            tavily_enabled=True,
            tavily_api_key="test-key",
        ),
        http_client=client,
    )
    monkeypatch.setattr(service, "_extract_with_firecrawl", firecrawl_fails)
    monkeypatch.setattr(service, "_extract_with_tavily", tavily_fails)

    with pytest.raises(SourceAcquisitionFailure, match="no text"):
        service.acquire(SourceAcquisitionRequest(
            input_type=SourceInputType.URL,
            entry_point=SourceEntryPoint.CHAT,
            url=url,
        ))

    assert client.calls == [url, reader_url]


def test_unsafe_url_never_reaches_external_collectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://private.example/jobs/1"
    reader_url = f"https://r.jina.ai/{url}"
    tavily_calls: list[str] = []
    firecrawl_calls: list[str] = []
    client = FakeHttpClient({
        url: UnsafeSourceUrl("source URL resolves to a non-public network address"),
        reader_url: AssertionError("Jina must not be called"),
    })
    service = SourceAcquisitionService(
        settings=replace(
            SETTINGS,
            jina_enabled=True,
            firecrawl_enabled=True,
            firecrawl_api_key="firecrawl-key",
            tavily_enabled=True,
            tavily_api_key="test-key",
        ),
        http_client=client,
    )
    monkeypatch.setattr(
        service,
        "_extract_with_firecrawl",
        lambda target_url: firecrawl_calls.append(target_url) or "unexpected",
    )
    monkeypatch.setattr(
        service,
        "_extract_with_tavily",
        lambda target_url: tavily_calls.append(target_url) or "unexpected",
    )

    with pytest.raises(SourceAcquisitionFailure, match="non-public"):
        service.acquire(SourceAcquisitionRequest(
            input_type=SourceInputType.URL,
            entry_point=SourceEntryPoint.CHAT,
            url=url,
        ))

    assert client.calls == [url]
    assert not firecrawl_calls
    assert not tavily_calls


def test_firecrawl_scrape_uses_v2_bearer_key_and_exact_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://example.com/careers/role?track=exact"
    captured: dict[str, object] = {}

    class FakeResponse:
        content = b"result"

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "success": True,
                "data": {
                    "markdown": "Backend Engineer\nRequirements\nPython API experience",
                },
            }

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            target_url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            captured.update(url=target_url, headers=headers, json=json)
            return FakeResponse()

    monkeypatch.setattr(
        "jobis_ai.career_pipeline.source.service.httpx.Client",
        FakeClient,
    )
    service = SourceAcquisitionService(settings=replace(
        SETTINGS,
        source_fetch_timeout_seconds=45.0,
        firecrawl_enabled=True,
        firecrawl_api_key="firecrawl-key",
    ))

    result = service._extract_with_firecrawl(url)

    assert result.startswith("Backend Engineer")
    assert captured["timeout"] == 45.0
    assert captured["url"] == "https://api.firecrawl.dev/v2/scrape"
    assert captured["headers"] == {"Authorization": "Bearer firecrawl-key"}
    assert captured["json"] == {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "waitFor": 2_000,
        "timeout": 45_000,
        "maxAge": 0,
    }


def test_tavily_extract_uses_bearer_key_and_exact_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/1262?track=exact"
    captured: dict[str, object] = {}

    class FakeResponse:
        content = b"result"

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "results": [{
                    "raw_content": "Backend Engineer\nRequirements\nPython API experience",
                }],
            }

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            target_url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            captured.update(url=target_url, headers=headers, json=json)
            return FakeResponse()

    monkeypatch.setattr(
        "jobis_ai.career_pipeline.source.service.httpx.Client",
        FakeClient,
    )
    service = SourceAcquisitionService(settings=replace(
        SETTINGS,
        tavily_enabled=True,
        tavily_api_key="test-key",
    ))

    result = service._extract_with_tavily(url)

    assert result.startswith("Backend Engineer")
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    assert captured["json"] == {
        "urls": url,
        "extract_depth": "advanced",
        "format": "text",
        "include_images": False,
    }


def test_jobkorea_script_iframe_is_merged_by_shared_collector() -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/128"
    iframe_url = "https://www.jobkorea.co.kr/Recruit/GI_Read_Comt_Ifrm?Gno=128"
    page = (
        '<html><body>채용</body><script>{"src":"/Recruit/GI_Read_Comt_Ifrm?Gno=128"}'
        "</script></html>"
    )
    iframe = "<html><body><h2>지원 자격</h2><p>" + "Linux 개발 경험 필수 " * 20 + "</p></body></html>"
    client = FakeHttpClient({
        url: FetchedResource(data=page.encode(), content_type="text/html", final_url=url),
        iframe_url: FetchedResource(
            data=iframe.encode(),
            content_type="text/html",
            final_url=iframe_url,
        ),
    })
    service = SourceAcquisitionService(settings=SETTINGS, http_client=client)

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.POSTINGS_PAGE,
        url=url,
    ))

    assert "Linux 개발 경험 필수" in source.raw_text
    assert client.calls == [url, iframe_url]


def test_jobkorea_recommendation_tail_is_removed() -> None:
    url = "https://www.jobkorea.co.kr/Recruit/GI_Read/129"
    page = (
        "<html><body><h1>백엔드 개발자 채용</h1><p>지원 자격: Java</p>"
        f"<p>{'Java Spring API 개발 및 운영 경험이 필요합니다. ' * 10}</p>"
        "<p>로그인 하고 비슷한 조건의 AI추천공고를 확인해 보세요!</p>"
        "<p>타사 영업 채용 경력 12년</p></body></html>"
    )
    client = FakeHttpClient({
        url: FetchedResource(data=page.encode(), content_type="text/html", final_url=url),
    })
    service = SourceAcquisitionService(settings=SETTINGS, http_client=client)

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.URL,
        entry_point=SourceEntryPoint.CHAT,
        url=url,
    ))

    assert "백엔드 개발자 채용" in source.raw_text
    assert "타사 영업" not in source.raw_text
    assert any(item.code == "UNRELATED_TAIL_DROPPED" for item in source.warnings)


def test_non_posting_page_is_rejected_without_inventing_a_posting() -> None:
    url = "https://example.invalid/login"
    client = FakeHttpClient({
        url: FetchedResource(
            data="<html><title>로그인</title><body>로그인이 필요합니다</body></html>".encode(),
            content_type="text/html",
            final_url=url,
        )
    })
    service = SourceAcquisitionService(settings=SETTINGS, http_client=client)

    with pytest.raises(SourceAcquisitionFailure) as raised:
        service.acquire(SourceAcquisitionRequest(
            input_type=SourceInputType.URL,
            entry_point=SourceEntryPoint.CHAT,
            url=url,
        ))

    assert raised.value.code is ErrorCode.SOURCE_FETCH_FAILED
    assert "담당 업무와 지원 조건" in str(raised.value)


def test_low_confidence_image_stays_in_verification_state() -> None:
    service = SourceAcquisitionService(
        settings=SETTINGS,
        image_recognizer=FakeImageRecognizer(["지원 자격: QA 경력 19년"], confidence=0.42),
    )

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.IMAGE,
        entry_point=SourceEntryPoint.POSTINGS_PAGE,
        image_base64=_image_base64(),
        image_media_type="image/png",
        original_filename="posting.png",
    ))

    assert source.status is SourceStatus.AWAITING_VERIFICATION
    assert any(item.code == "SOURCE_EXTRACTION_LOW_CONFIDENCE" for item in source.warnings)
    assert source.raw_text == "지원 자격: QA 경력 19년"


def test_overlapping_image_tiles_keep_segments_but_deduplicate_raw_text() -> None:
    repeated = "Kafka 사용 경험 우대"
    service = SourceAcquisitionService(
        settings=SETTINGS,
        image_recognizer=FakeImageRecognizer([repeated]),
    )

    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.IMAGE,
        entry_point=SourceEntryPoint.CHAT,
        image_base64=_image_base64(width=100, height=450),
        image_media_type="image/png",
        original_filename="long-posting.png",
    ))

    assert len(source.segments) > 1
    assert {segment.overlap_group for segment in source.segments} == {"image-tiles"}
    assert source.raw_text == repeated


def test_user_correction_creates_verified_snapshot_and_unlocks_gate() -> None:
    service = SourceAcquisitionService(settings=SETTINGS)
    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.TEXT,
        entry_point=SourceEntryPoint.CHAT,
        text="지원 자격: QA 경력 19년",
    ))
    correction = PostingCorrection(
        field="experience",
        before="경력 19년",
        after="신입",
        reason=CorrectionReason.OCR_CORRECTION,
    )

    result = service.verify(SourceVerificationRequest(
        source_document=source,
        verified_text="지원 자격: 신입",
        corrections=[correction],
        verified_by=VerifiedBy.USER,
    ))

    assert result.source_document.status is SourceStatus.VERIFIED
    assert result.verified_snapshot.verified_text == "지원 자격: 신입"
    assert all(segment.source_locator is not None for segment in result.verified_snapshot.evidence_segments)
    assert all("경력 19년" not in segment.text for segment in result.verified_snapshot.evidence_segments)
    assert require_verified_snapshot(result.source_document, result.verified_snapshot)

    second = service.verify(SourceVerificationRequest(
        source_document=result.source_document,
        verified_text="지원 자격: 신입",
        corrections=[correction],
        verified_by=VerifiedBy.USER,
        previous_snapshot_id=result.verified_snapshot.verified_snapshot_id,
    ))
    assert second.verified_snapshot.verified_snapshot_id != result.verified_snapshot.verified_snapshot_id
    assert second.verified_snapshot.previous_snapshot_id == result.verified_snapshot.verified_snapshot_id


def test_unverified_source_is_rejected_by_analysis_gate() -> None:
    service = SourceAcquisitionService(settings=SETTINGS)
    source = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.TEXT,
        entry_point=SourceEntryPoint.CHAT,
        text="백엔드 개발자 채용 공고",
    ))

    with pytest.raises(SourceAcquisitionFailure) as raised:
        require_verified_snapshot(source, None)

    assert raised.value.code is ErrorCode.SOURCE_NOT_VERIFIED


def test_source_revision_changes_document_revision_but_not_canonical_cache_key() -> None:
    service = SourceAcquisitionService(settings=SETTINGS)
    first = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.TEXT,
        entry_point=SourceEntryPoint.CHAT,
        extraction_revision=1,
        text="백엔드 개발자 채용 공고",
    ))
    second = service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.TEXT,
        entry_point=SourceEntryPoint.POSTINGS_PAGE,
        extraction_revision=2,
        text="백엔드 개발자 채용 공고",
    ))

    assert second.extraction_revision == 2
    assert first.canonical_input_hash == second.canonical_input_hash


def test_url_security_blocks_private_networks_and_normalizes_public_urls() -> None:
    policy = UrlSafetyPolicy(resolver=lambda _host: ["127.0.0.1"])
    with pytest.raises(UnsafeSourceUrl, match="non-public"):
        policy.validate("http://example.com/internal")

    assert canonicalize_url("HTTPS://Example.COM:443/posting?b=2&a=1#top") == (
        "https://example.com/posting?a=1&b=2"
    )

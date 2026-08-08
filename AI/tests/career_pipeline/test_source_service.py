from __future__ import annotations

import base64
import io

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
    def __init__(self, resources: dict[str, FetchedResource]) -> None:
        self.resources = resources
        self.calls: list[str] = []

    def get(self, url: str, *, max_bytes: int, headers: dict[str, str] | None = None) -> FetchedResource:
        self.calls.append(url)
        return self.resources[url]


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
    assert source.extractor_version == "source-extractor-3.0.0"


def test_chat_and_postings_page_share_canonical_input_and_adapter() -> None:
    url = "https://example.invalid/posting/123?b=2&a=1"
    final_url = "https://example.invalid/posting/123?a=1&b=2"
    html = """
    <html><head><title>백엔드 개발자 채용</title></head>
    <body><h1>백엔드 개발자 모집</h1><h2>지원 자격</h2><p>Java 경험 필수</p></body></html>
    """
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
    assert "does not look like a job posting" in str(raised.value)


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

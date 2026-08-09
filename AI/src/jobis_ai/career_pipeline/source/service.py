from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import httpx

from jobis_ai.career_pipeline.config import Settings
from jobis_ai.career_pipeline.contracts.common import WarningItem, WarningSeverity
from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.contracts.source import (
    ExtractionMethod,
    ExtractionSegment,
    PostingCorrection,
    SourceAcquisitionRequest,
    SourceDocument,
    SourceInputType,
    SourceLocator,
    SourceStatus,
    SourceVerificationRequest,
    SourceVerificationResult,
    VerifiedPostingSnapshot,
)

from .html import ExtractedHtml, derived_iframe_urls
from .http_client import SourceHttpClient
from .image import ClovaImageRecognizer, ImageRecognizer, decode_image_base64, split_image_tiles
from .security import UnsafeSourceUrl, UrlSafetyPolicy, canonicalize_url


EXTRACTOR_VERSION = "source-extractor-3.2.0"
MIN_MEANINGFUL_CHARS = 120
MINIMUM_USEFUL_POSTING_LENGTH = 200
MAX_IFRAMES = 8
MAX_IMAGES = 10
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

logger = logging.getLogger(__name__)


class SourceAcquisitionFailure(RuntimeError):
    def __init__(self, *, code: ErrorCode, message: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class SourceAcquisitionService:
    def __init__(
        self,
        *,
        settings: Settings,
        http_client: SourceHttpClient | None = None,
        image_recognizer: ImageRecognizer | None = None,
    ) -> None:
        self._settings = settings
        self._http = http_client or SourceHttpClient(
            safety=UrlSafetyPolicy(),
            timeout_seconds=settings.source_fetch_timeout_seconds,
        )
        self._image = image_recognizer or ClovaImageRecognizer(
            api_key=settings.clova_api_key,
            endpoint=settings.clova_vlm_url,
        )

    def acquire(self, request: SourceAcquisitionRequest) -> SourceDocument:
        try:
            if request.input_type is SourceInputType.TEXT:
                assert request.text is not None
                original_input = request.text
                canonical_url = None
                canonical_value = _normalize_text(request.text)
                segments, warnings = self._from_text(request.text)
            elif request.input_type is SourceInputType.URL:
                assert request.url is not None
                original_input = request.url
                canonical_base_url = canonicalize_url(request.url)
                external_fragment = urlsplit(request.url.strip()).fragment
                canonical_value = _with_fragment(canonical_base_url, external_fragment)
                segments, warnings, final_base_url = self._from_url(
                    canonical_base_url,
                    external_fragment=external_fragment,
                )
                canonical_url = _with_fragment(final_base_url, external_fragment)
            else:
                assert request.image_base64 is not None
                assert request.original_filename is not None
                original_input = request.original_filename
                canonical_url = None
                image_bytes = decode_image_base64(
                    request.image_base64,
                    max_bytes=self._settings.source_max_image_bytes,
                )
                canonical_value = (
                    f"{request.image_media_type}:"
                    f"{hashlib.sha256(image_bytes).hexdigest()}"
                )
                segments, warnings = self._from_image(image_bytes)
        except SourceAcquisitionFailure:
            raise
        except (UnsafeSourceUrl, ValueError) as exc:
            raise SourceAcquisitionFailure(
                code=ErrorCode.SOURCE_FETCH_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            raise SourceAcquisitionFailure(
                code=ErrorCode.SOURCE_FETCH_FAILED,
                message=f"source could not be fetched: {exc}",
                retryable=True,
            ) from exc

        raw_text = _merge_segments(segments)
        if not raw_text:
            raise SourceAcquisitionFailure(
                code=ErrorCode.SOURCE_FETCH_FAILED,
                message="source extraction returned no text",
                retryable=True,
            )
        if (
            request.input_type is SourceInputType.URL
            and not _is_sufficient_posting_text(raw_text)
        ):
            raise SourceAcquisitionFailure(
                code=ErrorCode.SOURCE_FETCH_FAILED,
                message=(
                    "공고의 담당 업무와 지원 조건을 충분히 가져오지 못했습니다. "
                    "채용 공고 원문을 직접 붙여 넣거나 실제 공고 상세 URL을 사용해 주세요."
                ),
                retryable=False,
            )

        confidences = [item.confidence for item in segments if item.confidence is not None]
        if confidences and min(confidences) < 0.7:
            warnings.append(WarningItem(
                code=ErrorCode.SOURCE_EXTRACTION_LOW_CONFIDENCE.value,
                message="일부 원문 추출 신뢰도가 낮습니다. 직무와 경력 숫자를 확인해주세요.",
                severity=WarningSeverity.WARNING,
            ))

        return SourceDocument(
            source_document_id=f"src-{uuid4()}",
            input_type=request.input_type,
            original_input=original_input,
            canonical_url=canonical_url,
            captured_at=datetime.now(timezone.utc),
            extraction_revision=request.extraction_revision,
            extractor_version=EXTRACTOR_VERSION,
            canonical_input_hash=_sha256(f"{EXTRACTOR_VERSION}\n{canonical_value}"),
            raw_text=raw_text,
            content_hash=_sha256(raw_text),
            segments=segments,
            warnings=warnings,
            status=SourceStatus.AWAITING_VERIFICATION,
        )

    def verify(self, request: SourceVerificationRequest) -> SourceVerificationResult:
        source = request.source_document
        for correction in request.corrections:
            _validate_correction(source.raw_text, request.verified_text, correction)
        snapshot = VerifiedPostingSnapshot(
            verified_snapshot_id=f"vps-{uuid4()}",
            source_document_id=source.source_document_id,
            source_revision=source.extraction_revision,
            previous_snapshot_id=request.previous_snapshot_id,
            verified_text=request.verified_text,
            evidence_segments=_verified_evidence_segments(request.verified_text),
            corrections=request.corrections,
            verified_by=request.verified_by,
            verified_at=datetime.now(timezone.utc),
            snapshot_hash=_sha256(f"{source.content_hash}\n{request.verified_text}"),
        )
        return SourceVerificationResult(
            source_document=source.model_copy(update={"status": SourceStatus.VERIFIED}),
            verified_snapshot=snapshot,
        )

    def _from_text(self, text: str) -> tuple[list[ExtractionSegment], list[WarningItem]]:
        normalized = _normalize_text(text)
        if not normalized:
            raise ValueError("pasted source text is empty")
        return [self._segment(normalized, ExtractionMethod.USER_PASTE, 0, confidence=1.0)], []

    def _from_url(
        self,
        url: str,
        *,
        external_fragment: str = "",
    ) -> tuple[list[ExtractionSegment], list[WarningItem], str]:
        segments: list[ExtractionSegment] = []
        warnings: list[WarningItem] = []
        deferred_failures: list[tuple[str, Exception]] = []
        final_url = url

        try:
            resource = self._http.get(url, max_bytes=self._settings.source_max_text_bytes)
        except UnsafeSourceUrl:
            # Never turn an external reader into a proxy for a private URL.
            raise
        except (httpx.HTTPError, OSError, ValueError) as exc:
            deferred_failures.append(("DIRECT_FETCH_FAILED", exc))
        else:
            final_url = resource.final_url
            media_type = resource.content_type.split(";", 1)[0].strip().lower()
            if media_type.startswith("image/"):
                try:
                    image_segments, image_warnings = self._from_image(resource.data)
                    segments.extend(image_segments)
                    warnings.extend(image_warnings)
                except (httpx.HTTPError, OSError, ValueError, SourceAcquisitionFailure) as exc:
                    deferred_failures.append(("DIRECT_IMAGE_READ_FAILED", exc))
            elif media_type in {
                "text/html",
                "application/xhtml+xml",
                "text/plain",
                "application/octet-stream",
            }:
                html = resource.text()
                parsed = ExtractedHtml(html, final_url)
                main_text = _join_distinct(parsed.meta_description, parsed.text)
                main_text, removed_tail = _drop_unrelated_tail(main_text)
                if removed_tail:
                    warnings.append(WarningItem(
                        code="UNRELATED_TAIL_DROPPED",
                        message=f"기업정보 이후 타사 공고/광고 꼬리 {removed_tail}자를 제거했습니다.",
                        severity=WarningSeverity.INFO,
                    ))
                if main_text:
                    segments.append(self._segment(main_text, ExtractionMethod.HTML, len(segments)))

                iframe_urls = list(dict.fromkeys(
                    parsed.iframe_urls + derived_iframe_urls(final_url)
                ))
                if len(iframe_urls) > MAX_IFRAMES:
                    warnings.append(WarningItem(
                        code="IFRAME_LIMIT_REACHED",
                        message=f"iframe {len(iframe_urls)}개 중 {MAX_IFRAMES}개만 수집했습니다.",
                    ))
                for iframe_url in iframe_urls[:MAX_IFRAMES]:
                    try:
                        iframe = self._http.get(
                            iframe_url,
                            max_bytes=self._settings.source_max_text_bytes,
                            headers={"Referer": final_url},
                        )
                    except (httpx.HTTPError, OSError, ValueError, UnsafeSourceUrl) as exc:
                        deferred_failures.append(("IFRAME_FETCH_FAILED", exc))
                        continue
                    iframe_media = iframe.content_type.split(";", 1)[0].lower()
                    if iframe_media.startswith("image/"):
                        try:
                            image_segments, image_warnings = self._from_image(
                                iframe.data,
                                segment_offset=len(segments),
                            )
                            segments.extend(image_segments)
                            warnings.extend(image_warnings)
                        except (httpx.HTTPError, OSError, ValueError, SourceAcquisitionFailure) as exc:
                            deferred_failures.append(("IFRAME_IMAGE_READ_FAILED", exc))
                        continue
                    parsed_iframe = ExtractedHtml(iframe.text(), iframe.final_url)
                    iframe_text = _join_distinct(
                        parsed_iframe.meta_description,
                        parsed_iframe.text,
                    )
                    if len(iframe_text) >= MIN_MEANINGFUL_CHARS:
                        segments.append(self._segment(
                            iframe_text,
                            ExtractionMethod.IFRAME,
                            len(segments),
                        ))
                        continue
                    for image_url in parsed_iframe.image_urls[:MAX_IMAGES]:
                        try:
                            image = self._http.get(
                                image_url,
                                max_bytes=self._settings.source_max_image_bytes,
                                headers={"Referer": iframe.final_url},
                            )
                            image_segments, image_warnings = self._from_image(
                                image.data,
                                segment_offset=len(segments),
                            )
                            segments.extend(image_segments)
                            warnings.extend(image_warnings)
                        except (
                            httpx.HTTPError,
                            OSError,
                            ValueError,
                            UnsafeSourceUrl,
                            SourceAcquisitionFailure,
                        ) as exc:
                            deferred_failures.append(("IMAGE_FETCH_OR_READ_FAILED", exc))
            else:
                deferred_failures.append((
                    "DIRECT_CONTENT_TYPE_UNSUPPORTED",
                    ValueError(f"unsupported source content type: {media_type}"),
                ))

        # A URL fragment often selects one opening inside a client-rendered career
        # book. The base document can pass the coarse posting-text gate while still
        # describing the wrong (or no specific) position. For this URL shape, run
        # every configured dynamic collector once before the user verifies the text.
        collect_dynamic_route = bool(external_fragment.strip())
        direct_text = _merge_segments(segments)
        external_url = _with_fragment(final_url, external_fragment)
        if collect_dynamic_route:
            logger.info(
                "source dynamic-route collection enabled url=%s",
                external_url,
            )
        if (
            collect_dynamic_route or not _is_sufficient_posting_text(direct_text)
        ) and self._settings.jina_enabled:
            reader_target = quote(external_url, safe=":/?=&")
            reader_url = f"https://r.jina.ai/{reader_target}"
            headers = {"Accept": "text/plain"}
            if self._settings.jina_api_key:
                headers["Authorization"] = f"Bearer {self._settings.jina_api_key}"
            try:
                reader = self._http.get(
                    reader_url,
                    max_bytes=self._settings.source_max_text_bytes,
                    headers=headers,
                )
                reader_text, removed_tail = _drop_unrelated_tail(
                    _normalize_text(reader.text())
                )
                if reader_text:
                    segments.append(self._segment(
                        reader_text,
                        ExtractionMethod.DIRECT_TEXT,
                        len(segments),
                    ))
                    logger.info(
                        "source collector succeeded collector=jina chars=%d",
                        len(reader_text),
                    )
                    if removed_tail:
                        warnings.append(WarningItem(
                            code="UNRELATED_TAIL_DROPPED",
                            message=(
                                "기업정보 이후 타사 공고/광고 꼬리 "
                                f"{removed_tail}자를 제거했습니다."
                            ),
                            severity=WarningSeverity.INFO,
                        ))
            except (httpx.HTTPError, OSError, ValueError, UnsafeSourceUrl) as exc:
                deferred_failures.append(("JINA_FETCH_FAILED", exc))

        merged_text = _merge_segments(segments)
        if (
            (collect_dynamic_route or not _is_sufficient_posting_text(merged_text))
            and self._settings.firecrawl_enabled
            and self._settings.firecrawl_api_key
        ):
            try:
                firecrawl_text, removed_tail = _drop_unrelated_tail(
                    _normalize_text(self._extract_with_firecrawl(external_url))
                )
                if firecrawl_text:
                    segments.append(self._segment(
                        firecrawl_text,
                        ExtractionMethod.DIRECT_TEXT,
                        len(segments),
                    ))
                    logger.info(
                        "source collector succeeded collector=firecrawl chars=%d",
                        len(firecrawl_text),
                    )
                    if removed_tail:
                        warnings.append(WarningItem(
                            code="UNRELATED_TAIL_DROPPED",
                            message=(
                                "기업정보 이후 타사 공고/광고 꼬리 "
                                f"{removed_tail}자를 제거했습니다."
                            ),
                            severity=WarningSeverity.INFO,
                        ))
            except (httpx.HTTPError, OSError, ValueError) as exc:
                deferred_failures.append(("FIRECRAWL_FETCH_FAILED", exc))

        merged_text = _merge_segments(segments)
        if (
            (collect_dynamic_route or not _is_sufficient_posting_text(merged_text))
            and self._settings.tavily_enabled
            and self._settings.tavily_api_key
        ):
            try:
                tavily_text, removed_tail = _drop_unrelated_tail(
                    _normalize_text(self._extract_with_tavily(external_url))
                )
                if tavily_text:
                    segments.append(self._segment(
                        tavily_text,
                        ExtractionMethod.DIRECT_TEXT,
                        len(segments),
                    ))
                    logger.info(
                        "source collector succeeded collector=tavily chars=%d",
                        len(tavily_text),
                    )
                    if removed_tail:
                        warnings.append(WarningItem(
                            code="UNRELATED_TAIL_DROPPED",
                            message=(
                                "기업정보 이후 타사 공고/광고 꼬리 "
                                f"{removed_tail}자를 제거했습니다."
                            ),
                            severity=WarningSeverity.INFO,
                        ))
            except (httpx.HTTPError, OSError, ValueError) as exc:
                deferred_failures.append(("TAVILY_FETCH_FAILED", exc))

        merged_text = _merge_segments(segments)
        if deferred_failures:
            logger.info(
                "source URL collection completed with failed auxiliary paths: %s",
                ", ".join(code for code, _exc in deferred_failures),
            )
        if merged_text and not _is_sufficient_posting_text(merged_text):
            for code, exc in deferred_failures:
                warnings.append(WarningItem(code=code, message=str(exc)))

        return segments, warnings, final_url

    def _extract_with_firecrawl(self, url: str) -> str:
        with httpx.Client(timeout=self._settings.source_fetch_timeout_seconds) as client:
            response = client.post(
                FIRECRAWL_SCRAPE_URL,
                headers={
                    "Authorization": f"Bearer {self._settings.firecrawl_api_key}",
                },
                json={
                    "url": url,
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                    "waitFor": 2_000,
                    "timeout": int(
                        self._settings.source_fetch_timeout_seconds * 1_000
                    ),
                    "maxAge": 0,
                },
            )
            response.raise_for_status()
        if len(response.content) > self._settings.source_max_text_bytes:
            raise ValueError("Firecrawl response exceeds the source text safety limit")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ValueError("Firecrawl extraction was not successful")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Firecrawl extraction returned an invalid result")
        markdown = data.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            raise ValueError("Firecrawl extraction returned no readable content")
        return markdown

    def _extract_with_tavily(self, url: str) -> str:
        with httpx.Client(timeout=self._settings.source_fetch_timeout_seconds) as client:
            response = client.post(
                TAVILY_EXTRACT_URL,
                headers={
                    "Authorization": f"Bearer {self._settings.tavily_api_key}",
                },
                json={
                    "urls": url,
                    "extract_depth": "advanced",
                    "format": "text",
                    "include_images": False,
                },
            )
            response.raise_for_status()
        if len(response.content) > self._settings.source_max_text_bytes:
            raise ValueError("Tavily response exceeds the source text safety limit")
        payload = response.json()
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or not results:
            raise ValueError("Tavily extraction returned no result")
        result = results[0]
        if not isinstance(result, dict):
            raise ValueError("Tavily extraction returned an invalid result")
        raw_content = result.get("raw_content")
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise ValueError("Tavily extraction returned no readable content")
        return raw_content

    def _from_image(
        self,
        image_bytes: bytes,
        *,
        segment_offset: int = 0,
    ) -> tuple[list[ExtractionSegment], list[WarningItem]]:
        if isinstance(self._image, ClovaImageRecognizer) and not self._image.configured:
            raise SourceAcquisitionFailure(
                code=ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
                message="image extraction requires CLOVA_API_KEY",
                retryable=False,
            )
        tiles, omitted = split_image_tiles(image_bytes)
        warnings: list[WarningItem] = []
        if omitted:
            warnings.append(WarningItem(
                code="IMAGE_TILES_OMITTED",
                message=f"긴 이미지의 가운데 {omitted}개 타일이 안전 한도로 생략되었습니다.",
            ))
        segments: list[ExtractionSegment] = []
        for index, tile in enumerate(tiles):
            recognized = self._image.recognize(tile)
            text = _normalize_text(recognized.text)
            if not text:
                warnings.append(WarningItem(
                    code="IMAGE_TILE_EMPTY",
                    message=f"이미지 타일 {index + 1}에서 텍스트를 읽지 못했습니다.",
                ))
                continue
            segments.append(self._segment(
                text,
                ExtractionMethod.VLM,
                segment_offset + index,
                confidence=recognized.confidence,
                source_locator=SourceLocator(
                    image_index=index,
                    bounding_box=(0.0, tile.top_ratio, 1.0, tile.bottom_ratio),
                ),
                overlap_group="image-tiles" if len(tiles) > 1 else None,
            ))
        if segments and all(item.confidence is None for item in segments):
            warnings.append(WarningItem(
                code="EXTRACTION_CONFIDENCE_UNAVAILABLE",
                message="이미지 공급자가 신뢰도 수치를 제공하지 않아 사용자 확인이 필요합니다.",
                severity=WarningSeverity.INFO,
            ))
        return segments, warnings

    @staticmethod
    def _segment(
        text: str,
        method: ExtractionMethod,
        index: int,
        *,
        confidence: float | None = None,
        source_locator: SourceLocator | None = None,
        overlap_group: str | None = None,
    ) -> ExtractionSegment:
        fingerprint = hashlib.sha256(f"{method.value}:{index}:{text}".encode()).hexdigest()[:16]
        locator = source_locator
        if locator is None:
            locator = SourceLocator(char_start=0, char_end=len(text))
        return ExtractionSegment(
            segment_id=f"seg-{fingerprint}",
            text=text,
            method=method,
            source_locator=locator,
            confidence=confidence,
            overlap_group=overlap_group,
        )


def require_verified_snapshot(
    source: SourceDocument,
    snapshot: VerifiedPostingSnapshot | None,
) -> VerifiedPostingSnapshot:
    if (
        source.status is not SourceStatus.VERIFIED
        or snapshot is None
        or snapshot.source_document_id != source.source_document_id
        or snapshot.source_revision != source.extraction_revision
    ):
        raise SourceAcquisitionFailure(
            code=ErrorCode.SOURCE_NOT_VERIFIED,
            message="공고 원문을 먼저 확인해주세요.",
            retryable=False,
        )
    return snapshot


def _validate_correction(before_text: str, verified_text: str, correction: PostingCorrection) -> None:
    if correction.before and correction.before not in before_text:
        raise ValueError(f"correction before text was not present: {correction.field}")
    if correction.after not in verified_text:
        raise ValueError(f"correction after text is missing from verifiedText: {correction.field}")


def _verified_evidence_segments(text: str) -> list[ExtractionSegment]:
    segments: list[ExtractionSegment] = []
    cursor = 0
    parts = [part.strip() for part in re.split(r"\n+|(?<=[.!?。])\s+", text) if part.strip()]
    for index, part in enumerate(parts):
        start = text.find(part, cursor)
        if start < 0:
            start = text.find(part)
        end = start + len(part)
        cursor = max(cursor, end)
        fingerprint = hashlib.sha256(f"{index}:{part}".encode()).hexdigest()[:16]
        segments.append(ExtractionSegment(
            segment_id=f"vseg-{fingerprint}",
            text=part,
            method=ExtractionMethod.USER_PASTE,
            source_locator=SourceLocator(char_start=start, char_end=end),
            confidence=1.0,
        ))
    return segments


def _normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    value = "\n".join(line.rstrip() for line in value.splitlines())
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _join_distinct(*parts: str) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = _normalize_text(part)
        key = re.sub(r"\s+", " ", normalized).casefold()
        if normalized and key not in seen:
            seen.add(key)
            output.append(normalized)
    return "\n\n".join(output)


_TAIL_MARKERS = (
    "## 스마트픽",
    "[기업정보 전체보기]",
    "공고를 확인해 보세요",
)


def _drop_unrelated_tail(text: str) -> tuple[str, int]:
    cuts = [index for marker in _TAIL_MARKERS if (index := text.find(marker)) != -1]
    if not cuts:
        return text, 0
    cut = min(cuts)
    return text[:cut].rstrip(), len(text) - cut


def _merge_segments(segments: list[ExtractionSegment]) -> str:
    output: list[str] = []
    overlap_seen: dict[str, set[str]] = {}
    for segment in segments:
        if not segment.overlap_group:
            output.append(segment.text)
            continue
        seen = overlap_seen.setdefault(segment.overlap_group, set())
        kept: list[str] = []
        for line in segment.text.splitlines():
            key = re.sub(r"\s+", " ", line).strip().casefold()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            kept.append(line)
        merged = _normalize_text("\n".join(kept))
        if merged:
            output.append(merged)
    return _join_distinct(*output)


_RESPONSIBILITY_SIGNALS = (
    "담당업무", "주요 업무", "주요업무", "하는 일", "업무 내용",
    "responsibilities", "what you'll do", "role description",
)
_REQUIREMENT_SIGNALS = (
    "자격요건", "자격 요건", "지원자격", "지원 자격",
    "필수 요건", "필수요건", "요구사항",
    "requirements", "qualifications", "what we're looking for",
)
_PREFERENCE_SIGNALS = (
    "우대사항", "우대 사항", "preferred", "nice to have", "우대 요건",
)
_EMPLOYMENT_SIGNALS = (
    "채용", "모집", "고용형태", "고용 형태", "근무형태", "근무 형태", "경력", "신입",
    "employment", "career", "experience",
)


def _looks_like_posting(text: str) -> bool:
    return _posting_signal_groups(text)[0] >= 2


def _is_sufficient_posting_text(text: str) -> bool:
    normalized = _normalize_for_posting_quality(text)
    signal_groups, responsibilities, requirements = _posting_signal_groups(
        normalized,
        normalized=True,
    )
    return (
        len(normalized) >= MINIMUM_USEFUL_POSTING_LENGTH
        and signal_groups >= 2
        and (responsibilities or requirements)
    )


def _normalize_for_posting_quality(text: str) -> str:
    # Keep this contract aligned with backend PostingContentQuality.
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _posting_signal_groups(
    text: str,
    *,
    normalized: bool = False,
) -> tuple[int, bool, bool]:
    value = text if normalized else _normalize_for_posting_quality(text)
    responsibilities = _contains_any(value, _RESPONSIBILITY_SIGNALS)
    requirements = _contains_any(value, _REQUIREMENT_SIGNALS)
    groups = int(responsibilities) + int(requirements)
    groups += int(_contains_any(value, _PREFERENCE_SIGNALS))
    groups += int(_contains_any(value, _EMPLOYMENT_SIGNALS))
    return groups, responsibilities, requirements


def _contains_any(value: str, signals: tuple[str, ...]) -> bool:
    return any(signal in value for signal in signals)


def _with_fragment(url: str, fragment: str) -> str:
    if not fragment:
        return url
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, fragment))


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"

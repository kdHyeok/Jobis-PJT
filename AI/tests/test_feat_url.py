"""기존 feat_url 진입점이 공통 SourceAcquisition 계약을 쓰는지 검증한다."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

import jobis_ai.feat_url as feat_url
from jobis_ai.career_pipeline.contracts.common import WarningItem
from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.contracts.source import SourceEntryPoint, SourceInputType
from jobis_ai.career_pipeline.source.service import SourceAcquisitionFailure


PAGE_URL = "https://www.jobkorea.example/Recruit/GI_Read/49664777"


def test_fetch_job_posting_delegates_to_shared_source_contract(monkeypatch) -> None:
    captured = []

    class FakeService:
        def __init__(self, *, settings) -> None:
            assert settings is not None

        def acquire(self, request):
            captured.append(request)
            return SimpleNamespace(
                raw_text="백엔드 개발자 채용\n지원 자격: Java",
                warnings=[WarningItem(code="SAMPLE_WARNING", message="확인 필요")],
            )

    monkeypatch.setattr(feat_url, "SourceAcquisitionService", FakeService)

    result = feat_url.fetch_job_posting(PAGE_URL)

    assert result.text.startswith("백엔드 개발자 채용")
    assert result.warnings == [{"code": "SAMPLE_WARNING", "message": "확인 필요"}]
    assert captured[0].input_type is SourceInputType.URL
    assert captured[0].entry_point is SourceEntryPoint.INTERNAL
    assert captured[0].url == PAGE_URL


def test_fetch_job_posting_requests_manual_input_only_after_shared_failure(monkeypatch) -> None:
    class FailingService:
        def __init__(self, *, settings) -> None:
            pass

        def acquire(self, request):
            raise SourceAcquisitionFailure(
                code=ErrorCode.SOURCE_FETCH_FAILED,
                message="all collectors failed",
                retryable=True,
            )

    monkeypatch.setattr(feat_url, "SourceAcquisitionService", FailingService)

    result = feat_url.fetch_job_posting(PAGE_URL)

    assert result.text == ""
    assert result.warnings == [{
        "code": "source_fetch_failed",
        "message": (
            "공고 원문을 자동으로 수집하지 못했습니다. "
            "원문을 붙여넣거나 공고 이미지를 첨부해주세요."
        ),
    }]


def test_tall_image_is_sliced_into_tiles() -> None:
    from jobis_ai.extract import ExtractResult

    Image = pytest.importorskip("PIL.Image")
    result = ExtractResult(text="")
    buffer = io.BytesIO()
    Image.new("RGB", (940, 9400), (255, 255, 255)).save(buffer, "PNG")

    tiles = feat_url._vlm_tiles(buffer.getvalue(), result, "tall.png")

    assert 1 < len(tiles) <= feat_url._MAX_VLM_TILES
    assert all(tile.startswith("data:image/jpeg;base64,") for tile in tiles)

"""기존 에이전트 입력과 통합 SourceAcquisition 계약의 호환 어댑터.

URL 수집의 실제 구현은 ``career_pipeline.source.SourceAcquisitionService`` 하나다.
이 모듈은 기존 ``ExtractResult`` 소비자와 파일 이미지 VLM 경로의 호환성만 유지한다.
"""

from __future__ import annotations

import contextvars
import json
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..career_pipeline.config import Settings as SourceSettings
from ..career_pipeline.contracts.source import (
    SourceAcquisitionRequest,
    SourceEntryPoint,
    SourceInputType,
)
from ..career_pipeline.source.service import (
    SourceAcquisitionFailure,
    SourceAcquisitionService,
)
from ..config import get_settings
from ..extract import ExtractResult


logger = logging.getLogger(__name__)

_VLM_TILE_MAX_WIDTH = 1440
_VLM_TILE_ASPECT = 2
_VLM_TILE_OVERLAP = 100
_MAX_VLM_TILES = 8
_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_VLM_PROMPT = (
    "이 이미지는 채용공고의 일부다. 이미지에 있는 모든 텍스트를 빠짐없이, "
    "레이아웃 순서대로 그대로 옮겨 적어라. 요약하거나 해석하지 마라."
)


def _clova_vlm(image_content: dict, result: ExtractResult, label: str) -> str:
    settings = get_settings()
    if not settings.clova_api_key:
        result.warn("clova_no_key", "CLOVA_API_KEY 미설정 — 이미지 공고 텍스트를 건너뜁니다.")
        return ""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    image_content,
                    {"type": "text", "text": _VLM_PROMPT},
                ],
            }
        ],
        "maxTokens": 2048,
    }
    try:
        request = urllib.request.Request(
            settings.clova_vlm_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.clova_api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            data = json.loads(response.read().decode("utf-8"))
        content = (data.get("result", {}).get("message", {}).get("content") or "").strip()
        if "답변을 제공해 드릴 수 없" in content or "답변할 수 없" in content:
            result.warn("clova_vlm_refused", f"Clova VLM이 응답을 거부함({label})")
            return ""
        return content
    except Exception as exc:  # noqa: BLE001 - 공급자 실패는 기존 warning 계약으로 변환한다
        result.warn("clova_vlm_error", f"Clova VLM 호출 실패({label}): {exc}")
        return ""


def _vlm_tiles(data: bytes, result: ExtractResult, label: str) -> list[str]:
    """긴 공고 이미지를 해상도를 유지한 JPEG data URI 타일로 나눈다."""

    import base64
    import io

    try:
        from PIL import Image
    except ImportError:
        result.warn("pillow_missing", "pillow 미설치 — 이미지 공고를 쪼갤 수 없어 건너뜁니다.")
        return []
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001 - 깨진 사용자 이미지도 warning으로 돌려준다
        result.warn("image_decode_error", f"이미지를 읽지 못했습니다({label}): {exc}")
        return []

    if image.mode not in ("RGB", "L"):
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image, mask=image.convert("RGBA").split()[-1])
        image = flat
    else:
        image = image.convert("RGB")

    width, height = image.size
    if width > _VLM_TILE_MAX_WIDTH:
        height = round(height * _VLM_TILE_MAX_WIDTH / width)
        width = _VLM_TILE_MAX_WIDTH
        image = image.resize((width, height), Image.LANCZOS)

    tile_height = width * _VLM_TILE_ASPECT
    step = max(1, tile_height - _VLM_TILE_OVERLAP)
    tops = list(range(0, height, step)) or [0]
    if len(tops) > 1 and height - tops[-1] <= _VLM_TILE_OVERLAP:
        tops.pop()
    if len(tops) > _MAX_VLM_TILES:
        result.warn(
            "vlm_tiles_capped",
            f"이미지 공고 {len(tops)}조각 중 앞 {_MAX_VLM_TILES}조각만 읽습니다({label}).",
        )
        tops = tops[:_MAX_VLM_TILES]

    uris: list[str] = []
    for top in tops:
        buffer = io.BytesIO()
        image.crop((0, top, width, min(top + tile_height, height))).save(
            buffer,
            "JPEG",
            quality=80,
        )
        uris.append(
            "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        )
    return uris


def clova_vlm_file(path: str, result: ExtractResult) -> str:
    """로컬 공고 캡처 이미지를 타일 단위로 읽어 기존 파일 입력 계약으로 반환한다."""

    image_path = Path(path)
    if image_path.suffix.lower() not in _MIME_BY_EXT:
        result.warn("unsupported_image_type", f"지원하지 않는 이미지 형식: {image_path.suffix}")
        return ""
    tiles = _vlm_tiles(image_path.read_bytes(), result, image_path.name)
    if not tiles:
        return ""
    with ThreadPoolExecutor(max_workers=min(4, len(tiles))) as pool:
        futures = [
            pool.submit(
                contextvars.copy_context().run,
                _clova_vlm,
                {"type": "image_url", "dataUri": {"data": tile}},
                result,
                f"{image_path.name} 조각 {index + 1}/{len(tiles)}",
            )
            for index, tile in enumerate(tiles)
        ]
        parts = [future.result() for future in futures]
    return "\n\n".join(part for part in parts if part)


def fetch_job_posting(url: str) -> ExtractResult:
    """공고 URL을 공통 SourceAcquisition 계약으로 수집해 기존 결과형으로 변환한다."""

    result = ExtractResult(text="")
    try:
        source = SourceAcquisitionService(settings=SourceSettings.from_env()).acquire(
            SourceAcquisitionRequest(
                input_type=SourceInputType.URL,
                entry_point=SourceEntryPoint.INTERNAL,
                url=url,
            )
        )
    except SourceAcquisitionFailure as exc:
        logger.warning("job posting source acquisition failed: code=%s", exc.code.value)
        result.warn(
            "source_fetch_failed",
            "공고 원문을 자동으로 수집하지 못했습니다. 원문을 붙여넣거나 공고 이미지를 첨부해주세요.",
        )
        return result

    result.text = source.raw_text
    for warning in source.warnings:
        result.warn(warning.code, warning.message)
    return result

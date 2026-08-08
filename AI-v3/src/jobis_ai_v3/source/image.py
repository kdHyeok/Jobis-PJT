from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Protocol

import httpx
from PIL import Image


VLM_PROMPT = (
    "이 이미지는 채용 공고 원문입니다. 이미지에 보이는 모든 텍스트를 레이아웃 순서대로 "
    "빠짐없이 옮겨 적으세요. 요약, 해석, 경력 숫자 보정, 직무 추론을 하지 마세요. "
    "읽을 수 없는 부분은 [판독 불가]라고 표시하세요."
)


@dataclass(frozen=True, slots=True)
class ImageTile:
    index: int
    total: int
    top_ratio: float
    bottom_ratio: float
    jpeg_bytes: bytes


@dataclass(frozen=True, slots=True)
class RecognizedTile:
    tile: ImageTile
    text: str
    confidence: float | None = None


class ImageRecognizer(Protocol):
    def recognize(self, tile: ImageTile) -> RecognizedTile: ...


class ClovaImageRecognizer:
    def __init__(self, *, api_key: str, endpoint: str, timeout_seconds: float = 120.0) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._endpoint)

    def recognize(self, tile: ImageTile) -> RecognizedTile:
        encoded = base64.b64encode(tile.jpeg_bytes).decode("ascii")
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "dataUri": {"data": f"data:image/jpeg;base64,{encoded}"},
                    },
                    {"type": "text", "text": VLM_PROMPT},
                ],
            }],
            "maxTokens": 4096,
        }
        response = httpx.post(
            self._endpoint,
            json=body,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = str(payload.get("result", {}).get("message", {}).get("content") or "").strip()
        if not content:
            raise ValueError("image provider returned no extracted text")
        if "답변을 제공해 드릴 수 없" in content or "답변할 수 없" in content:
            raise ValueError("image provider refused to read the source image")
        return RecognizedTile(tile=tile, text=content, confidence=None)


def decode_image_base64(value: str, *, max_bytes: int) -> bytes:
    payload = value.strip()
    if payload.startswith("data:"):
        _, separator, payload = payload.partition(",")
        if not separator:
            raise ValueError("invalid image data URI")
    try:
        data = base64.b64decode(payload, validate=True)
    except ValueError as exc:
        raise ValueError("imageBase64 is not valid base64") from exc
    if not data:
        raise ValueError("image payload is empty")
    if len(data) > max_bytes:
        raise ValueError(f"image exceeds the {max_bytes} byte safety limit")
    return data


def split_image_tiles(
    data: bytes,
    *,
    max_width: int = 1440,
    aspect: int = 2,
    overlap: int = 100,
    max_tiles: int = 12,
) -> tuple[list[ImageTile], int]:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001 - decoder errors are user-facing source errors
        raise ValueError("uploaded image could not be decoded") from exc
    if image.width < 1 or image.height < 1:
        raise ValueError("uploaded image has invalid dimensions")

    if image.mode not in {"RGB", "L"}:
        rgba = image.convert("RGBA")
        flattened = Image.new("RGB", image.size, (255, 255, 255))
        flattened.paste(rgba, mask=rgba.getchannel("A"))
        image = flattened
    else:
        image = image.convert("RGB")

    if image.width > max_width:
        resized_height = round(image.height * max_width / image.width)
        image = image.resize((max_width, resized_height), Image.Resampling.LANCZOS)

    width, height = image.size
    tile_height = width * aspect
    step = max(1, tile_height - overlap)
    tops = list(range(0, height, step)) or [0]
    if len(tops) > 1 and height - tops[-1] <= overlap:
        tops.pop()
    original_count = len(tops)
    if len(tops) > max_tiles:
        head = (max_tiles + 1) // 2
        tail = max_tiles - head
        tops = tops[:head] + (tops[-tail:] if tail else [])

    tiles: list[ImageTile] = []
    for index, top in enumerate(tops):
        bottom = min(top + tile_height, height)
        output = io.BytesIO()
        image.crop((0, top, width, bottom)).save(output, "JPEG", quality=84, optimize=True)
        tiles.append(ImageTile(
            index=index,
            total=len(tops),
            top_ratio=top / height,
            bottom_ratio=bottom / height,
            jpeg_bytes=output.getvalue(),
        ))
    return tiles, original_count - len(tiles)

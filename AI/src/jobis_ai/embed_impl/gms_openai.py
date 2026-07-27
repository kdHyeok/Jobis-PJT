"""GMS(SSAFY API 게이트웨이) 경유 OpenAI 임베딩 어댑터.

`https://gms.ssafy.io/gmsapi/api.openai.com/v1` 로 OpenAI 호환 임베딩 API 를 프록시한다.
인증은 `Authorization: Bearer <GMS_KEY>`.

공식 `openai` SDK(httpx 기반)를 쓴다 — 처음엔 표준 라이브러리 `urllib` 로 직접 호출했는데,
GMS 응답이 `http.client.IncompleteRead` 를 유발해(청크 전송/길이 처리 이슈로 추정) 그대로
두면 이 모듈의 "예외를 던지지 않는다" 규칙이 깨졌다. `openai` SDK 는 이미 `langchain-openai`
의존성으로 설치돼 있고 전송 계층을 훨씬 견고하게 처리하므로 이걸로 교체했다.

**절대 규칙(embed.py 와 동일): 예외를 던지지 않는다.** 실패해도 `EmbedResult(warnings=[...])`
로 정상 반환하고, `similarity`/`similarity_matrix` 는 판정 불가 시 `None`(0.0 아님)을 돌려준다.
"""

from __future__ import annotations

import math

from jobis_ai.config import get_settings
from jobis_ai.embed import EmbedResult


class GmsOpenAIEmbedder:
    """`Embedder` 계약 구현체. GMS_KEY 로 인증해 OpenAI 임베딩 모델을 호출한다."""

    def embed(self, texts: list[str]) -> EmbedResult:
        if not texts:
            return EmbedResult()

        settings = get_settings()
        if not settings.has_embed_key:
            return EmbedResult(warnings=[{
                "code": "embed_not_configured",
                "message": "GMS_KEY가 설정되지 않아 임베딩을 호출하지 않습니다.",
            }])

        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=settings.gms_key,
                base_url=settings.embed_base_url,
                timeout=20,
                max_retries=2,
            )
            response = client.embeddings.create(model=settings.embed_model, input=texts)
        except Exception as exc:  # noqa: BLE001 — 절대 규칙: 무엇이 터지든 예외를 밖으로 던지지 않는다
            return EmbedResult(warnings=[{
                "code": "embed_call_failed",
                "message": f"임베딩 호출 실패: {exc}",
            }])

        try:
            # OpenAI 임베딩 API는 입력 순서를 보장하지만, index로 한 번 더 정렬해 방어한다.
            items = sorted(response.data, key=lambda d: d.index)
            vectors = [item.embedding for item in items]
        except (AttributeError, TypeError) as exc:
            return EmbedResult(warnings=[{
                "code": "embed_bad_response",
                "message": f"임베딩 응답 형식이 예상과 다릅니다: {exc}",
            }])

        return EmbedResult(vectors=vectors)

    def similarity(self, left: str, right: str) -> float | None:
        result = self.embed([left, right])
        if len(result.vectors) != 2:
            return None
        return _cosine(result.vectors[0], result.vectors[1])

    def similarity_matrix(
        self, lefts: list[str], rights: list[str]
    ) -> list[list[float]] | None:
        if not lefts or not rights:
            return None

        # 한 번의 배치 호출로 lefts+rights 를 전부 임베딩(§embed.py 배치 취지).
        result = self.embed([*lefts, *rights])
        if len(result.vectors) != len(lefts) + len(rights):
            return None

        left_vecs = result.vectors[: len(lefts)]
        right_vecs = result.vectors[len(lefts):]
        return [[_cosine(lv, rv) for rv in right_vecs] for lv in left_vecs]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

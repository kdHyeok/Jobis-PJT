"""테스트 공통 설정.

자동 테스트는 실제 LLM/임베딩을 호출하지 않는다(결정적·고속·CI 친화). `.env`에 실제
GMS_KEY/EMBED_PROVIDER=openai/LLM_PROVIDER=openai 가 들어있어도(2026-07-20 GMS 연결),
테스트는 항상 미설정 상태로 강제한다 — 그래야 네트워크 없이, 비용 없이, 결정적으로 돈다.
실제 LLM/임베딩 동작 확인은 `tests/run_user1.py`(수동 실행)가 담당한다.
"""

from __future__ import annotations

import pytest

from jobis_ai.embed import NullEmbedder
from jobis_ai.llm import LLMNotConfiguredError


@pytest.fixture(autouse=True)
def force_mock_llm(monkeypatch):
    """structured.run_structured 가 (None, warnings) 를 반환 → 노드가 mock 폴백.

    gap_matcher 의 domain_keyword LLM 폴백(semantic_judge.judge_domain_relevance)도
    내부적으로 run_structured 를 쓰므로, 이 하나로 같이 막힌다.
    """

    def _raise(*_args, **_kwargs):
        raise LLMNotConfiguredError("test: LLM 강제 미설정(mock 폴백)")

    monkeypatch.setattr("jobis_ai.structured.get_llm", _raise)


@pytest.fixture(autouse=True)
def force_null_embedder(monkeypatch):
    """skill_taxonomy 가 실제 임베딩 API를 호출하지 않도록 강제한다.

    `from jobis_ai.embed import get_embedder` 로 이름을 자기 네임스페이스에 바인딩해서
    쓰므로, `jobis_ai.embed.get_embedder` 하나만 패치해선 안 먹는다 — 그 모듈에서 참조하는
    이름을 직접 패치해야 한다. (gap_matcher 는 2026-07-20부터 임베딩을 쓰지 않는다 — 서술형
    요구사항/도메인 키워드 2차 매칭이 LLM 의미 판정으로 바뀌었다. `force_mock_llm` 이 그쪽을
    막는다. docs/troubleshooting.md 2026-07-20 참고.)
    """

    monkeypatch.setattr("jobis_ai.skill_taxonomy.get_embedder", lambda: NullEmbedder())

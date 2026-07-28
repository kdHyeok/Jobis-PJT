"""LLM 기반 의미 관련성 판정 (semantic_judge) — §0 3계층 원칙의 명시적 예외.

**왜 예외인가**: `gap_matcher`의 3차 도메인 키워드 매칭은 원래 포함 매칭(룰)이 1차이고,
그걸로 못 잡으면 임베딩 유사도로 보강할 계획이었다(`skill_taxonomy`의 하이브리드와 동일
패턴). 그런데 실측(2026-07-20, `text-embedding-3-small`/`-large` 둘 다)에서 짧은 도메인
키워드 vs 기술 문장 비교에 **관련 없는 쌍이 관련 있는 쌍보다 더 높은 점수**를 주는 역전이
반복 재현됐다(예: "React"가 "Kafka"보다 "이벤트 드리븐 아키텍처"와 더 유사하다고 나옴).
임계값을 조정해도 못 고치는 근본적인 신호 부족이라 판단해, **이 판정 하나에 한해** LLM을
판단 계층에 쓰기로 팀이 결정했다(§0 원칙 위반을 인지한 상태의 의도적·국소적 예외).

**위험을 줄이는 장치**:
- 자유 서술 대신 **구조화 출력**(관련 문장의 인덱스 배열만) — 판단 이유를 지어내지 못하게
  막는다. `run_structured`(읽기 계층 인프라)를 그대로 재사용해 새 LLM 호출 경로를 안 만든다.
- `gap_matcher`의 3차 경로는 여전히 **포함 매칭(룰)이 먼저**다. 이 함수는 포함 매칭이
  실패했을 때만 호출되는 **폴백**이다.
- LLM 미설정/호출 실패는 예외를 던지지 않고 **None**(모른다)을 돌려준다. 호출부(`gap_matcher`)
  는 이걸 `not_met`이 아니라 `uncertain`으로 처리해야 한다(모른다/아니다 구분 원칙, gap_matcher.py 상단 참고).
- **이 패턴을 다른 판단 노드로 넓히지 말 것.** 여기 예외는 딱 이 케이스(실측으로 임베딩이
  실패)에만 근거가 있다 — "이것도 LLM이 편하겠다"며 따라 쓰면 §0 원칙이 형해화된다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from jobis_ai.structured import run_structured

_SYSTEM_PROMPT = (
    "당신은 도메인 관련성만 판정하는 분류기입니다. 번호 매겨진 topic(도메인 키워드/요구사항 문장)"
    "각각이 번호 매겨진 문장들과 의미상 관련이 있는지만 봅니다.\n"
    "- 새로운 사실을 지어내지 마세요. 주어진 문장에 있는 내용만 근거로 삼으세요.\n"
    "- 판단 이유를 설명하지 말고, topic 마다 관련 있는 문장의 번호만 배열로 반환하세요.\n"
    "- 모든 topic 에 대해 하나씩 답하세요. 관련 문장이 없으면 빈 배열입니다.\n"
    "- 애매하면 포함하지 마세요(관련 없음으로 처리)."
)


class _TopicRelevance(BaseModel):
    """주제 하나에 관련된 근거들. 인덱스만 다룬다 — 문장을 새로 쓰지 않는다."""

    topicIndex: int = Field(default=0, description="판정 대상 주제의 인덱스(입력 topics 순서, 0부터).")
    relatedIndexes: list[int] = Field(default_factory=list, description=(
        "이 주제와 실제로 관련된 근거의 인덱스 목록(입력 evidences 순서, 0부터). "
        "관련이 분명한 것만 넣는다. 없으면 빈 목록."))


class _BatchRelevance(BaseModel):
    """주제 전부에 대한 판정. 입력으로 준 주제를 빠뜨리지 않는다."""

    topics: list[_TopicRelevance] = Field(default_factory=list, description=(
        "입력 topics 전부에 대해 한 건씩. 관련 근거가 없는 주제도 빈 relatedIndexes 로 포함한다."))


# 배치 판정 결과 캐시 — check_sufficiency 와 analyze_gap 이 같은 (요구사항, 근거) 조합으로
# match() 를 두 번 부르므로, 두 번째 호출은 LLM 없이 여기서 끝난다 (2026-07-23 성능 개선).
# 프로세스 생명주기 캐시라 요청 간 재사용도 되지만, 키가 내용 전체라 오염은 없다.
_batch_cache: dict[tuple, dict[int, list[int]]] = {}


def clear_cache() -> None:
    """테스트 격리용."""

    _batch_cache.clear()


def judge_topics_relevance(
    topics: list[str], evidence_texts: list[str]
) -> dict[int, list[int]] | None:
    """여러 topic 을 **한 번의 LLM 호출**로 판정한다 (2026-07-23 배치화).

    기존에는 topic 마다 개별 호출이라 요구사항이 많은 공고에서 판정 한 번에 수 분이
    걸렸다(gpt-5-nano 콜당 수십 초 × N건 × 노드 2곳). 판정 기준은 단건과 동일하다 —
    묶는 것은 호출이지 판단이 아니다.

    반환: {입력 topics 의 인덱스: 관련 문장 인덱스 목록} | None(전체 판정 불가).
    빈 topic 은 결과 dict 에서 빠진다(호출부가 uncertain 처리).
    """

    texts = [t for t in evidence_texts if t]
    valid = [(i, t) for i, t in enumerate(topics) if t and t.strip()]
    if not valid or not texts:
        return None

    cache_key = (tuple(t for _, t in valid), tuple(texts))
    cached = _batch_cache.get(cache_key)
    if cached is not None:
        return {orig_i: cached[pos] for pos, (orig_i, _) in enumerate(valid) if pos in cached}

    numbered_topics = "\n".join(f"{pos}. {t}" for pos, (_, t) in enumerate(valid))
    numbered_texts = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
    user_content = f"[topics]\n{numbered_topics}\n\n[문장 목록]\n{numbered_texts}"

    # 이진 센서(관련 문장 번호만)는 경량 모델로 충분 — 해석·집계는 어차피 코드가 한다.
    result, _warnings = run_structured(
        _BatchRelevance, _SYSTEM_PROMPT, user_content, node="domain_keyword_judge", tier="light"
    )
    if result is None:
        return None

    by_pos: dict[int, list[int]] = {
        item.topicIndex: [i for i in item.relatedIndexes if 0 <= i < len(texts)]
        for item in result.topics
        if 0 <= item.topicIndex < len(valid)
    }
    # LLM 이 일부 topic 을 빼먹으면 '관련 없음'이 아니라 '무응답'이다 — 빈 배열로 채우지
    # 않고 결과에서 제외해 호출부가 uncertain 으로 처리하게 한다(모른다/아니다 구분 원칙).
    _batch_cache[cache_key] = by_pos
    return {orig_i: by_pos[pos] for pos, (orig_i, _) in enumerate(valid) if pos in by_pos}


def judge_domain_relevance(topic: str, evidence_texts: list[str]) -> list[int] | None:
    """단건 판정 — 배치 함수의 특수형. 캐시도 공유한다.

    반환: 관련된 인덱스 리스트(없으면 빈 리스트) | None(판정 불가 — LLM 미설정/호출 실패).
    None은 호출부가 `uncertain`으로 처리해야 한다. **절대 예외를 던지지 않는다**
    (`run_structured`가 이미 이 규칙을 보장한다 — 재시도 후 실패해도 (None, warnings)로 반환).
    """

    result = judge_topics_relevance([topic], evidence_texts)
    if result is None:
        return None
    return result.get(0)

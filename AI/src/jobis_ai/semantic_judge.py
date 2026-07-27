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
    "당신은 도메인 관련성만 판정하는 분류기입니다. 주어진 topic(도메인 키워드)이 "
    "번호 매겨진 문장들과 의미상 관련이 있는지만 봅니다.\n"
    "- 새로운 사실을 지어내지 마세요. 주어진 문장에 있는 내용만 근거로 삼으세요.\n"
    "- 판단 이유를 설명하지 말고, 관련 있는 문장의 번호만 배열로 반환하세요.\n"
    "- 애매하면 포함하지 마세요(관련 없음으로 처리)."
)


class _DomainRelevance(BaseModel):
    relatedIndexes: list[int] = Field(default_factory=list)


def judge_domain_relevance(topic: str, evidence_texts: list[str]) -> list[int] | None:
    """topic과 의미상 관련된 evidence_texts의 인덱스 목록을 LLM으로 판정한다.

    반환: 관련된 인덱스 리스트(없으면 빈 리스트) | None(판정 불가 — LLM 미설정/호출 실패).
    None은 호출부가 `uncertain`으로 처리해야 한다. **절대 예외를 던지지 않는다**
    (`run_structured`가 이미 이 규칙을 보장한다 — 재시도 후 실패해도 (None, warnings)로 반환).
    """

    texts = [t for t in evidence_texts if t]
    if not topic.strip() or not texts:
        return None

    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
    user_content = f"topic: {topic}\n\n문장 목록:\n{numbered}"

    result, _warnings = run_structured(
        _DomainRelevance, _SYSTEM_PROMPT, user_content, node="domain_keyword_judge"
    )
    if result is None:
        return None
    return [i for i in result.relatedIndexes if 0 <= i < len(texts)]

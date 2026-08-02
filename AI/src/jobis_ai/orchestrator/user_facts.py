"""사용자 발화의 지속 사실(목표·제약·상황)을 추출해 세션에 누적한다 (D82).

읽기 계층(§1)이다 — 비정형 발화 → 정형 사실 목록. 판단하지 않고, 발화에 실제로 있는
것만 옮긴다. "9월까지 취업하고 싶다", "야간 근무는 어렵다", "부산 거주" 같은 사실이
한 턴 지나면 사라져 에이전트들이 매번 백지에서 시작하던 것을 고친다 — 이력서·공고가
자산으로 남듯, 발화 속 중요 사실도 자산으로 남는다.

비용: 턴당 경량(light) 콜 1회. 문서 붙여넣기(긴 발화)는 자료이지 발화가 아니므로 건너뛴다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from jobis_ai.structured import run_structured

# 세션에 누적 보관할 사실 상한 — 넘치면 오래된 것부터 버린다.
_MAX_FACTS = 20
# 이보다 긴 발화는 붙여넣은 문서(이력서·공고)일 가능성이 높다 — 자료는 인테이크가 담당한다.
_SKIP_OVER_CHARS = 600


class _FactsRead(BaseModel):
    """발화 → 지속 사실 목록. 스키마 description 이 곧 추출 지시다."""

    facts: list[str] = Field(default_factory=list, description=(
        "이후 대화에도 유효한 **취업 관련 개인 사실**만 — 목표(직군·회사·시기), "
        "제약(지역·근무 형태·연봉), 상황(재직 중·졸업 시기·경력 전환 등). "
        "발화에 실제로 있는 것만 짧은 한 문장씩 옮긴다. 이번 턴에만 유효한 지시·질문, "
        "붙여넣은 문서 내용, 인사말·감사는 넣지 않는다. 없으면 빈 배열."))


_SYSTEM = ("사용자 발화에서 이후 대화에도 유효한 취업 관련 개인 사실만 추출한다. "
           "추측·확장 금지 — 발화에 없는 사실을 만들지 않는다.")


def extract_user_facts(message: str, existing: list[str] | None) -> tuple[list[str], list[dict]]:
    """발화에서 지속 사실을 뽑아 기존 목록에 **병합**한다(중복·포함 관계 제거).

    실패·미설정이면 기존 목록 그대로 — 사실 축적은 강화(enrichment)라 턴을 막지 않는다.
    미설정 경고는 올리지 않는다: 이 콜의 미설정은 턴 본체의 미설정과 같은 사실이고,
    브릿지가 이 경고로 턴 전체를 미설정 실패로 오판하면 안 된다.
    """

    have = [str(f).strip() for f in (existing or []) if str(f).strip()]
    text = (message or "").strip()
    if not text or len(text) > _SKIP_OVER_CHARS:
        return have, []

    read, warnings = run_structured(_FactsRead, _SYSTEM, text, node="user_facts", tier="light")
    warnings = [w for w in warnings if w.get("code") != "llm_not_configured"]
    if read is None:
        return have, warnings

    merged = list(have)
    for fact in read.facts:
        fact = str(fact).strip()
        if fact and all(fact not in kept and kept not in fact for kept in merged):
            merged.append(fact)
    return merged[-_MAX_FACTS:], warnings

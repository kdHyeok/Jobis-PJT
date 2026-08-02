"""의미 축(dense 임베딩 + 크로스인코더) 질의 텍스트 구성 — 단일 진실 출처.

왜 별 모듈인가
--------------
`QuerySpec.text` 하나가 BM25·dense·재순위 세 곳에 동시에 쓰이는데, 어휘 축과 의미 축이
원하는 질의가 다르다. BM25는 토큰이 많을수록 재현율이 오르지만, 임베딩은 범용 토큰
(Python·Git·Linux)이 붙으면 벡터가 "일반 IT 공고" 쪽으로 끌려가 직군 판별력을 잃는다.

실측(`eval/report_io_tracks.json`): 입력 B는 입력 A보다 정보가 더 많은데도 dense가
−0.3030 낮았다 (95% CI [−0.492, −0.133], 유의). 같은 조건에서 bm25는 −0.043으로
거의 무변화 — 어휘 축은 희석되지 않는다는 뜻이다. 직군별로도 해석과 일치한다:
범용 기술만 있는 qa(−0.671)·security(−0.591)는 붕괴, 판별력 있는 조합인
fullstack(+0.361)·sre(+0.331)는 개선.

이 모듈이 의미 축 질의를 만들고, `spec_adapter`(입력 B)와 평가 하네스가 **같은 함수를
공유한다**. A/B에서 이긴 구성이 곧 서비스에 나가는 구성이 되도록 하기 위한 것이다.

채택 절차: eval/PREREG_query_text.md (사전 등록 -> 측정 -> ACTIVE 갱신)
"""
from __future__ import annotations

from .whitelist import with_aliases

# 사전등록 A/B 채택 결과. 측정 전 기본값은 현행(V0)이며, 채택 시에만 바꾼다.
ACTIVE = "V0"


def lexical_text(role: str, tech: list[str]) -> str:
    """어휘 축(BM25) 질의 — 모든 변형에서 동일하게 고정한다."""
    return " ".join([role] + list(tech)[:8])


def _v0(role: str, tech: list[str], exp: int | None) -> str | None:
    """현행. None을 반환해 QuerySpec.semantic_text가 text로 폴백하게 한다."""
    return None


def _v1(role: str, tech: list[str], exp: int | None) -> str:
    """직군 단독 — 희석 원인을 완전 제거. 판별 기술의 이득도 함께 잃는다."""
    return role


def _v2(role: str, tech: list[str], exp: int | None) -> str:
    """코퍼스 측 `chunking.context_prefix`와 같은 서식으로 정렬.

    청크 텍스트는 항상 `[직무] …\\n[핵심조건] 경력 N년 이상 · … · 기술: a, b, c`로
    시작한다. 질의를 같은 골격으로 만들면 기술 정보를 버리지 않고도 질의–문서 형식
    불일치를 없앨 수 있다. 회사/지역/고용형태는 질의에 없으므로 넣지 않는다 —
    가짜 값을 채우면 그게 새 잡음이 된다.
    """
    exp_s = "신입 가능" if exp is None else f"경력 {exp}년 이상"
    tech_s = ", ".join(with_aliases(t) for t in list(tech)[:8]) or "명시 없음"
    return f"[직무] {role}\n[핵심조건] {exp_s} · 기술: {tech_s}"


def _v3(role: str, tech: list[str], exp: int | None) -> str:
    """기술 절제 — 희석이 정말 '개수' 때문인지 보는 용량-반응 대조군."""
    return " ".join([role] + list(tech)[:3])


VARIANTS = {
    "V0": (_v0, "현행 — dense_text = text = 직군 + 기술[:8]"),
    "V1": (_v1, "직군 단독 — dense_text = 직군"),
    "V2": (_v2, "프리픽스 정렬 — 코퍼스 context_prefix와 동일 서식"),
    "V3": (_v3, "기술 절제 — 직군 + 기술[:3]"),
}


def semantic_text(role: str, tech: list[str], exp: int | None,
                  variant: str | None = None) -> str | None:
    """의미 축 질의. None이면 호출측이 lexical_text로 폴백한다."""
    return VARIANTS[variant or ACTIVE][0](role, tech, exp)


def describe(variant: str | None = None) -> str:
    return VARIANTS[variant or ACTIVE][1]

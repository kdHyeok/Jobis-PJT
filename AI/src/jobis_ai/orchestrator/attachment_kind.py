"""첨부 종류 재분류 — 프론트가 붙인 kind 를 내용으로 검증한다.

붙여넣기 슬롯 오배정 문제: 프론트는 "직전에 요청한 자료"의 슬롯으로 다음 붙여넣기를
그대로 보낸다 — 공고를 기다리는 중이면 이력서를 붙여넣어도 job_posting 으로 온다.
그 상태로 저장되면 이력서 슬롯은 계속 비어 있고, 이후 모든 진단이 헛돈다.

저장 전에 내용을 보고 명백히 반대 종류면 바로잡는다. 판정은 결정론(신호 어휘
스코어) 우선, 애매할 때만 LLM 경량 분류(§0 원칙의 예외 — 의미 판정), 그래도
모르면 프론트의 kind 를 믿는다. **확신 있을 때만 뒤집는다** — 오탐으로 맞는
첨부를 뒤집는 것이 오배정을 방치하는 것보다 나쁘다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from jobis_ai.structured import run_structured

# 서로 반대쪽 문서에는 잘 나오지 않는 신호 어휘. 개수 차이로 판정하므로
# 한두 개가 상대 문서에 섞여 나와도(예: 공고의 "졸업예정자") 뒤집히지 않는다.
_RESUME_SIGNALS = (
    "자기소개", "저는 ", "기여도", "담당 역할", "담당역할", "수료", "졸업",
    "포트폴리오", "github.com", "깃허브", "블로그", "수상", "어학",
    "인적사항", "경력사항", "프로젝트 경험",
    # **서술체 신호**(2026-08-01 실측 추가). "이력서 / 경력 / 프로젝트 / 기술 스택 / 학력"
    # 형식의 평범한 이력서가 "졸업" 하나만 맞아 판정 포기(r>=2 미달)됐고, 자산으로 승격되지
    # 않아 플래너가 `resume_diagnosis` 를 정확히 골랐는데도(확신 0.95) 검증기가 전제 붕괴로
    # 빼고 career_chat 이 이력서 원문 위에서 답했다 — D68 이 막으려던 그 사고다.
    #
    # 이력서는 **1인칭 과거 서술체**("~을 담당했습니다")이고 공고는 개조식 명사형이다.
    # 그 문체 차이를 신호로 쓴다 — 공고에서 "담당업무"는 나오지만 "담당했"은 나오지 않는다.
    "재직중", "재직 중", "이력서", "경력기술서",
    "담당했", "구현했", "개선했", "참여했", "개발했", "설계했",
)
_POSTING_SIGNALS = (
    "채용", "모집", "자격요건", "지원자격", "우대사항", "담당업무", "주요업무",
    "복리후생", "근무지", "근무형태", "고용형태", "전형", "마감", "지원방법",
    "연봉", "정규직", "경력무관", "인재상",
)

# 이보다 짧으면 신호가 부족해 종류를 판정하지 않는다.
#
# **공개다** — 판정을 포기하는 길이는 "프론트가 선언한 kind 를 그대로 믿는" 구간과 같은
# 값이어야 한다. `chat._apply_attachments` 의 짧은-이력서 가드가 이 상수를 쓴다: 여기서
# 판정을 포기한 텍스트를 저장 단계가 무조건 신뢰하면, 짧은 발화 한 줄이 저장된 이력서를
# 통째로 교체한다(D98). 두 곳이 같은 경계를 봐야 그 틈이 생기지 않는다.
MIN_ASSET_CHARS = 40


class _KindRead(BaseModel):
    """텍스트가 이력서인지 채용 공고인지 — 경량 분류."""

    kind: Literal["resume", "job_posting", "unknown"] = Field(description=(
        "resume: 구직자 개인이 자신의 경력·프로젝트·학력·기술을 서술한 글. "
        "job_posting: 회사가 지원자를 모집하려고 요건·업무·처우를 안내하는 글. "
        "unknown: 어느 쪽인지 확실하지 않음."))


_SYSTEM = """주어진 텍스트가 '이력서'인지 '채용 공고'인지 분류한다.
- resume: 구직자 개인이 자기 경력·프로젝트·학력·기술을 서술한 글 (1인칭 서술, 개인 연락처·깃허브 등)
- job_posting: 회사가 지원자를 모집하는 글 (자격요건·우대사항·담당업무·처우·전형 안내 등)
확실하지 않으면 unknown 으로 답한다."""


def _heuristic(text: str) -> str | None:
    low = text.lower()
    r = sum(1 for s in _RESUME_SIGNALS if s in low)
    p = sum(1 for s in _POSTING_SIGNALS if s in low)
    if r >= 2 and r >= p + 2:
        return "resume"
    if p >= 2 and p >= r + 2:
        return "job_posting"
    return None


def detect_kind(text: str) -> str | None:
    """붙여넣은 원문의 종류를 **결정론으로만** 판별 — 확신 없으면 None.

    브릿지의 승격 판단용: 공고 표지어가 없는 이력서 붙여넣기가 일반 대화로 흘러
    career_chat 이 이력서 원문 위에서 즉흥 조언을 만든 실측(2026-07-31)의 수정이다.
    애매한 긴 글을 자산으로 승격하면 일반 대화가 이력서로 저장되므로, 신호 어휘
    스코어가 확실할 때만 답한다(LLM 없음 — 모든 긴 발화에 분류 비용을 태우지 않는다).
    """

    body = (text or "").strip()
    if len(body) < MIN_ASSET_CHARS:
        return None
    return _heuristic(body)


def resolve_kind(claimed: str, text: str) -> tuple[str, list[dict]]:
    """저장할 kind 를 정한다 — 내용이 명백히 반대 종류면 바로잡고, 애매하면 claimed.

    resume/job_posting 만 다룬다. resume_extra(기존 이력서 보완)는 짧은 조각이
    정상이라 내용 판정이 성립하지 않으므로 손대지 않는다.
    """

    if claimed not in ("resume", "job_posting"):
        return claimed, []
    body = (text or "").strip()
    if len(body) < MIN_ASSET_CHARS:
        return claimed, []

    guess = _heuristic(body)
    if guess is not None:
        return guess, []

    # 결정론으로 못 가르는 경우만 LLM — 분류이므로 경량 등급, 앞부분이면 충분하다.
    read, warnings = run_structured(
        _KindRead, _SYSTEM, body[:3000], node="attachment_kind", tier="light",
    )
    if read is not None and read.kind in ("resume", "job_posting"):
        return read.kind, warnings
    return claimed, warnings

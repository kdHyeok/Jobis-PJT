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
)
_POSTING_SIGNALS = (
    "채용", "모집", "자격요건", "지원자격", "우대사항", "담당업무", "주요업무",
    "복리후생", "근무지", "근무형태", "고용형태", "전형", "마감", "지원방법",
    "연봉", "정규직", "경력무관", "인재상",
)

# 이보다 짧으면 신호가 부족해 판정하지 않는다(프론트를 믿는다).
_MIN_CHARS = 40


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


def resolve_kind(claimed: str, text: str) -> tuple[str, list[dict]]:
    """저장할 kind 를 정한다 — 내용이 명백히 반대 종류면 바로잡고, 애매하면 claimed.

    resume/job_posting 만 다룬다. resume_extra(기존 이력서 보완)는 짧은 조각이
    정상이라 내용 판정이 성립하지 않으므로 손대지 않는다.
    """

    if claimed not in ("resume", "job_posting"):
        return claimed, []
    body = (text or "").strip()
    if len(body) < _MIN_CHARS:
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

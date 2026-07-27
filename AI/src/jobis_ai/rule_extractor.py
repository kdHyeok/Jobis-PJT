"""1차 룰 추출기 (rule_extractor) — LLM 이전에 명확한 패턴부터 확정한다.

설계 §3.1 하이브리드 추출의 **1단계**. 순수 룰은 결정론·무비용·무환각이지만 비정형 문장에
약하고, LLM 은 그 반대다. 그래서 **정규식이 먼저 확실한 것을 못 박고, 남은 비정형만 LLM 에
넘긴다.** 이로써 LLM 호출량과 환각 표면이 줄고 재현율은 유지된다.

역할 경계:
- **읽기(Read) 계층**이다. 원문에 있는 것을 뽑을 뿐, "이 사람이 부족하다" 같은 판단은 하지 않는다.
- 확신이 없으면 **뽑지 않는다.** 애매한 걸 억지로 잡으면 2차 LLM 이 고칠 기회를 잃는다.
  놓친 것은 LLM 이 잡는 게 설계 의도다(재현율은 LLM 이, 정밀도는 룰이 담당).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobis_ai.skill_taxonomy import get_skill_taxonomy

# --- 경력 연차 ---
# "경력 3년 이상", "3년 이상", "최소 3년", "3년+", "3~5년", "3-5년", "3년 차"
_YEARS_RANGE = re.compile(r"(\d{1,2})\s*[~\-–]\s*(\d{1,2})\s*년")
_YEARS_MIN = re.compile(r"(?:최소\s*)?(\d{1,2})\s*년\s*(?:이상|\+|차|이상의)")
_YEARS_PLUS = re.compile(r"(\d{1,2})\s*년\s*\+")
_NEWCOMER = re.compile(r"신입|경력\s*무관|경력무관|무관")

# --- 연락처/링크 ---
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+")

# --- 섹션 헤더 ---
# 국내 공고는 "자격요건 / 우대사항" 구조가 관행적으로 고정돼 있어 룰로 나누는 게 안전하다.
# 이 분리가 되면 requirement 의 required/preferred 를 LLM 추측이 아니라 **위치로 확정**할 수 있다.
#
# 헤더 장식 처리(실제 공고로 검증한 결과 반영):
# - 접두 불릿: `■ 자격 요건` 처럼 도형 불릿을 붙이는 공고가 매우 흔하다. 이걸 빼먹으면
#   섹션 분리가 통째로 실패하고 전문이 LLM 으로 넘어간다.
# - 접미 괄호: `자격 요건 (필수)` 처럼 부연을 다는 공고도 흔하다.
_BULLET = r"[\s\-*#•·■▶▷●◆◇□▪○◎★☆\[\(【]*"
_HEADER_TAIL = r"\s*[\)\]】]?\s*(\([^)\n]{0,20}\))?\s*[:：]?\s*$"

_REQUIRED_HEADER = re.compile(
    rf"^{_BULLET}(자격\s*요건|지원\s*자격|필수\s*(요건|사항|자격|조건)|자격\s*조건|"
    rf"이런\s*분을\s*찾아요|이런\s*분과\s*함께|requirements?|qualifications?|must\s*have)"
    rf"{_HEADER_TAIL}",
    re.IGNORECASE | re.MULTILINE,
)
_PREFERRED_HEADER = re.compile(
    rf"^{_BULLET}(우대\s*(사항|요건|조건)|이런\s*분이면\s*더\s*좋아요|preferred|"
    rf"nice\s*to\s*have|plus){_HEADER_TAIL}",
    re.IGNORECASE | re.MULTILINE,
)
# 요건 섹션의 끝을 알리는 다른 헤더들(복리후생 등). 여기까지만 섹션으로 본다.
_OTHER_HEADER = re.compile(
    rf"^{_BULLET}(복리\s*후생|혜택|근무\s*(조건|환경|지역|시간)|채용\s*(절차|과정)|"
    rf"전형\s*절차|기타\s*사항|주요\s*업무|담당\s*업무|모집\s*부문|조직\s*소개|"
    rf"지원\s*방법|제출\s*서류|benefits?|process|about\s*us){_HEADER_TAIL}",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class RuleExtraction:
    """1차 룰 추출 결과.

    techStack       : 원문에 명시된 알려진 기술 (skill_taxonomy 표준명, 등장 순서)
    minYears        : 요구 최소 경력 연차. 신입/경력무관이면 0. 근거 없으면 None(추측 금지)
    yearsEvidence   : minYears 를 뽑은 원문 조각 (추적성)
    emails / urls   : 원문의 연락처·링크
    requiredSection : '자격요건' 섹션 본문 (없으면 "")
    preferredSection: '우대사항' 섹션 본문 (없으면 "")
    """

    techStack: list[str] = field(default_factory=list)
    minYears: int | None = None
    yearsEvidence: str = ""
    emails: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    requiredSection: str = ""
    preferredSection: str = ""

    @property
    def has_sections(self) -> bool:
        """섹션 분리에 성공했는지. True 면 required/preferred 를 위치로 확정할 수 있다."""

        return bool(self.requiredSection or self.preferredSection)


def _extract_years(text: str) -> tuple[int | None, str]:
    """요구 최소 경력 연차 + 근거 조각.

    범위("3~5년")는 하한을, "이상"은 그 값을 최소로 본다. 신입/경력무관은 0.
    어느 패턴에도 안 걸리면 None — **연차 미상을 0 으로 찍지 않는다**(0 은 '신입 채용'이라는
    적극적 정보라서, 미상과 섞으면 seniority 판정이 틀어진다).
    """

    for pattern in (_YEARS_MIN, _YEARS_PLUS):
        match = pattern.search(text)
        if match:
            return int(match.group(1)), match.group(0).strip()

    match = _YEARS_RANGE.search(text)
    if match:
        return int(match.group(1)), match.group(0).strip()

    match = _NEWCOMER.search(text)
    if match:
        return 0, match.group(0).strip()

    return None, ""


def _slice_section(text: str, start: int, end_candidates: list[int]) -> str:
    """헤더 다음부터 가장 가까운 다른 헤더 전까지를 섹션 본문으로 자른다."""

    ends = [e for e in end_candidates if e > start]
    return text[start : min(ends)].strip() if ends else text[start:].strip()


def _extract_sections(text: str) -> tuple[str, str]:
    """'자격요건' / '우대사항' 섹션 본문을 분리한다. 실패하면 ("", "").

    헤더가 없는 자유서술 공고도 많다 — 그 경우 빈 문자열을 돌려주고, 파서는 전문을
    LLM 에 넘긴다(억지로 나누지 않는다).
    """

    req_match = _REQUIRED_HEADER.search(text)
    pref_match = _PREFERRED_HEADER.search(text)
    if not req_match and not pref_match:
        return "", ""

    # 모든 헤더의 시작 위치 = 섹션 경계 후보
    boundaries: list[int] = []
    for pattern in (_REQUIRED_HEADER, _PREFERRED_HEADER, _OTHER_HEADER):
        boundaries += [m.start() for m in pattern.finditer(text)]

    required = _slice_section(text, req_match.end(), boundaries) if req_match else ""
    preferred = _slice_section(text, pref_match.end(), boundaries) if pref_match else ""
    return required, preferred


def extract_rules(text: str) -> RuleExtraction:
    """원문 → 룰로 확정 가능한 필드들. LLM 을 호출하지 않는다.

    파서(§3.1)는 이 결과를 먼저 확정한 뒤, 남은 비정형 문장만 `run_structured` 로 넘긴다.
    """

    content = text or ""
    if not content.strip():
        return RuleExtraction()

    min_years, years_evidence = _extract_years(content)
    required_section, preferred_section = _extract_sections(content)

    return RuleExtraction(
        techStack=get_skill_taxonomy().find_in_text(content),
        minYears=min_years,
        yearsEvidence=years_evidence,
        emails=_dedup(_EMAIL.findall(content)),
        urls=_dedup(_URL.findall(content)),
        requiredSection=required_section,
        preferredSection=preferred_section,
    )


def _dedup(items: list[str]) -> list[str]:
    """등장 순서를 지키며 중복 제거."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

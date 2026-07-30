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
# 경계 둘을 강제한다(실측 버그, 잡코리아 Gno=49546576 회사 소개 "2025년 차세대 휴머노이드"):
# - 숫자 왼쪽 (?<!\d) — 연도("2025")의 꼬리("25")를 연차로 읽지 않는다
# - '차' 뒤 (?![가-힣]) — "차세대·차량"의 '차'는 연차의 '차'가 아니다
_YEARS_RANGE = re.compile(r"(?<!\d)(\d{1,2})\s*[~\-–]\s*(\d{1,2})\s*년")
_YEARS_MIN = re.compile(r"(?:최소\s*)?(?<!\d)(\d{1,2})\s*년\s*(?:이상의?|\+|차(?![가-힣]))")
_YEARS_PLUS = re.compile(r"(?<!\d)(\d{1,2})\s*년\s*\+")
# "경력 : 1년" — 이상/차 없이 라벨로만 적는 표기(잡코리아 표 공고 실측 Gno=49638104).
_YEARS_LABELED = re.compile(r"경력\s*[:：]?\s*(?<!\d)(\d{1,2})\s*년")
# bare "무관"을 넣으면 안 된다 — "학력무관"·"성별: 무관"까지 경력무관(0년)으로 오판한다
# (실측 Gno=49638104: 경력 1년 공고가 "학력무관" 탓에 신입으로 읽혔다).
_NEWCOMER = re.compile(r"신입|경력\s*[:：]?\s*무관")

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
    rf"이런\s*분들?[을과]\s*(찾아요|찾고\s*있어요|함께)|"
    rf"requirements?|qualifications?|must\s*have)"
    rf"{_HEADER_TAIL}",
    re.IGNORECASE | re.MULTILINE,
)
_PREFERRED_HEADER = re.compile(
    rf"^{_BULLET}(우대\s*(사항|요건|조건)|이런\s*분이면\s*더\s*좋아요|preferred|"
    rf"nice\s*to\s*have|plus){_HEADER_TAIL}",
    re.IGNORECASE | re.MULTILINE,
)
# 섹션으로 인정하는 최소 실질 내용 — 이보다 짧으면 헤더 오인(목차·표 라벨)으로 본다.
_MIN_SECTION_CHARS = 10

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

    for pattern in (_YEARS_MIN, _YEARS_PLUS, _YEARS_RANGE, _YEARS_LABELED):
        match = pattern.search(text)
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


# 요건 목록 줄의 표지 — 불릿 도형 또는 "1." "1)" 번호.
_LIST_LINE = re.compile(r"^\s*(?:[-*•·▪◦∙‣■□]|\d{1,2}[.)])\s*\S", re.MULTILINE)


def _listlike(section: str) -> bool:
    """섹션 본문이 요건 목록답게 보이는가 — 앞부분에 불릿/번호 줄이 있는가.

    껍데기 라벨 뒤에 붙는 급여·근무지 안내문(사람인)이나 접수기간(잡코리아)은 목록이
    아니라 서술문이다. 앞 400자만 본다 — 진짜 섹션이면 목록이 바로 시작된다.
    """

    return bool(_LIST_LINE.search(section[:400]))


def _extract_sections(text: str) -> tuple[str, str]:
    """'자격요건' / '우대사항' 섹션 본문을 분리한다. 실패하면 ("", "").

    헤더가 없는 자유서술 공고도 많다 — 그 경우 빈 문자열을 돌려주고, 파서는 전문을
    LLM 에 넘긴다(억지로 나누지 않는다).
    """

    req_matches = list(_REQUIRED_HEADER.finditer(text))
    req_match = req_matches[0] if req_matches else None
    pref_matches = list(_PREFERRED_HEADER.finditer(text))
    pref_match = pref_matches[0] if pref_matches else None
    if not req_match and not pref_match:
        return "", ""

    # 모든 헤더의 시작 위치 = 섹션 경계 후보
    boundaries: list[int] = []
    for pattern in (_REQUIRED_HEADER, _PREFERRED_HEADER, _OTHER_HEADER):
        boundaries += [m.start() for m in pattern.finditer(text)]

    # 우대 헤더도 사이트 껍데기에 뜬다 — 사람인 상단의 "우대사항" 탭 라벨 뒤에는 급여·근무지
    # 안내가 붙어 있어, 첫 매치를 잡으면 그 안내문이 우대 섹션으로 확정되고 진짜 우대사항
    # ("■ 우대 사항" + 불릿 목록)이 통째로 빠진다(실측 rec_idx=54347596). 요건 섹션 본문은
    # 불릿/번호 목록이 관행이므로, 매치가 여럿이면 **본문이 목록으로 시작하는 첫 후보**를 고른다.
    if len(pref_matches) > 1:
        for candidate in pref_matches:
            if _listlike(_slice_section(text, candidate.end(), boundaries)):
                pref_match = candidate
                break

    # 사이트 껍데기에도 같은 라벨이 뜬다 — 잡코리아 사이드바의 "지원자격"(뒤따르는 내용은
    # 접수기간·마감일)이 본문의 "자격 요건"보다 앞에 있어, 첫 매치를 잡으면 내용 없는
    # 섹션이 확정되고 파서는 "그 섹션에서만" 뽑으라는 지시 탓에 필수요건을 통째로 놓친다
    # (실측 Gno=49675900). 자격요건/우대사항은 관행상 붙어 다니는 쌍이므로, 매치가 여럿이면
    # **우대사항 헤더 앞에서 가장 가까운 것**을 본문 헤더로 본다.
    if pref_match and len(req_matches) > 1:
        before_pref = [m for m in req_matches if m.start() < pref_match.start()]
        if before_pref:
            req_match = before_pref[-1]

    required = _slice_section(text, req_match.end(), boundaries) if req_match else ""
    preferred = _slice_section(text, pref_match.end(), boundaries) if pref_match else ""

    # 찾은 헤더의 섹션이 실질 내용 없이 비면 분리 전체를 신뢰하지 않는다 — 목차/표 컬럼
    # 라벨("1. 필수사항 2. 자격요건 3. 우대사항")을 헤더로 오인한 것이다(실측 Gno=49638104:
    # 필수 섹션이 "3." 두 글자로 확정돼 파서가 "그 섹션에서만" 지시로 필수요건을 통째로
    # 놓쳤다). 확신이 없으면 뽑지 않는다 — 전문이 LLM 으로 가는 쪽이 낫다.
    def _hollow(match: re.Match | None, section: str) -> bool:
        return match is not None and len(section) < _MIN_SECTION_CHARS

    if _hollow(req_match, required) or _hollow(pref_match, preferred):
        return "", ""
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

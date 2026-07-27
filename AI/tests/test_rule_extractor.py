"""rule_extractor 유닛 테스트 — 실제 페르소나 공고로 검증한다.

`tests/docs/user1`(백엔드 신입 공고), `tests/docs/user2`(프론트엔드 인턴 공고)는
서로 다른 형식을 쓴다. 손으로 만든 샘플만 쓰면 실제 공고의 헤더 장식(`■`, `·`)이나
접미 괄호(`(필수)`)를 놓치는 걸 못 잡는다 — 실제로 그래서 놓쳤었다.
"""

from pathlib import Path

import pytest

from jobis_ai.rule_extractor import extract_rules

_DOCS = Path(__file__).parent / "docs"


@pytest.fixture(scope="module")
def user1_posting() -> str:
    return (_DOCS / "user1" / "공고.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def user2_posting() -> str:
    return (_DOCS / "user2" / "채용공고.txt").read_text(encoding="utf-8")


# --- 실제 공고 섹션 분리 ---------------------------------------------------
def test_user1_splits_sections_despite_decorated_headers(user1_posting):
    """`■ 자격 요건 (필수)` — 도형 불릿 + 접미 괄호. 국내 공고에서 매우 흔한 형식이다."""
    rules = extract_rules(user1_posting)

    assert rules.has_sections, "헤더 장식 때문에 섹션 분리가 실패하면 전문이 LLM 으로 넘어간다"
    assert "Spring Boot 기반 웹 백엔드 개발 경험" in rules.requiredSection
    assert "Git 기반 협업 경험" in rules.requiredSection
    assert "Docker" in rules.preferredSection
    assert "Spring Boot 기반 웹 백엔드" not in rules.preferredSection, "필수가 우대로 새면 안 된다"


def test_user2_splits_sections_with_different_header_wording(user2_posting):
    """실제 공고는 '지원 자격' / '우대 사항' 을 쓴다(자격요건이 아니라)."""
    rules = extract_rules(user2_posting)

    assert rules.has_sections
    assert "TypeScript" in rules.requiredSection
    assert "React 기반 웹 애플리케이션" in rules.requiredSection
    assert "Three.js" in rules.preferredSection


def test_major_duties_section_does_not_leak_into_requirements(user1_posting):
    """'주요 업무'는 요구사항이 아니다 — 섹션 경계로 잘려야 한다."""
    rules = extract_rules(user1_posting)
    assert "Redis 캐시를 활용한 조회 성능 개선" not in rules.requiredSection


# --- 실제 공고 기술스택 추출 -----------------------------------------------
def test_user1_tech_stack_extracted_without_llm(user1_posting):
    stack = set(extract_rules(user1_posting).techStack)
    assert {"Java", "Spring Boot", "MySQL", "Redis", "AWS", "Git", "Docker"} <= stack


def test_user2_tech_stack_extracted_without_llm(user2_posting):
    stack = set(extract_rules(user2_posting).techStack)
    assert {"JavaScript", "TypeScript", "React"} <= stack


# --- 연차 추출 -------------------------------------------------------------
def test_user1_detects_newcomer_posting(user1_posting):
    assert extract_rules(user1_posting).minYears == 0, "'신입~주니어' → 0년"


@pytest.mark.parametrize("text,expected", [
    ("경력 3년 이상의 서버 개발 경험", 3),
    ("최소 5년 이상", 5),
    ("3~5년", 3),
    ("3-5년", 3),
    ("2년+", 2),
    ("신입 채용", 0),
    ("경력 무관", 0),
])
def test_years_extraction_variants(text, expected):
    assert extract_rules(text).minYears == expected


def test_years_unknown_stays_none_not_zero():
    """연차 미상을 0 으로 찍지 않는다. 0 은 '신입 채용'이라는 적극적 정보라서,
    미상과 섞으면 seniority 판정이 틀어진다."""
    assert extract_rules("좋은 개발자를 찾습니다").minYears is None


# --- 연락처/링크 -----------------------------------------------------------
def test_extracts_emails_and_urls():
    rules = extract_rules("문의: recruit@example.com\n상세: https://example.com/jobs/1")
    assert rules.emails == ["recruit@example.com"]
    assert rules.urls == ["https://example.com/jobs/1"]


# --- 헤더 없는 공고 --------------------------------------------------------
def test_freeform_posting_yields_no_sections_not_forced_split():
    """헤더가 없는 자유서술 공고는 억지로 나누지 않는다 — 파서가 전문을 LLM 에 넘긴다."""
    rules = extract_rules("우리 팀은 React 로 개발합니다. 함께할 분을 찾아요.")
    assert rules.has_sections is False
    assert rules.requiredSection == "" and rules.preferredSection == ""
    assert "React" in rules.techStack, "섹션이 없어도 기술스택은 뽑는다"


def test_empty_input_is_safe():
    rules = extract_rules("")
    assert rules.techStack == [] and rules.minYears is None

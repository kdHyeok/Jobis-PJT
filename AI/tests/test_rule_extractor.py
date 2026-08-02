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


def test_years_ignores_calendar_year_tail():
    """연도의 꼬리를 연차로 읽지 않는다 (실측: 잡코리아 Gno=49546576).

    회사 소개 "2025년 차세대 휴머노이드"가 요건 "경력 : 5년 이상"보다 앞에 있어
    minYears=25 로 오염됐었다 — 왼쪽 숫자 경계 + '차' 뒤 한글 경계로 막는다.
    """

    text = "2025년 차세대 휴머노이드 로봇 ALLEX 를 공개했습니다.\nㆍ경력 : 5년 이상"
    rules = extract_rules(text)
    assert rules.minYears == 5
    assert rules.yearsEvidence == "5년 이상"


@pytest.mark.parametrize("text", [
    "2025년 차세대 제품",          # 연도 + 차세대
    "2023~2025년 프로젝트 수행",   # 연도 범위
    "창립 10년차별화된 기술",      # '차' 뒤에 한글이 붙은 조어
])
def test_years_calendar_noise_stays_none(text):
    assert extract_rules(text).minYears is None


def test_years_earliest_mention_beats_pattern_priority():
    """헤더 요약의 표기가 본문 나열 속 표기를 이긴다 (실측 Gno=49564982).

    SI 파견 공고가 프로젝트 수십 건을 나열하는데, 헤더 "경력 1~5년"(범위 패턴)보다
    우선순위가 높은 "8년 이상"이 본문에서 걸려 요구 연차 8년으로 오염됐었다 —
    문서에서 먼저 나온 표기가 이긴다."""

    text = (
        "채용 - 금융,공공 운영개발[SM,SI], 경력 1~5년, 학력무관\n"
        "1. 사이트 : 금융권 2. 스킬 : RDBMS 8년 이상 경험 -풀스택 개발자\n"
        "2. 사이트 : 비공개 프론트엔드 개발자 ; 5년차 이상\n"
    )
    rules = extract_rules(text)
    assert rules.minYears == 1
    assert rules.yearsEvidence == "1~5년"


def test_years_still_matches_nyeoncha_forms():
    """진짜 연차 표기("N년 차 / N년차")는 여전히 잡는다."""

    assert extract_rules("10년 차 개발자를 찾습니다").minYears == 10
    assert extract_rules("3년차 이상 지원 가능").minYears == 3


# --- 섹션 분리: 사이트 껍데기 라벨 --------------------------------------------
def test_required_section_skips_content_free_sidebar_label():
    """잡코리아 사이드바 "지원자격"(내용은 접수기간·마감일)이 본문 "자격 요건"보다
    앞에 있어도, 우대사항과 쌍을 이루는 본문 헤더가 이긴다 (실측 Gno=49675900 —
    첫 매치를 잡으면 필수요건이 통째로 비어 나갔다)."""

    text = (
        "지원자격\n"
        "접수기간 · 방법\n시작일 2026.07.29(수)\n마감일 상시채용\n"
        "복리후생\n연금·보험 국민연금, 고용보험\n"
        "주요 업무\n- 자체 LLM 선정·평가 및 모델 구축\n"
        "자격 요건\n- LLM 기반 서비스 개발 경험\n- 벡터DB 활용 경험\n"
        "우대 사항\n- 사이버 보안 도메인 이해\n"
    )
    rules = extract_rules(text)
    assert "LLM 기반 서비스 개발 경험" in rules.requiredSection
    assert "접수기간" not in rules.requiredSection
    assert "사이버 보안 도메인 이해" in rules.preferredSection


def test_toc_style_headers_not_trusted_as_sections():
    """목차/표 컬럼 라벨("1. 필수사항 2. 자격요건 3. 우대사항")을 헤더로 오인해
    내용 없는 섹션을 확정하지 않는다 (실측 Gno=49638104 — 필수 섹션이 "3." 으로
    확정돼 필수요건이 통째로 비어 나갔다). 확신이 없으면 전문을 LLM 에 넘긴다."""

    text = (
        "자격요건 및 우대사항\n1.\n필수사항\n2.\n자격요건\n3.\n우대사항\n"
        "- 일본취업 비자 발급에 결격 사유가 없는 자\n- JLPT 2급 이상\n"
    )
    rules = extract_rules(text)
    assert rules.requiredSection == ""
    assert rules.preferredSection == ""


def test_required_header_matches_findeu_variants():
    """실측 헤더 변형(Gno=49546576): "이런 분들을 찾고 있어요"."""

    text = (
        "이런 분들을 찾고 있어요\nㆍ학력 : 대졸이상\nㆍ경력 : 5년 이상\n"
        "이런 분이면 더 좋아요\nㆍ관련 석·박사 우대\n"
    )
    rules = extract_rules(text)
    assert "대졸이상" in rules.requiredSection
    assert "석·박사 우대" in rules.preferredSection


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


def test_years_bare_mugwan_is_not_career_mugwan():
    """"학력무관"·"성별: 무관"을 경력무관(0년)으로 오판하지 않는다
    (실측 Gno=49638104: 경력 1년 공고가 "학력무관" 탓에 신입으로 읽혔다)."""

    assert extract_rules("학력무관 경력 : 1년").minYears == 1
    assert extract_rules("성별: 무관\n경력: 3년").minYears == 3
    assert extract_rules("학력무관인 포지션입니다").minYears is None   # 경력 정보 없음 → 미상
    assert extract_rules("경력: 무관").minYears == 0                   # 진짜 경력무관
    assert extract_rules("경력무관").minYears == 0


def test_years_labeled_form_without_isang():
    """"경력 : 1년" — 이상/차 없이 라벨로만 적는 표 공고 표기도 잡는다."""

    rules = extract_rules("고용형태: 정규직\n경력 : 1년\n학력: 대졸")
    assert rules.minYears == 1
    assert "1년" in rules.yearsEvidence


def test_shell_preferred_label_does_not_hijack_real_section():
    """사람인 상단 '우대사항' 탭 라벨 뒤엔 급여·근무지 안내가 붙는다 — 첫 매치를 잡으면
    진짜 우대사항(불릿 목록)이 통째로 빠진다(실측 rec_idx=54347596)."""

    text = (
        "회사 기술스택\nReact, Next.js, TypeScript\n\n"
        "우대사항\n\n"                                        # 껍데기 라벨 (본문 없음)
        "급여 면접 후 결정 근무지역 경기 고양시 일산서구, 서울 강남구 외 다수\n"
        "어떻게 합격률이 분석됐나요? 최신 이력서 데이터를 기준으로 산출돼요.\n\n"
        "■ 자격 요건\n- Python 기초 활용 능력\n- 모델 학습 및 파인튜닝 경험 필수\n\n"
        "■ 우대 사항\n- NLP/LLM 학습 데이터 구축 경험\n- PyTorch 기반 모델 학습 경험\n"
        "- SQL 기초 지식\n\n"
        "복리후생\n퇴직금, 4대 보험\n"
    )
    extraction = extract_rules(text)
    assert "NLP/LLM 학습 데이터 구축 경험" in extraction.preferredSection
    assert "급여 면접 후 결정" not in extraction.preferredSection
    assert "Python 기초 활용 능력" in extraction.requiredSection


def test_single_preferred_header_behaviour_unchanged():
    text = (
        "자격 요건\n- Java 백엔드 경험\n\n"
        "우대 사항\n- Docker 운영 경험\n- AWS 경험\n"
    )
    extraction = extract_rules(text)
    assert "Docker 운영 경험" in extraction.preferredSection
    assert "Java 백엔드 경험" in extraction.requiredSection


# --- 연차: LLM 읽기 채택 vs 룰 폴백 (D118) ---------------------------------
def _apply(read_years, evidence, text):
    """_apply_rule_extraction 만 떼어 돌린다 (LLM 호출 없음)."""
    from jobis_ai.contracts.domain import NormalizedJobPosting
    from jobis_ai.graph.read_nodes import _apply_rule_extraction

    posting = NormalizedJobPosting(
        jobTitle="AI Agent 개발자", minYears=read_years, yearsEvidence=evidence)
    warnings = _apply_rule_extraction(posting, extract_rules(text), text)
    return posting, warnings


def test_llm_years_win_over_regex_when_evidence_is_in_source():
    """룰은 '가장 앞에 나온 연차 표기'를 고른다 — 회사 소개가 먼저 오면 그걸 요구 연차로
    읽는다. LLM 은 '어디에 적힌 숫자인가'를 갈라 읽고, 근거가 원문에 있으면 이긴다."""
    text = "당사는 10년 이상 축적된 노하우를 가진 기업입니다.\n자격요건\n- 경력 3년 이상"
    assert extract_rules(text).minYears == 10         # 룰 단독은 여전히 오독한다
    posting, warnings = _apply(3, "경력 3년 이상", text)
    assert (posting.minYears, posting.yearsEvidence) == (3, "경력 3년 이상")
    assert not [w for w in warnings if w["code"] == "years_evidence_unverified"]


def test_llm_years_without_source_evidence_fall_back_to_rule_with_warning():
    """근거가 원문에 없으면 지어낸 것이다 — 버리고 룰로 되돌리되 **이유를 남긴다**(§2-6)."""
    text = "경력 : 3년 이상\n- 생성형 AI 개발 경험"
    posting, warnings = _apply(7, "경력 7년 이상", text)
    assert posting.minYears == 3
    assert [w for w in warnings if w["code"] == "years_evidence_unverified"]


def test_seniority_follows_llm_years_not_company_blurb():
    """공고 소개문의 'Leading' 이 연차 판정을 뒤집지 않는다."""
    text = "IEA Global Leading DX Company\n경력 : 3년 이상\n- AI Agent 개발 경험"
    posting, _ = _apply(3, "경력 : 3년 이상", text)
    assert posting.seniority == "mid"


def test_prose_section_under_shell_label_is_distrusted_not_handed_to_parser():
    """실측 Gno=49638113: 잡코리아 사이드바 '지원자격' 뒤는 접수기간·지원자 통계 서술문이다.
    진짜 자격요건은 iframe 상세라 한 줄로 붙어 와 `^` 앵커에 안 걸린다. 이 서술문을 필수
    섹션으로 넘기면 파서가 '그 섹션에서만' 지시를 따라 필수 요건을 통째로 놓친다 —
    확신이 없으면 분리를 포기하고 전문을 LLM 에 넘긴다."""
    text = (
        "지원자격\n\n접수기간 · 방법\n\n남은기간 20일\n\n시작일\n\n2026.07.23(목)\n\n"
        "마감일\n\n2026.08.22(토)\n\n접수방법\n\n잡코리아 이력서\n\n지원자 수\n\n16 명\n"
    )
    rules = extract_rules(text)
    assert (rules.requiredSection, rules.preferredSection) == ("", "")


def test_araea_bullet_counts_as_a_requirement_list():
    """`ㆍ`(U+318D)는 가운뎃점 `·`(U+00B7)와 다른 글자다. 국내 공고가 불릿으로 흔히 쓴다."""
    text = "자격요건\nㆍ경력 3년 이상\nㆍPython 개발 경험\n\n우대사항\nㆍRAG 구축 경험\n"
    rules = extract_rules(text)
    assert "Python 개발 경험" in rules.requiredSection
    assert "RAG 구축 경험" in rules.preferredSection

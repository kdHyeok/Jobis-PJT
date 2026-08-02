"""첨부 종류 재분류 테스트 — 프론트가 붙인 kind 를 내용으로 바로잡는다.

LLM 은 conftest 가 강제 미설정하므로 결정론(신호 어휘 스코어) 경로와
"애매하면 프론트를 믿는다" 폴백만 검증한다.
"""

from __future__ import annotations

import pytest

from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.orchestrator import session as session_mod
from jobis_ai.orchestrator.attachment_kind import resolve_kind
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.orchestrator.session import SessionStore

_RESUME_TEXT = (
    "김지원\nContact\n이메일: jiwon.dev@email.com\n깃허브: github.com/jiwon-dev\n\n"
    "1. 자기소개\n사용자 경험을 고민하는 프론트엔드 개발자입니다.\n"
    "2. 기술 스택\nReact, TypeScript\n"
    "3. 프로젝트 경험\n담당 역할: 프론트엔드 (기여도 50%)\n"
    "4. 학력\nOO대학교 컴퓨터공학과 졸업 예정, 부트캠프 수료"
)

_POSTING_TEXT = (
    "[프론트엔드 개발자 채용]\n모집부문: 웹 프론트엔드\n"
    "자격요건: React 3년 이상\n우대사항: TypeScript 경험자\n"
    "담당업무: 웹 서비스 UI 개발\n근무지: 서울\n고용형태: 정규직\n"
    "전형절차: 서류 - 면접\n연봉: 협의"
)


@pytest.fixture(autouse=True)
def fresh_session_store(monkeypatch):
    store = SessionStore()
    monkeypatch.setattr(session_mod, "_STORE", store)
    return store


# --- resolve_kind (결정론 경로) ------------------------------------------------
def test_resume_pasted_into_posting_slot_is_corrected():
    kind, _ = resolve_kind("job_posting", _RESUME_TEXT)
    assert kind == "resume"


def test_posting_pasted_into_resume_slot_is_corrected():
    kind, _ = resolve_kind("resume", _POSTING_TEXT)
    assert kind == "job_posting"


def test_matching_kind_is_kept():
    assert resolve_kind("resume", _RESUME_TEXT)[0] == "resume"
    assert resolve_kind("job_posting", _POSTING_TEXT)[0] == "job_posting"


def test_ambiguous_text_trusts_frontend_kind():
    # 신호가 부족하고 LLM 미설정 → claimed 유지 (기존 테스트들의 짧은 샘플도 이 경로).
    assert resolve_kind("resume", "Python Django 백엔드 개발 3년 경력의 개발자")[0] == "resume"


def test_short_text_and_resume_extra_untouched():
    assert resolve_kind("job_posting", "짧은 글")[0] == "job_posting"
    assert resolve_kind("resume_extra", _POSTING_TEXT)[0] == "resume_extra"


# --- 오케스트레이터 통합 — 잘못 온 첨부가 올바른 세션 슬롯에 저장된다 ------------
def test_store_corrects_slot_and_says_so(fresh_session_store):
    res = handle_chat(ChatRequest(
        sessionId="s-kind", message="",
        attachments=[ChatAttachment(kind="job_posting", sourceType=SourceType.text,
                                    value=_RESUME_TEXT)],
    ))
    session = fresh_session_store.get("s-kind")
    assert (session.get("resume") or {}).get("value") == _RESUME_TEXT   # 이력서 슬롯에 저장
    assert not session.get("job_posting")                               # 공고 슬롯은 비어 있다
    assert "이력서로 등록했어요" in res.reply                            # 바로잡음을 말한다


def test_plain_resume_sections_are_detected():
    """평범한 형식의 이력서를 판별해야 한다 — 못 잡으면 자산 승격이 안 된다(2026-08-01 실측).

    "이력서 / 경력 / 프로젝트 / 기술 스택 / 학력" 형식이 신호 하나만 맞아 판정 포기됐고,
    자산이 없어 플래너가 `resume_diagnosis` 를 정확히 골랐는데도(확신 0.95) 검증기가 전제
    붕괴로 빼고 `career_chat` 이 이력서 원문 위에서 답했다 — D68 이 막으려던 그 사고다.
    """

    from jobis_ai.orchestrator.attachment_kind import detect_kind

    resume = (
        "이력서\n\n경력\n- 오로라테크 백엔드 개발자 (2022.03 ~ 재직중)\n\n프로젝트\n"
        "- 사내 결제 게이트웨이 재설계: Python/Django 로 정산 배치를 재작성해 마감 처리 시간을 "
        "6시간에서 40분으로 줄였습니다. PostgreSQL 쿼리 튜닝과 인덱스 재설계를 담당했습니다.\n"
        "- 상담 로그 수집 파이프라인: Airflow DAG 로 일 200만 건 상담 로그를 수집·정제했습니다.\n\n"
        "기술 스택\nPython, Django, PostgreSQL, Airflow, Docker\n\n학력\n- OO대학교 졸업"
    )
    assert detect_kind(resume) == "resume"


def test_posting_is_not_flipped_by_new_resume_signals():
    """서술체 신호를 늘렸어도 공고는 공고다 — 오탐이 맞는 첨부를 뒤집는 것이 더 나쁘다."""

    from jobis_ai.orchestrator.attachment_kind import detect_kind

    posting = (
        "AI/Agent 엔지니어 채용\n\n담당업무\n- LLM 기반 에이전트 파이프라인 설계 및 운영\n\n"
        "자격요건\n- 데이터 엔지니어링 경력 3~7년\n- Python 기반 데이터 처리 실무 경험\n\n"
        "우대사항\n- LangChain 활용 경험\n\n전형절차\n서류 - 과제 - 면접\n"
        "지원방법: 이력서를 제출해 주세요"      # '이력서' 가 섞여도 뒤집히지 않는다
    )
    assert detect_kind(posting) == "job_posting"

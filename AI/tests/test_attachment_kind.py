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

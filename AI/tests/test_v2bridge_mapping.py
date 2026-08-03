"""v2bridge 매핑(엔진 산출물 → v2 계약)의 결정론 검증 — LLM 없이 돈다."""

from __future__ import annotations

from uuid import uuid4

import pytest

from jobis_ai.v2bridge import mapping
from jobis_ai.v2bridge.models import (
    AnalysisResponse,
    CareerSnapshot,
    ExistingNode,
)


# ---------------------------------------------------------------------------
# verdict — application_plan 판정 코드의 번역
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status,expected", [
    ("APPLY_NOW", "APPLY_NOW"),
    ("APPLY_WITH_POLISH", "APPLY_NOW"),
    ("REINFORCE_FIRST", "STRENGTHEN_THEN_APPLY"),
    ("MID_TERM_TARGET", "ALTERNATIVE_FIRST"),
])
def test_verdict_translates_plan_status(status, expected):
    assert mapping.verdict_from_plan(status) == expected


def test_undetermined_never_becomes_a_verdict():
    """판정 보류를 임의 verdict 로 내보내지 않는다 (모른다 ≠ 아니다)."""

    with pytest.raises(mapping.VerdictUndetermined):
        mapping.verdict_from_plan("UNDETERMINED")
    with pytest.raises(mapping.VerdictUndetermined):
        mapping.verdict_from_plan("")


def test_evaluation_uses_engine_reasons_only():
    evaluation = mapping.build_evaluation(
        {"summary": "판정 요약", "fitGrade": "중"},
        {"status": "REINFORCE_FIRST", "reasons": ["필수 요건 2건 미충족"]},
        [],
    )
    assert evaluation.verdict == "STRENGTHEN_THEN_APPLY"
    assert evaluation.summary == "판정 요약"
    assert evaluation.reasons == ["필수 요건 2건 미충족"]


def test_evaluation_falls_back_to_unmet_requirements():
    evaluation = mapping.build_evaluation(
        {"summary": "", "fitGrade": "하"},
        {"status": "REINFORCE_FIRST", "headline": "", "reasons": []},
        [{"text": "Docker 경험", "status": "not_met"},
         {"text": "Java", "status": "met"}],
    )
    assert evaluation.reasons == ["미충족: Docker 경험"]
    assert evaluation.summary   # 계약상 필수 — 판정 사실로 조립된다


# ---------------------------------------------------------------------------
# slug / canonical key
# ---------------------------------------------------------------------------
def test_slug_is_ascii_only_and_never_fabricated():
    assert mapping.slug("Spring Boot") == "spring-boot"
    assert mapping.slug("쿠버네티스 운영") == ""   # ascii 로 못 옮기면 위조하지 않는다


# ---------------------------------------------------------------------------
# ChangeProposal — REUSE 매칭·ref 유일성·계약 검증 통과
# ---------------------------------------------------------------------------
def _career(nodes=()):
    return CareerSnapshot(graph_id=uuid4(), version=3, nodes=list(nodes), fragments=[])


def _existing(title, canonical_key, **kw):
    return ExistingNode(
        id=kw.get("id") or uuid4(), canonical_key=canonical_key, title=title,
        domain=kw.get("domain", "BACKEND"), kind=kw.get("kind", "SKILL"),
        scope_definition=kw.get("scope", "기존 노드"), level=kw.get("level", 2),
        progress_status=kw.get("progress", "COMPLETED"),
    )


def test_change_proposal_reuses_matching_node_and_creates_the_rest():
    existing = _existing("Docker", "skill.docker")
    career = _career([existing])
    posting = {"companyName": "예시", "jobTitle": "백엔드 개발자", "roleCategory": "backend"}
    req_status = [
        {"requirementId": "r1", "type": "required", "text": "Docker 컨테이너 운영 경험",
         "status": "met", "confidence": 0.9},
        {"requirementId": "r2", "type": "preferred", "text": "Kubernetes 운영 경험",
         "status": "not_met", "confidence": 0.8},
    ]
    gaps = [{"requirementId": "r2", "missingSkills": ["Kubernetes"]}]

    proposal = mapping.build_change_proposal(career, posting, req_status, gaps, str(uuid4()))

    assert proposal.base_graph_version == 3
    by_ref = {n.ref: n for n in proposal.nodes}
    assert by_ref["opportunity"].kind == "OPPORTUNITY"

    reused = [n for n in proposal.nodes if n.action == "REUSE"]
    assert len(reused) == 1 and reused[0].existing_node_id == existing.id

    created = [n for n in proposal.nodes if n.action == "CREATE" and n.kind == "SKILL"]
    assert len(created) == 1 and created[0].title == "Kubernetes"
    assert created[0].scope_definition == "Kubernetes 운영 경험"   # 충족 기준은 공고 원문

    # 모든 요건 노드는 기회 노드로 향하는 경로 간선을 갖는다.
    assert {(e.from_ref, e.to_ref, e.edge_kind) for e in proposal.edges} == {
        (reused[0].ref, "opportunity", "OPPORTUNITY_PATH"),
        (created[0].ref, "opportunity", "OPPORTUNITY_PATH"),
    }
    assert [r.kind for r in proposal.requirements] == ["REQUIRED", "PREFERRED"]
    assert float(proposal.requirements[0].confidence) == 0.9

    # 계약 전체 검증(COMPLETED 응답으로 조립해도 통과해야 한다).
    # COMPLETED 는 competencyProposal 을 요구한다 — legacy 만으로는 통과하지 않는다.
    job = mapping.build_job_context(posting)
    AnalysisResponse(
        status="COMPLETED",
        job=job,
        evaluation=mapping.build_evaluation(
            {"summary": "요약"}, {"status": "APPLY_NOW", "reasons": ["근거"]}, req_status),
        change_proposal=proposal,
        competency_proposal=mapping.build_competency_proposal(
            posting, req_status, [], job.primary_track or "BACKEND"),
    )


def test_change_proposal_korean_only_requirement_gets_posting_scoped_key():
    """ascii 슬러그가 불가능한 요건은 공고 범위 키를 받는다 — 위조 영문명을 만들지 않는다."""

    career = _career()
    req_status = [{"requirementId": "r1", "type": "required",
                   "text": "대규모 트래픽 운영 경험", "status": "uncertain"}]
    proposal = mapping.build_change_proposal(
        career, {"roleCategory": "backend"}, req_status, [], str(uuid4()))
    created = [n for n in proposal.nodes if n.action == "CREATE" and n.kind == "SKILL"]
    assert len(created) == 1
    assert created[0].canonical_key.startswith("skill.posting-")


def test_two_requirements_matching_same_node_share_one_reuse():
    """REUSE 노드의 UUID 는 변경안 안에서 유일해야 한다 — 같은 노드는 ref 를 공유한다."""

    existing = _existing("Java", "skill.java")
    career = _career([existing])
    req_status = [
        {"requirementId": "r1", "type": "required", "text": "Java 백엔드 개발", "status": "met"},
        {"requirementId": "r2", "type": "preferred", "text": "Java 성능 튜닝", "status": "met"},
    ]
    proposal = mapping.build_change_proposal(
        career, {"roleCategory": "backend"}, req_status, [], str(uuid4()))
    reused = [n for n in proposal.nodes if n.action == "REUSE"]
    assert len(reused) == 1
    assert {r.node_ref for r in proposal.requirements} == {reused[0].ref}


# ---------------------------------------------------------------------------
# 되묻기 → 선택형 질문
# ---------------------------------------------------------------------------
def test_question_without_options_is_never_fabricated():
    assert mapping.build_question({"field": "preferences",
                                   "question": "선호 근무지가 어디인가요?"}) is None


def test_question_with_options_becomes_contract_question():
    question = mapping.build_question({
        "field": "target_track",
        "question": "어느 직무로 지원하나요?",
        "options": ["백엔드", "프론트엔드"],
    })
    assert question is not None
    assert question.key == "target_track"
    assert [o.label for o in question.options] == ["백엔드", "프론트엔드"]
    assert len({o.value for o in question.options}) == 2


def test_question_key_is_stable_for_same_text():
    q = {"field": "질문(패턴 밖)", "question": "어느 직무로 지원하나요?"}
    assert mapping.question_key(q) == mapping.question_key(dict(q))
    assert mapping.question_key(q).startswith("q-")


# ---------------------------------------------------------------------------
# 대화 매핑·커리어 텍스트·조각 변환
# ---------------------------------------------------------------------------
def test_chat_intent_prefers_dispatched_agent():
    assert mapping.chat_intent(["fit_analysis"]) == "POSTING_ANALYSIS"
    assert mapping.chat_intent(["unknown", "roadmap_manager"]) == "ROADMAP_QUESTION"
    assert mapping.chat_intent([]) == "GENERAL_CAREER"


def test_chat_actions_translate_requested_assets_only():
    should_request, actions = mapping.chat_actions([
        {"field": "job_posting", "question": "공고를 주세요"},
        {"field": "resume", "question": "이력서를 주세요"},
    ])
    assert should_request is True
    assert {a.action for a in actions} == {"ATTACH_POSTING", "OPEN_STORAGE"}
    assert mapping.chat_actions([]) == (False, [])


def test_open_map_is_offered_when_the_turn_produced_map_content():
    """로드맵을 **채팅으로 읊지 않기 위한 유일한 레버**(백엔드 계약).

    지도에 생긴 것을 말로 다시 나열하면 사용자는 같은 내용을 두 번 보고 지도를 열 이유가
    없어진다. 채팅은 생겼다는 사실만 알린다.
    """

    _, actions = mapping.chat_actions([], ["fit_analysis", "application_plan"])
    assert [a.action for a in actions] == ["OPEN_MAP"]
    assert actions[0].label == "커리어 지도 보기"

    _, roadmap = mapping.chat_actions([], ["roadmap_manager"])
    assert [a.action for a in roadmap] == ["OPEN_MAP"]


def test_open_map_follows_what_ran_not_what_was_said():
    """실행 사실로만 정한다 — 답변 문장을 뒤져 '로드맵을 만든 것 같다'고 추측하지 않는다."""

    assert mapping.chat_actions([], ["career_chat", "posting_analysis"]) == (False, [])
    assert mapping.chat_actions([], []) == (False, [])


def test_career_text_carries_fragments_and_completed_nodes():
    career = CareerSnapshot(
        graph_id=uuid4(), version=1,
        nodes=[_existing("Spring", "skill.spring", progress="COMPLETED"),
               _existing("Kafka", "skill.kafka", progress="IN_PROGRESS")],
        fragments=[{"id": str(uuid4()), "kind": "PROJECT", "title": "게시판 API",
                    "description": "Spring Boot 게시판", "detail": {}}],
    )
    text = mapping.career_text(career)
    assert "[PROJECT] 게시판 API" in text
    assert "[보유 역량] Spring" in text
    assert "Kafka" not in text   # 완료되지 않은 노드는 보유 근거가 아니다


def test_fragments_from_profile_maps_v2_kinds():
    fragments = mapping.fragments_from_profile({
        "skills": [{"name": "Python", "level": "상"}],
        "experiences": [{"company": "회사", "role": "백엔드", "period": "2년"}],
        "education": [{"school": "대학", "major": "컴퓨터공학", "degree": "학사"}],
        "awards": [{"title": "해커톤 대상", "organization": "주최"}],
    })
    kinds = {f.kind for f in fragments}
    assert kinds == {"SKILL", "EXPERIENCE", "EDUCATION", "ACHIEVEMENT"}
    python = next(f for f in fragments if f.kind == "SKILL")
    assert python.canonical_key == "skill.python"
    korean = next(f for f in fragments if f.kind == "ACHIEVEMENT")
    assert korean.canonical_key is None   # ascii 불가 제목에 키를 위조하지 않는다
    assert mapping.extraction_summary(fragments)

"""v2 계약 ↔ 판정 엔진 어댑터. 계약은 무상태, 엔진은 세션 기반 — 그 사이를 여기서 잇는다.

원칙:
  · **매 요청이 문맥 전부다.** 요청에 담긴 공고·커리어로 세션을 그때그때 다시 세운다
    (analysis_job_id 단위로 격리 — 재시도가 와도 같은 상태에서 다시 시작한다).
  · **엔진의 되묻기를 어댑터가 대신 판단하지 않는다.** 단,
      - 동의 게이트(confirm_*): 백엔드의 분석 요청 자체가 사용자의 실행 지시다 → "네"로 답한다.
      - 자산 요청(resume/job_posting): v2 요청에 확정 자료가 전부 담겨 온다 →
        "가진 자료가 전부"라고 사실대로 답한다(없는 자료를 지어내지 않는다).
      - 그 밖의 질문: 선택지가 있으면 NEEDS_INPUT 으로 사용자에게 올리고, 없으면
        "정보 없음"으로 답해 엔진의 uncertain 처리(모른다 ≠ 아니다)에 맡긴다.
  · 판정에 이르지 못하면 그럴듯한 결과 대신 예외를 낸다 — 백엔드가 FAILED 로 기록하고
    재시도할 수 있다(폴백은 이유를 삼키지 않는다, AGENTS.md §2-6).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from pydantic import BaseModel, Field

from jobis_ai.v2bridge import mapping
from jobis_ai.v2bridge.models import (
    AnalysisRequest,
    AnalysisResponse,
    CareerExtractionRequest,
    CareerExtractionResponse,
    ChatRequest,
    ChatResponse,
    EvidenceVerificationRequest,
    EvidenceVerificationResponse,
)

log = logging.getLogger(__name__)

# 오케스트레이터 왕복 상한 (webbridge/runner.MAX_TURNS 와 같은 취지).
MAX_TURNS = 4
# 되묻기 자동 응답 분류. 이 밖의 field 는 "사용자에게 물을 질문"으로 본다.
_CONSENT_FIELDS = {"confirm_pipeline", "confirm_fit"}
_ASSET_FIELDS = {"resume", "resume_extra", "job_posting"}

_ANALYZE_INTENT = "이 공고와 내 자료로 적합도를 분석해 주세요."
_ASSET_ANSWER = "요청에 담긴 커리어 자료가 제가 가진 전부예요. 그 근거만으로 판정해 주세요."
_NO_INFO_ANSWER = "따로 밝힐 정보가 없어요. 확인된 자료만으로 진행해 주세요."


class EngineNotConfigured(Exception):
    """LLM 이 설정되지 않아 어떤 판정도 낼 수 없다 → 503 AI_PROVIDER_NOT_CONFIGURED."""


class EngineFailed(Exception):
    """엔진이 돌았지만 계약이 요구하는 결과에 이르지 못했다 → 503 AI_PROVIDER_UNAVAILABLE."""


def provider_name() -> str:
    try:
        # config 가 .env 를 로드한다 — os.getenv 로 직접 읽으면 .env 값을 놓친다(실측).
        from jobis_ai.config import get_settings
        return get_settings().llm_provider
    except Exception:   # noqa: BLE001 — health 는 설정이 깨져도 응답해야 한다
        return os.getenv("LLM_PROVIDER", "unknown")


# ---------------------------------------------------------------------------
# 분석 (/v1/analyses)
# ---------------------------------------------------------------------------
# 판정 그래프가 갱신하는 상태 중 v2 응답 조립에 필요한 키 (webbridge/runner._STATE_KEYS 참조).
_STATE_KEYS = ("normalizedJobPosting", "gapAnalysisResult", "analysisResult")


class _StateCollector:
    """trace 의 node 이벤트에서 판정 상태를 줍는다 (runner._Relay 의 수집 부분만)."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = {}

    def __call__(self, event: dict) -> None:
        if event.get("kind") != "node":
            return
        update = (event.get("detail") or {}).get("update") or {}
        for key in _STATE_KEYS:
            if update.get(key) is not None:
                self.state[key] = update[key]

    def absorb_results(self, results: dict[str, Any]) -> None:
        """그래프를 타지 않는 에이전트 산출물도 줍는다 (runner._absorb_results 와 동일)."""

        posting = (results.get("posting_analysis") or {}).get("postingAnalysis")
        if posting and not self.state.get("normalizedJobPosting"):
            self.state["normalizedJobPosting"] = posting
        fit = results.get("fit_analysis")
        if isinstance(fit, dict) and fit.get("status") == "completed" \
                and not self.state.get("analysisResult"):
            self.state["analysisResult"] = fit


def analyze(request: AnalysisRequest) -> AnalysisResponse:
    from jobis_ai import trace
    from jobis_ai.contracts.api import ChatRequest as EngineChatRequest
    from jobis_ai.orchestrator.chat import handle_chat
    from jobis_ai.orchestrator.session import get_session_store
    from jobis_ai.structured import llm_unconfigured

    session_id = f"v2-analysis-{request.analysis_job_id}"
    store = get_session_store()
    store.clear(session_id)   # 재시도·질문 재개가 와도 요청에 담긴 문맥에서 다시 시작한다
    assets: dict[str, Any] = {
        "job_posting": {"sourceType": "text", "value": request.posting.raw_text},
    }
    resume_text = mapping.career_text(request.career).strip()
    if resume_text:
        assets["resume"] = {"sourceType": "text", "value": resume_text}
    store.update(session_id, assets)

    answered = {a.question_key: a for a in request.answers}
    message = _ANALYZE_INTENT
    if request.answers:
        facts = " ".join(f"확인된 사실: {a.question_text} → {a.answer_label}."
                         for a in request.answers)
        message = f"{_ANALYZE_INTENT} {facts}"

    collector = _StateCollector()
    for _turn in range(MAX_TURNS):
        with trace.recording(sink=collector):
            response = handle_chat(EngineChatRequest(sessionId=session_id, message=message))
        if llm_unconfigured(list(response.warnings or [])):
            raise EngineNotConfigured("LLM 이 설정되지 않아 판정할 수 없어요")
        collector.absorb_results(response.results or {})

        analysis = collector.state.get("analysisResult") or {}
        if analysis.get("status") == "completed":
            return _completed(request, collector.state, session_id)

        follow_ups = list(response.followUpQuestions or [])
        if not follow_ups:
            raise EngineFailed("엔진이 판정 없이 종료했어요 — 재시도해 주세요")

        parts: list[str] = []
        for question in follow_ups:
            field = str(question.get("field") or "")
            text = str(question.get("question") or question.get("text") or "").strip()
            key = mapping.question_key(question)
            if key in answered:
                parts.append(f"{text} → {answered[key].answer_label}")
            elif field in _CONSENT_FIELDS:
                # 백엔드의 분석 작업 실행이 곧 사용자의 실행 지시다 — 동의를 지어내는 게 아니다.
                parts.append("네, 진행해 주세요.")
            elif field in _ASSET_FIELDS:
                parts.append(_ASSET_ANSWER)
            else:
                built = mapping.build_question(question) if request.question_count < 3 else None
                if built is not None:
                    return AnalysisResponse(status="NEEDS_INPUT", question=built)
                # 선택지가 없거나 질문 예산(3회)이 다 됐다 — 모르는 건 모른다로 두고 진행.
                log.info("[v2bridge] 되묻기를 정보 없음으로 진행 (field=%s, budget=%d)",
                         field, request.question_count)
                parts.append(f"{text} → {_NO_INFO_ANSWER}" if text else _NO_INFO_ANSWER)
        message = " / ".join(parts)

    raise EngineFailed("왕복 상한 안에 판정에 이르지 못했어요 — 재시도해 주세요")


def _completed(request: AnalysisRequest, state: dict[str, Any],
               session_id: str) -> AnalysisResponse:
    analysis = state.get("analysisResult") or {}
    posting = state.get("normalizedJobPosting") or {}
    req_status = list((state.get("gapAnalysisResult") or {}).get("requirementStatus") or [])

    decision = _application_plan(session_id, analysis)
    try:
        evaluation = mapping.build_evaluation(analysis, decision, req_status)
    except mapping.VerdictUndetermined as exc:
        # 판정 보류를 그럴듯한 verdict 로 바꾸지 않는다 — 실패로 알려 재시도하게 한다.
        raise EngineFailed(str(exc)) from exc

    return AnalysisResponse(
        status="COMPLETED",
        job=mapping.build_job_context(posting),
        evaluation=evaluation,
        change_proposal=mapping.build_change_proposal(
            request.career, posting, req_status,
            list(analysis.get("gaps") or []), str(request.posting.id)),
    )


def _application_plan(session_id: str, analysis: dict) -> dict:
    """application_plan 에이전트 → decision. 실패하면 빈 dict (호출부가 실패로 처리)."""

    from jobis_ai.agents import get_agent_registry
    from jobis_ai.orchestrator.session import get_session_store

    spec = get_agent_registry().get("application_plan")
    if spec is None:
        return {}
    store = get_session_store()
    store.update(session_id, {"analysis": analysis})
    session = store.get(session_id)
    session["_sessionId"] = session_id
    try:
        outcome = spec.entry(session)
    except Exception:   # noqa: BLE001 — 판정 보류로 흘러가 EngineFailed 가 된다
        log.exception("[v2bridge] application_plan 실행 실패")
        return {}
    if outcome.sessionUpdates:
        store.update(session_id, outcome.sessionUpdates)
    return ((outcome.data or {}).get("applicationPlan") or {}).get("decision") or {}


# ---------------------------------------------------------------------------
# 대화 (/v1/chat)
# ---------------------------------------------------------------------------
def promote_pasted_posting(utterance: str):
    """대화창에 공고·이력서 원문을 그대로 붙여넣은 턴 → (발화, 첨부) 로 승격.

    구 브릿지(webbridge)와 같은 처리 — 이게 없으면 붙여넣은 공고가 "긴 대화"로 처리돼
    공고 정리(항목화) 대신 일반 대화 답변이 나간다(2026-07-30 실측). 감지는 webbridge 의
    결정론 판별(_posting_in_message)을 그대로 쓴다 — 두 브릿지의 기준이 갈리면 안 된다.

    kind 는 엔진의 내용 분류(resolve_kind)로 정한다. 공고 표지어만 보고 job_posting 으로
    박으면 이력서에도 "주요 업무" 같은 어휘가 있어 오배정되고, 엔진이 저장 전에 바로잡긴
    하지만 "공고가 아니라 이력서로 보여서…"라는 해명 문장이 사용자에게 나간다
    (2026-07-30 실측 — 어색하다는 피드백). 같은 분류기를 여기서 먼저 태워 힌트를 맞춘다.
    URL 은 내용 판정이 성립하지 않으므로 공고로 고정한다(D62).
    """

    from jobis_ai.contracts.api import ChatAttachment, SourceType
    from jobis_ai.orchestrator.attachment_kind import resolve_kind
    from jobis_ai.webbridge.http_handlers import _posting_in_message

    pasted = _posting_in_message(utterance)
    if not pasted:
        return utterance, []
    if pasted.startswith(("http://", "https://")):
        kind, source = "job_posting", SourceType.url
    else:
        kind, _kind_warnings = resolve_kind("job_posting", pasted)
        if kind not in ("resume", "job_posting"):
            kind = "job_posting"
        source = SourceType.text
    attachment = ChatAttachment(kind=kind, sourceType=source, value=pasted)
    # 발화는 비운다 — 첨부만 온 턴의 중립 발화는 handle_chat 이 합성하고 플래너가 정한다
    # (webbridge 와 동일. 여기서 "분석해 줘"를 지어 넣으면 흐름 하드코딩이다).
    return "", [attachment]


def chat(request: ChatRequest) -> ChatResponse:
    from jobis_ai.contracts.api import ChatRequest as EngineChatRequest
    from jobis_ai.orchestrator.chat import handle_chat
    from jobis_ai.orchestrator.session import get_session_store
    from jobis_ai.structured import llm_unconfigured

    utterance = next((m.content for m in reversed(request.messages) if m.role == "USER"), "")
    if not utterance.strip():
        raise EngineFailed("사용자 발화가 없어요")
    utterance, attachments = promote_pasted_posting(utterance)

    session_id = f"v2-chat-{request.conversation_id}"
    summary_text = _career_summary_text(request)
    if summary_text:
        # 백엔드가 매 요청 실어 보내는 확정 커리어 요약 — 이력 원천으로 갱신해 둔다(무상태 계약).
        get_session_store().update(
            session_id, {"resume": {"sourceType": "text", "value": summary_text}})

    response = handle_chat(EngineChatRequest(
        sessionId=session_id, message=utterance, attachments=attachments))
    if llm_unconfigured(list(response.warnings or [])):
        raise EngineNotConfigured("LLM 이 설정되지 않아 대화할 수 없어요")
    reply = (response.reply or "").strip()
    if not reply:
        raise EngineFailed("엔진이 빈 답변을 반환했어요")

    follow_ups = list(response.followUpQuestions or [])
    should_request_posting, actions = mapping.chat_actions(follow_ups)
    return ChatResponse(
        message=reply[:4000],
        intent=mapping.chat_intent(list(response.dispatched or [])),
        should_request_posting=should_request_posting,
        suggested_actions=actions,
    )


def _career_summary_text(request: ChatRequest) -> str:
    """CareerSummary → 이력 원천 텍스트. 백엔드가 보낸 확정 항목만 옮긴다."""

    career = request.career
    sections = [
        ("완료한 커리어 지도 항목", career.completed_nodes),
        ("진행 중인 목표", career.active_goals),
        ("최근 관심 공고", career.recent_postings),
        ("보유 증빙", career.saved_evidence),
    ]
    lines = [f"[{title}]\n" + "\n".join(f"- {item}" for item in items)
             for title, items in sections if items]
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# 커리어 조각 추출 (/v1/career-extractions)
# ---------------------------------------------------------------------------
def extract_career(request: CareerExtractionRequest) -> CareerExtractionResponse:
    from jobis_ai.graph import nodes as graph_nodes
    from jobis_ai.structured import llm_unconfigured

    # 백엔드는 rawText 를 항상 채워 보낸다(파일·URL 도 서버가 원문을 뽑아 옴) — 텍스트로 처리.
    out = graph_nodes.build_user_profile({
        "resumeInput": {"sourceType": "text", "value": request.raw_text},
    })
    warnings = list(out.get("warnings") or [])
    if llm_unconfigured(warnings):
        raise EngineNotConfigured("LLM 이 설정되지 않아 조각을 추출할 수 없어요")

    fragments = mapping.fragments_from_profile(out.get("normalizedUserProfile") or {})
    if not fragments:
        # 계약이 조각 1개 이상을 요구한다. 샘플·추측 조각을 만들지 않고 실패로 알린다.
        raise EngineFailed("원문에서 커리어 조각을 찾지 못했어요 — 원문을 보완해 재시도해 주세요")
    return CareerExtractionResponse(
        summary=mapping.extraction_summary(fragments), fragments=fragments)


# ---------------------------------------------------------------------------
# 증빙 검증 (/v1/evidence-verifications)
# ---------------------------------------------------------------------------
class _EvidenceRead(BaseModel):
    """서술형 증빙 ↔ 노드 범위의 대조 판정 — semantic_judge 계열의 의도적 LLM 판정 예외다
    (AGENTS.md §1: 서술형 요구의 이진 판정). 링크 내용을 실제로 읽지 않으므로 제출된
    설명·주소에 드러난 것만 근거로 삼게 스키마 설명으로 좁힌다."""

    verdict: str = Field(default="NEEDS_WORK", description=(
        "VERIFIED=제출 설명이 노드의 범위(scopeDefinition)를 충족함을 구체 근거로 보여줌 / "
        "NEEDS_WORK=방향은 맞지만 근거가 부족함 / REJECTED=이 노드와 무관하거나 근거 없음. "
        "링크 내용을 열어볼 수 없으므로 설명·주소에 드러난 것만 인정한다. "
        "확인되지 않으면 VERIFIED 를 쓰지 않는다."))
    confidence: float = Field(default=0.0, description=(
        "판정 확신도 0~1. 제출물에 실제로 있는 근거의 구체성으로만 정한다. "
        "근거 없이 0.75 이상을 주지 않는다."))
    summary: str = Field(default="", description=(
        "무엇이 확인됐고 무엇이 안 됐는지 두세 문장. 제출물에 없는 사실을 쓰지 않는다."))
    strengths: list[str] = Field(default_factory=list, description=(
        "제출물에서 확인된 근거. 실제로 드러난 것만, 없으면 빈 목록."))
    gaps: list[str] = Field(default_factory=list, description=(
        "노드 범위 대비 부족한 점. 확인 불가와 부족을 구분해 쓴다."))
    nextActions: list[str] = Field(default_factory=list, description=(
        "부족을 메울 다음 행동 제안. 격차(gaps)에 대응하는 것만."))


_EVIDENCE_SYSTEM = """너는 커리어 지도 노드의 증빙을 검토하는 검토자다.
- 노드의 scopeDefinition 이 판정 기준이다. 제출된 제목·설명·주소에 **실제로 드러난 것만** 근거로 삼는다.
- 링크 내용을 열어 읽을 수 없다 — 열어봤다고 가정하거나 내용을 추측하지 않는다.
- 확인되지 않으면 VERIFIED 를 주지 않는다. 모르면 모른다고 쓴다(NEEDS_WORK + 무엇이 필요한지).
- 합격 가능성·역량 수준을 단정하지 않는다. 이 증빙이 이 노드를 증명하는지만 본다."""

_ALLOWED_VERDICTS = {"VERIFIED", "NEEDS_WORK", "REJECTED"}


def verify_evidence(request: EvidenceVerificationRequest) -> EvidenceVerificationResponse:
    import json

    from jobis_ai.structured import llm_unconfigured, run_structured

    payload = {
        "node": {"title": request.node.title, "domain": request.node.domain,
                 "kind": request.node.kind, "level": request.node.level,
                 "scopeDefinition": request.node.scope_definition},
        "evidence": {"type": request.evidence.evidence_type,
                     "title": request.evidence.title,
                     "sourceUrl": request.evidence.source_url or "",
                     "content": request.evidence.content},
    }
    read, warnings = run_structured(
        _EvidenceRead, _EVIDENCE_SYSTEM, json.dumps(payload, ensure_ascii=False),
        node="v2_evidence_verify",
    )
    if read is None:
        if llm_unconfigured(warnings):
            raise EngineNotConfigured("LLM 이 설정되지 않아 증빙을 검증할 수 없어요")
        raise EngineFailed("증빙 판정을 만들지 못했어요 — 재시도해 주세요")

    verdict = read.verdict if read.verdict in _ALLOWED_VERDICTS else "NEEDS_WORK"
    confidence = min(max(float(read.confidence or 0.0), 0.0), 1.0)
    summary = (read.summary or "").strip()
    if not summary:
        # 요약이 비면 판정 사실로만 조립한다 (LLM 재호출 없이).
        summary = (f"확인된 근거 {len(read.strengths)}건, 보완 필요 {len(read.gaps)}건으로 "
                   f"{verdict} 판정이에요.")
    return EvidenceVerificationResponse(
        verdict=verdict, confidence=confidence, summary=summary[:2000],
        strengths=[s[:500] for s in read.strengths][:10],
        gaps=[g[:500] for g in read.gaps][:10],
        next_actions=[n[:500] for n in read.nextActions][:10],
    )

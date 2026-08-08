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
import re
import hashlib
from dataclasses import replace
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from jobis_ai.v2bridge import enrich, mapping
from jobis_ai.v2bridge.models import (
    AnalysisRequest,
    AnalysisResponse,
    CareerExtractionRequest,
    CareerExtractionResponse,
    ChatRequest,
    ChatResponse,
    CompetencyAssessmentRequest,
    CompetencyAssessmentResponse,
    CompetencyLearningRequest,
    CompetencyLearningResponse,
    EvidenceVerificationRequest,
    EvidenceVerificationResponse,
    PostingImportRequest,
    PostingImportResponse,
    PostingImportWarning,
)

log = logging.getLogger(__name__)

# 오케스트레이터 왕복 상한 (webbridge/runner.MAX_TURNS 와 같은 취지).
MAX_TURNS = 4
POSTING_INSUFFICIENT = "POSTING_TEXT_INSUFFICIENT"
CAREER_DATA_REQUIRED = "CAREER_DATA_REQUIRED"
# 되묻기 자동 응답 분류. 이 밖의 field 는 "사용자에게 물을 질문"으로 본다.
_CONSENT_FIELDS = {"confirm_pipeline", "confirm_fit"}
_ASSET_REQUEST_CODE = {
    "resume": CAREER_DATA_REQUIRED,
    "resume_extra": CAREER_DATA_REQUIRED,
    "job_posting": POSTING_INSUFFICIENT,
}

_ANALYZE_INTENT = "이 공고와 내 자료로 적합도를 분석해 주세요."
_NO_INFO_ANSWER = "따로 밝힐 정보가 없어요. 확인된 자료만으로 진행해 주세요."

# Backend/PostgreSQL owns these cross-turn assets.  SQLite remains an engine
# implementation cache only; every request replaces it with this allow-listed
# snapshot and every response returns the updated snapshot.
_WORKSPACE_KEYS = frozenset({
    "history",
    "resume", "job_posting", "profile", "analysis", "analysis_key", "recommendations",
    "roadmap", "coverletter", "interview", "application_plan",
    "posting_summary", "posting_library", "resume_library",
    "judgment_summary", "preparationPeriodWeeks", "availableHoursPerWeek",
    "preferences", "pendingConsent", "pendingRequest", "resumeAskedFor", "user_facts",
    "unsupported_requests",
})

_OUTPUT_ASSETS = {
    "posting_summary": "posting_summary",
    "analysis": "analysis",
    "roadmap": "roadmap",
    "judgment_summary": "judgment_summary",
    "profile": "profile",
    "recommendations": "recommendations",
    "coverletter": "coverletter",
    "interview": "interview",
    "application_plan": "application_plan",
    "preparationPeriodWeeks": "preparation_period_weeks",
    "availableHoursPerWeek": "available_hours_per_week",
}


def _workspace_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    return {key: session[key] for key in _WORKSPACE_KEYS if key in session}


class EngineNotConfigured(Exception):
    """LLM 이 설정되지 않아 어떤 판정도 낼 수 없다 → 503 AI_PROVIDER_NOT_CONFIGURED."""


class EngineTimedOut(Exception):
    """LLM/CLI 호출 제한 시간을 실제로 초과했다."""


class EngineFailed(Exception):
    """엔진이 돌았지만 계약이 요구하는 결과에 이르지 못했다 → 503 AI_PROVIDER_UNAVAILABLE."""

    def __init__(self, message: str, *, code: str = "AI_PROVIDER_UNAVAILABLE") -> None:
        super().__init__(message)
        self.code = code


class AnalysisConvergenceFailed(EngineFailed):
    """에이전트가 호출에는 성공했지만 분석 상태가 반복돼 결과에 이르지 못했다."""


def provider_name() -> str:
    try:
        # config 가 .env 를 로드한다 — os.getenv 로 직접 읽으면 .env 값을 놓친다(실측).
        from jobis_ai.config import get_settings
        return get_settings().llm_provider
    except Exception:   # noqa: BLE001 — health 는 설정이 깨져도 응답해야 한다
        return os.getenv("LLM_PROVIDER", "unknown")


def import_posting(request: PostingImportRequest) -> PostingImportResponse:
    """대화 오케스트레이터와 같은 URL 어댑터로 공고 원문만 수집한다.

    저장과 개인화 분석 시작은 백엔드의 명시적인 사용자 작업으로 남겨 둔다.
    """

    from jobis_ai.feat_url import fetch_job_posting

    collected = fetch_job_posting(request.source_url)
    return PostingImportResponse(
        final_url=request.source_url,
        raw_text=(collected.text or "")[:100_000],
        warnings=[
            PostingImportWarning(
                code=str(warning.get("code") or "posting_import_warning"),
                message=str(warning.get("message") or "공고 수집 결과를 확인해 주세요."),
            )
            for warning in collected.warnings
        ],
    )


def _llm_timed_out(warnings: list[dict]) -> bool:
    for warning in warnings:
        if str(warning.get("code") or "") != "llm_call_failed":
            continue
        message = str(warning.get("message") or "").lower()
        if any(token in message for token in ("timed out", "timeout", "time out")):
            return True
    return False


# ---------------------------------------------------------------------------
# 분석 (/v1/analyses)
# ---------------------------------------------------------------------------
# 판정 그래프가 갱신하는 상태 중 v2 응답 조립에 필요한 키 (webbridge/runner._STATE_KEYS 참조).
_STATE_KEYS = (
    "normalizedJobPosting",
    "normalizedUserProfile",
    "gapAnalysisResult",
    "analysisResult",
    "profileCompletionQuestions",
)


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


def _requires_known_info_finalization(request: AnalysisRequest) -> bool:
    """질문 상한 또는 포괄적 경험 부재 확인 → 더 묻지 않고 보유 정보로 판정한다."""

    if request.question_count >= 3:
        return True
    return any(
        answer.answer_status == "CONFIRMED_ABSENT"
        and answer.absence_scope == "GENERAL_EXPERIENCE"
        for answer in request.answers
    )


def _merge_node_update(state: dict[str, Any], update: dict[str, Any]) -> None:
    """LangGraph reducer와 같은 방식으로 직접 실행한 노드의 부분 갱신을 합친다."""

    for key, value in update.items():
        if key in {"warnings", "sources", "toolLog"}:
            state[key] = [*(state.get(key) or []), *(value or [])]
        elif key in {"retryCount", "nodeFailed"}:
            state[key] = {**(state.get(key) or {}), **(value or {})}
        else:
            state[key] = value


def _apply_confirmed_absences(report, answers) -> int:
    """사용자가 명시한 부재만 MatchReport에 반영한다. 확인 못 한 항목은 건드리지 않는다."""

    confirmed_requirement_ids = {
        requirement_id
        for answer in answers
        if answer.answer_status == "CONFIRMED_ABSENT"
        for requirement_id in answer.related_requirement_ids
    }
    general_experience_absent = any(
        answer.answer_status == "CONFIRMED_ABSENT"
        and answer.absence_scope == "GENERAL_EXPERIENCE"
        for answer in answers
    )

    changed = 0
    resolved_matches = []
    for match in report.matches:
        confirmed_for_requirement = match.requirementId in confirmed_requirement_ids
        confirmed_for_seniority = general_experience_absent and match.kind == "seniority"
        if confirmed_for_requirement or confirmed_for_seniority:
            changed += 1
            resolved_matches.append(replace(
                match,
                status="not_met",
                matchedEvidenceIds=[],
                confidence=1.0,
                method="user_confirmed_absence",
                reason=(
                    "사용자가 이 요구사항에 해당하는 경험이 없다고 명시했습니다."
                    if confirmed_for_requirement
                    else "사용자가 프로젝트·업무 경험이 없다고 명시했습니다."
                ),
            ))
        else:
            resolved_matches.append(match)
    report.matches = resolved_matches
    return changed


def _finalize_with_known_information(
        request: AnalysisRequest,
        collected_state: dict[str, Any],
        session_id: str,
) -> AnalysisResponse:
    """확인 질문이 끝나면 UNKNOWN을 억지로 미충족 처리하지 않고 분석을 완료한다.

    실제 공고 파서·프로필 빌더가 만든 상태와 실제 gap matcher를 그대로 쓴다. 사용자가
    명시적으로 없다고 답한 요구조건(및 포괄 부재일 때 연차)만 `not_met`으로 바꾸며,
    확인하지 못한 나머지는 `uncertain`으로 보존한다. 판정·로드맵 노드는 기존 코드를
    호출하고 이 브리지는 상태 전이만 담당한다.
    """

    from jobis_ai.contracts.domain import GapAnalysisResult
    from jobis_ai.gap_matcher import get_gap_matcher, overall_fit, to_gap_payload
    from jobis_ai.graph import nodes as graph_nodes

    posting = collected_state.get("normalizedJobPosting")
    profile = collected_state.get("normalizedUserProfile")
    if posting is None or profile is None:
        raise AnalysisConvergenceFailed(
            "질문 답변은 받았지만 공고·프로필 중간 상태를 회수하지 못했습니다."
        )

    state: dict[str, Any] = {
        **collected_state,
        "analysisId": str(request.analysis_job_id),
        "preparationPeriodWeeks": 8,
        "availableHoursPerWeek": 10,
        "includeAlternatives": True,
        "followUpQuestions": [],
        "warnings": list(collected_state.get("warnings") or []),
        "sources": list(collected_state.get("sources") or []),
        "toolLog": list(collected_state.get("toolLog") or []),
        "retryCount": dict(collected_state.get("retryCount") or {}),
        "nodeFailed": dict(collected_state.get("nodeFailed") or {}),
    }

    # 기업 맥락·RAG 경고는 기존 analyze_gap 노드가 소유한다. 같은 매칭 조합의 의미 판정은
    # core 캐시를 타므로 아래 재계산이 별도 LLM 왕복을 만들지 않는다.
    base_update = graph_nodes.analyze_gap(state)
    base_gap = dict(base_update.get("gapAnalysisResult") or {})
    _merge_node_update(state, base_update)

    requirements = graph_nodes._build_comparison_requirements(posting)
    report = get_gap_matcher().match(requirements, profile)
    changed = _apply_confirmed_absences(report, request.answers)

    gap = GapAnalysisResult(**to_gap_payload(report))
    gap.overallScore, gap.fitGrade = overall_fit(gap.scoreBasis.model_dump())
    gap.companyContext = list(base_gap.get("companyContext") or [])
    gap.sources = list(base_gap.get("sources") or [])
    uncertain_count = sum(match.status == "uncertain" for match in report.matches)
    if uncertain_count:
        gap.uncertainties.append(
            f"확인하지 못한 요구사항 {uncertain_count}건은 미충족으로 단정하지 않고 판정 불가로 남겼습니다."
        )
    state["gapAnalysisResult"] = gap.model_dump()
    state["followUpQuestions"] = []
    state["warnings"] = [
        *(state.get("warnings") or []),
        {
            "code": "clarification_finalized_with_known_information",
            "message": (
                f"추가 질문을 마치고 사용자 확인 부재 {changed}건과 보유 정보로 판정을 완료했습니다."
            ),
            "node": "v2bridge",
        },
    ]

    if gap.fitGrade in {"중", "하"}:
        _merge_node_update(state, graph_nodes.plan_roadmap(state))
    _merge_node_update(state, graph_nodes.find_alternatives(state))
    _merge_node_update(state, graph_nodes.verify_result(state))
    state["followUpQuestions"] = []
    _merge_node_update(state, graph_nodes.assemble_output(state))

    analysis = state.get("analysisResult") or {}
    if analysis.get("status") != "completed":
        raise AnalysisConvergenceFailed(
            "확인된 정보로 결과를 조립했지만 완료 상태에 이르지 못했습니다."
        )
    return _completed(request, state, session_id)


def analyze(request: AnalysisRequest) -> AnalysisResponse:
    from jobis_ai import trace
    from jobis_ai.contracts.api import ChatRequest as EngineChatRequest
    from jobis_ai.orchestrator.chat import handle_chat
    from jobis_ai.orchestrator.session import get_session_store
    from jobis_ai.structured import llm_unconfigured

    # 직무 선택에 따라 로드맵 경로가 실제로 갈리는 혼합 공고는 무거운 분석을 시작하기
    # 전에 먼저 확인한다. 특정 회사에 질문을 고정하지 않고 공고에 나타난 경로 근거로만
    # 결정하며, 이미 같은 질문에 답했다면 다시 묻지 않는다.
    if request.question_count < 3:
        role_question = mapping.role_clarification_question(
            {},
            raw_text=request.posting.raw_text,
            answers=request.answers,
        )
        if role_question is not None:
            return AnalysisResponse(status="NEEDS_INPUT", question=role_question)

    session_id = f"v2-analysis-{request.analysis_job_id}"
    store = get_session_store()
    store.clear(session_id)   # 재시도·질문 재개가 와도 요청에 담긴 문맥에서 다시 시작한다
    from jobis_ai.orchestrator.attachment_kind import is_bare_url

    posting_is_url = is_bare_url(request.posting.raw_text)
    assets: dict[str, Any] = {
        "job_posting": {
            "sourceType": "url" if posting_is_url else "text",
            "value": (
                request.posting.source_url or request.posting.raw_text
                if posting_is_url
                else request.posting.raw_text
            ),
        },
    }
    resume_text = mapping.career_text(request.career).strip()
    clarification_evidence = "\n\n".join(
        f"[사용자 추가 답변]\n질문: {answer.question_text}\n답변: {answer.answer_label}"
        for answer in request.answers
        if answer.answer_label.strip()
    )
    if clarification_evidence:
        resume_text = "\n\n".join(
            part for part in (resume_text, clarification_evidence) if part
        )
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
        response_warnings = list(response.warnings or [])
        if llm_unconfigured(response_warnings):
            raise EngineNotConfigured("LLM 이 설정되지 않아 판정할 수 없어요")
        if _llm_timed_out(response_warnings):
            raise EngineTimedOut("AI 모델 호출 제한 시간을 초과했습니다.")
        collector.absorb_results(response.results or {})

        normalized_posting = collector.state.get("normalizedJobPosting") or {}
        if request.question_count < 3:
            role_question = mapping.role_clarification_question(
                normalized_posting,
                raw_text=request.posting.raw_text,
                answers=request.answers,
            )
            if role_question is not None:
                return AnalysisResponse(status="NEEDS_INPUT", question=role_question)

        analysis = collector.state.get("analysisResult") or {}
        if analysis.get("status") == "completed":
            return _completed(request, collector.state, session_id)

        follow_ups = list(response.followUpQuestions or [])
        if not follow_ups:
            if _requires_known_info_finalization(request):
                return _finalize_with_known_information(
                    request, collector.state, session_id
                )
            raise EngineFailed("엔진이 판정 없이 종료했어요 — 재시도해 주세요")

        if _requires_known_info_finalization(request):
            log.info(
                "[v2bridge] 추가 질문을 종료하고 확인된 정보로 판정 "
                "(budget=%d, confirmedAbsence=%d)",
                request.question_count,
                sum(
                    answer.answer_status == "CONFIRMED_ABSENT"
                    for answer in request.answers
                ),
            )
            return _finalize_with_known_information(
                request, collector.state, session_id
            )

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
            elif field in _ASSET_REQUEST_CODE:
                code = _ASSET_REQUEST_CODE[field]
                message = text or (
                    "분석할 커리어 자료를 먼저 등록해 주세요."
                    if code == CAREER_DATA_REQUIRED
                    else "채용 공고 본문을 다시 등록해 주세요."
                )
                raise EngineFailed(message, code=code)
            else:
                built = mapping.build_question(question) if request.question_count < 3 else None
                if built is not None:
                    return AnalysisResponse(status="NEEDS_INPUT", question=built)
                # 선택지가 없거나 질문 예산(3회)이 다 됐다 — 모르는 건 모른다로 두고 진행.
                log.info("[v2bridge] 되묻기를 정보 없음으로 진행 (field=%s, budget=%d)",
                         field, request.question_count)
                parts.append(f"{text} → {_NO_INFO_ANSWER}" if text else _NO_INFO_ANSWER)
        message = " / ".join(parts)

    raise AnalysisConvergenceFailed(
        "AI 호출은 끝났지만 왕복 상한 안에 분석 상태가 수렴하지 않았습니다."
    )


def analyze_events(request: AnalysisRequest):
    """Run analysis while relaying observational trace events.

    The final result still comes from :func:`analyze`; this generator is only a
    progress window around it. Keeping one decision path prevents streamed and
    non-streamed requests from producing different roadmaps.
    """

    import queue as queue_module
    import threading

    from jobis_ai import trace
    from jobis_ai.v2bridge.stream import StreamBuilder

    builder = StreamBuilder(request.analysis_job_id)
    yield builder.backbone()

    relay: queue_module.Queue[tuple[str, Any]] = queue_module.Queue()

    def run_analysis() -> None:
        try:
            with trace.recording(sink=lambda event: relay.put(("event", event))):
                response = analyze(request)
            relay.put(("done", response))
        except Exception as exc:  # noqa: BLE001 - encoded as a typed stream error
            relay.put(("error", exc))

    threading.Thread(
        target=run_analysis,
        daemon=True,
        name=f"jobis-analysis-{request.analysis_job_id}",
    ).start()

    outcome: AnalysisResponse | None = None
    failure: Exception | None = None
    while outcome is None and failure is None:
        try:
            kind, payload = relay.get(timeout=12)
        except queue_module.Empty:
            heartbeat = builder.heartbeat()
            if heartbeat is not None:
                yield heartbeat
            continue

        if kind == "event":
            yield from builder.from_trace(payload)
        elif kind == "done":
            outcome = payload
        else:
            failure = payload

    if failure is not None:
        if isinstance(failure, EngineNotConfigured):
            code = "AI_PROVIDER_NOT_CONFIGURED"
        elif isinstance(failure, EngineTimedOut):
            code = "AI_TIMEOUT"
        elif isinstance(failure, AnalysisConvergenceFailed):
            code = "ANALYSIS_CONVERGENCE_FAILED"
        else:
            code = getattr(failure, "code", "AI_PROVIDER_UNAVAILABLE")
        yield builder.error(str(code), str(failure))
        return

    for event in (
        builder.validating(),
        builder.validated(),
        builder.roadmap() if outcome.status == "COMPLETED" else None,
        builder.assembled(),
    ):
        if event is not None:
            yield event
    if builder.suppressed:
        log.info(
            "[v2bridge] suppressed %d progress events for analysis %s",
            builder.suppressed,
            request.analysis_job_id,
        )
    yield builder.result(outcome)


def _completed(request: AnalysisRequest, state: dict[str, Any],
               session_id: str) -> AnalysisResponse:
    analysis = state.get("analysisResult") or {}
    posting, _role_resolution = mapping.enrich_posting_role(
        state.get("normalizedJobPosting") or {},
        raw_text=request.posting.raw_text,
        answers=request.answers,
    )
    req_status = list((state.get("gapAnalysisResult") or {}).get("requirementStatus") or [])

    decision = _application_plan(session_id, analysis)
    try:
        evaluation = mapping.build_evaluation(analysis, decision, req_status)
    except mapping.VerdictUndetermined as exc:
        # 판정 보류를 그럴듯한 verdict 로 바꾸지 않는다 — 실패로 알려 재시도하게 한다.
        raise EngineFailed(str(exc)) from exc

    job = mapping.build_job_context(
        posting,
        raw_text=request.posting.raw_text,
        answers=request.answers,
        source_text=(request.posting.raw_text if request.posting.source_type == "URL" else None),
    )
    if job.primary_track is None:
        raise EngineFailed("공고의 직무 경로를 확정하지 못했습니다")
    competency_proposal = mapping.build_competency_proposal(
        posting,
        req_status,
        list(analysis.get("gaps") or []),
        job.primary_track,
    )
    if competency_proposal is None:
        raise EngineFailed("공고에서 검증 가능한 역량과 프로젝트 과제를 만들지 못했습니다")

    return AnalysisResponse(
        status="COMPLETED",
        job=job,
        evaluation=evaluation,
        competency_proposal=competency_proposal,
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
# 붙여넣은 자료 **뒤에 붙은 요청 문장**의 표지. 개조식이 대부분인 공고·이력서 본문과 갈리는
# 신호만 쓴다(물음표로 끝나거나 대화체 요청 어미). 애매하면 잡지 않는다 — 잘못 잡으면 자료
# 본문 한 줄이 발화로 새어 나간다.
_REQUEST_TAIL = re.compile(
    r"[?？]\s*$"
    r"|(?:해\s*줘|해\s*주세요|알려\s*줘|알려\s*주세요|부탁\s*(?:해|드려|합니다|드립니다)"
    r"|좋을까요|어떨까요|가능할까요|괜찮을까요|추천\s*해\s*주|정리\s*해\s*주)\s*[.!]?\s*$"
)

# 요청 문장으로 인정하는 한 줄의 길이 상한 / 줄 수 상한.
_REQUEST_TAIL_MAX_CHARS = 200
_REQUEST_TAIL_MAX_LINES = 2


def _trailing_request(text: str) -> str:
    """붙여넣은 자료 뒤에 붙은 요청 문장을 떼어 돌려준다. 없으면 빈 문자열.

    자료를 통째로 첨부하면 이 문장이 **첨부 속으로 삼켜지고 발화는 비워진다.** 그러면
    `handle_chat` 이 중립 발화("방금 드린 자료로 이어서…")를 합성하므로 플래너도, 에이전트의
    루프도 **사용자가 무엇을 물었는지 모른다** — 실측(2026-08-01): 공고 원문 끝에 "이 공고
    기준으로 어떤 스택을 공부하고 어떤 프로젝트를 만들면 좋을까요?" 를 붙여 보냈는데 요약만
    돌아왔다. D69 가 URL 혼합 메시지에 한 보존을 붙여넣기 경로에도 한다.

    **첨부에서 이 문장을 지우지는 않는다.** 자르다 자료 본문을 잃는 것이 요청 한 줄이 원문에
    남는 것보다 나쁘다 — 파서는 필드를 뽑을 뿐이라 꼬리 한 줄에 해를 입지 않는다.
    """

    from jobis_ai.webbridge.http_handlers import _POSTING_MARKERS

    tail: list[str] = []
    for line in reversed([ln.strip() for ln in (text or "").splitlines()]):
        if not line:
            if tail:
                break          # 빈 줄 = 자료 본문과의 경계
            continue
        if (len(line) > _REQUEST_TAIL_MAX_CHARS
                or not _REQUEST_TAIL.search(line)
                or _POSTING_MARKERS.search(line)):   # 자료 본문 줄이다
            break
        tail.insert(0, line)
        if len(tail) >= _REQUEST_TAIL_MAX_LINES:
            break
    return " ".join(tail)


def promote_pasted_posting(utterance: str):
    """대화창에 공고·이력서 원문을 그대로 붙여넣은 턴 → (발화, 첨부) 로 승격.

    이게 없으면 붙여넣은 공고가 자산 없이 일반 대화로만 처리된다. 문서 종류는
    내용 신호로만 판별하고, 분석할지 질문에 답할지는 LLM 플래너가 사용자 요청과
    대화 맥락을 보고 결정한다. URL은 여기서 고정 분류하지 않고 URL intake에 맡긴다.
    """

    from jobis_ai.contracts.api import ChatAttachment, SourceType
    from jobis_ai.orchestrator.attachment_kind import detect_kind, resolve_kind
    from jobis_ai.posting_detection import POSTING_MIN_CHARS, posting_in_message

    pasted = posting_in_message(utterance)
    if not pasted:
        text = (utterance or "").strip()
        if "http://" in text or "https://" in text:
            return utterance, []
        kind = detect_kind(text) if len(text) >= POSTING_MIN_CHARS else None
        if kind in ("resume", "job_posting"):
            return _trailing_request(text), [
                ChatAttachment(kind=kind, sourceType=SourceType.text, value=text)
            ]
        return utterance, []
    if pasted.startswith(("http://", "https://")):
        kind, source = "job_posting", SourceType.url
    else:
        kind, _warnings = resolve_kind("job_posting", pasted)
        if kind not in ("resume", "job_posting"):
            kind = "job_posting"
        source = SourceType.text
    return _trailing_request(pasted), [
        ChatAttachment(kind=kind, sourceType=source, value=pasted)
    ]


_MODE_LABELS = {
    "CAREER_CHAT": "커리어 대화",
    "POSTING_QA": "공고 질문",
    "RESUME_DIAGNOSIS": "이력서 진단",
    "POSTING_COMPARE": "공고 비교",
    "RESUME_COMPARE": "이력서 비교",
    "INTERVIEW_PREP": "면접 준비",
    "COVER_LETTER": "자기소개서 작성",
    "APPLICATION_PLAN": "지원 계획",
    "JOB_DISCOVERY": "대체 공고 탐색",
}


def _selected_asset_attachments(
        request: ChatRequest, *, include_postings: bool = True) -> list:
    """Service-selected assets → engine attachments, without interpreting content."""

    from jobis_ai.contracts.api import ChatAttachment, SourceType
    from jobis_ai.orchestrator.attachment_kind import is_bare_url

    attachments: list[ChatAttachment] = []
    if include_postings:
        for posting in request.task.postings:
            if posting.raw_text.strip() and not is_bare_url(posting.raw_text):
                source_type, value = SourceType.text, posting.raw_text
            elif is_bare_url(posting.raw_text):
                source_type, value = SourceType.url, posting.raw_text.strip()
            elif posting.source_url:
                source_type, value = SourceType.url, posting.source_url
            else:
                continue
            attachments.append(ChatAttachment(
                kind="job_posting", sourceType=source_type, value=value))

    for source in request.task.career_sources:
        value = source.raw_text.strip()
        if not value:
            parts = [source.title, source.summary or ""]
            parts.extend(
                "\n".join(filter(None, (fragment.kind, fragment.title,
                                          fragment.description)))
                for fragment in source.fragments
            )
            value = "\n\n".join(part for part in parts if part.strip())
        if value:
            attachments.append(ChatAttachment(
                kind="resume", sourceType=SourceType.text, value=value))
    return attachments


def _progress_agent_id(step: str) -> str:
    raw = step.split(":", 1)[1] if ":" in step else step
    normalized = re.sub(r"[^a-z0-9_-]+", "_", raw.lower()).strip("_")
    if len(normalized) < 2:
        normalized = f"step_{normalized or 'unknown'}"
    if not normalized[0].isalpha():
        normalized = f"step_{normalized}"
    return normalized[:50]


def _agent_progress(step: dict):
    from jobis_ai.v2bridge.models import AgentProgress

    return AgentProgress(
        step=str(step.get("step") or "")[:120] or None,
        agent_id=_progress_agent_id(str(step.get("step") or "step_unknown")),
        label=str(step.get("label") or step.get("step") or "진행 단계")[:80],
        status="COMPLETED",
        message=str(step.get("detail") or "완료")[:300],
    )


def _reply_sources(results: dict) -> list:
    """Expose only source objects actually returned by real agents/RAG."""

    from jobis_ai.v2bridge.models import ChatReplySource

    mapped: list[ChatReplySource] = []
    seen: set[tuple[str, str]] = set()
    for data in (results or {}).values():
        if not isinstance(data, dict):
            continue
        candidates = data.get("sources") or []
        if isinstance(candidates, dict):
            candidates = [candidates]
        for source in candidates:
            if not isinstance(source, dict):
                continue
            title = str(source.get("title") or source.get("companyName")
                        or source.get("url") or source.get("source") or "").strip()
            if not title:
                continue
            excerpt = str(source.get("excerpt") or source.get("reason")
                          or source.get("text") or "").strip()
            identity = (title, excerpt)
            if identity in seen:
                continue
            seen.add(identity)
            mapped.append(ChatReplySource(
                source_type="POSTING",
                source_id=None,
                title=title[:200],
                excerpt=excerpt[:500] or None,
            ))
    return mapped[:12]


def _reply_attributions(response) -> list:
    """Preserve the engine's sentence-level authorship without reinterpreting it."""

    from jobis_ai.v2bridge.models import ChatReplyAttribution

    mapped = []
    for source in list(response.replySources or [])[:30]:
        if not isinstance(source, dict):
            continue
        agent = str(source.get("agent") or "orchestrator").strip()
        channel = str(source.get("channel") or "unknown").strip()
        if not agent or not channel:
            continue
        mapped.append(ChatReplyAttribution(
            agent_id=agent[:80],
            channel=channel[:40],
            text=str(source.get("text") or "")[:4000],
        ))
    return mapped


_ARTIFACT_TYPES = {
    "resume_diagnosis": "DIAGNOSIS",
    "posting_analysis": "DIAGNOSIS",
    "fit_analysis": "DIAGNOSIS",
    "interview_prep": "INTERVIEW_SET",
    "coverletter_draft": "COVER_LETTER_DRAFT",
    "application_plan": "APPLICATION_PLAN",
    "job_recommend": "JOB_DISCOVERY_PLAN",
}

_WORK_PRODUCT_TYPES = {
    "preference_intake": "PREFERENCES",
    "posting_analysis": "POSTING_ANALYSIS",
    "resume_diagnosis": "DIAGNOSIS",
    "fit_analysis": "COMPARISON",
    "job_recommend": "JOB_RECOMMENDATIONS",
    "interview_prep": "INTERVIEW_SET",
    "coverletter_draft": "COVER_LETTER_DRAFT",
    "application_plan": "APPLICATION_PLAN",
    "roadmap_manager": "ROADMAP_VIEW",
}


def _summary_from_result(label: str, data: dict, reply: str | None) -> str:
    """Pick an existing summary-like value; never synthesize domain findings."""

    candidates = [
        data.get("summary"),
        data.get("headline"),
        data.get("status"),
    ]
    plan = data.get("applicationPlan")
    if isinstance(plan, dict):
        decision = plan.get("decision") or {}
        if isinstance(decision, dict):
            candidates.extend((decision.get("headline"), decision.get("label")))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:2000]
    if reply and reply.strip():
        return reply.strip()[:2000]
    return f"{label} 산출물이 생성되었습니다."


def _agent_reply(response, agent_id: str) -> str | None:
    texts = []
    for source in list(response.replySources or []):
        if not isinstance(source, dict) or source.get("agent") != agent_id:
            continue
        text = str(source.get("text") or "").strip()
        if text:
            texts.append(text)
    joined = "\n".join(texts).strip()
    return joined[:4000] or None


def _work_products(response) -> list:
    """Expose every structured real-agent result instead of keeping only the last one."""

    from jobis_ai.orchestrator.router import agent_label
    from jobis_ai.v2bridge.models import ChatAgentWorkProduct

    products = []
    results = response.results or {}
    for agent_id in list(response.dispatched or []):
        product_type = _WORK_PRODUCT_TYPES.get(agent_id)
        data = results.get(agent_id)
        if product_type is None or not isinstance(data, dict):
            continue
        label = agent_label(agent_id)
        agent_reply = _agent_reply(response, agent_id)
        products.append(ChatAgentWorkProduct(
            agent_id=agent_id,
            product_type=product_type,
            title=label[:200],
            reply=agent_reply,
            summary=_summary_from_result(label, data, agent_reply),
            data=data,
        ))
    return products[:12]


def _warnings(response) -> list:
    from jobis_ai.v2bridge.models import ChatAgentWarning

    mapped = []
    for warning in list(response.warnings or [])[:30]:
        if isinstance(warning, dict):
            code = str(warning.get("code") or "agent_warning").strip()
            message = str(warning.get("message") or warning.get("detail") or "").strip()
            agent_id = str(warning.get("agent") or warning.get("agentId") or "").strip()
            recoverable = bool(warning.get("recoverable", True))
        else:
            code, message, agent_id, recoverable = (
                "agent_warning", str(warning).strip(), "", True)
        if not message:
            continue
        mapped.append(ChatAgentWarning(
            code=code[:100] or "agent_warning",
            message=message[:1000],
            agent_id=agent_id[:50] or None,
            recoverable=recoverable,
        ))
    return mapped


def _detailed_status(results: dict) -> str | None:
    application = (results or {}).get("application_plan") or {}
    plan = application.get("applicationPlan") if isinstance(application, dict) else None
    decision = plan.get("decision") if isinstance(plan, dict) else None
    status = decision.get("status") if isinstance(decision, dict) else None
    return str(status)[:80] if status else None


def _agent_plan(
        request: ChatRequest,
        response,
        events: list[dict],
        *,
        include_selected_postings: bool = True,
):
    """Translate the observed dispatch/parallel batches into a drawable DAG."""

    from jobis_ai.orchestrator.router import agent_label
    from jobis_ai.v2bridge.models import ChatAgentPlan, ChatPlanEdge, PlannedChatAgent

    dispatches = []
    confidence = getattr(response, "confidence", None) if response is not None else None
    planned = []
    parallel_groups = []
    for event in events:
        detail = event.get("detail") or {}
        if event.get("kind") == "planner":
            planned = list(detail.get("selectedAgents") or planned)
            confidence = detail.get("confidence", confidence)
        elif event.get("kind") == "dispatch" and detail.get("queue"):
            dispatches = list(detail.get("queue") or [])
        elif event.get("kind") == "dispatch" and detail.get("agents"):
            dispatches = list(detail.get("agents") or [])
        elif event.get("kind") == "dispatch" and detail.get("inserted"):
            inserted = detail.get("inserted")
            inserted_agents = inserted if isinstance(inserted, list) else [inserted]
            dispatches = list(dict.fromkeys(
                [str(item) for item in inserted_agents if item] + dispatches
            ))
        elif event.get("kind") == "parallel" and detail.get("agents"):
            parallel_groups.append(list(detail.get("agents") or []))
    if response is not None:
        completed_agents = list(response.dispatched or [])
        dispatches = list(dict.fromkeys(dispatches + completed_agents))
    agents = [
        str(item) for item in dispatches
        if re.fullmatch(r"[a-z][a-z0-9_-]{1,49}", str(item))
    ]
    if not agents:
        agents = [
            str(item) for item in planned
            if re.fullmatch(r"[a-z][a-z0-9_-]{1,49}", str(item))
        ]

    groups: list[list[str]] = []
    consumed: set[str] = set()
    for agent in agents:
        if agent in consumed:
            continue
        group = next((group for group in parallel_groups if agent in group), None)
        normalized = [item for item in (group or [agent]) if item in agents and item not in consumed]
        if not normalized:
            normalized = [agent]
        groups.append(normalized)
        consumed.update(normalized)

    nodes = []
    run_ids: dict[str, str] = {}
    order = 0
    final = response is not None
    for group_index, group in enumerate(groups):
        for agent in group:
            run_id = f"{agent}-{order + 1}"
            run_ids[agent] = run_id
            nodes.append(PlannedChatAgent(
                run_id=run_id,
                agent_id=agent,
                label=agent_label(agent)[:80],
                group_index=group_index,
                order_index=order,
                status="COMPLETED" if final else "PENDING",
            ))
            order += 1
    edges = []
    for group_index in range(len(groups) - 1):
        for source in groups[group_index]:
            for target in groups[group_index + 1]:
                edges.append(ChatPlanEdge(
                    from_run_id=run_ids[source], to_run_id=run_ids[target]))
    return ChatAgentPlan(
        intent=(mapping.chat_intent(agents) if agents else "OTHER"),
        confidence=confidence if isinstance(confidence, (int, float)) else None,
        agents=nodes,
        edges=edges,
        selected_posting_ids=(
            [item.id for item in request.task.postings]
            if include_selected_postings else []
        ),
        selected_career_source_ids=[item.id for item in request.task.career_sources],
        updated_during_run=agents != [
            str(item) for item in planned
            if re.fullmatch(r"[a-z][a-z0-9_-]{1,49}", str(item))
        ],
    )


def _artifact(request: ChatRequest, response, reply: str):
    """Wrap an existing agent result for the lab viewer; values pass through unchanged."""

    from jobis_ai.orchestrator.router import agent_label
    from jobis_ai.v2bridge.models import ChatArtifact

    dispatched = list(response.dispatched or [])
    results = response.results or {}
    selected = next((name for name in reversed(dispatched)
                     if name in _ARTIFACT_TYPES and isinstance(results.get(name), dict)), None)
    if selected is None:
        return None
    artifact_type = _ARTIFACT_TYPES[selected]
    if request.task.mode in ("POSTING_COMPARE", "RESUME_COMPARE"):
        artifact_type = "COMPARISON"
    sections = [
        {"title": str(key), "value": value}
        for key, value in list(results[selected].items())[:20]
    ]
    return ChatArtifact(
        artifact_type=artifact_type,
        title=agent_label(selected)[:200],
        summary=reply[:2000],
        sections=sections,
    )


def _pending_confirmation(follow_ups: list[dict]):
    from jobis_ai.v2bridge.models import PendingConfirmation

    for question in follow_ups:
        raw_options = question.get("options") or []
        options = [
            str(option.get("label") or option.get("value") or "")
            if isinstance(option, dict) else str(option)
            for option in raw_options
        ]
        options = [option for option in options if option.strip()][:5]
        text = str(question.get("question") or question.get("text") or "").strip()
        reason = str(question.get("reason") or question.get("field") or "").strip()
        if text and reason and len(options) >= 2:
            return PendingConfirmation(
                question=text[:500], reason=reason[:500], options=options)
    return None


def _posting_review_text(posting: dict[str, Any], *, raw_text: str = "") -> str:
    """Render only decision-relevant posting facts for user confirmation.

    The posting agent has already interpreted the source semantically.  This
    renderer deliberately excludes company promotion, benefits, contacts,
    submission instructions and the generic hiring-process copy that should
    not influence fit analysis or a roadmap.
    """

    def text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    def values(items: Any, *, requirement: bool = False) -> list[str]:
        result: list[str] = []
        for item in items or []:
            value = item.get("text") if requirement and isinstance(item, dict) else item
            cleaned = text(value)
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result

    lines: list[str] = ["# 채용 공고 핵심 정보"]
    company = text(posting.get("companyName"))
    title = text(posting.get("jobTitle"))
    role_evidence = _combined_web_role_evidence(posting, raw_text)
    role = text(posting.get("roleCategory")) if not role_evidence else ""
    if company:
        lines.append(f"- 회사: {company}")
    if title:
        lines.append(f"- 공고명: {title}")
    if role:
        lines.append(f"- 직무 분야: {role}")

    if role_evidence:
        lines.extend(("", "## 직무 구분 확인"))
        lines.append("- 프론트엔드와 백엔드 모집 내용이 함께 있어 분석 직무를 선택해야 합니다.")
        lines.extend(f"- {value}" for value in role_evidence)

    years = text(posting.get("yearsEvidence"))
    seniority = text(posting.get("seniority"))
    if years or seniority:
        lines.append(f"- 경력 조건: {years or seniority}")

    sections = (
        ("담당 업무", values(posting.get("responsibilities"))),
        ("필수 요건", values(posting.get("requiredRequirements"), requirement=True)),
        ("우대 사항", values(posting.get("preferredRequirements"), requirement=True)),
        ("기술 환경", values(posting.get("techStack"))),
        ("근무·지원 조건", values(posting.get("conditions"))),
        ("확인이 필요한 내용", values(posting.get("uncertainties"))),
    )
    for heading, entries in sections:
        if not entries:
            continue
        lines.extend(("", f"## {heading}"))
        lines.extend(f"- {entry}" for entry in entries)
    return "\n".join(lines).strip()


def _combined_web_role_evidence(posting: dict[str, Any], raw_text: str) -> list[str]:
    """Preserve a combined web posting instead of relabeling it as full-stack.

    The legacy contract has only one roleCategory and aliases a broad "web
    developer" title to fullstack. This guard does not make the final role
    decision; it only keeps explicit front/back source lines so AI v3 can create
    separate positions and ask the user which one to analyze.
    """
    if str(posting.get("roleCategory") or "").strip().lower() != "fullstack":
        return []
    folded = raw_text.casefold()
    if any(value in folded for value in ("fullstack", "full-stack", "풀스택", "풀 스택")):
        return []
    front_markers = ("frontend", "front-end", "프론트엔드", "프론트 엔드")
    back_markers = ("backend", "back-end", "백엔드", "백 엔드")
    if not (
        any(value in folded for value in front_markers)
        and any(value in folded for value in back_markers)
    ):
        return []
    result: list[str] = []
    for line in raw_text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip(" -\t")
        lowered = cleaned.casefold()
        if not cleaned or not any(
            marker in lowered for marker in (*front_markers, *back_markers)
        ):
            continue
        if cleaned not in result:
            result.append(cleaned[:500])
        if len(result) >= 8:
            break
    return result


def _posting_analysis_actions(request: ChatRequest, pasted_attachments: list,
                              dispatched: list[str], utterance: str = "",
                              session: dict[str, Any] | None = None,
                              results: dict[str, Any] | None = None):
    """Offer the AI-interpreted posting as an editable review, never auto-run it."""

    from jobis_ai.v2bridge.models import ProposedAgentAction

    # "공고 기준으로 바로 로드맵 만들어줘" — 로드맵 직접 요청은 담당 에이전트가 안 돌았어도
    # 세션의 공고로 제안을 만들어 백엔드가 무음 V3(로드맵 재료 적재)를 시작할 수 있게 한다.
    roadmap_requested = bool(re.search(
        r"로드맵.{0,16}(생성|만들|시작|진행|해\s*줘|해주세요|부탁)", utterance))
    if not ({"posting_analysis", "fit_analysis"}.intersection(dispatched)
            or roadmap_requested):
        return []
    posting = next((
        item for item in pasted_attachments
        if item.kind == "job_posting"
        and str(getattr(item.sourceType, "value", item.sourceType)).lower() == "text"
        and len((item.value or "").strip()) >= 20
    ), None)
    source_url = None
    if posting is not None:
        raw_text = posting.value.strip()
    else:
        stored = (session or {}).get("job_posting") or {}
        raw_text = str(stored.get("value") or "").strip()
        source_url = str(stored.get("sourceUrl") or "").strip() or None
    posting_facts = ((results or {}).get("posting_analysis") or {}).get("postingAnalysis")
    if not isinstance(posting_facts, dict):
        posting_facts = (session or {}).get("posting_summary") or {}
    if len(raw_text) < 20 and isinstance(posting_facts, dict):
        raw_text = str(posting_facts.get("_sourceText") or "").strip()
    if len(raw_text) < 20 or not isinstance(posting_facts, dict):
        return []

    review_text = _posting_review_text(posting_facts, raw_text=raw_text)
    if len(review_text) < 20:
        return []

    fingerprint = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]
    explicitly_requested = roadmap_requested or bool(re.search(
        r"(분석|적합도|준비도).{0,12}(해\s*줘|해주세요|해봐|보고\s*싶|알려\s*줘)|"
        r"(해\s*줘|해주세요).{0,12}(분석|적합도|준비도)",
        utterance,
        re.IGNORECASE,
    ))
    return [ProposedAgentAction(
        action_id=f"analyze-posting-{fingerprint}",
        action_type="ANALYZE_POSTING",
        label="정리한 공고 확인",
        description="분석에 필요한 직무·업무·경력·필수·우대 조건만 추렸어요. 내용을 확인하거나 고친 뒤 분석을 시작합니다.",
        # An explicit request may prepare and open the review automatically.
        # Actual V3 analysis still cannot start until the user confirms the
        # editable review in the service UI.
        requires_consent=not explicitly_requested,
        payload={
            "sourceType": "URL" if source_url else "TEXT",
            "sourceUrl": source_url,
            "rawText": raw_text,
            "reviewText": review_text,
            "userInitiated": explicitly_requested,
        },
    )]


def _work_product_actions(products: list, utterance: str) -> list:
    """Offer only reversible service actions for products the real agents returned."""

    from jobis_ai.v2bridge.models import ProposedAgentAction

    actions = []
    for product in products:
        fingerprint = hashlib.sha256(
            f"{product.agent_id}:{product.summary}".encode("utf-8")
        ).hexdigest()[:16]
        if product.product_type == "COVER_LETTER_DRAFT":
            actions.append(ProposedAgentAction(
                action_id=f"save-draft-{fingerprint}",
                action_type="SAVE_DRAFT",
                label="자소서 초안으로 저장",
                description="검토 중인 에이전트 산출물을 내 자소서 초안 목록에 저장합니다.",
                requires_consent=True,
                payload={"productType": product.product_type, "data": product.data},
            ))
        elif product.product_type == "INTERVIEW_SET":
            explicitly_requested = bool(re.search(r"(면접|인터뷰).{0,10}(시작|연습|준비|해\s*줘)", utterance))
            actions.append(ProposedAgentAction(
                action_id=f"start-interview-{fingerprint}",
                action_type="START_INTERVIEW",
                label="면접 연습 이어가기",
                description="질문과 답변 기록을 면접 연습 세션으로 저장하고 이어갑니다.",
                requires_consent=not explicitly_requested,
                payload={
                    "productType": product.product_type,
                    "userInitiated": explicitly_requested,
                    "data": product.data,
                },
            ))
        if len(actions) >= 4:
            break
    return actions


def _outputs_snapshot(session_id: str) -> dict[str, Any]:
    from jobis_ai.orchestrator.session import get_session_store

    return get_session_store().get(session_id) or {}


def _profile_snapshot(session_id: str) -> tuple[dict, int]:
    from jobis_ai.orchestrator.session import get_session_store

    session = get_session_store().get(session_id) or {}
    return (
        dict(session.get("preferences") or {}),
        len(session.get("user_facts") or []),
    )


def _competency_proposal_for_chat(session_id: str):
    from jobis_ai.orchestrator.session import get_session_store

    session = get_session_store().get(session_id) or {}
    analysis = session.get("analysis") or {}
    posting = session.get("posting_summary") or {}
    judgment = session.get("judgment_summary") or {}
    req_status = list(judgment.get("requirementStatus") or [])
    if analysis.get("status") != "completed" or not posting or not req_status:
        return None, None

    gaps = list(analysis.get("gaps") or [])
    enriched_posting, resolution = mapping.enrich_posting_role(
        posting,
        raw_text=str((session.get("job_posting") or {}).get("value") or ""),
    )
    track = resolution.primary_track
    drafts, _ = mapping.draft_competencies(enriched_posting, req_status, gaps, track)
    enrichment, warnings = enrich.classify_posting(enriched_posting, drafts)
    for warning in warnings:
        log.info(
            "[v2bridge] 대화 경로 공고 분류 경고: %s",
            warning.get("message") or warning,
        )
    proposal = mapping.build_competency_proposal(
        enriched_posting,
        req_status,
        gaps,
        track,
        enrichment,
    )
    if proposal is None:
        return None, None
    return proposal, mapping.build_job_context(
        enriched_posting,
        raw_text=str((session.get("job_posting") or {}).get("value") or ""),
    )


def _collected_outputs(session_id: str, before: dict[str, Any]):
    from jobis_ai.orchestrator.session import get_session_store
    from jobis_ai.v2bridge.models import CollectedOutputs

    session = get_session_store().get(session_id) or {}
    payload: dict[str, Any] = {}
    for asset, field in _OUTPUT_ASSETS.items():
        value = session.get(asset)
        if value in (None, {}, []) or value == before.get(asset):
            continue
        payload[field] = value
    if "analysis" in payload:
        proposal, job_context = _competency_proposal_for_chat(session_id)
        if proposal is not None:
            payload["competency_proposal"] = proposal
            payload["job_context"] = job_context
    state = {key: value for key, value in session.items() if value not in (None, [], {})}
    previous = {
        key: value for key, value in (before or {}).items() if value not in (None, [], {})
    }
    if state != previous:
        payload["session_state"] = state
    return CollectedOutputs(**payload) if payload else None


def _collected_assets(
    session_id: str,
    attachments: list,
    dispatched: list[str],
    before: tuple[dict, int] = ({}, 0),
    outputs_before: dict[str, Any] | None = None,
):
    from jobis_ai.orchestrator.attachment_kind import is_bare_url
    from jobis_ai.orchestrator.session import get_session_store
    from jobis_ai.v2bridge.models import CollectedAssets, CollectedPosting, CollectedResume

    kinds = {str(getattr(item, "kind", "") or "") for item in attachments or []}
    fetched = "posting_fetch" in (dispatched or [])
    session = get_session_store().get(session_id) or {}
    outputs = _collected_outputs(session_id, outputs_before or {})
    before_preferences, before_fact_count = before
    preferences_now = {
        key: [str(value) for value in (values or [])]
        for key, values in (session.get("preferences") or {}).items()
    }
    preferences = (
        preferences_now
        if preferences_now and preferences_now != before_preferences
        else None
    )
    all_facts = [str(item) for item in session.get("user_facts") or [] if str(item).strip()]
    facts = all_facts[:200] if len(all_facts) > before_fact_count else None

    posting = None
    if fetched or "job_posting" in kinds:
        asset = session.get("job_posting") or {}
        text = str(asset.get("value") or "").strip()
        url = str(asset.get("sourceUrl") or "").strip() or (
            text if is_bare_url(text) else ""
        )
        if text and not is_bare_url(text):
            posting = CollectedPosting(
                source_type="URL" if url else "TEXT",
                source_url=url or None,
                raw_text=text[:100_000],
            )
    resume = None
    if "resume" in kinds:
        asset = session.get("resume") or {}
        text = str(asset.get("value") or "").strip()
        if text and asset.get("origin") != "career_summary":
            resume = CollectedResume(
                title=str(asset.get("_label") or "대화로 받은 이력서")[:200],
                raw_text=text[:100_000],
            )
    if all(
        value is None
        for value in (posting, resume, preferences, facts, outputs)
    ):
        return None
    return CollectedAssets(
        posting=posting,
        resume=resume,
        outputs=outputs,
        preferences=preferences,
        facts=facts,
    )


def _summary_from_structured(structured: dict[str, Any] | None) -> dict[str, Any] | None:
    """V3 StructuredPosting → 채팅 요약 dict(NormalizedJobPosting 모양). 순수 변환, LLM 없음.

    V3 가 근거 ID 체계로 이미 해석한 공고는 채팅이 다시 해석하지 않고 이 투영을 지식으로
    쓴다(이중 분석 제거). 없는 사실을 만들지 않는다 — 연차 표기(yearsEvidence)는 공고
    원문 문구가 아니므로 비워 두고 개월 수만 연 단위로 환산해 넘긴다.
    """

    if not structured:
        return None
    positions = list(structured.get("positions") or [])
    if not positions:
        return None
    position = positions[0] or {}
    requirements = (list(position.get("requirements") or [])
                    + list(structured.get("sharedConditions") or []))

    def _texts(obligation: str) -> list[dict[str, str]]:
        return [{"text": text} for r in requirements
                if (r or {}).get("obligation") == obligation
                and (text := str(r.get("atomicText") or r.get("sourceText") or "").strip())]

    experience = position.get("experience") or {}
    min_months = experience.get("minMonths")
    max_months = experience.get("maxMonths")
    return {
        "companyName": str((structured.get("company") or {}).get("displayName") or ""),
        "jobTitle": str(structured.get("postingTitle")
                        or position.get("sourceTitle") or ""),
        "minYears": min_months // 12 if isinstance(min_months, int) else None,
        "maxYears": max_months // 12 if isinstance(max_months, int) else None,
        "yearsEvidence": "",
        "responsibilities": [text for r in (position.get("responsibilities") or [])
                             if (text := str((r or {}).get("atomicText")
                                             or (r or {}).get("sourceText") or "").strip())],
        "requiredRequirements": _texts("REQUIRED"),
        "preferredRequirements": _texts("PREFERRED"),
    }


def _seed_session_state(session_id: str, request: ChatRequest) -> None:
    from jobis_ai.orchestrator.session import ASSET_KEYS, get_session_store

    incoming = dict(request.career.session_state or {})
    if request.career.interview:
        incoming["interview"] = dict(request.career.interview)
    if not incoming:
        return
    store = get_session_store()
    session = store.get(session_id)
    updates = {
        key: value
        for key, value in incoming.items()
        if key in ASSET_KEYS and value not in (None, {}, []) and not session.get(key)
    }
    if updates:
        store.update(session_id, updates)


def chat_events(request: ChatRequest):
    """대화 한 턴을 **진행 이벤트 스트림**으로 처리한다(D75) — /v1/chat/stream 의 본체.

    yield 하는 항목:
      {"type": "progress", step, label, detail, elapsedMs}  — 실행 중 단계(실시간)
      {"type": "result", "response": ChatResponse}          — 마지막 한 건

    단건 계약(chat)은 이 제너레이터를 소진해 result 만 돌려준다 — 두 경로의 처리·검증이
    갈리지 않는다.
    """

    import queue as queue_mod
    import threading

    from jobis_ai import trace
    from jobis_ai.contracts.api import ChatRequest as EngineChatRequest
    from jobis_ai.orchestrator.chat import handle_chat
    from jobis_ai.orchestrator.session import get_session_store
    from jobis_ai.structured import llm_unconfigured

    raw_utterance = next((
        m.content for m in reversed(request.messages) if m.role == "USER"
    ), "")
    if not raw_utterance.strip():
        raise EngineFailed("사용자 발화가 없어요")
    utterance, pasted_attachments = promote_pasted_posting(raw_utterance)
    current_posting_submitted = (
        bool(re.search(r"https?://", raw_utterance, re.IGNORECASE))
        or any(item.kind == "job_posting" for item in pasted_attachments)
    )
    # 현재 발화에 새 공고가 있으면 그것이 이번 턴의 유일한 분석 대상이다. AUTO가
    # 실어 보낸 과거 공고를 첨부로 먼저 적용하면 오케스트레이터가 새 URL 수집을
    # 건너뛰고 이전 공고를 다시 분석한다.
    # AUTO 모드의 자동 선택 자산은 **새 제출이 아니다** — 세션 블롭·커리어 컨텍스트로
    # 이미 아는 지식인데 첨부로 재적용하면 매 턴 "받았어요" ack 이 반복되고 분석·파싱
    # 캐시가 지워진다(실측 2026-08-07: "나 이력서있나?"에 "공고를 받았어요."×3 접두).
    # 첨부는 사용자가 이번 턴에 준 것과 명시 선택(mode != AUTO)만 취급한다.
    if request.task.mode == "AUTO":
        attachments = list(pasted_attachments)
    else:
        attachments = _selected_asset_attachments(
            request,
            include_postings=not current_posting_submitted,
        ) + pasted_attachments
    if request.task.mode != "AUTO":
        mode_label = _MODE_LABELS.get(request.task.mode, request.task.mode)
        utterance = f"[사용자가 선택한 작업: {mode_label}]\n{utterance}".strip()

    session_id = f"v2-chat-{request.conversation_id}"
    store = get_session_store()
    # PostgreSQL snapshot is canonical.  Clear any process-local leftovers first
    # so a restarted/retried worker cannot observe stale state from SQLite.
    if request.workspace_state is not None:
        store.clear(session_id)
        hydrated = {
            key: value
            for key, value in request.workspace_state.items()
            if key in _WORKSPACE_KEYS
        }
        if hydrated:
            store.update(session_id, hydrated)
    _seed_session_state(session_id, request)
    # 백엔드가 매 턴 싣는 사용자 DB 자료 — 에이전트가 저장소 상태를 보고 대화한다.
    # 원천 우선순위: 대화에 붙여넣은 원문 > DB 이력서 원문 > 확정 커리어 요약(M7).
    db_resume_text = ""
    db_resume_title = ""
    if request.career.resumes:
        newest = request.career.resumes[0]
        db_resume_text = (newest.raw_text or "").strip()
        db_resume_title = (newest.title or "커리어 저장소 이력서").strip()
        # DB 이력서는 **라이브러리에도** 올린다 — "커리어 저장소 이력서로 판정해줘" 같은
        # 지목이 라이브러리 라벨·출처로 해석되기 때문이다(실측 2026-08-07 12:17:
        # 저장소에 올린 직후 "기억하는 목록에서 찾지 못했어요"가 나갔다).
        from jobis_ai.agents._common import resume_source_hash, upsert_resume_library

        sess_now = store.get(session_id)
        library = list(sess_now.get("resume_library") or [])
        known = {r.get("_sourceHash") for r in library}
        changed = False
        for stored in request.career.resumes:
            text = (stored.raw_text or "").strip()
            if not text:
                continue
            asset = {"sourceType": "text", "value": text, "origin": "career_summary",
                     "_label": (stored.title or "커리어 저장소 이력서")[:200]}
            src_hash = resume_source_hash(asset)
            if src_hash in known:
                continue
            library = upsert_resume_library(
                {**sess_now, "resume_library": library},
                {"_sourceHash": src_hash, "_source": asset, "_sourceText": text,
                 "_origin": "career_summary", "_label": asset["_label"]})
            known.add(src_hash)
            changed = True
        if changed:
            store.update(session_id, {"resume_library": library})
    summary_text = db_resume_text or _career_summary_text(request)
    if summary_text:
        existing = store.get(session_id).get("resume") or {}
        if not existing or existing.get("origin") == "career_summary":
            resume_asset: dict[str, Any] = {
                "sourceType": "text", "value": summary_text, "origin": "career_summary"}
            if db_resume_title and db_resume_text:
                resume_asset["_label"] = db_resume_title[:200]
            store.update(session_id, {"resume": resume_asset})
    if request.career.postings and not store.get(session_id).get("posting_library"):
        library = []
        for stored_posting in request.career.postings:
            entry = _summary_from_structured(stored_posting.structured_posting)
            if entry is None and stored_posting.parsed_data:
                entry = dict(stored_posting.parsed_data)
            if entry is None:
                continue
            entry.setdefault("_sourceHash", hashlib.md5(
                (stored_posting.raw_text or "").encode("utf-8")).hexdigest())
            library.append(entry)
        if library:
            store.update(session_id, {"posting_library": library[:10]})
    roadmap_nodes = list((request.career.roadmap or {}).get("nodes") or [])
    if roadmap_nodes and not store.get(session_id).get("roadmap"):
        store.update(session_id, {"roadmap": roadmap_nodes[:100]})
    # 이전 대화에서 수집돼 DB 에 영속된 선호·사실·가용시간 — 세션에 없을 때만 되살린다.
    career_seed_updates: dict[str, Any] = {}
    session_now = store.get(session_id)
    if request.career.preferences and not session_now.get("preferences"):
        career_seed_updates["preferences"] = dict(request.career.preferences)
    if request.career.facts and not session_now.get("user_facts"):
        career_seed_updates["user_facts"] = list(request.career.facts)[:200]
    if (request.career.preparation_period_weeks
            and not session_now.get("preparationPeriodWeeks")):
        career_seed_updates["preparationPeriodWeeks"] = (
            request.career.preparation_period_weeks)
    if (request.career.available_hours_per_week
            and not session_now.get("availableHoursPerWeek")):
        career_seed_updates["availableHoursPerWeek"] = (
            request.career.available_hours_per_week)
    if career_seed_updates:
        store.update(session_id, career_seed_updates)

    profile_before = _profile_snapshot(session_id)
    outputs_before = _outputs_snapshot(session_id)

    # 엔진을 워커 스레드에서 돌리고 trace 이벤트를 큐로 중계한다 — 이벤트가 생기는 즉시
    # yield 되어야 스트리밍이다(턴이 끝나고 몰아 보내면 타임라인과 다를 게 없다).
    relay: "queue_mod.Queue[tuple]" = queue_mod.Queue()

    def _run() -> None:
        try:
            with trace.recording(sink=lambda ev: relay.put(("event", ev))):
                engine_response = handle_chat(EngineChatRequest(
                    sessionId=session_id, message=utterance, attachments=attachments))
            relay.put(("done", engine_response))
        except Exception as exc:   # noqa: BLE001 — 소비 루프가 그대로 다시 올린다
            relay.put(("error", exc))

    threading.Thread(target=_run, daemon=True).start()

    mapper = mapping.ProgressMapper()
    steps: list[dict] = []
    trace_events: list[dict] = []
    response = None
    while response is None:
        kind, payload = relay.get()
        if kind == "event":
            trace_events.append(payload)
            step = mapper.map(payload)
            if step:
                steps.append(step)
                step_id = str(step.get("step") or "")
                yield {
                    "type": "progress",
                    "step": step.get("step"),
                    "label": step.get("label"),
                    "detail": step.get("detail"),
                    "elapsedMs": step.get("elapsedMs", 0),
                    "progress": _agent_progress(step),
                    "running": step_id.startswith("start:") or step_id.startswith("loop:"),
                }
            if payload.get("kind") in {"dispatch", "parallel"}:
                plan = _agent_plan(
                    request,
                    None,
                    trace_events,
                    include_selected_postings=not current_posting_submitted,
                )
                if plan.agents:
                    yield {"type": "plan", "plan": plan}
        elif kind == "error":
            raise payload
        else:
            response = payload

    if llm_unconfigured(list(response.warnings or [])):
        raise EngineNotConfigured("LLM 이 설정되지 않아 대화할 수 없어요")
    reply = (response.reply or "").strip()
    if not reply:
        raise EngineFailed("엔진이 빈 답변을 반환했어요")

    follow_ups = list(response.followUpQuestions or [])
    should_request_posting, actions = mapping.chat_actions(follow_ups)
    products = _work_products(response)
    current_session = store.get(session_id)
    proposed_actions = _posting_analysis_actions(
        request,
        pasted_attachments,
        list(response.dispatched or []),
        utterance,
        current_session,
        response.results or {},
    )
    proposed_actions.extend(_work_product_actions(products, utterance))
    has_posting_review = any(
        action.action_type == "ANALYZE_POSTING" for action in proposed_actions
    )
    public_reply = reply
    public_products = products
    public_artifact = _artifact(request, response, reply)
    if has_posting_review:
        # artifact·work product·확인용 review가 같은 내용을 반복하지 않게 카드류만
        # 걷어낸다. 채팅 발화(reply)는 에이전트가 만든 원문을 그대로 내보낸다 —
        # 공고 요약·질문에 대한 답이 여기 실리므로 고정 문구로 교체하면 안 된다.
        public_products = []
        public_artifact = None
    # 사후 타임라인에는 "실행 중…"(start:*) 단계를 싣지 않는다 — progress_steps 와 동일 규약.
    final_steps = [s for s in steps if not str(s["step"]).startswith("start:")][:60]
    pending = _pending_confirmation(follow_ups)
    workspace_state = _workspace_snapshot(current_session)
    collected = _collected_assets(
        session_id,
        attachments,
        list(response.dispatched or []),
        profile_before,
        outputs_before,
    )
    yield {"type": "result", "response": ChatResponse(
        progress=[_agent_progress(s) for s in final_steps[:60]],
        message=public_reply[:4000],
        intent=mapping.chat_intent(list(response.dispatched or [])),
        should_request_posting=should_request_posting,
        suggested_actions=actions,
        reply_sources=_reply_sources(response.results or {}),
        proposed_actions=proposed_actions,
        pending_confirmation=pending,
        artifact=public_artifact,
        plan=_agent_plan(
            request,
            response,
            trace_events,
            include_selected_postings=not current_posting_submitted,
        ),
        confidence=response.confidence,
        detailed_status=_detailed_status(response.results or {}),
        work_products=public_products,
        warnings=_warnings(response),
        reply_attributions=_reply_attributions(response),
        workspace_state=workspace_state,
        collected=collected,
    )}


def chat(request: ChatRequest) -> ChatResponse:
    """단건 계약(/v1/chat) — 스트림을 소진하고 최종 응답만 돌려준다."""

    response: ChatResponse | None = None
    for item in chat_events(request):
        if item.get("type") == "result":
            response = item["response"]
    if response is None:
        raise EngineFailed("엔진이 결과 없이 종료했어요 — 재시도해 주세요")
    return response


def session_state(conversation_id: str) -> dict:
    """대화 세션에 쌓인 자산 요약 — 디버그·백엔드 관측용(프로토타입 2.0.0 GET /session 이식, D128).

    판단하지 않는다 — 세션 자산의 목록·개수를 옮겨 적을 뿐이다. 전에는 "이 세션이 지금
    무엇을 기억하나"를 보려면 sessions.sqlite3 을 직접 열어야 했다.
    """

    from jobis_ai.agents._common import resume_identity
    from jobis_ai.orchestrator.session import get_session_store

    session = get_session_store().get(f"v2-chat-{conversation_id}")
    analysis = session.get("analysis") or {}
    return {
        "conversationId": conversation_id,
        "exists": bool(session),
        "activeResume": resume_identity(session.get("resume"))[1],
        "resumeLibrary": [str(r.get("_label") or "")
                          for r in session.get("resume_library") or []],
        "postingLibrary": [{"company": str(p.get("companyName") or ""),
                            "title": str(p.get("jobTitle") or "")}
                           for p in session.get("posting_library") or []],
        "recommendations": [{"company": str(r.get("companyName") or ""),
                             "title": str(r.get("title") or ""),
                             "url": str(r.get("url") or "")}
                            for r in session.get("recommendations") or []],
        "analysisGrade": analysis.get("fitGrade"),
        "historyTurns": len(session.get("history") or []),
    }


# ---------------------------------------------------------------------------
# 역량 검증·학습 콘텐츠 (/v1/competency-assessments, /v1/competency-learning)
# ---------------------------------------------------------------------------
class _AssessmentQuestionRead(BaseModel):
    prompt: str = Field(min_length=1, max_length=6_000)
    code_snippet: str | None = Field(default=None, max_length=8_000)
    core_criteria: list[str] = Field(min_length=2, max_length=8)
    future_extensions: list[str] = Field(default_factory=list, max_length=8)


class _AssessmentEvaluationRead(BaseModel):
    score: int = Field(ge=0, le=100)
    feedback: str = Field(min_length=1, max_length=4_000)
    covered_criteria: list[str] = Field(default_factory=list, max_length=12)
    gaps: list[str] = Field(default_factory=list, max_length=12)
    future_extensions: list[str] = Field(default_factory=list, max_length=12)


_ASSESSMENT_QUESTION_SYSTEM = """너는 취업 준비 서비스의 역량 검증 문제 출제자다.
입력의 competency.scopeDefinition과 levelDefinition이 출제 가능한 범위의 전부다.
- 다른 프레임워크·상위 기술·별도 노드의 지식을 문제의 정답 조건에 넣지 않는다.
- target은 예시 상황을 고르는 데만 사용하고 난이도와 검증 범위를 바꾸지 않는다.
- 한 번에 정확히 한 문제만 낸다. 여러 하위 질문을 나열하지 않는다.
- CONCEPT는 원리와 선택 이유, CODE는 짧은 코드 해석·수정, SCENARIO는 범위 안의 적용 판단을 묻는다.
- coreCriteria는 답변에 반드시 포함돼야 하는 관찰 가능한 채점 기준이다.
- futureExtensions는 이번 점수에는 포함하지 않는 다음 학습 주제다.
- 이전 문제와 같은 질문을 표현만 바꿔 반복하지 않는다."""


_LANGUAGE_SCOPE_GUARDS: dict[str, tuple[str, ...]] = {
    "java": (
        "spring", "spring boot", "jpa", "hibernate", "트랜잭션", "transaction",
        "servlet", "서블릿", "웹 서버", "rest api", "kafka",
    ),
    "python": (
        "fastapi", "django", "flask", "wsgi", "asgi", "sqlalchemy",
        "웹 서버", "서버 아키텍처", "rest api", "마이크로서비스", "microservice",
        "트랜잭션", "transaction",
    ),
    "kotlin": ("spring", "android", "ktor", "트랜잭션", "transaction", "웹 서버"),
    "javascript": ("react", "vue", "angular", "next.js", "node.js", "웹 서버"),
    "typescript": ("react", "vue", "angular", "next.js", "node.js", "웹 서버"),
}


def _scope_guard_violations(
        request: CompetencyAssessmentRequest | CompetencyLearningRequest,
        required_content: str) -> list[str]:
    """언어 기초 노드의 필수 콘텐츠가 후속 프레임워크 영역으로 새지 않게 막는다."""

    competency = request.competency
    baseline = " ".join((
        competency.title,
        competency.scope_definition,
        str(competency.level_definition),
    )).lower()
    content = required_content.lower()
    key = competency.canonical_key.lower()
    language = next((name for name in _LANGUAGE_SCOPE_GUARDS if name in key), None)
    forbidden: list[str] = []
    if language is not None:
        forbidden.extend(_LANGUAGE_SCOPE_GUARDS[language])
    blueprint = competency.assessment_blueprint or {}
    for field in ("excludedTopics", "outOfScope", "excluded_topics"):
        values = blueprint.get(field) if isinstance(blueprint, dict) else None
        if isinstance(values, list):
            forbidden.extend(str(value) for value in values)
    return sorted({
        term for term in forbidden
        if term.lower() not in baseline and term.lower() in content
    })


def _question_required_content(read: _AssessmentQuestionRead) -> str:
    return "\n".join(filter(None, (
        read.prompt,
        read.code_snippet or "",
        *read.core_criteria,
    )))


_ASSESSMENT_EVALUATION_SYSTEM = """너는 역량 검증 답변의 의미를 채점하는 검토자다.
입력에 포함된 competency.scopeDefinition, 문제, 답변만 근거로 평가한다.
- 범위 밖의 지식을 요구하거나 가산점·감점을 주지 않는다.
- 90~100: 핵심 원리와 적용 이유가 정확하고 빠짐없음.
- 75~89: 핵심은 정확하며 작은 누락만 있음.
- 60~74: 방향은 맞지만 핵심 기준 일부가 부족함.
- 0~59: 핵심 오해, 답변 회피, 또는 적용 불가능.
- 모범답안을 지어 사용자의 답변에 있었다고 말하지 않는다.
- futureExtensions는 이번 점수에 반영하지 않는 다음 학습 주제다."""


def _assessment_payload(request: CompetencyAssessmentRequest) -> dict:
    return {
        "competency": request.competency.model_dump(by_alias=True),
        "target": request.target.model_dump(by_alias=True),
        "previousQuestions": [
            {"kind": turn.question_kind, "prompt": turn.prompt}
            for turn in request.turns
        ],
    }


def _generate_assessment_question(
        request: CompetencyAssessmentRequest, kind: str):
    import json

    from jobis_ai.structured import llm_unconfigured, run_structured
    from jobis_ai.v2bridge.models import AssessmentQuestion

    payload = _assessment_payload(request)
    payload["requiredKind"] = kind
    warnings: list[dict] = []
    read = None
    violations: list[str] = []
    for _attempt in range(2):
        system = _ASSESSMENT_QUESTION_SYSTEM
        if violations:
            system += (
                "\n이전 결과가 현재 노드 밖의 주제를 포함해 폐기됐다. "
                f"다음 주제를 사용하지 말고 다시 작성한다: {', '.join(violations)}"
            )
        read, attempt_warnings = run_structured(
            AssessmentQuestion,
            system,
            json.dumps(payload, ensure_ascii=False),
            node="v2_competency_question",
        )
        warnings.extend(attempt_warnings)
        if read is None:
            break
        violations = _scope_guard_violations(request, _question_required_content(read))
        if not violations:
            break
        read = None
    if read is None:
        if llm_unconfigured(warnings):
            raise EngineNotConfigured("LLM 이 설정되지 않아 역량 검증 문제를 만들 수 없어요")
        if violations:
            raise EngineFailed(
                "생성된 문제가 현재 역량 범위를 벗어났어요 — 같은 단계에서 다시 시도해 주세요"
            )
        raise EngineFailed("역량 범위에 맞는 검증 문제를 만들지 못했어요 — 재시도해 주세요")
    return read.model_copy(update={"kind": kind})


def _evaluate_assessment_answer(
        request: CompetencyAssessmentRequest, turn):
    import json

    from jobis_ai.structured import llm_unconfigured, run_structured
    from jobis_ai.v2bridge.models import AssessmentAnswerEvaluation

    payload = _assessment_payload(request)
    payload["question"] = {
        "kind": turn.question_kind,
        "prompt": turn.prompt,
        "codeSnippet": turn.code_snippet,
    }
    payload["answer"] = turn.answer_text
    read, warnings = run_structured(
        _AssessmentEvaluationRead,
        _ASSESSMENT_EVALUATION_SYSTEM,
        json.dumps(payload, ensure_ascii=False),
        node="v2_competency_evaluation",
    )
    if read is None:
        if llm_unconfigured(warnings):
            raise EngineNotConfigured("LLM 이 설정되지 않아 역량 답변을 평가할 수 없어요")
        raise EngineFailed("역량 답변 평가를 만들지 못했어요 — 재시도해 주세요")
    verdict = "PASS" if read.score >= 75 else "PARTIAL" if read.score >= 60 else "FAIL"
    return AssessmentAnswerEvaluation(
        score=read.score,
        verdict=verdict,
        feedback=read.feedback,
        covered_criteria=read.covered_criteria,
        gaps=read.gaps,
        future_extensions=read.future_extensions,
    )


def _next_assessment_kind(scores: dict[str, int]) -> str | None:
    order = ("CONCEPT", "CODE", "SCENARIO")
    for kind in order:
        if scores.get(kind, 0) < 60:
            return kind
    average = sum(scores.get(kind, 0) for kind in order) / len(order)
    if average >= 75:
        return None
    return min(order, key=lambda kind: scores.get(kind, 0))


def assess_competency(
        request: CompetencyAssessmentRequest) -> CompetencyAssessmentResponse:
    """Generate/evaluate within the backend-owned deterministic assessment protocol."""

    scores = {key: int(value) for key, value in request.retained_scores.items()}
    for turn in request.turns:
        if turn.score is not None and turn.question_kind in {"CONCEPT", "CODE", "SCENARIO"}:
            scores[turn.question_kind] = max(scores.get(turn.question_kind, 0), turn.score)

    pending = next((
        turn for turn in reversed(request.turns)
        if turn.answer_text and turn.score is None
    ), None)
    evaluation = None
    strengths: list[str] = []
    gaps: list[str] = []
    next_actions: list[str] = []
    if pending is not None:
        evaluation = _evaluate_assessment_answer(request, pending)
        if pending.question_kind in {"CONCEPT", "CODE", "SCENARIO"}:
            scores[pending.question_kind] = max(
                scores.get(pending.question_kind, 0), evaluation.score)
        strengths = list(evaluation.covered_criteria)
        gaps = list(evaluation.gaps)
        next_actions = list(evaluation.future_extensions)

    requested_kind = request.required_question_kind
    next_kind = requested_kind or _next_assessment_kind(scores)
    next_question = None
    # 미응답으로 남은 UI 턴은 시도 횟수로 세지 않는다. 종료 여부는 백엔드가 보낸
    # 실제 답변/점수와 requiredQuestionKind로 결정한다.
    answered_turns = sum(bool((turn.answer_text or "").strip()) for turn in request.turns)
    if answered_turns < 5 and next_kind is not None:
        next_question = _generate_assessment_question(request, next_kind)

    if evaluation is None:
        summary = f"{request.competency.title} 수준 {request.competency.required_level} 검증을 시작합니다."
    else:
        summary = (
            f"{pending.question_kind} 답변은 {evaluation.score}점입니다. "
            + ("다음 유형을 확인합니다." if next_question else "현재 답변 결과를 정리했습니다.")
        )
    return CompetencyAssessmentResponse(
        answer_evaluation=evaluation,
        next_question=next_question,
        session_summary=summary,
        strengths=strengths,
        gaps=gaps,
        next_actions=next_actions,
    )


class _LearningModuleRead(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1_000)
    concepts: list[str] = Field(min_length=1, max_length=10)
    example: str | None = Field(default=None, max_length=4_000)
    practice: str = Field(min_length=1, max_length=2_000)
    completion_criteria: list[str] = Field(min_length=1, max_length=8)


class _LearningRead(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    target_context: str | None = Field(default=None, max_length=2_000)
    modules: list[_LearningModuleRead] = Field(min_length=1, max_length=8)
    recommended_resources: list[str] = Field(default_factory=list, max_length=10)
    assessment_readiness: list[str] = Field(default_factory=list, max_length=10)


_LEARNING_SYSTEM = """너는 커리어 지도 기술 노드의 학습 가이드를 만드는 교육 설계자다.
- competency.scopeDefinition과 levelDefinition 밖의 기술을 필수 과정에 넣지 않는다.
- target은 예제의 업무 맥락에만 반영한다. 공용 역량 범위를 회사별로 바꾸지 않는다.
- 2~5개 모듈로, 개념→짧은 적용→검증 준비 순서로 작성한다.
- practice는 작은 별도 프로젝트를 양산하지 않고 코드 조각·설명·판단 연습으로 만든다.
- recommendedResources에는 존재를 확인할 수 없는 책·강의 URL을 지어내지 않는다.
- completionCriteria는 사용자가 스스로 확인할 수 있는 행동 기준으로 쓴다."""


def _learning_required_content(read: _LearningRead) -> str:
    values = [read.title, read.summary, *read.assessment_readiness]
    for module in read.modules:
        values.extend((
            module.title,
            module.objective,
            *module.concepts,
            module.example or "",
            module.practice,
            *module.completion_criteria,
        ))
    return "\n".join(filter(None, values))


def competency_learning(
        request: CompetencyLearningRequest) -> CompetencyLearningResponse:
    import json

    from jobis_ai.structured import llm_unconfigured, run_structured
    from jobis_ai.v2bridge.models import LearningModule

    payload = {
        "competency": request.competency.model_dump(by_alias=True),
        "target": request.target.model_dump(by_alias=True),
    }
    warnings: list[dict] = []
    read = None
    violations: list[str] = []
    for _attempt in range(2):
        system = _LEARNING_SYSTEM
        if violations:
            system += (
                "\n이전 결과가 현재 노드 밖의 주제를 포함해 폐기됐다. "
                f"다음 주제를 필수 과정에 넣지 말고 다시 작성한다: {', '.join(violations)}"
            )
        read, attempt_warnings = run_structured(
            _LearningRead,
            system,
            json.dumps(payload, ensure_ascii=False),
            node="v2_competency_learning",
        )
        warnings.extend(attempt_warnings)
        if read is None:
            break
        violations = _scope_guard_violations(request, _learning_required_content(read))
        if not violations:
            break
        read = None
    if read is None:
        if llm_unconfigured(warnings):
            raise EngineNotConfigured("LLM 이 설정되지 않아 학습 가이드를 만들 수 없어요")
        if violations:
            raise EngineFailed(
                "생성된 학습 가이드가 현재 역량 범위를 벗어났어요 — 다시 생성을 요청해 주세요"
            )
        raise EngineFailed("역량 범위에 맞는 학습 가이드를 만들지 못했어요 — 재시도해 주세요")
    return CompetencyLearningResponse(
        title=read.title,
        summary=read.summary,
        scope_reminder=request.competency.scope_definition,
        target_context=read.target_context,
        modules=[LearningModule(**module.model_dump()) for module in read.modules],
        recommended_resources=read.recommended_resources,
        assessment_readiness=read.assessment_readiness,
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

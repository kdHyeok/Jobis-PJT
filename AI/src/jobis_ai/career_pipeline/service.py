from __future__ import annotations

import hashlib
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

from jobis_ai.career_pipeline.capability_graph import (
    CapabilityGraphContractError,
    CapabilityGraphPort,
    CapabilityGraphUnavailable,
    closure_content_hash,
)
from jobis_ai.career_pipeline.contracts.capability_graph import (
    ActiveGraphCondition,
    CapabilityGraphClosure,
    CapabilityGraphQueryRequest,
    GraphConditionKind,
)
from jobis_ai.career_pipeline.contracts.common import CanonicalKey
from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.contracts.fit import (
    FitAnalysisRequest,
    FitAnalysisStatus,
    VerificationState,
)
from jobis_ai.career_pipeline.contracts.normalization import (
    CapabilityCatalogEntry,
    CapabilityCatalogSnapshot,
    CapabilityKind,
)
from jobis_ai.career_pipeline.contracts.pipeline import (
    AnalysisPipelineRequest,
    AnalysisPipelineResult,
    PipelineStatus,
    PostingReview,
)
from jobis_ai.career_pipeline.contracts.posting import (
    AmbiguityType,
    PostingInterpretationRequest,
    RequirementCategory,
    RequirementObligation,
)
from jobis_ai.career_pipeline.contracts.progress import AnalysisStage, ProgressEvent, ProgressStatus
from jobis_ai.career_pipeline.contracts.project_planning import ProjectPlanningRequest
from jobis_ai.career_pipeline.contracts.resolution import PostingResolutionRequest, ResolutionStatus
from jobis_ai.career_pipeline.contracts.roadmap import (
    CurrentRoadmapSnapshot,
    OpportunityTargetInput,
    RoadmapAction,
    RoadmapDraftRequest,
    RoadmapNodeKind,
    RoadmapProposal,
)
from jobis_ai.career_pipeline.fit import compile_project_fit
from jobis_ai.career_pipeline.interpretation import (
    PostingInterpretationFailure,
    PostingInterpretationService,
)
from jobis_ai.career_pipeline.normalization import (
    CapabilityNormalizationService,
    compile_project_normalization,
)
from jobis_ai.career_pipeline.project_planning import ProjectPlanningFailure, ProjectPlanningService
from jobis_ai.career_pipeline.llm import LlmProgressEvent
from jobis_ai.career_pipeline.resolution import PostingResolutionService
from jobis_ai.career_pipeline.roadmap import RoadmapDraftService


PIPELINE_VERSION = "analysis-pipeline-3.2.0"
_CANONICAL_KEY = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
LOGGER = logging.getLogger("uvicorn.error.jobis_ai.career_pipeline.pipeline")


class AnalysisPipelineFailure(RuntimeError):
    def __init__(self, *, code: ErrorCode, message: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


def _require_actionable_roadmap_proposal(
    proposal: RoadmapProposal,
    current_roadmap: CurrentRoadmapSnapshot,
) -> None:
    """A completed analysis must contain a usable draft, not capability shells."""

    if not proposal.operations:
        raise AnalysisPipelineFailure(
            code=ErrorCode.CONTRACT_VALIDATION_FAILED,
            message="Roadmap proposal has no operations.",
            retryable=False,
        )
    existing_by_id = {node.node_id: node for node in current_roadmap.nodes}
    project_operations = [
        operation for operation in proposal.operations
        if operation.node_kind is RoadmapNodeKind.TARGET_PROJECT
    ]
    opportunity_operations = [
        operation for operation in proposal.operations
        if operation.node_kind is RoadmapNodeKind.OPPORTUNITY
    ]
    if not project_operations or not opportunity_operations:
        raise AnalysisPipelineFailure(
            code=ErrorCode.CONTRACT_VALIDATION_FAILED,
            message="Roadmap proposal requires a target project and an opportunity.",
            retryable=False,
        )
    for operation in project_operations:
        if operation.action is RoadmapAction.CREATE_TARGET_PROJECT:
            tasks = list((operation.project_spec.tasks if operation.project_spec else []) or [])
        else:
            existing = existing_by_id.get(operation.existing_node_id or "")
            tasks = list((existing.project_spec.tasks if existing and existing.project_spec else []) or [])
        if tasks:
            break
    else:
        raise AnalysisPipelineFailure(
            code=ErrorCode.CONTRACT_VALIDATION_FAILED,
            message="Roadmap target project requires at least one learning task.",
            retryable=False,
        )


class AnalysisPipelineService:
    def __init__(
        self,
        *,
        posting_service: PostingInterpretationService,
        resolution_service: PostingResolutionService,
        normalization_service: CapabilityNormalizationService,
        project_planning_service: ProjectPlanningService,
        graph_port: CapabilityGraphPort,
        roadmap_service: RoadmapDraftService,
    ) -> None:
        self._posting = posting_service
        self._resolution = resolution_service
        # Kept for the standalone normalization API. The integrated pipeline no
        # longer performs a second whole-posting LLM normalization pass.
        self._normalization = normalization_service
        self._project_planning = project_planning_service
        self._graph = graph_port
        self._roadmap = roadmap_service

    def run(
        self,
        request: AnalysisPipelineRequest,
        event_sink: Callable[[ProgressEvent], None] | None = None,
    ) -> AnalysisPipelineResult:
        emit = _ProgressEmitter(request.job_id, event_sink)

        interpretation_request = PostingInterpretationRequest(
            source_document=request.source_document,
            verified_snapshot=request.verified_snapshot,
            as_of_date=request.as_of_date,
            approved_role_catalog=request.approved_role_catalog,
        )
        structured = request.structured_posting_checkpoint
        if structured is None:
            emit.start(
                AnalysisStage.POSITION_DISCOVERY,
                "회사와 모집 직무를 먼저 확인하고 있어요",
            )
            try:
                structured = self._posting.discover(
                    interpretation_request,
                    progress_callback=lambda event: emit.llm_progress(
                        AnalysisStage.POSITION_DISCOVERY,
                        event,
                    ),
                )
            except PostingInterpretationFailure as exc:
                emit.fail(
                    AnalysisStage.POSITION_DISCOVERY,
                    "직무 범위 확인에 실패했어요",
                    str(exc),
                )
                raise AnalysisPipelineFailure(
                    code=exc.code,
                    message=str(exc),
                    retryable=exc.retryable,
                ) from exc
            emit.partial(
                AnalysisStage.POSITION_DISCOVERY,
                "확인된 공고 범위",
                _discovery_partial(structured),
                detail=f"모집 직무 {len(structured.positions)}개를 확인했어요",
            )
            emit.complete(
                AnalysisStage.POSITION_DISCOVERY,
                "회사와 모집 직무 확인을 완료했어요",
            )

        resolution = self._resolution.resolve(PostingResolutionRequest(
            structured_posting=structured,
            answers=request.clarification_answers,
        ))
        if resolution.status is ResolutionStatus.AWAITING_ANSWER:
            waiting_stage = _waiting_stage(resolution.active_ambiguity.type)
            emit.wait(waiting_stage, resolution.active_ambiguity.question.text)
            return AnalysisPipelineResult(
                job_id=request.job_id,
                common_analysis_id=request.common_analysis_id,
                status=PipelineStatus.AWAITING_CLARIFICATION,
                structured_posting=structured,
                resolution=resolution,
            )
        if resolution.status is not ResolutionStatus.READY_FOR_ANALYSIS:
            raise AnalysisPipelineFailure(
                code=ErrorCode.AMBIGUITY_UNRESOLVED,
                message="The posting still contains an unresolved blocking ambiguity.",
                retryable=False,
            )

        if _is_discovery_checkpoint(structured):
            emit.start(
                AnalysisStage.POSTING_DETAIL,
                "선택한 직무의 업무와 필수·우대 요건을 분석하고 있어요",
            )
            try:
                structured = self._posting.interpret_selected(
                    interpretation_request,
                    discovery=structured,
                    selected_position_id=resolution.selected_position_id,
                    progress_callback=lambda event: emit.llm_progress(
                        AnalysisStage.POSTING_DETAIL,
                        event,
                    ),
                )
            except PostingInterpretationFailure as exc:
                emit.fail(
                    AnalysisStage.POSTING_DETAIL,
                    "선택 직무 상세 분석에 실패했어요",
                    str(exc),
                )
                raise AnalysisPipelineFailure(
                    code=exc.code,
                    message=str(exc),
                    retryable=exc.retryable,
                ) from exc
            resolution = self._resolution.resolve(PostingResolutionRequest(
                structured_posting=structured,
                answers=request.clarification_answers,
            ))
            emit.partial(
                AnalysisStage.POSTING_DETAIL,
                "선택 직무 상세 분석",
                _detail_partial(structured, resolution.selected_position_id),
                detail="담당 업무와 필수·우대 요건을 원문 근거로 확인했어요",
            )
            emit.complete(
                AnalysisStage.POSTING_DETAIL,
                "선택 직무 상세 분석을 완료했어요",
            )

        review = _posting_review(request, structured, resolution)
        confirmed_review = request.confirmed_posting_review_id == review.review_id
        if (
            not confirmed_review
            and (
                request.require_posting_confirmation
                or request.confirmed_posting_review_id is not None
            )
        ):
            emit.wait(
                AnalysisStage.AWAITING_POSTING_CONFIRMATION,
                "선택한 직무와 경력 기준에 맞게 정리한 공고를 확인해 주세요",
            )
            return AnalysisPipelineResult(
                job_id=request.job_id,
                common_analysis_id=request.common_analysis_id,
                status=PipelineStatus.AWAITING_POSTING_CONFIRMATION,
                structured_posting=structured,
                resolution=resolution,
                posting_review=review,
            )
        emit.skip(
            AnalysisStage.AWAITING_POSTING_CONFIRMATION,
            "분석 기준 확인을 자동으로 통과했어요",
            detail=(
                "AUTO_CONFIRMED: 확인한 분석 기준과 현재 공고 검토가 일치합니다."
                if confirmed_review
                else "PRECONFIRMED: 호출자가 분석 기준 확인을 완료한 요청입니다."
            ),
        )

        graph_catalog = self._load_graph_catalog()
        normalization_catalog = _normalization_catalog(graph_catalog)

        # The target project is the semantic pivot. The planner chooses approved
        # atomic capabilities because concrete project tasks need them; the
        # posting is no longer flattened directly into roadmap skill nodes.
        emit.start(AnalysisStage.PROJECT_PLANNING, "회사 맞춤 프로젝트와 수행 과제를 설계하고 있어요")
        try:
            blueprint = self._project_planning.plan(ProjectPlanningRequest(
                common_analysis_id=request.common_analysis_id,
                structured_posting=structured,
                selected_position_id=resolution.selected_position_id,
                graph_catalog=graph_catalog,
            ), progress_callback=lambda event: emit.llm_progress(
                AnalysisStage.PROJECT_PLANNING,
                event,
            ))
        except ProjectPlanningFailure as exc:
            emit.fail(
                AnalysisStage.PROJECT_PLANNING,
                "회사 맞춤 프로젝트 생성에 실패했어요",
                str(exc),
            )
            raise AnalysisPipelineFailure(
                code=exc.code,
                message=str(exc),
                retryable=exc.retryable,
            ) from exc
        emit.partial(
            AnalysisStage.PROJECT_PLANNING,
            "회사 맞춤 프로젝트 초안",
            {
                "kind": "PROJECT_BLUEPRINT",
                "title": blueprint.title,
                "summary": f"수행 과제 {len(blueprint.tasks)}개를 설계했어요",
                "taskCount": len(blueprint.tasks),
                "taskPreview": [task.title for task in blueprint.tasks[:3]],
            },
            detail=f"회사 맞춤 수행 과제 {len(blueprint.tasks)}개를 만들었어요",
        )
        emit.complete(AnalysisStage.PROJECT_PLANNING, "회사 맞춤 프로젝트 초안을 만들었어요")

        emit.start(AnalysisStage.CAPABILITY_NORMALIZATION, "프로젝트 과제를 원자 역량과 연결하고 있어요")
        try:
            normalization = compile_project_normalization(
                common_analysis_id=request.common_analysis_id,
                structured_posting=structured,
                selected_position_id=resolution.selected_position_id,
                catalog=normalization_catalog,
                blueprint=blueprint,
            )
        except ValueError as exc:
            raise AnalysisPipelineFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc
        emit.complete(AnalysisStage.CAPABILITY_NORMALIZATION, "프로젝트에 필요한 원자 역량을 확정했어요")

        target_keys = _target_capability_keys(blueprint)
        emit.start(AnalysisStage.CAPABILITY_GRAPH_LOOKUP, "필요 역량의 선행 학습 관계를 조회하고 있어요")
        try:
            role_context_keys = _role_context_keys(
                structured,
                resolution.selected_position_id,
            )
            language_choice_keys = _language_choice_keys(
                target_keys,
                normalization_catalog,
            )
            closure = (
                self._graph.get_learning_closure(CapabilityGraphQueryRequest(
                    target_capability_keys=target_keys,
                    boundary_capability_keys=_verified_capability_keys(request, graph_catalog),
                    active_conditions=[
                        *[
                            ActiveGraphCondition(
                                kind=GraphConditionKind.ROLE_CONTEXT,
                                key="selected-role",
                                value=key,
                            )
                            for key in role_context_keys
                        ],
                        *[
                            ActiveGraphCondition(
                                kind=GraphConditionKind.LANGUAGE_CHOICE,
                                key="selected-language",
                                value=key,
                            )
                            for key in language_choice_keys
                        ],
                    ],
                    requested_graph_version=request.requested_graph_version,
                ))
                if target_keys
                else _empty_closure(graph_catalog)
            )
        except CapabilityGraphUnavailable as exc:
            raise AnalysisPipelineFailure(
                code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
                message=str(exc),
                retryable=True,
            ) from exc
        except CapabilityGraphContractError as exc:
            raise AnalysisPipelineFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc
        emit.partial(
            AnalysisStage.CAPABILITY_GRAPH_LOOKUP,
            "선행 역량 확인 결과",
            {
                "kind": "CAPABILITY_GRAPH",
                "title": "필요 역량과 선행 학습 관계",
                "summary": (
                    f"목표 역량 {len(closure.target_capability_keys)}개와 "
                    f"선행 관계 {len(closure.edges)}개를 확인했어요"
                ),
                "targetCount": len(closure.target_capability_keys),
                "relationCount": len(closure.edges),
            },
            detail="프로젝트에 필요한 역량의 선행 관계를 확인했어요",
        )
        emit.complete(AnalysisStage.CAPABILITY_GRAPH_LOOKUP, "선행 학습 관계를 확인했어요")

        # Only now do user facts affect the draft. They can change progress and
        # fit, but never the project curriculum or public graph topology.
        emit.start(AnalysisStage.PROFILE_ASSEMBLY, "사용자의 커리어 근거를 준비 경로와 대조하고 있어요")
        emit.complete(AnalysisStage.PROFILE_ASSEMBLY, "사용자의 커리어 근거를 확인했어요")
        emit.start(AnalysisStage.FIT_ANALYSIS, "완성된 준비 경로에 현재 역량을 표시하고 있어요")
        fit = compile_project_fit(FitAnalysisRequest(
            common_analysis_id=request.common_analysis_id,
            structured_posting=structured,
            selected_position_id=resolution.selected_position_id,
            selected_experience_track=resolution.selected_experience_track,
            user_evidence=request.user_evidence,
            skip_remaining_evidence_questions=request.skip_remaining_evidence_questions,
        ), blueprint)
        if fit.status is FitAnalysisStatus.AWAITING_USER_EVIDENCE:
            emit.wait(
                AnalysisStage.AWAITING_USER_EVIDENCE,
                fit.active_ambiguity.question.text,
            )
            return AnalysisPipelineResult(
                job_id=request.job_id,
                common_analysis_id=request.common_analysis_id,
                status=PipelineStatus.AWAITING_USER_EVIDENCE,
                structured_posting=structured,
                resolution=resolution,
                posting_review=review,
                fit=fit,
                normalization=normalization,
                project_blueprint=blueprint,
                capability_graph=closure,
            )
        emit.skip(
            AnalysisStage.AWAITING_USER_EVIDENCE,
            "추가 근거 질문 없이 적합도 분석을 확정했어요",
            detail=(
                "QUESTION_LIMIT_REACHED: 질문 상한에 도달해 확인되지 않은 요건은 UNKNOWN으로 보존합니다."
                if request.skip_remaining_evidence_questions
                else "NO_BLOCKING_FORMAL_EVIDENCE_GAP: 추가 확인이 필요한 필수 자격·경력 요건이 없습니다."
            ),
        )
        emit.complete(AnalysisStage.FIT_ANALYSIS, "현재 역량 표시를 완료했어요")

        position = next(
            item for item in structured.positions
            if item.position_id == resolution.selected_position_id
        )
        if structured.company is None:
            raise AnalysisPipelineFailure(
                code=ErrorCode.POSTING_STRUCTURE_INVALID,
                message="A company name is required before creating a roadmap opportunity.",
                retryable=False,
            )

        emit.start(AnalysisStage.ROADMAP_PROPOSAL, "프로젝트와 선행 역량으로 로드맵 초안을 만들고 있어요")
        proposal = self._roadmap.compose(RoadmapDraftRequest(
            common_analysis_id=request.common_analysis_id,
            structured_posting=structured,
            selected_position_id=resolution.selected_position_id,
            fit_assessment=fit.assessment,
            normalization=normalization,
            project_blueprint=blueprint,
            capability_graph=closure,
            user_evidence=request.user_evidence,
            current_roadmap=request.current_roadmap,
            opportunity=OpportunityTargetInput(
                opportunity_id=request.opportunity_id,
                company_name=structured.company.display_name,
                position_title=position.source_title,
                posting_title=structured.posting_title,
            ),
        ))
        _require_actionable_roadmap_proposal(proposal, request.current_roadmap)
        emit.partial(
            AnalysisStage.ROADMAP_PROPOSAL,
            "로드맵 초안",
            {
                "kind": "ROADMAP_PROPOSAL",
                "title": "새 로드맵 초안",
                "summary": f"지도 변경 작업 {len(proposal.operations)}개를 준비했어요",
                "operationCount": len(proposal.operations),
            },
            detail="검토할 수 있는 로드맵 변경 초안을 만들었어요",
        )
        emit.complete(AnalysisStage.ROADMAP_PROPOSAL, "로드맵 변경 초안을 준비했어요")
        emit.start(AnalysisStage.RESULT_ASSEMBLY, "분석 결과의 계약을 최종 검증하고 있어요")
        result = AnalysisPipelineResult(
            job_id=request.job_id,
            common_analysis_id=request.common_analysis_id,
            status=PipelineStatus.COMPLETED,
            structured_posting=structured,
            resolution=resolution,
            posting_review=review,
            fit=fit,
            normalization=normalization,
            project_blueprint=blueprint,
            capability_graph=closure,
            roadmap_proposal=proposal,
        )
        emit.complete(AnalysisStage.RESULT_ASSEMBLY, "검증된 분석 초안을 반환했어요")
        return result

    def _load_graph_catalog(self):
        try:
            return self._graph.get_catalog()
        except CapabilityGraphUnavailable as exc:
            raise AnalysisPipelineFailure(
                code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
                message=str(exc),
                retryable=True,
            ) from exc
        except CapabilityGraphContractError as exc:
            raise AnalysisPipelineFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc


class _ProgressEmitter:
    def __init__(self, job_id: str, sink: Callable[[ProgressEvent], None] | None) -> None:
        self._job_id = job_id
        self._sink = sink
        self._sequence = 0
        self._started = time.monotonic()
        self._stage_started: dict[AnalysisStage, float] = {}

    def start(self, stage: AnalysisStage, label: str) -> None:
        self._stage_started[stage] = time.monotonic()
        self._send(
            stage,
            ProgressStatus.RUNNING,
            label,
            stage_duration_ms=None,
            detail=None,
            partial_result=None,
        )

    def complete(self, stage: AnalysisStage, label: str) -> None:
        started = self._stage_started.pop(stage, None)
        duration_ms = (
            max(0, int((time.monotonic() - started) * 1000))
            if started is not None
            else None
        )
        self._send(
            stage,
            ProgressStatus.COMPLETED,
            label,
            stage_duration_ms=duration_ms,
            detail=None,
            partial_result=None,
        )

    def wait(self, stage: AnalysisStage, label: str) -> None:
        self._send(
            stage,
            ProgressStatus.WAITING,
            label,
            stage_duration_ms=None,
            detail=None,
            partial_result=None,
        )

    def skip(self, stage: AnalysisStage, label: str, *, detail: str) -> None:
        self._send(
            stage,
            ProgressStatus.SKIPPED,
            label,
            stage_duration_ms=None,
            detail=detail,
            partial_result=None,
        )

    def llm_progress(self, stage: AnalysisStage, event: LlmProgressEvent) -> None:
        self._send(
            stage,
            ProgressStatus.RUNNING,
            "분석 에이전트가 작업 중이에요",
            stage_duration_ms=None,
            detail=event.message,
            partial_result=None,
        )

    def partial(
        self,
        stage: AnalysisStage,
        label: str,
        partial_result: dict,
        *,
        detail: str,
    ) -> None:
        self._send(
            stage,
            ProgressStatus.RUNNING,
            label,
            stage_duration_ms=None,
            detail=detail,
            partial_result=partial_result,
        )

    def fail(self, stage: AnalysisStage, label: str, detail: str) -> None:
        started = self._stage_started.pop(stage, None)
        duration_ms = (
            max(0, int((time.monotonic() - started) * 1000))
            if started is not None
            else None
        )
        self._send(
            stage,
            ProgressStatus.FAILED,
            label,
            stage_duration_ms=duration_ms,
            detail=detail,
            partial_result=None,
        )

    def _send(
        self,
        stage: AnalysisStage,
        status: ProgressStatus,
        label: str,
        *,
        stage_duration_ms: int | None,
        detail: str | None,
        partial_result: dict | None,
    ) -> None:
        self._sequence += 1
        elapsed_ms = max(0, int((time.monotonic() - self._started) * 1000))
        LOGGER.info(
            "analysis_stage job_id=%s sequence=%d stage=%s status=%s "
            "stage_duration_ms=%s elapsed_ms=%d",
            self._job_id,
            self._sequence,
            stage.value,
            status.value,
            stage_duration_ms,
            elapsed_ms,
        )
        if self._sink is None:
            return
        self._sink(ProgressEvent(
            event_id=f"event-{self._job_id}-{self._sequence}",
            job_id=self._job_id,
            sequence=self._sequence,
            stage=stage,
            status=status,
            label=label,
            detail=detail,
            occurred_at=datetime.now(UTC),
            elapsed_ms=elapsed_ms,
            stage_duration_ms=stage_duration_ms,
            partial_result=partial_result,
        ))


def _is_discovery_checkpoint(posting) -> bool:
    return posting.analysis_version.startswith("posting-discovery-")


def _discovery_partial(posting) -> dict:
    return {
        "kind": "POSITION_DISCOVERY",
        "title": "확인된 공고 범위",
        "company": posting.company.display_name if posting.company else None,
        "postingTitle": posting.posting_title,
        "positions": [
            {
                "positionId": position.position_id,
                "title": position.source_title,
                "roleFamily": position.role.family,
                "roleSpecialization": position.role.specialization,
                "experienceKind": position.experience.kind.value,
                "minMonths": position.experience.min_months,
                "experiencedMinMonths": position.experience.experienced_min_months,
            }
            for position in posting.positions
        ],
    }


def _detail_partial(posting, selected_position_id: str) -> dict:
    selected = next(
        position
        for position in posting.positions
        if position.position_id == selected_position_id
    )
    required = [
        item
        for item in selected.requirements
        if item.obligation is RequirementObligation.REQUIRED
    ]
    preferred = [
        item
        for item in selected.requirements
        if item.obligation is RequirementObligation.PREFERRED
    ]
    return {
        "kind": "POSTING_DETAIL",
        "title": f"{selected.source_title} 상세 분석",
        "positionTitle": selected.source_title,
        "summary": (
            f"담당 업무 {len(selected.responsibilities)}개 · "
            f"필수 {len(required)}개 · 우대 {len(preferred)}개"
        ),
        "responsibilityCount": len(selected.responsibilities),
        "requiredCount": len(required),
        "preferredCount": len(preferred),
        "requiredPreview": [item.atomic_text for item in required[:3]],
        "preferredPreview": [item.atomic_text for item in preferred[:3]],
    }


def _waiting_stage(ambiguity_type: AmbiguityType) -> AnalysisStage:
    if ambiguity_type is AmbiguityType.POSITION_SELECTION:
        return AnalysisStage.AWAITING_POSITION_SELECTION
    if ambiguity_type is AmbiguityType.EXPERIENCE_TRACK_SELECTION:
        return AnalysisStage.AWAITING_EXPERIENCE_TRACK_SELECTION
    return AnalysisStage.CONTRACT_VALIDATION


def _posting_review(request, structured, resolution) -> PostingReview:
    position = next(
        item for item in structured.positions
        if item.position_id == resolution.selected_position_id
    )
    selected_requirements = [
        *position.requirements,
        *[
            requirement
            for requirement in structured.shared_conditions
            if position.position_id in requirement.applies_to_position_ids
        ],
    ]
    unique_requirements = list({
        requirement.requirement_id: requirement
        for requirement in selected_requirements
    }.values())
    review_identity = "\n".join([
        structured.verified_snapshot_id,
        structured.analysis_version,
        position.position_id,
        resolution.selected_experience_track.value
        if resolution.selected_experience_track is not None
        else "UNKNOWN",
        position.model_dump_json(by_alias=True),
        *sorted(
            requirement.model_dump_json(by_alias=True)
            for requirement in unique_requirements
        ),
    ])
    review_id = "posting-review-" + hashlib.sha256(
        review_identity.encode("utf-8")
    ).hexdigest()[:24]

    responsibility_requirements = [
        requirement for requirement in unique_requirements
        if requirement.category is RequirementCategory.RESPONSIBILITY
    ]
    review_requirements = [
        requirement for requirement in unique_requirements
        if requirement.category is not RequirementCategory.RESPONSIBILITY
    ]

    def by_obligation(obligation):
        return [
            requirement for requirement in review_requirements
            if requirement.obligation is obligation
        ]

    return PostingReview(
        review_id=review_id,
        verified_snapshot_id=structured.verified_snapshot_id,
        company_name=(
            structured.company.display_name if structured.company is not None else None
        ),
        posting_title=structured.posting_title,
        selected_position_id=position.position_id,
        position_title=position.source_title,
        selected_experience_track=resolution.selected_experience_track,
        experience=position.experience,
        responsibilities=position.responsibilities,
        responsibility_requirements=responsibility_requirements,
        required_requirements=by_obligation(RequirementObligation.REQUIRED),
        preferred_requirements=by_obligation(RequirementObligation.PREFERRED),
        informational_requirements=by_obligation(RequirementObligation.INFORMATIONAL),
        original_text=request.verified_snapshot.verified_text,
    )


def _target_capability_keys(blueprint) -> list[CanonicalKey]:
    return sorted({
        key
        for task in blueprint.tasks
        for key in task.capability_keys
    })


def _verified_capability_keys(
    request: AnalysisPipelineRequest,
    graph_catalog,
) -> list[CanonicalKey]:
    graph_keys = {item.canonical_key for item in graph_catalog.capabilities}
    return sorted({
        competency.competency_id
        for competency in request.user_evidence.competencies
        if competency.verification_state is VerificationState.VERIFIED
        and competency.competency_id in graph_keys
    })


def _normalization_catalog(graph_catalog) -> CapabilityCatalogSnapshot:
    return CapabilityCatalogSnapshot(
        catalog_version=f"graph-{graph_catalog.graph_version}-{graph_catalog.content_hash[-12:]}",
        entries=[
            CapabilityCatalogEntry(
                canonical_key=item.canonical_key,
                display_name=item.display_name,
                kind=item.kind,
                scope_definition=item.scope_definition,
                aliases=item.aliases,
                version=item.version,
            )
            for item in graph_catalog.capabilities
        ],
    )


def _empty_closure(graph_catalog) -> CapabilityGraphClosure:
    closure = CapabilityGraphClosure(
        graph_version=graph_catalog.graph_version,
        generated_at=datetime.now(UTC),
        content_hash="sha256:" + "0" * 64,
        nodes=[],
        edges=[],
        sources=[],
    )
    return closure.model_copy(update={"content_hash": closure_content_hash(closure)})


def _role_context_keys(structured, selected_position_id: str) -> list[CanonicalKey]:
    position = next(
        item for item in structured.positions
        if item.position_id == selected_position_id
    )
    value = position.role.canonical_role_id
    return [value] if value is not None and _CANONICAL_KEY.fullmatch(value) else []


def _language_choice_keys(target_keys, catalog) -> list[CanonicalKey]:
    by_key = {item.canonical_key: item for item in catalog.entries}
    return sorted(
        key for key in target_keys
        if key in by_key and by_key[key].kind is CapabilityKind.PROGRAMMING_LANGUAGE
    )

"""전담 에이전트 레지스트리 (개선방안 §2.2 MVP 로스터).

각 에이전트는 세션 자산(dict)을 받아 AgentResult 를 반환하는 진입 함수 하나로 노출된다.
오케스트레이터(dispatch_router)는 이 레지스트리에 등록된 이름만 호출할 수 있다 —
"알려진 도구 중에서만 고른다"(agent_develop §3.6-1)를 코드로 강제하는 지점.

에이전트는 판정을 하지 않는다. 판정이 필요하면 판정 엔진(fit_analysis → build_graph)을
부르고, 생성 에이전트는 판정 산출물의 소비자로만 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AgentResult:
    """에이전트 실행 결과. reply 는 대화로 나가는 문장, data 는 구조화 산출물."""

    reply: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)
    followUpQuestions: list[dict] = field(default_factory=list)
    # 세션에 저장할 자산 (예: {"analysis": {...}}) — 오케스트레이터가 세션에 병합한다.
    sessionUpdates: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSpec:
    """capability manifest 의 한 항목 (agent_develop §3.6 capability manifest)."""

    name: str
    description: str
    # 세션 자산 전제조건: "resume" | "job_posting" | "analysis" | "roadmap"
    preconditions: tuple[str, ...]
    entry: Callable[[dict], AgentResult]
    # 실행 성공 시 세션에 생기는 자산 — 플래너 검증기가 전제 자동 삽입을 추론하는 근거.
    produces: tuple[str, ...] = ()
    # 무거운 파이프라인(LLM 여러 회·수십 초) 여부. 검증기가 이 에이전트를 **자동 삽입**할 때는
    # 말없이 시작하지 않고 사용자에게 먼저 묻는다(동의 게이트). 명시 선택이면 그대로 실행.
    heavy: bool = False


def get_agent_registry() -> dict[str, AgentSpec]:
    """이름 → AgentSpec. 함수로 감싼 것은 순환 import 방지(에이전트가 그래프/서비스를 임포트)."""

    from jobis_ai.agents import (
        application_plan,
        career_chat,
        coverletter_draft,
        fit_analysis,
        interview_prep,
        job_recommend,
        posting_analysis,
        preference_intake,
        resume_diagnosis,
        roadmap_manager,
    )

    specs = [
        AgentSpec(
            name="fit_analysis",
            description="공고×이력서 적합도 판정 (기존 판정 엔진 전체)",
            preconditions=("resume", "job_posting"),
            entry=fit_analysis.run,
            produces=("analysis", "roadmap"),
            heavy=True,
        ),
        AgentSpec(
            name="posting_analysis",
            description="공고만으로 핵심 요구사항 정리(요구 연차·기술 스택·필수/우대) — 이력서 없이 가능, 판정은 안 함",
            preconditions=("job_posting",),
            entry=posting_analysis.run,
        ),
        AgentSpec(
            name="job_recommend",
            description="이력서 기반 공고 추천 — 대화로 수집한 선호(직군·도메인·회사·지역·기술스택)를 검색·랭킹에 반영",
            preconditions=("resume",),
            entry=job_recommend.run,
            produces=("recommendations",),
        ),
        AgentSpec(
            name="career_chat",
            description="기능과 직접 관련 없는 진로 고민·하소연·일반 질문을 받아주는 대화 — 필요할 때만 기능을 부드럽게 안내",
            preconditions=(),
            entry=career_chat.run,
        ),
        AgentSpec(
            name="preference_intake",
            description="이력서 없이 대화로 원하는 직군·회사·도메인을 파악 — 충분히 모이면 이력서를 자연스럽게 요청",
            preconditions=(),
            entry=preference_intake.run,
            produces=("preferences",),
        ),
        AgentSpec(
            name="resume_diagnosis",
            description="이력서 진단 — 강점·빈약 항목·보완 질문",
            preconditions=("resume",),
            entry=resume_diagnosis.run,
        ),
        AgentSpec(
            name="interview_prep",
            description="적합도 분석 결과 기반 면접 예상 질문 생성",
            preconditions=("analysis",),
            entry=interview_prep.run,
        ),
        AgentSpec(
            name="coverletter_draft",
            description="적합도 분석 근거 기반 자소서 초안 (항상 사용자 검토 게이트)",
            preconditions=("resume", "analysis"),
            entry=coverletter_draft.run,
            produces=("coverletter",),
        ),
        AgentSpec(
            name="application_plan",
            description="적합도 판정 결과로 '지금 목표로 둘지'(목표 상태)와 지원 경로 2~3개를 세운다 — 판정은 룰, 문구는 LLM",
            preconditions=("analysis",),
            entry=application_plan.run,
            produces=("application_plan",),
        ),
        AgentSpec(
            name="roadmap_manager",
            description="저장된 준비 로드맵 조회 (수정·진척은 후속)",
            preconditions=("roadmap",),
            entry=roadmap_manager.run,
        ),
    ]
    return {s.name: s for s in specs}

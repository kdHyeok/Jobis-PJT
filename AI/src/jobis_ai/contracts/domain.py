"""에이전트 간 데이터 계약 (설계 8~14장의 각 에이전트 출력 스키마).

각 워커 에이전트는 아래 구조화 JSON 을 산출하고, GraphState 에 dict 로 실린다.
스켈레톤 단계에서는 mock 노드가 이 모델을 생성해 `.model_dump()` 로 상태에 넣는다.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Job Posting Parser (설계 8.2)
# ---------------------------------------------------------------------------
class Requirement(BaseModel):
    requirementId: str
    text: str
    type: Literal["required", "preferred"] = "required"


class NormalizedJobPosting(BaseModel):
    jobTitle: str = ""
    companyName: str = ""
    roleCategory: str = ""
    seniority: str = ""
    # 요구 최소 경력 연차(원문에 숫자가 있을 때만, rule_extractor 산출). None = 근거 없음.
    # seniority 사다리는 이 값을 5칸으로 뭉갠 손실 요약이다 — 판정·표기는 이 원본을 우선한다
    # (0년과 2년이 같은 junior 칸에 들어가 "신입이 '2년 이상' 공고를 충족" 오판이 났던 원인).
    minYears: int | None = None
    # 요구 **상한** 연차 — 범위 표기("경력 3~7년")일 때만 값이 있다. None = 상한 없음/미상.
    # 상한이 있다는 것은 정보다("시니어는 안 뽑는다"). 전에는 파싱에서 버려져 "3년 이상"으로만
    # 남았다(2026-08-01 리뷰 지적 — `grep maxYears src/` 가 0건이었다).
    # **지금은 보존·노출만 한다.** 판정에 쓰는 것은 별 결정이다(평가셋 재측정이 필요하다).
    maxYears: int | None = None
    # minYears 를 뽑은 원문 조각 ("경력 2년 이상") — 화면 표기는 공고가 한 말을 그대로 쓴다.
    yearsEvidence: str = ""
    requiredRequirements: list[Requirement] = Field(default_factory=list)
    preferredRequirements: list[Requirement] = Field(default_factory=list)
    # **담당업무·조직·전형·기타 조건은 요건과 함께 읽는다(D157).** 전에는 칸이 없어서 공고
    # 담당이 `read_posting`(원문 grep)으로 긁게 했는데, grep 은 줄 단위라 여러 줄로 적힌
    # 담당업무·전형 절차 블록을 못 잡았다 — 실측(2026-08-02) 근무시간·복리후생이 원문에
    # 있는데 "기재 없음"으로 나갔고, 외부 LLM 과 비교(2026-08-04)에서 담당업무·조직이
    # 통째로 빠진 것이 가장 큰 격차였다. 읽기는 읽기 계층에서 한 번에 한다(§1).
    responsibilities: list[str] = Field(default_factory=list)
    # "라벨: 값" 한 줄씩 — 공고마다 항목이 다르므로 스키마를 늘리지 않고 자유 목록으로 받는다.
    conditions: list[str] = Field(default_factory=list)
    hiringProcess: list[str] = Field(default_factory=list)
    teamContext: str = ""
    techStack: list[str] = Field(default_factory=list)
    domainKeywords: list[str] = Field(default_factory=list)
    rawChunks: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    id: str = ""
    school: str = ""
    major: str = ""
    degree: str = ""  # 고졸/전문학사/학사/석사/박사
    status: str = ""  # 졸업/재학/휴학/중퇴/수료
    period: str = ""


class ExperienceEntry(BaseModel):
    """정규직/계약직/인턴 등 **고용 관계가 있었던 재직 이력만.**

    팀/개인/부트캠프 프로젝트는 고용 관계가 아니므로 여기 넣지 않는다 — `ProjectEntry` 로.
    안 나누면 같은 프로젝트가 experiences 와 projects 양쪽에 중복 서술된다(실제 페르소나
    테스트에서 확인된 문제. tests/docs/결과.txt 의 SecondHand 항목 참고).
    """

    id: str = ""
    company: str = ""
    role: str = ""
    employmentType: str = ""  # 정규직/계약직/인턴/파견
    period: str = ""
    summary: str = ""
    relatedProjectIds: list[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    """팀/개인/부트캠프/사이드 프로젝트. 고용 관계가 없는 실습성 활동은 전부 여기."""

    id: str = ""
    title: str = ""
    projectType: str = ""  # 팀 프로젝트/개인 프로젝트/부트캠프 프로젝트 등
    period: str = ""
    teamSize: str = ""
    role: str = ""
    summary: str = ""
    techStack: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)


class SkillEntry(BaseModel):
    name: str = ""
    level: str = ""  # beginner/intermediate/advanced. 원문에 없으면 빈 문자열(추측 금지)


class BootcampEntry(BaseModel):
    id: str = ""
    name: str = ""
    organization: str = ""
    track: str = ""
    period: str = ""
    summary: str = ""


class AwardEntry(BaseModel):
    id: str = ""
    title: str = ""
    organization: str = ""
    date: str = ""
    description: str = ""


class CertificationEntry(BaseModel):
    id: str = ""
    name: str = ""  # 가능하면 cert_db 표준명과 맞춰 표기 (취득 여부 매칭에 쓸 수 있도록)
    status: str = ""  # 취득/필기합격/응시예정 등. 자격증마다 단계 표현이 달라 enum화하지 않음
    acquiredDate: str = ""


class LanguageEntry(BaseModel):
    id: str = ""
    name: str = ""  # 한국어/영어/일본어 등
    testName: str = ""  # 토익/오픽/JLPT 등. 시험 없이 자기서술만 있으면 빈 문자열
    score: str = ""  # 점수/등급. OPIc "IH" 처럼 등급제도 있어 문자열로 둔다
    testDate: str = ""
    proficiency: str = ""  # 자유 서술 숙련도 (예: "Native"). 시험 점수가 없을 때 대체


# ---------------------------------------------------------------------------
# User Profile Builder (설계 9.2)
# ---------------------------------------------------------------------------
class NormalizedUserProfile(BaseModel):
    education: list[EducationEntry] = Field(default_factory=list)
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[SkillEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
    languages: list[LanguageEntry] = Field(default_factory=list)
    bootcamp: list[BootcampEntry] = Field(default_factory=list)
    awards: list[AwardEntry] = Field(default_factory=list)
    evidenceMap: list[dict] = Field(default_factory=list)
    # 표준 스킬명 → 그 스킬이 실제로 등장한 evidenceId 들 (설계 §3.2-④).
    # **룰로 만든다** — LLM 이 "이 근거가 이 스킬을 증명한다"고 주장하게 두면 환각 근거가 섞인다.
    # gap_matcher 가 matchedEvidenceIds 를 채울 때 이 표를 인용하므로 추적성의 핵심이다.
    skillEvidence: dict[str, list[str]] = Field(default_factory=dict)
    clarificationQuestions: list[dict] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Gap Analyzer (설계 10.2)
# ---------------------------------------------------------------------------
class RequirementStatus(BaseModel):
    requirementId: str
    type: Literal["required", "preferred"]
    text: str
    status: Literal["met", "partially_met", "not_met", "uncertain"]
    matchedEvidenceIds: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0


class Gap(BaseModel):
    requirementId: str
    severity: Literal["high", "medium", "low"]
    reason: str = ""
    evidenceMissing: bool = True
    # 이 gap 에서 부족한 표준 스킬명들 (gap_matcher 가 계산).
    # plan_roadmap 이 skill_to_cert 로 관련 자격증을 찾을 때의 입력이다(§3.6).
    missingSkills: list[str] = Field(default_factory=list)


class ScoreBasis(BaseModel):
    techSkill: Optional[float] = None
    projectExperience: Optional[float] = None
    certLanguage: Optional[float] = None
    roleRelevance: Optional[float] = None
    domainFit: Optional[float] = None


class GapAnalysisResult(BaseModel):
    requirementStatus: list[RequirementStatus] = Field(default_factory=list)
    strengths: list[dict] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    scoreBasis: ScoreBasis = Field(default_factory=ScoreBasis)
    # 종합 적합도 (scoreBasis 를 가중 평균한 값과 그 등급, 2026-07-21).
    # overallScore/fitGrade 는 계산 근거가 하나도 없으면 각각 None/"판정불가" 로 남는다.
    overallScore: Optional[float] = None
    fitGrade: str = ""
    companyContext: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Roadmap Planner (설계 11.2)
# ---------------------------------------------------------------------------
class RoadmapItem(BaseModel):
    title: str
    startDate: str
    endDate: str
    goal: str = ""
    tasks: list[str] = Field(default_factory=list)
    doneCriteria: str = ""
    priority: Literal["high", "medium", "low"] = "medium"
    relatedRequirementIds: list[str] = Field(default_factory=list)
    estimatedHours: int = 0


class RoadmapResult(BaseModel):
    roadmap: list[RoadmapItem] = Field(default_factory=list)
    totalWeeks: int = 0
    weeklyLoadHours: int = 0
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Alternative Path Finder (설계 14.2, 2차 우선순위)
# ---------------------------------------------------------------------------
class AlternativeJob(BaseModel):
    type: Literal["similar_role", "lower_seniority", "similar_stack", "stepping_stone"]
    title: str = ""
    companyName: str = ""
    matchedStrengths: list[str] = Field(default_factory=list)
    reducedGaps: list[str] = Field(default_factory=list)
    reason: str = ""
    sourceJobPostingId: Optional[str] = None
    # 실공고에서 온 대안이면 그 공고 URL. 사용자가 붙여넣으면 그 공고로 분석이 이어진다
    # (job_recommend 와 같은 규칙 — 공고를 제시할 때는 URL 을 함께 준다).
    # 실공고 근거 없는 경로 제안(stepping_stone)은 빈 문자열이다.
    url: str = ""
    confidence: float = 0.0


class PathComparison(BaseModel):
    directPath: dict = Field(default_factory=dict)
    alternativePaths: list[dict] = Field(default_factory=list)


class AlternativePathResult(BaseModel):
    alternativeJobs: list[AlternativeJob] = Field(default_factory=list)
    pathComparison: PathComparison = Field(default_factory=PathComparison)
    sources: list[dict] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Result Verifier (설계 12.2)
# ---------------------------------------------------------------------------
class Violation(BaseModel):
    type: Literal["forbidden_expression", "missing_field", "inconsistent", "no_evidence"]
    location: str = ""
    detail: str = ""


class RetrySignal(BaseModel):
    required: bool = False
    targetAgent: Optional[str] = None
    reason: str = ""


class VerifierResult(BaseModel):
    passed: bool = True
    warnings: list[dict] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)
    retrySignal: RetrySignal = Field(default_factory=RetrySignal)

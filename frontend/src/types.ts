export type User = {
  id: string;
  email: string;
  displayName: string;
  status: string;
  accountRole: "USER" | "OPERATOR";
  createdAt: string;
};

export type GoalProfile = {
  currentGoalPostingId: string | null;
  currentGoalCompanyName: string | null;
  currentGoalRoleTitle: string | null;
  finalGoalText: string | null;
  updatedAt: string | null;
};

export type CareerNode = {
  id: string;
  canonicalKey: string;
  title: string;
  subtitle: string | null;
  domain: string;
  kind: string;
  scopeDefinition: string | null;
  level: number;
  detail: Record<string, unknown>;
  rank: number;
  progressStatus: string | null;
  completionMethod: string | null;
  completedAt: string | null;
};

export type CareerEdge = {
  id: string;
  fromNodeId: string;
  toNodeId: string;
  edgeKind: string;
};

export type Requirement = {
  postingId: string;
  nodeId: string;
  kind: "REQUIRED" | "PREFERRED";
  sourceText: string | null;
  confidence: number | null;
};

export type CareerMap = {
  graph: {
    id: string;
    title: string;
    version: number;
    updatedAt: string;
  };
  nodes: CareerNode[];
  edges: CareerEdge[];
  requirements: Requirement[];
};

export type Posting = {
  id: string;
  sourceType: string;
  sourceUrl: string | null;
  companyName: string | null;
  roleTitle: string | null;
  experienceText: string | null;
  closesAt?: string | null;
  lifecycleStatus?: "ACTIVE" | "EXPIRED" | "CLOSED" | "UNKNOWN";
  analysisJobId: string | null;
  analysisStatus: string | null;
  archivedAt: string | null;
  createdAt: string;
};

export type AnalysisJob = {
  id: string;
  postingId: string;
  status:
    | "QUEUED"
    | "RUNNING"
    | "WAITING_FOR_INPUT"
    | "SUCCEEDED"
    | "FAILED";
  stage: string;
  stageMessage: string;
  queuePosition: number | null;
  attemptCount: number;
  questionCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  result: {
    evaluation?: {
      verdict: "APPLY_NOW" | "STRENGTHEN_THEN_APPLY" | "ALTERNATIVE_FIRST";
      summary: string;
      reasons: string[];
    };
    job?: {
      companyName?: string;
      roleTitle?: string;
      experienceText?: string | null;
      employmentType?: string | null;
      closesAt?: string | null;
      lifecycleStatus?: "ACTIVE" | "EXPIRED" | "CLOSED" | "UNKNOWN";
      primaryTrack?: string;
      experienceRequirement?: {
        type: "NONE" | "REQUIRED" | "PREFERRED";
        minimumMonths: number;
        maximumMonths: number | null;
        sourceText: string;
      };
    };
  } | null;
  changeSetId: string | null;
  changeSetStatus: string | null;
  proposal: {
    competencies: AnalyzedCompetency[];
    requirements: AnalyzedRequirement[];
    targetProject: TargetProjectBrief;
  } | null;
  progressEvents: AnalysisProgressEvent[];
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  pendingQuestion: AnalysisQuestion | null;
  questionHistory: Array<{
    id: string;
    key: string;
    text: string;
    answerValue: string;
    answeredAt: string;
    ordinal: number;
  }>;
};

export type AnalysisStageDefinition = {
  id: string;
  label: string;
  role: string;
  message: string;
  color: string;
};

export type AnalysisStageUpdate = {
  id: string;
  status: "PENDING" | "RUNNING" | "WAITING" | "COMPLETED" | "FAILED";
  message: string | null;
};

export type AnalysisProgressEvent = {
  type: "RUN_STARTED" | "STAGE_UPDATED" | "RESULT" | "ERROR";
  runId: string;
  sequence: number;
  occurredAt: string;
  stages: AnalysisStageDefinition[];
  stage: AnalysisStageUpdate | null;
  result?: unknown;
  errorCode: string | null;
  errorMessage: string | null;
};

export type AnalysisQuestionOption = {
  value: string;
  label: string;
  description: string;
};

export type AnalysisQuestion = {
  id: string;
  key: string;
  text: string;
  reason: string;
  options: AnalysisQuestionOption[];
  ordinal: number;
};

export type AnalyzedCompetency = {
  ref: string;
  canonicalKey: string;
  title: string;
  domain: string;
  kind: string;
  stage: string;
  scopeDefinition: string;
  requiredLevel: number;
  roadmapEligible: boolean;
  verificationMethod: string | null;
};

export type AnalyzedRequirement = {
  competencyRef: string;
  relation: "REQUIRED" | "PREFERRED" | "RESPONSIBILITY";
  sourceText: string;
  confidence: number;
};

export type TargetProjectBrief = {
  title: string;
  objective: string;
  domainContext: string;
  requiredCompetencyRefs: string[];
  optionalCompetencyRefs: string[];
  deliverables: string[];
  acceptanceCriteria: string[];
};

export type RoadmapCompetency = {
  id: string;
  canonicalKey: string;
  title: string;
  kind: string;
  scopeDefinition: string;
  requiredLevel: number;
  relation: "REQUIRED" | "PREFERRED" | "MIXED";
  progressStatus: string;
  verifiedLevel: number;
  careerNodeId: string | null;
};

export type RoadmapProject = {
  title: string;
  objective: string;
  domainContext: string;
  requiredCompetencyKeys: string[];
  optionalCompetencyKeys: string[];
  deliverables: string[];
  acceptanceCriteria: string[];
};

export type RoadmapNode = {
  id: string;
  type: "MILESTONE" | "GATE" | "PROJECT" | "OPPORTUNITY";
  title: string;
  subtitle: string | null;
  domain: string;
  stage: string;
  rank: number;
  optional: boolean;
  postingIds: string[];
  competencies: RoadmapCompetency[];
  project: RoadmapProject | null;
  postingId: string | null;
  status: string;
  careerNodeId: string | null;
  requirementKinds?: Record<string, "REQUIRED" | "PREFERRED">;
};

export type RoadmapSnapshot = {
  version: number;
  title: string;
  nodes: RoadmapNode[];
  edges: Array<{
    fromId: string;
    toId: string;
    kind:
      | "PREREQUISITE"
      | "OPTIONAL"
      | "PROJECT_PATH"
      | "OPPORTUNITY_PATH"
      | "CAREER_PATH";
  }>;
  targets: Array<{
    postingId: string;
    companyName: string;
    roleTitle: string;
    completedRequired: number;
    required: number;
    completedPreferred: number;
    preferred: number;
  }>;
};

export type RoadmapWorkspace = {
  current: RoadmapSnapshot;
  draft: {
    id: string;
    version: number;
    changes: {
      added: string[];
      removed: string[];
      retained: string[];
    };
    snapshot: RoadmapSnapshot;
    createdAt: string;
  } | null;
  targetCount: number;
};

export type ConversationMessage = {
  id: string;
  role: "USER" | "ASSISTANT" | "SYSTEM";
  kind: "TEXT" | "POSTING" | "ANALYSIS_STATUS" | "EVIDENCE_STATUS";
  content: string;
  postingId: string | null;
  analysisJobId: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
};

export type Conversation = {
  id: string;
  title: string;
  status: "ACTIVE" | "ARCHIVED";
  messages: ConversationMessage[];
  lastMessageAt: string;
  createdAt: string;
};

export type ConversationSummary = {
  id: string;
  title: string;
  status: "ACTIVE" | "ARCHIVED";
  lastMessage: string;
  lastMessageAt: string;
  createdAt: string;
};

export type SendMessageResult = {
  userMessage: ConversationMessage;
  assistantMessage: ConversationMessage | null;
  analysisJobId: string | null;
  chatReplyJobId: string | null;
  aiAvailable: boolean;
};

/**
 * 대화 한 턴의 진행 단계 하나 — 어느 에이전트가 무슨 도구로 무엇을 했나.
 *
 * `agent` 는 화자 키다(에이전트 이름 또는 `orchestrator`). 색·로고는 이 키로 `agents.ts`
 * 등록부에서 고른다 — `label` 은 다듬을 수 있는 문구라 화면 식별자로 쓰지 않는다.
 */
export type ChatAgentStep = {
  agent: string;
  step: string;
  label: string;
  detail: string;
  elapsedMs: number | null;
  /** 담당이 완성한 사용자향 발화 본문(D153) — 있으면 과정 라벨과 별개의 말풍선 내용이 된다. */
  message?: string | null;
};

/**
 * AI 답변 메타데이터 중 화면이 읽는 항목. 전체 응답이 메시지 metadata 에 그대로 저장된다.
 *
 * `degradedReason` 이 있으면 그 답변은 LLM 실패 뒤 만들어진 결정론 요약본이다 —
 * 분석 결과처럼 읽히면 안 되므로 화면에 그대로 알린다.
 */
export type ChatReplyMetadata = {
  replySources?: ChatReplySource[];
  degradedReason?: string;
};

/** 최종 답변의 문장별 화자 — 여러 담당이 만든 답변을 화자별 말풍선으로 나누는 근거. */
export type ChatReplySource = {
  agent: string;
  channel: string;
  text: string;
};

export type ChatReplyJob = {
  id: string;
  conversationId: string;
  triggerMessageId: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  stage: string;
  stageMessage: string;
  attemptCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  progressSteps: ChatAgentStep[] | null;
};

export type NotificationItem = {
  id: string;
  type: string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  readAt: string | null;
  createdAt: string;
};

export type PostingDetail = Posting & {
  rawText: string;
  employmentType: string | null;
  parsedData: string | null;
  updatedAt: string;
};

export type PostingPage = {
  items: Posting[];
  page: number;
  size: number;
  total: number;
};

export type Evidence = {
  id: string;
  nodeId: string;
  evidenceType: string;
  title: string;
  sourceUrl: string | null;
  content: Record<string, unknown>;
  verificationStatus:
    | "PENDING"
    | "RUNNING"
    | "VERIFIED"
    | "NEEDS_WORK"
    | "REJECTED"
    | "FAILED";
  verificationResult: {
    verdict?: "VERIFIED" | "NEEDS_WORK" | "REJECTED";
    confidence?: number;
    summary?: string;
    strengths?: string[];
    gaps?: string[];
    nextActions?: string[];
  } | null;
  attemptCount: number;
  errorMessage: string | null;
  createdAt: string;
  completedAt: string | null;
};

export type CompetencyAssessmentTurn = {
  id: string;
  ordinal: number;
  questionKind: "CONCEPT" | "CODE" | "SCENARIO" | "FOLLOW_UP";
  prompt: string;
  codeSnippet: string | null;
  answerText: string | null;
  score: number | null;
  verdict: "PASS" | "PARTIAL" | "FAIL" | null;
  feedback: string | null;
  coveredCriteria: string[];
  gaps: string[];
  coreCriteria: string[];
  futureExtensions: string[];
  answeredAt: string | null;
};

export type CompetencyAssessment = {
  id: string;
  competencyId: string;
  competencyTitle: string;
  canonicalKey: string;
  targetPostingId: string | null;
  companyName: string | null;
  roleTitle: string | null;
  requiredLevel: number;
  status: "IN_PROGRESS" | "PASSED" | "NEEDS_STUDY" | "ABANDONED";
  questionCount: number;
  retainedScores: Partial<
    Record<"CONCEPT" | "CODE" | "SCENARIO", number>
  >;
  averageScore: number | null;
  achievedLevel: number;
  confidence: number | null;
  summary: string | null;
  strengths: string[];
  gaps: string[];
  nextActions: string[];
  reviewStatus: "NONE" | "REQUESTED" | "APPROVED" | "REJECTED";
  appealText: string | null;
  turns: CompetencyAssessmentTurn[];
  createdAt: string;
  completedAt: string | null;
};

export type PostingDuplicateCandidate = {
  id: string;
  matchKind: "PLATFORM_ID" | "URL" | "CONTENT_HASH" | "FUZZY";
  similarityScore: number;
  proposedAction: "MERGE" | "SEPARATE" | "REVIEW";
  proposalReason: string;
  status: "OPEN" | "MERGED" | "SEPARATED" | "ON_HOLD";
  left: {
    id: string;
    companyName: string;
    roleTitle: string;
    sourceUrl: string | null;
    lifecycleStatus: string;
  };
  right: {
    id: string;
    companyName: string;
    roleTitle: string;
    sourceUrl: string | null;
    lifecycleStatus: string;
  };
  createdAt: string;
};

export type AssessmentReviewItem = {
  sessionId: string;
  userId: string;
  userEmail: string;
  competencyTitle: string;
  requiredLevel: number;
  status: string;
  reviewStatus: string;
  appealText: string;
  averageScore: number | null;
  summary: string | null;
  createdAt: string;
};

export type AlternativePosting = {
  id: string;
  companyName: string;
  roleTitle: string;
  sourceUrl: string | null;
  experienceText: string | null;
  primaryTrack: string;
  matchScore: number;
  reason: string;
  experienceMatched: boolean;
  matchedRequired: number;
  required: number;
  matchedPreferred: number;
  preferred: number;
  gaps: string[];
};

export type CareerFragmentKind =
  | "SKILL"
  | "PROJECT"
  | "EXPERIENCE"
  | "EDUCATION"
  | "CREDENTIAL"
  | "ACHIEVEMENT"
  | "LINK";

export type CareerFragment = {
  id: string;
  sourceId: string;
  sourceTitle: string;
  kind: CareerFragmentKind;
  title: string;
  description: string;
  canonicalKey: string | null;
  detail: Record<string, unknown>;
  reviewStatus: "SUGGESTED" | "CONFIRMED" | "REJECTED";
  archivedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type CareerSourceSummary = {
  id: string;
  sourceType: "TEXT" | "FILE" | "URL";
  title: string;
  sourceUrl: string | null;
  status: "QUEUED" | "RUNNING" | "REVIEW_READY" | "CONFIRMED" | "FAILED";
  stage: string;
  stageMessage: string;
  summary: string | null;
  attemptCount: number;
  errorMessage: string | null;
  confirmedCount: number;
  suggestedCount: number;
  archivedAt: string | null;
  createdAt: string;
  completedAt: string | null;
};

export type CareerSourceDetail = {
  source: CareerSourceSummary;
  rawText: string;
  fragments: CareerFragment[];
};

export type CareerFragmentPage = {
  items: CareerFragment[];
  page: number;
  size: number;
  total: number;
};

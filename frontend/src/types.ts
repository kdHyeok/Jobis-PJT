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
  analysisProvider: "LEGACY" | "UNIFIED";
  status:
    | "QUEUED"
    | "RUNNING"
    | "WAITING_FOR_INPUT"
    | "SUCCEEDED"
    | "FAILED"
    | "CANCELLED";
  stage: string;
  stageMessage: string;
  queuePosition: number | null;
  attemptCount: number;
  questionCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  result: {
    evaluation?: {
      verdict:
        | "APPLY_NOW"
        | "STRENGTHEN_THEN_APPLY"
        | "ALTERNATIVE_FIRST"
        | "REVIEW_REQUIRED";
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
    status?: string;
    structuredPosting?: Record<string, unknown>;
    resolution?: Record<string, unknown>;
    postingReview?: V3PostingReview;
    fit?: Record<string, unknown>;
    normalization?: Record<string, unknown>;
    capabilityGraph?: Record<string, unknown>;
    roadmapProposal?: Record<string, unknown>;
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
    answerStatus?: "PROVIDED" | "CONFIRMED_ABSENT" | "SKIPPED";
    answeredAt: string;
    ordinal: number;
  }>;
};

export type V3PostingReviewRequirement = {
  requirementId: string;
  sourceText: string;
  atomicText: string;
  obligation: "REQUIRED" | "PREFERRED" | "INFORMATIONAL";
  category: string;
  confidence: number;
};

export type V3PostingReview = {
  reviewId: string;
  verifiedSnapshotId: string;
  companyName: string | null;
  postingTitle: string | null;
  selectedPositionId: string;
  positionTitle: string;
  selectedExperienceTrack: "NEW_GRADUATE" | "EXPERIENCED" | null;
  experience: {
    kind:
      | "NEW_GRADUATE"
      | "EXPERIENCE_REQUIRED"
      | "RANGE"
      | "NO_RESTRICTION"
      | "NEW_GRADUATE_OR_EXPERIENCED"
      | "UNKNOWN";
    minMonths: number | null;
    maxMonths: number | null;
    experiencedMinMonths: number | null;
  };
  responsibilities: Array<{
    responsibilityId: string;
    sourceText: string;
    atomicText: string;
    confidence: number;
  }>;
  responsibilityRequirements: V3PostingReviewRequirement[];
  requiredRequirements: V3PostingReviewRequirement[];
  preferredRequirements: V3PostingReviewRequirement[];
  informationalRequirements: V3PostingReviewRequirement[];
  originalText: string;
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
  type: "RUN_STARTED" | "STAGE_UPDATED" | "PROGRESS" | "RESULT" | "ERROR";
  runId?: string;
  sequence: number;
  occurredAt?: string;
  stages?: AnalysisStageDefinition[];
  stage?: AnalysisStageUpdate | null;
  progress?: {
    contractVersion: string;
    eventId: string;
    jobId: string;
    sequence: number;
    stage: string;
    status:
      | "PENDING"
      | "RUNNING"
      | "WAITING"
      | "COMPLETED"
      | "SKIPPED"
      | "FAILED"
      | "CANCELLED";
    label: string;
    detail: string | null;
    occurredAt: string;
    elapsedMs: number;
    stageDurationMs?: number | null;
    partialResult?: {
      kind: string;
      title: string;
      summary?: string;
      company?: string | null;
      positions?: Array<{
        positionId: string;
        title: string;
        experienceKind?: string;
        minMonths?: number | null;
        experiencedMinMonths?: number | null;
      }>;
      requiredPreview?: string[];
      preferredPreview?: string[];
      taskPreview?: string[];
      [key: string]: unknown;
    } | null;
    warnings: Array<{ code: string; message: string; severity?: string }>;
  };
  result?: unknown;
  errorCode?: string | null;
  errorMessage?: string | null;
};

export type V3SourceDocument = {
  contractVersion: string;
  sourceDocumentId: string;
  inputType: "TEXT" | "URL" | "IMAGE";
  originalInput: string;
  canonicalUrl: string | null;
  extractionRevision: number;
  rawText: string;
  status: string;
  warnings: Array<{ code: string; message: string; severity?: string }>;
  segments: Array<{
    segmentId: string;
    text: string;
    method: string;
    confidence: number | null;
    warnings: Array<{ code: string; message: string; severity?: string }>;
  }>;
};

export type V3SourceView = {
  id: string;
  postingId: string | null;
  sourceDocument: V3SourceDocument;
  verifiedSnapshotId: string | null;
  verifiedSnapshot: {
    verifiedSnapshotId: string;
    verifiedText: string;
    snapshotHash: string;
  } | null;
};

export type V3ProjectTask = {
  taskKey: string;
  necessity: "REQUIRED" | "RECOMMENDED" | "EXTENSION";
  title: string;
  objective: string;
  acceptanceCriteria: string[];
  capabilityKeys: string[];
  requirementIds: string[];
  dependsOnTaskKeys?: string[];
  progressState?: "NOT_STARTED" | "CLAIMED" | "EVIDENCED" | "VERIFIED";
  evidenceCount?: number;
};

export type V3ProjectSpec = {
  objective: string;
  deliverables: string[];
  verificationCriteria: string[];
  requiredCapabilityKeys: string[];
  preferredCapabilityKeys: string[];
  requiredProvisionalCandidateIds: string[];
  preferredProvisionalCandidateIds: string[];
  domainContext: string;
  tasks?: V3ProjectTask[];
};

export type V3RoadmapNode = {
  nodeId: string;
  nodeKind:
    | "CAPABILITY"
    | "TARGET_PROJECT"
    | "CAREER_GATE"
    | "OPPORTUNITY"
    | "EMPLOYMENT_EVENT"
    | "EXPERIENCE_INTERVAL";
  title: string;
  canonicalKey?: string;
  technologyKey?: string;
  graphNodeVersion?: number;
  verificationMethods?: Array<"EXPLAIN" | "IMPLEMENT" | "TEST" | "DEBUG" | "MEASURE" | "DOCUMENT">;
  objective?: string;
  excludedScope?: string[];
  completionPolicy?: "SELF_CONFIRM" | "ASSESSMENT";
  provisionalCandidateId?: string;
  targetRef?: string;
  sectionKey: string;
  progressState: "NOT_STARTED" | "CLAIMED" | "EVIDENCED" | "VERIFIED";
  careerNodeId?: string | null;
  scopeDefinition?: string;
  level?: number;
  displayRank: number;
  sectionMemberships?: Array<{
    sectionKey: string;
    chapterKey: string;
    chapterTitle: string;
    targetRef: string;
    reason: string;
  }>;
  projectSpec?: V3ProjectSpec;
  gateSpec?: Record<string, unknown>;
  opportunitySpec?: Record<string, unknown>;
  employmentSpec?: Record<string, unknown>;
  experienceIntervalSpec?: Record<string, unknown>;
};

export type V3RoadmapSnapshot = {
  roadmapVersion: number;
  nodes: V3RoadmapNode[];
  relations: Array<{
    relationId: string;
    fromNodeId: string;
    toNodeId: string;
    relationType: string;
    reason: string;
  }>;
};

export type V3RoadmapProposalView = {
  id: string;
  analysisJobId: string | null;
  contractProposalId: string;
  basedOnRoadmapVersion: number;
  proposedRoadmapVersion: number;
  status: "DRAFT" | "APPLIED" | "CANCELLED" | "SUPERSEDED";
  proposal: Record<string, unknown>;
  preview: {
    proposedRoadmapVersion: number;
    snapshot: V3RoadmapSnapshot;
    createdNodeIds: string[];
    reusedNodeIds: string[];
    createdRelationIds: string[];
    removedNodeIds?: string[];
    removedRelationIds?: string[];
  } | null;
  createdAt: string;
  updatedAt: string;
};

export type V3RoadmapVersion = {
  id: string;
  versionNumber: number;
  status: "PUBLISHED" | "SUPERSEDED";
  targetCount: number;
  createdAt: string;
  publishedAt: string | null;
};

export type V3EmploymentRecord = {
  id: string;
  canonicalRoleId: string | null;
  roleFamily: string;
  roleSpecialization: string;
  employer: string;
  roleTitle: string;
  startedOn: string;
  endedOn: string | null;
  evidenceUrl: string;
  description: string;
  evidenceState: "CLAIMED" | "EVIDENCED" | "VERIFIED" | "REJECTED";
  operatorReason: string | null;
  createdAt: string;
  reviewedAt: string | null;
};

export type V3RoadmapWorkspace = {
  currentRoadmap: V3RoadmapSnapshot;
  draftProposal: V3RoadmapProposalView | null;
};

export type V3AtomicAssessmentTurn = {
  id: string;
  ordinal: number;
  method: "EXPLAIN" | "IMPLEMENT" | "TEST" | "DEBUG" | "MEASURE" | "DOCUMENT";
  question: {
    questionId: string;
    prompt: string;
    starterCode?: string | null;
    answerInstructions: string;
    coreCriteria: string[];
    futureExtensions: string[];
  };
  answerText: string | null;
  grade: {
    score?: number;
    passed?: boolean;
    strengths?: string[];
    gaps?: string[];
    feedback?: string;
    scopeViolationDetected?: boolean;
  } | null;
  score: number | null;
  passed: boolean | null;
  createdAt: string;
  answeredAt: string | null;
};

export type V3AtomicAssessment = {
  id: string;
  capabilityKey: string;
  title: string;
  scopeDefinition: string;
  verificationMethods: string[];
  status: "IN_PROGRESS" | "PASSED" | "NEEDS_STUDY" | "ABANDONED" | "REVIEW_REQUESTED";
  requiredQuestionCount: number;
  answeredQuestionCount: number;
  averageScore: number | null;
  targetContext: Record<string, string | null>;
  turns: V3AtomicAssessmentTurn[];
  reviewPending: boolean;
  createdAt: string;
  completedAt: string | null;
};

export type V3AtomicAssessmentReviewItem = {
  id: string;
  sessionId: string;
  userId: string;
  userLabel: string;
  capabilityKey: string;
  title: string;
  averageScore: number | null;
  status: "PENDING" | "APPROVED" | "REJECTED" | "CANCELLED";
  reason: string;
  requestedAt: string;
};

export type V3AtomicMigrationCandidate = {
  id: string;
  atomicCapabilityId: string;
  canonicalKey: string;
  title: string;
  scopeDefinition: string;
  legacyCompetencyId: string;
  legacyTitle: string;
  legacyProgressStatus: string;
  legacyVerifiedLevel: number;
  confidence: number;
  reason: string;
  status: "PENDING_REVIEW" | "CONFIRMED" | "REJECTED" | "SUPERSEDED";
  createdAt: string;
  decidedAt: string | null;
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
  inputType: "CHOICE" | "TEXT";
  options: AnalysisQuestionOption[];
  relatedRequirementIds: string[];
  absenceScope: "NONE" | "GENERAL_EXPERIENCE" | "REQUIREMENTS";
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
  source?: "LEGACY" | "UNIFIED";
  v3NodeId?: string;
  completionPolicy?: "SELF_CONFIRM" | "ASSESSMENT";
  verificationMethods?: string[];
  excludedScope?: string[];
  provisionalCandidateId?: string;
  catalogStatus?: "APPROVED" | "PENDING_REVIEW";
};

export type RoadmapProject = {
  title: string;
  objective: string;
  domainContext: string;
  requiredCompetencyKeys: string[];
  optionalCompetencyKeys: string[];
  deliverables: string[];
  acceptanceCriteria: string[];
  tasks?: V3ProjectTask[];
};

export type RoadmapNode = {
  id: string;
  type: "MILESTONE" | "GATE" | "PROJECT" | "OPPORTUNITY" | "EMPLOYMENT" | "EXPERIENCE";
  title: string;
  subtitle: string | null;
  domain: string;
  stage: string;
  journeyStageRef?: string;
  rank: number;
  optional: boolean;
  postingIds: string[];
  competencies: RoadmapCompetency[];
  project: RoadmapProject | null;
  postingId: string | null;
  status: string;
  careerNodeId: string | null;
  requirementKinds?: Record<string, "REQUIRED" | "PREFERRED">;
  source?: "LEGACY" | "UNIFIED";
  v3NodeId?: string;
  goalMode?: "ACTIVE_APPLICATION" | "REOPENING_PREPARATION" | "REFERENCE_TARGET";
  postingLifecycleStatus?: "ACTIVE" | "EXPIRED" | "CLOSED" | "UNKNOWN";
  applicationDeadline?: string | null;
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
    goalMode?: "ACTIVE_APPLICATION" | "REOPENING_PREPARATION" | "REFERENCE_TARGET";
    lifecycleStatus?: "ACTIVE" | "EXPIRED" | "CLOSED" | "UNKNOWN";
    closesAt?: string | null;
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

export type CareerGoals = {
  currentPostingId: string | null;
  currentCompanyName: string | null;
  currentRoleTitle: string | null;
  finalPostingId: string | null;
  finalCompanyName: string | null;
  finalRoleTitle: string | null;
  finalGoalText: string | null;
};

export type RoadmapVersion = {
  id: string;
  version: number;
  status: "PUBLISHED" | "SUPERSEDED";
  baseVersion: number | null;
  targetCount: number;
  changes: {
    added: string[];
    removed: string[];
    retained: string[];
  };
  createdAt: string;
  publishedAt: string | null;
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
  hasOlderMessages: boolean;
  lastMessageAt: string;
  createdAt: string;
};

export type ConversationPage = {
  items: ConversationSummary[];
  page: number;
  size: number;
  total: number;
};

export type ConversationMessagePage = {
  items: ConversationMessage[];
  hasMore: boolean;
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

export type AgentMode =
  | "AUTO"
  | "CAREER_CHAT"
  | "POSTING_QA"
  | "RESUME_DIAGNOSIS"
  | "POSTING_COMPARE"
  | "RESUME_COMPARE"
  | "INTERVIEW_PREP"
  | "COVER_LETTER"
  | "APPLICATION_PLAN"
  | "JOB_DISCOVERY";

export type AgentContext = {
  mode: AgentMode;
  postingIds: string[];
  careerSourceIds: string[];
};

export type AgentProgressEvent = {
  agentId: string;
  label: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "NEEDS_CONFIRMATION" | "FAILED";
  message: string;
  occurredAt?: string;
};

export type AgentReplySource = {
  sourceType: "POSTING" | "CAREER_SOURCE" | "CAREER_FRAGMENT" | "ROADMAP";
  sourceId: string | null;
  title: string;
  excerpt: string | null;
};

export type AgentPendingConfirmation = {
  question: string;
  reason: string;
  options: string[];
};

export type AgentProposedAction = {
  actionId: string;
  actionType:
    | "NAVIGATE"
    | "ANALYZE_POSTING"
    | "COMPARE"
    | "SAVE_DRAFT"
    | "START_INTERVIEW"
    | "FIND_ALTERNATIVES";
  label: string;
  description: string;
  requiresConsent: boolean;
  payload: Record<string, unknown>;
};

export type AgentActionExecution = {
  actionId: string;
  status: "SUCCEEDED";
  actionType: AgentProposedAction["actionType"];
  resourceType: string;
  resourceId: string | null;
  postingId: string | null;
  analysisJobId: string | null;
  reusedAnalysis: boolean;
  message: string;
  result: Record<string, unknown>;
};

export type AgentArtifact = {
  artifactType:
    | "DIAGNOSIS"
    | "COMPARISON"
    | "INTERVIEW_SET"
    | "COVER_LETTER_DRAFT"
    | "APPLICATION_PLAN"
    | "JOB_DISCOVERY_PLAN";
  title: string;
  summary: string;
  sections: Array<Record<string, unknown>>;
};

export type PlannedAgent = {
  runId: string;
  agentId: string;
  label: string;
  groupIndex: number;
  orderIndex: number;
  reason: string | null;
  status: AgentProgressEvent["status"];
};

export type AgentExecutionPlan = {
  intent: string;
  confidence: number | null;
  agents: PlannedAgent[];
  edges: Array<{ fromRunId: string; toRunId: string }>;
  selectedPostingIds: string[];
  selectedCareerSourceIds: string[];
  pendingConfirmation: AgentPendingConfirmation | null;
  updatedDuringRun: boolean;
};

export type AgentWorkProduct = {
  agentId: string;
  productType:
    | "DIAGNOSIS"
    | "COMPARISON"
    | "INTERVIEW_SET"
    | "COVER_LETTER_DRAFT"
    | "APPLICATION_PLAN"
    | "JOB_RECOMMENDATIONS"
    | "PREFERENCES"
    | "ROADMAP_VIEW"
    | "POSTING_ANALYSIS";
  title: string;
  reply: string | null;
  summary: string;
  findings: string[];
  recommendations: string[];
  followUpQuestions: string[];
  replySources: AgentReplySource[];
  suggestedActions: Array<{ action: string; label: string }>;
  proposedActions: AgentProposedAction[];
  pendingConfirmation: AgentPendingConfirmation | null;
  artifact: AgentArtifact | null;
  data: Record<string, unknown>;
};

export type AgentWarning = {
  code: string;
  message: string;
  agentId: string | null;
  recoverable: boolean;
};

export type AgentChatResult = {
  message?: string;
  intent?: string;
  shouldRequestPosting?: boolean;
  suggestedActions?: Array<{ action: string; label: string }>;
  replySources?: AgentReplySource[];
  progress?: AgentProgressEvent[];
  proposedActions?: AgentProposedAction[];
  actionExecutions?: Record<string, AgentActionExecution>;
  pendingConfirmation?: AgentPendingConfirmation | null;
  artifact?: AgentArtifact | null;
  plan?: AgentExecutionPlan | null;
  confidence?: number | null;
  detailedStatus?: string | null;
  workProducts?: AgentWorkProduct[];
  warnings?: AgentWarning[];
  replyAttributions?: Array<{ agentId: string; channel: string; text: string }>;
};

export type ChatReplyJob = {
  id: string;
  conversationId: string;
  triggerMessageId: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  stage: string;
  stageMessage: string;
  attemptCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  requestContext: AgentContext;
  progressEvents: AgentProgressEvent[];
  result: AgentChatResult;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
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

export type ActivityJob = {
  id: string;
  type: "CHAT" | "VERIFICATION" | "ANALYSIS" | "CAREER";
  title: string;
  message: string;
  status: string;
  destinationType: "CONVERSATION" | "ROADMAP_NODE" | "POSTING" | "CAREER_SOURCE";
  destinationId: string;
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

export type CompetencyLearning = {
  title: string;
  summary: string;
  scopeReminder: string;
  targetContext: string | null;
  modules: Array<{
    title: string;
    objective: string;
    concepts: string[];
    example: string | null;
    practice: string;
    completionCriteria: string[];
  }>;
  recommendedResources: string[];
  assessmentReadiness: string[];
};

export type RepositoryConnection = {
  id: string;
  provider: "GITHUB" | "GITLAB";
  providerBaseUrl: string;
  accountName: string | null;
  status: "ACTIVE" | "REAUTH_REQUIRED" | "REVOKED";
  scopes: string[];
  createdAt: string;
  updatedAt: string;
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
    sourcePlatform: string | null;
    experienceText: string | null;
    primaryTrack: string;
    minimumExperienceMonths: number;
    maximumExperienceMonths: number | null;
    lastSeenAt: string;
    closesAt: string | null;
    requirementCount: number;
    observationCount: number;
  };
  right: {
    id: string;
    companyName: string;
    roleTitle: string;
    sourceUrl: string | null;
    lifecycleStatus: string;
    sourcePlatform: string | null;
    experienceText: string | null;
    primaryTrack: string;
    minimumExperienceMonths: number;
    maximumExperienceMonths: number | null;
    lastSeenAt: string;
    closesAt: string | null;
    requirementCount: number;
    observationCount: number;
  };
  createdAt: string;
};

export type OperatorAuditItem = {
  id: string;
  actionKind: "MERGE" | "SEPARATE" | "HOLD" | string;
  targetType: string;
  targetId: string;
  targetLabel: string | null;
  operatorName: string;
  reason: string | null;
  rolledBackAt: string | null;
  createdAt: string;
  rollbackable: boolean;
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
  status: "QUEUED" | "RUNNING" | "REVIEW_READY" | "CONFIRMED" | "FAILED" | "CANCELLED";
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

export type CareerFragmentMergePreview = {
  compatible: boolean;
  reason: string;
  kind: CareerFragmentKind | null;
  canonicalKey: string | null;
  fragmentCount: number;
};

export type CareerFragmentMergeResult = {
  fragment: CareerFragment;
  undoId: string;
};

export type CapabilityReviewCandidate = {
  id: string;
  analysisJobId: string;
  requirementId: string;
  candidateId: string;
  decisionKind: string;
  displayName: string;
  proposedKind: string | null;
  scopeDefinition: string | null;
  aliases: string;
  evidenceIds: string;
  matchCandidates: string;
  confidence: number | null;
  reason: string;
  status: "PENDING" | "ON_HOLD" | "APPROVED_STAGED" | "LINKED" | "NEEDS_SPLIT" | "REJECTED" | "PUBLISHED";
  selectedCanonicalKey: string | null;
  operatorReason: string | null;
  createdAt: string;
  decidedAt: string | null;
};

export type CapabilityGraphRelease = {
  id: string;
  graphVersion: string;
  publishedCandidates: number;
};

export type RoleReviewCandidate = {
  id: string;
  analysisJobId: string;
  positionId: string;
  sourceTitle: string;
  proposedFamily: string;
  proposedSpecialization: string;
  evidenceIds: string;
  confidence: number;
  status: "PENDING" | "ON_HOLD" | "APPROVED_STAGED" | "LINKED" | "REJECTED";
  selectedCanonicalRoleId: string | null;
  operatorReason: string | null;
  createdAt: string;
  decidedAt: string | null;
};

export type OperatorEmploymentReview = {
  id: string;
  userId: string;
  roleFamily: string;
  roleSpecialization: string;
  employer: string;
  roleTitle: string;
  startedOn: string;
  endedOn: string | null;
  evidenceUrl: string;
  description: string;
};

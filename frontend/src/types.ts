export type User = {
  id: string;
  email: string;
  displayName: string;
  status: string;
  createdAt: string;
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
    };
  } | null;
  changeSetId: string | null;
  changeSetStatus: string | null;
  proposal: {
    baseGraphVersion: number;
    nodes: ProposedNode[];
    edges: ProposedEdge[];
    requirements: ProposedRequirement[];
  } | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  pendingQuestion: AnalysisQuestion | null;
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

export type ProposedNode = {
  ref: string;
  action: "CREATE" | "REUSE";
  existingNodeId: string | null;
  canonicalKey: string;
  title: string;
  subtitle: string | null;
  domain: string;
  kind: string;
  scopeDefinition: string | null;
  level: number;
  detail: Record<string, unknown>;
};

export type ProposedEdge = {
  fromRef: string;
  toRef: string;
  edgeKind: string;
};

export type ProposedRequirement = {
  nodeRef: string;
  kind: "REQUIRED" | "PREFERRED";
  sourceText: string | null;
  confidence: number | null;
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

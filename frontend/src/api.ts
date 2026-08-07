import type {
  AnalysisJob,
  ActivityJob,
  AgentActionExecution,
  AgentContext,
  AlternativePosting,
  CareerFragment,
  CareerFragmentMergePreview,
  CareerFragmentMergeResult,
  CareerGoals,
  CapabilityReviewCandidate,
  CapabilityGraphRelease,
  CareerFragmentPage,
  CareerMap,
  CareerSourceDetail,
  CareerSourceSummary,
  ChatReplyJob,
  CompetencyAssessment,
  CompetencyLearning,
  Conversation,
  ConversationPage,
  ConversationMessagePage,
  ConversationSummary,
  Evidence,
  GoalProfile,
  NotificationItem,
  OperatorAuditItem,
  OperatorEmploymentReview,
  Posting,
  PostingDetail,
  PostingPage,
  RoadmapWorkspace,
  RoadmapVersion,
  RepositoryConnection,
  RoleReviewCandidate,
  SendMessageResult,
  User,
  PostingDuplicateCandidate,
  AssessmentReviewItem,
  V3RoadmapSnapshot,
  V3RoadmapWorkspace,
  V3EmploymentRecord,
  V3RoadmapProposalView,
  V3RoadmapVersion,
  V3AtomicAssessment,
  V3AtomicAssessmentReviewItem,
  V3AtomicMigrationCandidate,
  V3SourceView,
} from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

let csrfToken: string | null = null;
let csrfHeader = "X-XSRF-TOKEN";
let mutationQueue: Promise<void> = Promise.resolve();
let refreshPromise: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        csrfToken = null;
        await ensureCsrf();
        const headers = new Headers({ "Content-Type": "application/json" });
        if (csrfToken) headers.set(csrfHeader, csrfToken);
        const response = await fetch(`${API_BASE}/api/auth/refresh`, {
          method: "POST",
          credentials: "include",
          headers,
        });
        csrfToken = null;
        return response.ok;
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

async function ensureCsrf(): Promise<void> {
  if (csrfToken) return;
  const response = await fetch(`${API_BASE}/api/auth/csrf`, {
    credentials: "include",
  });
  if (!response.ok) throw new Error("보안 토큰을 준비하지 못했습니다.");
  const payload = (await response.json()) as {
    headerName: string;
    token: string;
  };
  csrfHeader = payload.headerName;
  csrfToken = payload.token;
}

async function executeRequest<T>(
  path: string,
  options: RequestInit = {},
  csrfRetry = true,
  authRetry = true,
): Promise<T> {
  const method = options.method?.toUpperCase() ?? "GET";
  const mutating = !["GET", "HEAD", "OPTIONS"].includes(method);
  if (mutating) {
    // Spring Security rotates the cookie-backed token after a successful
    // mutation. Always acquire the token held by the current cookie.
    csrfToken = null;
    await ensureCsrf();
  }

  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (csrfToken && mutating) {
    headers.set(csrfHeader, csrfToken);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  if (mutating) csrfToken = null;
  if (response.status === 204) return undefined as T;
  const responseText = await response.text();
  let body: unknown = null;
  if (responseText) {
    try {
      body = JSON.parse(responseText) as unknown;
    } catch {
      body = { message: responseText.slice(0, 500) };
    }
  }
  if (response.status === 403 && csrfRetry && mutating) {
    return executeRequest<T>(path, options, false, authRetry);
  }
  if (
    response.status === 401 &&
    authRetry &&
    !["/api/auth/login", "/api/auth/register", "/api/auth/refresh"].includes(path) &&
    await refreshSession()
  ) {
    return executeRequest<T>(path, options, csrfRetry, false);
  }
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent("jobiss:unauthorized"));
    }
    const error = body as { message?: string; detail?: { message?: string } };
    throw new Error(
      error?.message ?? error?.detail?.message ?? "요청을 처리하지 못했습니다.",
    );
  }
  return body as T;
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = options.method?.toUpperCase() ?? "GET";
  if (["GET", "HEAD", "OPTIONS"].includes(method)) {
    return executeRequest<T>(path, options);
  }

  const operation = mutationQueue.then(() => executeRequest<T>(path, options));
  mutationQueue = operation.then(
    () => undefined,
    () => undefined,
  );
  return operation;
}

export const api = {
  activityJobs(): Promise<ActivityJob[]> {
    return request("/api/activity/jobs");
  },
  async me(): Promise<User> {
    const payload = await request<{ user: User }>("/api/auth/me");
    return payload.user;
  },

  async login(email: string, password: string, rememberMe = false): Promise<User> {
    const payload = await request<{ user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, rememberMe }),
    });
    return payload.user;
  },

  async register(
    email: string,
    password: string,
    displayName: string,
  ): Promise<User> {
    const payload = await request<{ user: User }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        displayName,
        termsAccepted: true,
        privacyAccepted: true,
        policyVersion: "2026-08-04",
      }),
    });
    return payload.user;
  },

  requestPasswordReset(email: string): Promise<{ message: string }> {
    return request("/api/auth/password-reset/request", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },

  confirmPasswordReset(token: string, newPassword: string): Promise<void> {
    return request("/api/auth/password-reset/confirm", {
      method: "POST",
      body: JSON.stringify({ token, newPassword }),
    });
  },

  logout(): Promise<void> {
    return request("/api/auth/logout", { method: "POST" });
  },

  updateAccountProfile(email: string, displayName: string): Promise<User> {
    return request("/api/account/profile", {
      method: "PATCH",
      body: JSON.stringify({ email, displayName }),
    });
  },

  changeAccountPassword(currentPassword: string, newPassword: string): Promise<void> {
    return request("/api/account/password", {
      method: "POST",
      body: JSON.stringify({ currentPassword, newPassword }),
    });
  },

  exportAccountData(): Promise<Record<string, unknown>> {
    return request("/api/account/export");
  },

  deleteAccount(password: string): Promise<{
    requestId: string;
    status: string;
    requestedAt: string;
    purgeAfter: string;
  }> {
    return request("/api/account", {
      method: "DELETE",
      body: JSON.stringify({ password }),
    });
  },

  goalProfile(): Promise<GoalProfile> {
    return request("/api/profile/goals");
  },

  updateGoalProfile(
    currentGoalPostingId: string | null,
    finalGoalText: string | null,
  ): Promise<GoalProfile> {
    return request("/api/profile/goals", {
      method: "PUT",
      body: JSON.stringify({ currentGoalPostingId, finalGoalText }),
    });
  },

  careerMap(): Promise<CareerMap> {
    return request("/api/career-map");
  },

  selfConfirm(nodeId: string): Promise<void> {
    return request(`/api/career-map/nodes/${nodeId}/self-confirm`, {
      method: "POST",
    });
  },

  conversations(): Promise<ConversationSummary[]> {
    return request("/api/conversations");
  },

  searchConversations(options: {
    query?: string;
    status?: "ACTIVE" | "ARCHIVED" | "ALL";
    page?: number;
    size?: number;
  } = {}): Promise<ConversationPage> {
    const params = new URLSearchParams();
    Object.entries(options).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    return request(`/api/conversations/search?${params}`);
  },

  createConversation(): Promise<Conversation> {
    return request("/api/conversations", { method: "POST" });
  },

  conversation(id: string): Promise<Conversation> {
    return request(`/api/conversations/${id}`);
  },

  conversationMessagesBefore(
    id: string,
    beforeCreatedAt: string,
    beforeId: string,
    limit = 100,
  ): Promise<ConversationMessagePage> {
    const params = new URLSearchParams({
      beforeCreatedAt,
      beforeId,
      limit: String(limit),
    });
    return request(`/api/conversations/${id}/messages?${params}`);
  },

  renameConversation(id: string, title: string): Promise<ConversationSummary> {
    return request(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
  },

  archiveConversation(id: string): Promise<void> {
    return request(`/api/conversations/${id}/archive`, { method: "POST" });
  },

  restoreConversation(id: string): Promise<void> {
    return request(`/api/conversations/${id}/restore`, { method: "POST" });
  },

  deleteConversation(id: string): Promise<void> {
    return request(`/api/conversations/${id}`, { method: "DELETE" });
  },

  sendMessage(
    conversationId: string,
    content: string,
    posting?: {
      sourceType: "TEXT" | "URL";
      sourceUrl: string | null;
      rawText: string;
    },
    context?: AgentContext,
  ): Promise<SendMessageResult> {
    return request(`/api/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({
        clientMessageId: crypto.randomUUID(),
        content,
        posting: posting ?? null,
        context: context ?? null,
      }),
    });
  },

  chatReplyJobs(conversationId: string): Promise<ChatReplyJob[]> {
    return request(`/api/chat-reply-jobs/conversation/${conversationId}`);
  },

  chatReplyJob(id: string): Promise<ChatReplyJob> {
    return request(`/api/chat-reply-jobs/${id}`);
  },

  retryChatReply(id: string): Promise<void> {
    return request(`/api/chat-reply-jobs/${id}/retry`, { method: "POST" });
  },

  cancelChatReply(id: string): Promise<void> {
    return request(`/api/chat-reply-jobs/${id}/cancel`, { method: "POST" });
  },

  executeChatAction(
    jobId: string,
    actionId: string,
  ): Promise<AgentActionExecution> {
    return request(
      `/api/chat-reply-jobs/${jobId}/actions/${encodeURIComponent(actionId)}/execute`,
      { method: "POST" },
    );
  },

  postings(): Promise<Posting[]> {
    return request("/api/job-postings");
  },

  createPosting(
    sourceType: "TEXT" | "URL",
    sourceUrl: string | null,
    rawText: string,
    conversationId: string | null = null,
  ) {
    return request<{
      postingId: string;
      analysisJobId: string;
      status: string;
      reusedAnalysis: boolean;
      reuseMessage: string | null;
    }>(
      "/api/job-postings",
      {
        method: "POST",
        body: JSON.stringify({ sourceType, sourceUrl, rawText, conversationId }),
      },
    );
  },

  importPostingUrl(sourceUrl: string): Promise<{
    finalUrl: string;
    rawText: string;
    warnings: Array<{ code: string; message: string }>;
    collector: "AGENT";
  }> {
    return request("/api/job-postings/import-url", {
      method: "POST",
      body: JSON.stringify({ sourceUrl }),
    });
  },

  acquireV3Source(payload: {
    inputType: "TEXT" | "URL" | "IMAGE";
    entryPoint: "CHAT" | "POSTINGS_PAGE" | "INTERNAL";
    extractionRevision: number;
    postingId?: string | null;
    text?: string | null;
    url?: string | null;
    imageBase64?: string | null;
    imageMediaType?: string | null;
    originalFilename?: string | null;
  }): Promise<V3SourceView> {
    return request("/api/v3/sources", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  v3Source(sourceId: string): Promise<V3SourceView> {
    return request(`/api/v3/sources/${sourceId}`);
  },

  verifyV3Source(
    sourceId: string,
    payload: {
      verifiedText: string;
      corrections: Array<{
        field: string;
        before: string;
        after: string;
        reason: "OCR_CORRECTION" | "STRUCTURE_CORRECTION" | "MISSING_TEXT" | "DUPLICATE_TEXT" | "OTHER";
      }>;
      verifiedBy: "USER" | "OPERATOR";
      previousSnapshotId?: string | null;
    },
  ): Promise<V3SourceView> {
    return request(`/api/v3/sources/${sourceId}/verify`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  startV3Analysis(sourceId: string, conversationId: string | null = null) {
    return request<{
      postingId: string;
      analysisJobId: string;
      sourceId: string;
      verifiedSnapshotId: string;
      status: string;
      reusedAnalysis: boolean;
      reuseMessage: string | null;
    }>(`/api/v3/sources/${sourceId}/analyses`, {
      method: "POST",
      body: JSON.stringify({ conversationId }),
    });
  },

  analysisJob(id: string): Promise<AnalysisJob> {
    return request(`/api/analysis-jobs/${id}`);
  },

  analysisJobs(status = "", limit = 30): Promise<AnalysisJob[]> {
    const params = new URLSearchParams({ status, limit: String(limit) });
    return request(`/api/analysis-jobs?${params}`);
  },

  retryAnalysis(id: string): Promise<void> {
    return request(`/api/analysis-jobs/${id}/retry`, { method: "POST" });
  },

  cancelAnalysis(id: string): Promise<void> {
    return request(`/api/analysis-jobs/${id}/cancel`, { method: "POST" });
  },

  answerAnalysisQuestion(
    jobId: string,
    questionId: string,
    value: string,
    answerStatus: "PROVIDED" | "CONFIRMED_ABSENT" | "SKIPPED" = "PROVIDED",
  ): Promise<void> {
    return request(
      `/api/analysis-jobs/${jobId}/questions/${questionId}/answer`,
      {
        method: "POST",
        body: JSON.stringify({ value, answerStatus }),
      },
    );
  },

  approveAnalysis(id: string) {
    return request<{
      postingId: string;
      draftId: string;
      draftVersion: number;
      changes: { added: string[]; removed: string[]; retained: string[] };
    }>(
      `/api/analysis-jobs/${id}/approve`,
      { method: "POST" },
    );
  },

  roadmap(): Promise<RoadmapWorkspace> {
    return request("/api/roadmap");
  },

  careerGoals(): Promise<CareerGoals> {
    return request("/api/career-goals");
  },

  updateCareerGoals(payload: {
    currentPostingId: string | null;
    finalPostingId: string | null;
    finalGoalText: string | null;
  }): Promise<CareerGoals> {
    return request("/api/career-goals", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  v3Roadmap(): Promise<V3RoadmapWorkspace> {
    return request("/api/v3/roadmap");
  },

  previewV3Roadmap(proposalId: string): Promise<{
    proposalId: string;
    status: string;
    preview: {
      proposedRoadmapVersion: number;
      snapshot: V3RoadmapSnapshot;
      createdNodeIds: string[];
      reusedNodeIds: string[];
      createdRelationIds: string[];
      removedNodeIds?: string[];
      removedRelationIds?: string[];
    };
  }> {
    return request(`/api/v3/roadmap/proposals/${proposalId}/preview`, {
      method: "POST",
    });
  },

  applyV3Roadmap(proposalId: string, expectedRoadmapVersion: number): Promise<{
    proposalId: string;
    publicationId: string;
    roadmapVersion: number;
    status: string;
    roadmap: V3RoadmapSnapshot;
  }> {
    return request(`/api/v3/roadmap/proposals/${proposalId}/apply`, {
      method: "POST",
      body: JSON.stringify({ expectedRoadmapVersion }),
    });
  },

  cancelV3Roadmap(proposalId: string): Promise<{
    proposalId: string;
    status: string;
    currentRoadmap: V3RoadmapSnapshot;
  }> {
    return request(`/api/v3/roadmap/proposals/${proposalId}/cancel`, {
      method: "POST",
    });
  },

  createV3TargetRemovalDraft(postingId: string): Promise<V3RoadmapProposalView> {
    return request(`/api/v3/roadmap/targets/${encodeURIComponent(postingId)}/remove-draft`, {
      method: "POST",
    });
  },

  createV3ResetDraft(): Promise<V3RoadmapProposalView> {
    return request("/api/v3/roadmap/reset-draft", { method: "POST" });
  },

  v3RoadmapVersions(): Promise<V3RoadmapVersion[]> {
    return request("/api/v3/roadmap/versions");
  },

  restoreV3RoadmapVersion(versionId: string): Promise<{
    proposalId: string | null;
    publicationId: string;
    roadmapVersion: number;
    status: string;
    roadmap: V3RoadmapSnapshot;
  }> {
    return request(`/api/v3/roadmap/versions/${encodeURIComponent(versionId)}/restore`, {
      method: "POST",
    });
  },

  updateV3ProjectTaskState(
    projectNodeId: string,
    taskKey: string,
    state: "NOT_STARTED" | "CLAIMED",
  ) {
    return request(`/api/v3/roadmap/projects/${encodeURIComponent(projectNodeId)}/tasks/${encodeURIComponent(taskKey)}/state`, {
      method: "POST",
      body: JSON.stringify({ state }),
    });
  },

  addV3ProjectTaskEvidence(
    projectNodeId: string,
    taskKey: string,
    payload: { title: string; evidenceUrl: string; description: string },
  ) {
    return request(`/api/v3/roadmap/projects/${encodeURIComponent(projectNodeId)}/tasks/${encodeURIComponent(taskKey)}/evidence`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  v3EmploymentRecords(): Promise<V3EmploymentRecord[]> {
    return request("/api/v3/employment");
  },

  submitV3Employment(payload: {
    canonicalRoleId: string | null;
    roleFamily: string;
    roleSpecialization: string;
    employer: string;
    roleTitle: string;
    startedOn: string;
    endedOn: string | null;
    evidenceUrl: string;
    description: string;
  }): Promise<V3EmploymentRecord> {
    return request("/api/v3/employment", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  latestV3AtomicAssessment(canonicalKey: string): Promise<V3AtomicAssessment | null> {
    return request(`/api/v3/capabilities/${encodeURIComponent(canonicalKey)}/assessment`);
  },

  startV3AtomicAssessment(
    canonicalKey: string,
    target: Record<string, string | null>,
  ): Promise<V3AtomicAssessment> {
    return request(`/api/v3/capabilities/${encodeURIComponent(canonicalKey)}/assessment`, {
      method: "POST",
      body: JSON.stringify(target),
    });
  },

  selfConfirmV3AtomicCapability(canonicalKey: string): Promise<{
    canonicalKey: string;
    progressState: "VERIFIED";
    completionPolicy: "SELF_CONFIRM";
  }> {
    return request(`/api/v3/capabilities/${encodeURIComponent(canonicalKey)}/self-confirm`, {
      method: "POST",
    });
  },

  answerV3AtomicAssessment(sessionId: string, answer: string): Promise<V3AtomicAssessment> {
    return request(`/api/v3/assessments/${sessionId}/answers`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    });
  },

  abandonV3AtomicAssessment(sessionId: string): Promise<V3AtomicAssessment> {
    return request(`/api/v3/assessments/${sessionId}/abandon`, { method: "POST" });
  },

  reviewV3AtomicAssessment(sessionId: string, reason: string): Promise<V3AtomicAssessment> {
    return request(`/api/v3/assessments/${sessionId}/review`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  operatorV3AtomicAssessmentReviews(status = "PENDING"): Promise<V3AtomicAssessmentReviewItem[]> {
    return request(`/api/operator/atomic-assessment-reviews?status=${encodeURIComponent(status)}`);
  },

  operatorV3AtomicAssessmentReview(sessionId: string): Promise<V3AtomicAssessment> {
    return request(`/api/operator/atomic-assessment-reviews/${sessionId}`);
  },

  resolveV3AtomicAssessmentReview(
    sessionId: string,
    action: "APPROVE" | "REJECT",
    comment: string,
  ): Promise<void> {
    return request(`/api/operator/atomic-assessment-reviews/${sessionId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action, comment }),
    });
  },

  v3AtomicMigrationCandidates(canonicalKey: string): Promise<V3AtomicMigrationCandidate[]> {
    return request(`/api/v3/capability-migrations?canonicalKey=${encodeURIComponent(canonicalKey)}`);
  },

  resolveV3AtomicMigration(
    candidateId: string,
    action: "CONFIRM" | "REJECT",
  ): Promise<V3AtomicMigrationCandidate> {
    return request(`/api/v3/capability-migrations/${candidateId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });
  },

  roadmapVersions(): Promise<RoadmapVersion[]> {
    return request("/api/roadmap/versions");
  },

  restoreRoadmapVersion(id: string): Promise<{
    draftId: string;
    draftVersion: number;
    changes: { added: string[]; removed: string[]; retained: string[] };
  }> {
    return request(`/api/roadmap/versions/${id}/restore`, { method: "POST" });
  },

  regenerateRoadmap(): Promise<{
    draftId: string;
    draftVersion: number;
    changes: { added: string[]; removed: string[]; retained: string[] };
  }> {
    return request("/api/roadmap/draft", { method: "POST" });
  },

  applyRoadmapDraft(draftId: string, expectedVersion: number): Promise<{
    roadmapVersionId: string;
    graphVersion: number;
  }> {
    return request("/api/roadmap/draft/apply", {
      method: "POST",
      body: JSON.stringify({ draftId, expectedVersion }),
    });
  },

  discardRoadmapDraft(draftId: string, expectedVersion: number): Promise<{
    draftId: string;
    draftVersion: number;
  }> {
    return request("/api/roadmap/draft/discard", {
      method: "POST",
      body: JSON.stringify({ draftId, expectedVersion }),
    });
  },

  removeRoadmapTarget(postingId: string) {
    return request(`/api/roadmap/targets/${postingId}`, { method: "DELETE" });
  },

  resetRoadmapTargets() {
    return request("/api/roadmap/reset", { method: "POST" });
  },

  rejectAnalysis(id: string): Promise<void> {
    return request(`/api/analysis-jobs/${id}/reject`, { method: "POST" });
  },

  notifications(
    unreadOnly = false,
    limit = 30,
    beforeCreatedAt?: string,
    beforeId?: string,
    category = "ALL",
  ): Promise<{
    items: NotificationItem[];
    unreadCount: number;
    hasMore: boolean;
  }> {
    const params = new URLSearchParams({
      unreadOnly: String(unreadOnly),
      limit: String(limit),
      category,
    });
    if (beforeCreatedAt && beforeId) {
      params.set("beforeCreatedAt", beforeCreatedAt);
      params.set("beforeId", beforeId);
    }
    return request(`/api/notifications?${params}`);
  },

  readNotification(id: string): Promise<void> {
    return request(`/api/notifications/${id}/read`, { method: "POST" });
  },

  readAllNotifications(): Promise<void> {
    return request("/api/notifications/read-all", { method: "POST" });
  },

  deleteNotification(id: string): Promise<void> {
    return request(`/api/notifications/${id}`, { method: "DELETE" });
  },

  deleteReadNotifications(): Promise<void> {
    return request("/api/notifications/read", { method: "DELETE" });
  },

  searchPostings(options: {
    query?: string;
    status?: string;
    sort?: string;
    direction?: string;
    page?: number;
    size?: number;
    archived?: boolean;
  }): Promise<PostingPage> {
    const params = new URLSearchParams();
    Object.entries(options).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    return request(`/api/job-postings/search?${params}`);
  },

  posting(id: string): Promise<PostingDetail> {
    return request(`/api/job-postings/${id}`);
  },

  updatePosting(id: string, sourceUrl: string | null, rawText: string) {
    return request<{
      postingId: string;
      analysisJobId: string;
      status: string;
      reusedAnalysis: boolean;
      reuseMessage: string | null;
    }>(
      `/api/job-postings/${id}`,
      {
        method: "PATCH",
        body: JSON.stringify({ sourceUrl, rawText }),
      },
    );
  },

  archivePosting(id: string): Promise<void> {
    return request(`/api/job-postings/${id}/archive`, { method: "POST" });
  },

  restorePosting(id: string): Promise<void> {
    return request(`/api/job-postings/${id}/restore`, { method: "POST" });
  },

  deletePosting(id: string): Promise<void> {
    return request(`/api/job-postings/${id}`, { method: "DELETE" });
  },

  evidence(nodeId: string): Promise<Evidence[]> {
    return request(`/api/career-map/nodes/${nodeId}/evidence`);
  },

  submitEvidence(
    nodeId: string,
    payload: {
      evidenceType: string;
      title: string;
      sourceUrl: string | null;
      content: Record<string, unknown>;
    },
  ): Promise<Evidence> {
    return request(`/api/career-map/nodes/${nodeId}/evidence`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  retryEvidence(id: string): Promise<void> {
    return request(`/api/evidence/${id}/retry`, { method: "POST" });
  },

  latestAssessment(nodeId: string): Promise<CompetencyAssessment | undefined> {
    return request(`/api/career-map/nodes/${nodeId}/assessment`);
  },

  startAssessment(
    nodeId: string,
    targetPostingId: string | null,
  ): Promise<CompetencyAssessment> {
    return request(`/api/career-map/nodes/${nodeId}/assessment`, {
      method: "POST",
      body: JSON.stringify({ targetPostingId }),
    });
  },

  answerAssessment(
    sessionId: string,
    answer: string,
  ): Promise<CompetencyAssessment> {
    return request(`/api/competency-assessments/${sessionId}/answers`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    });
  },

  abandonAssessment(sessionId: string): Promise<CompetencyAssessment> {
    return request(`/api/competency-assessments/${sessionId}/abandon`, {
      method: "POST",
    });
  },

  requestAssessmentReview(
    sessionId: string,
    reason: string,
  ): Promise<CompetencyAssessment> {
    return request(`/api/competency-assessments/${sessionId}/review`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  latestLearning(
    nodeId: string,
    targetPostingId: string | null,
  ): Promise<CompetencyLearning | undefined> {
    const query = targetPostingId
      ? `?targetPostingId=${encodeURIComponent(targetPostingId)}`
      : "";
    return request(`/api/career-map/nodes/${nodeId}/learning${query}`);
  },

  generateLearning(
    nodeId: string,
    targetPostingId: string | null,
    refresh = false,
  ): Promise<CompetencyLearning> {
    return request(`/api/career-map/nodes/${nodeId}/learning`, {
      method: "POST",
      body: JSON.stringify({ targetPostingId, refresh }),
    });
  },

  repositoryConnections(): Promise<RepositoryConnection[]> {
    return request("/api/repository-connections");
  },

  startRepositoryConnection(provider: "GITHUB" | "GITLAB") {
    return request<{ provider: string; authorizationUrl: string; expiresAt: string }>(
      `/api/repository-connections/${provider.toLowerCase()}/start`,
      { method: "POST" },
    );
  },

  completeRepositoryConnection(
    provider: "GITHUB" | "GITLAB",
    payload: { state: string; code: string | null; installationId: string | null },
  ): Promise<RepositoryConnection> {
    return request(
      `/api/repository-connections/${provider.toLowerCase()}/complete`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  disconnectRepository(connectionId: string): Promise<void> {
    return request(`/api/repository-connections/${connectionId}`, {
      method: "DELETE",
    });
  },

  operatorPostingDuplicates(status = "OPEN"): Promise<PostingDuplicateCandidate[]> {
    return request(`/api/operator/posting-duplicates?status=${encodeURIComponent(status)}`);
  },

  operatorCapabilityReviews(status = "PENDING"): Promise<CapabilityReviewCandidate[]> {
    return request(`/api/operator/capability-reviews?status=${encodeURIComponent(status)}`);
  },

  operatorRoleReviews(status = "PENDING"): Promise<RoleReviewCandidate[]> {
    return request(`/api/operator/role-reviews?status=${encodeURIComponent(status)}`);
  },

  resolveOperatorRoleReview(
    candidateId: string,
    payload: {
      action: "APPROVE_NEW" | "LINK_EXISTING" | "REJECT" | "HOLD";
      canonicalRoleId: string | null;
      reason: string;
    },
  ): Promise<void> {
    return request(`/api/operator/role-reviews/${candidateId}/resolve`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  publishOperatorRoleCatalog(notes: string): Promise<{
    id: string;
    versionNumber: number;
    publishedCount: number;
  }> {
    return request("/api/operator/role-reviews/releases", {
      method: "POST",
      body: JSON.stringify({ notes }),
    });
  },

  operatorEmploymentReviews(): Promise<OperatorEmploymentReview[]> {
    return request("/api/operator/employment-reviews");
  },

  resolveOperatorEmploymentReview(
    id: string,
    payload: { action: "VERIFIED" | "REJECTED"; reason: string },
  ): Promise<void> {
    return request(`/api/operator/employment-reviews/${encodeURIComponent(id)}/resolve`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  resolveOperatorCapabilityReview(
    candidateId: string,
    payload: { action: "APPROVE_NEW" | "LINK_EXISTING" | "SPLIT" | "REJECT" | "HOLD"; canonicalKey: string | null; reason: string },
  ): Promise<void> {
    return request(`/api/operator/capability-reviews/${candidateId}/resolve`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  publishCapabilityGraphRelease(graphVersion: string, notes: string): Promise<CapabilityGraphRelease> {
    return request("/api/operator/capability-reviews/releases", {
      method: "POST",
      body: JSON.stringify({ graphVersion, notes }),
    });
  },

  resolvePostingDuplicate(
    candidateId: string,
    action: "MERGE" | "SEPARATE" | "HOLD",
    canonicalPostingId: string | null,
    reason: string,
  ): Promise<void> {
    return request(`/api/operator/posting-duplicates/${candidateId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action, canonicalPostingId, reason }),
    });
  },

  operatorPostingAudit(limit = 100): Promise<OperatorAuditItem[]> {
    return request(`/api/operator/posting-duplicates/audit?limit=${limit}`);
  },

  rollbackOperatorAction(auditId: string, reason: string): Promise<void> {
    return request(`/api/operator/posting-duplicates/audit/${auditId}/rollback`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  operatorAssessmentReviews(status = "REQUESTED"): Promise<AssessmentReviewItem[]> {
    return request(`/api/operator/assessment-reviews?status=${encodeURIComponent(status)}`);
  },

  operatorAssessmentReview(sessionId: string): Promise<CompetencyAssessment> {
    return request(`/api/operator/assessment-reviews/${sessionId}`);
  },

  resolveAssessmentReview(
    sessionId: string,
    action: "APPROVE" | "REJECT",
    comment: string,
  ): Promise<void> {
    return request(`/api/operator/assessment-reviews/${sessionId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action, comment }),
    });
  },

  alternativePostings(
    postingId: string,
    limit = 5,
  ): Promise<AlternativePosting[]> {
    return request(`/api/job-postings/${postingId}/alternatives?limit=${limit}`);
  },

  careerSources(archived = false): Promise<CareerSourceSummary[]> {
    return request(`/api/career-sources?archived=${archived}`);
  },

  careerSource(id: string): Promise<CareerSourceDetail> {
    return request(`/api/career-sources/${id}`);
  },

  createCareerSource(payload: {
    sourceType: "TEXT" | "FILE" | "URL";
    title: string;
    sourceUrl: string | null;
    rawText: string;
  }): Promise<CareerSourceDetail> {
    return request("/api/career-sources", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  uploadCareerSource(file: File, title: string): Promise<CareerSourceDetail> {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("title", title);
    return request("/api/career-sources/upload", {
      method: "POST",
      body: form,
    });
  },

  retryCareerSource(id: string): Promise<void> {
    return request(`/api/career-sources/${id}/retry`, { method: "POST" });
  },

  cancelCareerSource(id: string): Promise<void> {
    return request(`/api/career-sources/${id}/cancel`, { method: "POST" });
  },

  confirmCareerSource(id: string, fragmentIds: string[]): Promise<void> {
    return request(`/api/career-sources/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ fragmentIds }),
    });
  },

  addCareerSourceFragment(
    id: string,
    payload: {
      kind: CareerFragment["kind"];
      title: string;
      description: string;
      detail: Record<string, unknown>;
    },
  ): Promise<CareerFragment> {
    return request(`/api/career-sources/${id}/fragments`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  deleteCareerSource(id: string): Promise<void> {
    return request(`/api/career-sources/${id}`, { method: "DELETE" });
  },

  careerFragments(options: {
    query?: string;
    kind?: string;
    status?: string;
    sort?: string;
    direction?: string;
    archived?: boolean;
    page?: number;
    size?: number;
  }): Promise<CareerFragmentPage> {
    const params = new URLSearchParams();
    Object.entries(options).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    return request(`/api/career-fragments?${params}`);
  },

  updateCareerFragment(
    id: string,
    payload: {
      kind: CareerFragment["kind"];
      title: string;
      description: string;
      canonicalKey: string | null;
      detail: Record<string, unknown>;
    },
  ): Promise<CareerFragment> {
    return request(`/api/career-fragments/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  previewCareerFragmentMerge(fragmentIds: string[]): Promise<CareerFragmentMergePreview> {
    return request("/api/career-fragments/merge/preview", {
      method: "POST",
      body: JSON.stringify({ fragmentIds }),
    });
  },

  mergeCareerFragments(
    fragmentIds: string[],
    fragment: {
      kind: CareerFragment["kind"];
      title: string;
      description: string;
      canonicalKey: string | null;
      detail: Record<string, unknown>;
    },
  ): Promise<CareerFragmentMergeResult> {
    return request("/api/career-fragments/merge", {
      method: "POST",
      body: JSON.stringify({ fragmentIds, fragment }),
    });
  },

  undoCareerFragmentMerge(mergeEventId: string): Promise<CareerFragment> {
    return request(`/api/career-fragment-merges/${mergeEventId}/undo`, { method: "POST" });
  },

  archiveCareerFragment(id: string): Promise<void> {
    return request(`/api/career-fragments/${id}/archive`, { method: "POST" });
  },

  restoreCareerFragment(id: string): Promise<void> {
    return request(`/api/career-fragments/${id}/restore`, { method: "POST" });
  },

  deleteCareerFragment(id: string): Promise<void> {
    return request(`/api/career-fragments/${id}`, { method: "DELETE" });
  },
};

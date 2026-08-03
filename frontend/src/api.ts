import type {
  AnalysisJob,
  AlternativePosting,
  CareerFragment,
  CareerFragmentPage,
  CareerMap,
  CareerSourceDetail,
  CareerSourceSummary,
  ChatReplyJob,
  CompetencyAssessment,
  Conversation,
  ConversationSummary,
  Evidence,
  GoalProfile,
  NotificationItem,
  Posting,
  PostingDetail,
  PostingPage,
  RoadmapWorkspace,
  SendMessageResult,
  User,
  PostingDuplicateCandidate,
  AssessmentReviewItem,
} from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

let csrfToken: string | null = null;
let csrfHeader = "X-XSRF-TOKEN";
let mutationQueue: Promise<void> = Promise.resolve();

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
  if (options.body) headers.set("Content-Type", "application/json");
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
    return executeRequest<T>(path, options, false);
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
  async me(): Promise<User> {
    const payload = await request<{ user: User }>("/api/auth/me");
    return payload.user;
  },

  async login(email: string, password: string): Promise<User> {
    const payload = await request<{ user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
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
      body: JSON.stringify({ email, password, displayName }),
    });
    return payload.user;
  },

  logout(): Promise<void> {
    return request("/api/auth/logout", { method: "POST" });
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

  createConversation(): Promise<Conversation> {
    return request("/api/conversations", { method: "POST" });
  },

  conversation(id: string): Promise<Conversation> {
    return request(`/api/conversations/${id}`);
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
  ): Promise<SendMessageResult> {
    return request(`/api/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({
        clientMessageId: crypto.randomUUID(),
        content,
        posting: posting ?? null,
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

  answerAnalysisQuestion(
    jobId: string,
    questionId: string,
    value: string,
  ): Promise<void> {
    return request(
      `/api/analysis-jobs/${jobId}/questions/${questionId}/answer`,
      {
        method: "POST",
        body: JSON.stringify({ value }),
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

  regenerateRoadmap(): Promise<{
    draftId: string;
    draftVersion: number;
    changes: { added: string[]; removed: string[]; retained: string[] };
  }> {
    return request("/api/roadmap/draft", { method: "POST" });
  },

  applyRoadmapDraft(): Promise<{
    roadmapVersionId: string;
    graphVersion: number;
  }> {
    return request("/api/roadmap/draft/apply", { method: "POST" });
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

  notifications(unreadOnly = false): Promise<{
    items: NotificationItem[];
    unreadCount: number;
  }> {
    return request(`/api/notifications?unreadOnly=${unreadOnly}`);
  },

  readNotification(id: string): Promise<void> {
    return request(`/api/notifications/${id}/read`, { method: "POST" });
  },

  readAllNotifications(): Promise<void> {
    return request("/api/notifications/read-all", { method: "POST" });
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

  requestAssessmentReview(
    sessionId: string,
    reason: string,
  ): Promise<CompetencyAssessment> {
    return request(`/api/competency-assessments/${sessionId}/review`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  operatorPostingDuplicates(status = "OPEN"): Promise<PostingDuplicateCandidate[]> {
    return request(`/api/operator/posting-duplicates?status=${encodeURIComponent(status)}`);
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

  operatorAssessmentReviews(status = "REQUESTED"): Promise<AssessmentReviewItem[]> {
    return request(`/api/operator/assessment-reviews?status=${encodeURIComponent(status)}`);
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

  retryCareerSource(id: string): Promise<void> {
    return request(`/api/career-sources/${id}/retry`, { method: "POST" });
  },

  confirmCareerSource(id: string, fragmentIds: string[]): Promise<void> {
    return request(`/api/career-sources/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ fragmentIds }),
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

  mergeCareerFragments(
    fragmentIds: string[],
    fragment: {
      kind: CareerFragment["kind"];
      title: string;
      description: string;
      canonicalKey: string | null;
      detail: Record<string, unknown>;
    },
  ): Promise<CareerFragment> {
    return request("/api/career-fragments/merge", {
      method: "POST",
      body: JSON.stringify({ fragmentIds, fragment }),
    });
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

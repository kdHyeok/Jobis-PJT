import { expect, test, type APIResponse, type Page } from "@playwright/test";

type JsonObject = Record<string, any>;

const STANDARD_POSTING_URL = process.env.E2E_STANDARD_POSTING_URL
  ?? "https://www.jobkorea.co.kr/Recruit/GI_Read/49686653";
const JS_POSTING_URL = process.env.E2E_JS_POSTING_URL
  ?? "https://hanwhaaerospace-recruit.com/jdebook/#2@01-02@new";

const RESUME_TEXT = `
김테스트 | 백엔드·AI 서비스 엔지니어

경력 요약
- Java 17과 Spring Boot로 REST API를 개발하고 PostgreSQL 스키마와 쿼리를 설계했습니다.
- Python과 FastAPI로 문서 수집 및 LLM 기반 구조화 파이프라인을 구현했습니다.
- Docker Compose, Jenkins, GitLab CI를 이용해 빌드·테스트·배포 자동화를 운영했습니다.

프로젝트
1. JOBIS 취업 준비 플랫폼
- 채용공고 URL·이미지 수집, OCR, 구조화 분석과 역량 갭 분석 기능을 구현했습니다.
- 직접 HTML 수집 실패 시 Jina, Firecrawl, Tavily로 이어지는 폴백 흐름을 설계했습니다.
- Spring Boot 백엔드와 Python AI 서버 사이의 JSON 계약 테스트를 작성했습니다.

2. 문서 검색 AI
- 문서를 청킹하고 임베딩해 RAG 검색 API를 만들었습니다.
- 응답 근거와 평가 결과를 저장하고 재현 가능한 테스트 데이터셋을 관리했습니다.

기술
- Java, Spring Boot, Python, FastAPI, PostgreSQL, SQL, Docker, Git, Jenkins, REST API

교육 및 자격
- SSAFY 소프트웨어 교육 과정 수료
- 정보처리기사 보유
`.trim();

const IMAGE_POSTING_HTML = `<!doctype html><html lang="ko"><body style="font-family:Arial,sans-serif;background:#fff;padding:48px;width:920px">
  <h1>JOBIS 테스트 주식회사 - 백엔드 엔지니어 신입 채용</h1>
  <h2>담당 업무</h2>
  <p>Java와 Spring Boot를 이용한 REST API 개발, PostgreSQL 데이터 모델링, 자동화 테스트 작성 및 운영 장애 분석을 담당합니다.</p>
  <h2>필수 요건</h2>
  <p>Java 또는 Kotlin 활용 능력, HTTP와 REST API 이해, Git 협업 경험이 필요합니다. 신입 지원이 가능합니다.</p>
  <h2>우대 사항</h2>
  <p>Docker, AWS, CI/CD, Python 기반 AI 서비스 연동 경험을 우대합니다.</p>
  <h2>채용 조건</h2>
  <p>정규직, 서울 근무, 서류 전형과 기술 면접 후 최종 합격자를 결정합니다.</p>
</body></html>`;

async function json<T = JsonObject>(response: APIResponse): Promise<T> {
  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { message: text.slice(0, 500) };
  }
  expect(response.ok(), `${response.url()} -> ${response.status()} ${text.slice(0, 800)}`).toBeTruthy();
  return payload as T;
}

async function api<T = JsonObject>(
  page: Page,
  path: string,
  options: { method?: string; data?: unknown } = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {};
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = await json<{ headerName: string; token: string }>(
      await page.request.get("/api/auth/csrf"),
    );
    headers[csrf.headerName] = csrf.token;
  }
  return json<T>(await page.request.fetch(path, {
    method,
    data: options.data,
    headers,
  }));
}

async function poll<T>(
  load: () => Promise<T>,
  done: (value: T) => boolean,
  timeoutMs: number,
  label: string,
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let latest = await load();
  while (!done(latest) && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2_000));
    latest = await load();
  }
  expect(done(latest), `${label} timed out: ${JSON.stringify(latest).slice(0, 1_500)}`).toBeTruthy();
  return latest;
}

function assertPostingText(label: string, source: JsonObject): void {
  const rawText = String(source.sourceDocument?.rawText ?? "").trim();
  const signals = rawText.match(/채용|모집|직무|담당\s*업무|자격\s*요건|필수\s*요건|우대\s*사항|경력|신입|근무|지원/gi) ?? [];
  expect(rawText.length, `${label}: extracted posting text must be substantial`).toBeGreaterThanOrEqual(200);
  expect(signals.length, `${label}: extracted text lacks posting signals`).toBeGreaterThanOrEqual(2);
  console.log(`[live-smoke] ${label} collector=${source.sourceDocument?.segments?.map((item: JsonObject) => item.method).join(",") || "unknown"} chars=${rawText.length} warnings=${source.sourceDocument?.warnings?.length ?? 0}`);
}

async function waitChat(page: Page, jobId: string, label: string): Promise<JsonObject> {
  const job = await poll(
    () => api<JsonObject>(page, `/api/chat-reply-jobs/${jobId}`),
    (value) => ["SUCCEEDED", "FAILED", "CANCELLED"].includes(String(value.status)),
    5 * 60_000,
    label,
  );
  expect(job.status, `${label}: ${job.errorCode ?? ""} ${job.errorMessage ?? ""}`).toBe("SUCCEEDED");
  expect(String(job.result?.message ?? "").trim().length, `${label}: empty assistant response`).toBeGreaterThan(20);
  return job;
}

async function sendChat(
  page: Page,
  conversationId: string,
  content: string,
  context: JsonObject,
  label: string,
): Promise<JsonObject> {
  const sent = await api<JsonObject>(page, `/api/conversations/${conversationId}/messages`, {
    method: "POST",
    data: {
      clientMessageId: crypto.randomUUID(),
      content,
      posting: null,
      context,
    },
  });
  expect(sent.chatReplyJobId, `${label}: chat job was not created`).toBeTruthy();
  return waitChat(page, String(sent.chatReplyJobId), label);
}

function clarificationAnswer(question: JsonObject, stage: string): {
  value: string;
  answerStatus: "PROVIDED" | "CONFIRMED_ABSENT";
} {
  if (stage === "AWAITING_POSTING_CONFIRMATION") {
    return { value: "CONFIRM", answerStatus: "PROVIDED" };
  }

  const options = Array.isArray(question.options) ? question.options as JsonObject[] : [];
  if (options.length > 0) {
    const preferred = options.find((option) =>
      /NEW_GRADUATE|ENTRY|JUNIOR|신입/i.test(`${option.value ?? ""} ${option.label ?? ""}`),
    ) ?? options[0];
    return { value: String(preferred.value), answerStatus: "PROVIDED" };
  }

  if (question.absenceScope && question.absenceScope !== "NONE") {
    return { value: "해당 경험 없음", answerStatus: "CONFIRMED_ABSENT" };
  }

  return {
    value: "신입 지원자이며, 등록한 커리어 자료에 기재된 Java·Spring Boot 백엔드 프로젝트 경험을 기준으로 분석해 주세요.",
    answerStatus: "PROVIDED",
  };
}

async function waitUnifiedAnalysis(page: Page, jobId: string): Promise<JsonObject> {
  const deadline = Date.now() + 12 * 60_000;
  let answered = 0;
  let latest: JsonObject = {};

  while (Date.now() < deadline) {
    latest = await api<JsonObject>(page, `/api/analysis-jobs/${jobId}`);
    const status = String(latest.status);
    if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(status)) return latest;

    if (status === "WAITING_FOR_INPUT" && latest.pendingQuestion) {
      expect(answered, "analysis requested too many clarification answers").toBeLessThan(6);
      const answer = clarificationAnswer(latest.pendingQuestion, String(latest.stage));
      console.log(
        `[live-smoke] clarification key=${latest.pendingQuestion.key} `
        + `stage=${latest.stage} answer=${answer.answerStatus}:${answer.value}`,
      );
      await api(page, `/api/analysis-jobs/${jobId}/questions/${latest.pendingQuestion.id}/answer`, {
        method: "POST",
        data: answer,
      });
      answered += 1;
    }

    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }

  expect(false, `unified analysis timed out: ${JSON.stringify(latest).slice(0, 1_500)}`).toBeTruthy();
  return latest;
}

test.describe("predeploy live AI feature smoke", () => {
  test.skip(process.env.E2E_LIVE_AI !== "1", "Set E2E_LIVE_AI=1 to call the real AI and collectors.");
  test.setTimeout(20 * 60_000);

  test("career fragments, posting collectors, analysis, alternatives and roadmap", async ({ page, browser }) => {
    const runId = Date.now().toString(36);
    const suppliedEmail = process.env.E2E_LIVE_EMAIL;
    const suppliedPassword = process.env.E2E_LIVE_PASSWORD;
    expect(Boolean(suppliedEmail), "E2E_LIVE_EMAIL and E2E_LIVE_PASSWORD must be supplied together")
      .toBe(Boolean(suppliedPassword));
    const ownsAccount = !suppliedEmail;
    const email = suppliedEmail ?? `predeploy-${runId}@jobis.local`;
    const password = suppliedPassword ?? `Smoke-${runId}-Aa1!`;
    const featureFailures: string[] = [];

    try {
      if (ownsAccount) {
        await api(page, "/api/auth/register", {
          method: "POST",
          data: {
            email,
            password,
            displayName: "배포전검증",
            termsAccepted: true,
            privacyAccepted: true,
            policyVersion: "2026-08-04",
          },
        });
      } else {
        await api(page, "/api/auth/login", {
          method: "POST",
          data: { email, password, rememberMe: false },
        });
      }
      console.log(`[live-smoke] account=${email} mode=${ownsAccount ? "disposable" : "reused"}`);

      await page.goto("/app/storage");
      await expect(page.getByRole("heading", { name: "커리어 저장소" })).toBeVisible();

      const career = await api<JsonObject>(page, "/api/career-sources", {
        method: "POST",
        data: { sourceType: "TEXT", title: `배포전 검증 이력서 ${runId}`, sourceUrl: null, rawText: RESUME_TEXT },
      });
      const careerId = String(career.source?.id ?? career.id);
      expect(careerId).toBeTruthy();
      const careerReady = await poll(
        () => api<JsonObject>(page, `/api/career-sources/${careerId}`),
        (value) => ["REVIEW_READY", "CONFIRMED", "FAILED", "CANCELLED"].includes(String(value.source?.status)),
        5 * 60_000,
        "career fragmentation",
      );
      expect(careerReady.source.status, careerReady.source.errorMessage ?? "career extraction failed").toBe("REVIEW_READY");
      const fragments = careerReady.fragments as JsonObject[];
      const kinds = new Set(fragments.map((item) => item.kind));
      expect(fragments.length).toBeGreaterThanOrEqual(4);
      expect(kinds.size).toBeGreaterThanOrEqual(3);
      expect(kinds.has("SKILL")).toBeTruthy();
      expect(kinds.has("PROJECT") || kinds.has("EXPERIENCE")).toBeTruthy();
      await api(page, `/api/career-sources/${careerId}/confirm`, {
        method: "POST",
        data: { fragmentIds: fragments.map((item) => item.id) },
      });
      console.log(`[live-smoke] career fragments=${fragments.length} kinds=${[...kinds].join(",")}`);

      const conversation = await api<JsonObject>(page, "/api/conversations", { method: "POST" });
      const conversationId = String(conversation.id);
      await sendChat(page, conversationId,
        "커리어 저장소에 등록한 자료를 기준으로 기술·프로젝트·경력 조각이 어떻게 나뉘었는지 요약해줘.",
        { mode: "RESUME_DIAGNOSIS", postingIds: [], careerSourceIds: [careerId] },
        "career repository chat",
      );

      await page.goto("/app/postings/new");
      await expect(page.getByRole("heading", { name: "새 채용 공고 분석" })).toBeVisible();

      const standardSource = await api<JsonObject>(page, "/api/v3/sources", {
        method: "POST",
        data: { inputType: "URL", entryPoint: "POSTINGS_PAGE", extractionRevision: 1, url: STANDARD_POSTING_URL },
      });
      assertPostingText("standard-url", standardSource);

      const jsSource = await api<JsonObject>(page, "/api/v3/sources", {
        method: "POST",
        data: { inputType: "URL", entryPoint: "POSTINGS_PAGE", extractionRevision: 1, url: JS_POSTING_URL },
      });
      assertPostingText("javascript-url", jsSource);

      const imagePage = await browser.newPage({ viewport: { width: 1_100, height: 900 } });
      await imagePage.setContent(IMAGE_POSTING_HTML);
      const image = await imagePage.screenshot({ type: "png", fullPage: true });
      await imagePage.close();
      let analysisSource: JsonObject;
      try {
        const imageSource = await api<JsonObject>(page, "/api/v3/sources", {
          method: "POST",
          data: {
            inputType: "IMAGE",
            entryPoint: "POSTINGS_PAGE",
            extractionRevision: 1,
            imageBase64: image.toString("base64"),
            imageMediaType: "image/png",
            originalFilename: `predeploy-posting-${runId}.png`,
          },
        });
        assertPostingText("image-ocr", imageSource);
        const imageText = String(imageSource.sourceDocument.rawText);
        const recognizedTerms = ["Java", "Spring", "PostgreSQL", "Docker"].filter((term) => imageText.toLowerCase().includes(term.toLowerCase()));
        expect(recognizedTerms.length, "image OCR lost core technology terms").toBeGreaterThanOrEqual(2);
        analysisSource = imageSource;
      } catch (error) {
        featureFailures.push(`image-ocr: ${String(error)}`);
        console.log(`[live-smoke] image-ocr FAILED; continuing remaining contracts with equivalent TEXT source: ${String(error)}`);
        analysisSource = await api<JsonObject>(page, "/api/v3/sources", {
          method: "POST",
          data: {
            inputType: "TEXT",
            entryPoint: "POSTINGS_PAGE",
            extractionRevision: 1,
            text: "JOBIS 테스트 주식회사 백엔드 엔지니어 신입 채용\n담당 업무: Java와 Spring Boot REST API 개발, PostgreSQL 데이터 모델링, 자동화 테스트와 운영 장애 분석\n필수 요건: Java 또는 Kotlin, HTTP와 REST API 이해, Git 협업 경험, 신입 지원 가능\n우대 사항: Docker, AWS, CI/CD, Python 기반 AI 서비스 연동 경험\n채용 조건: 정규직, 서울 근무, 서류 전형과 기술 면접 후 최종 합격",
          },
        });
        assertPostingText("analysis-text-fallback", analysisSource);
      }

      const imageText = String(analysisSource.sourceDocument.rawText);

      const verifiedSource = await api<JsonObject>(page, `/api/v3/sources/${analysisSource.id}/verify`, {
        method: "POST",
        data: { verifiedText: imageText, corrections: [], verifiedBy: "USER" },
      });
      expect(verifiedSource.verifiedSnapshotId).toBeTruthy();
      const started = await api<JsonObject>(page, `/api/v3/sources/${analysisSource.id}/analyses`, {
        method: "POST",
        data: { conversationId },
      });
      const analysis = await waitUnifiedAnalysis(page, String(started.analysisJobId));
      expect(analysis.status, `${analysis.errorCode ?? ""} ${analysis.errorMessage ?? ""}`).toBe("SUCCEEDED");
      expect(analysis.analysisProvider).toBe("UNIFIED");
      expect(analysis.result?.postingReview?.requiredRequirements?.length ?? 0).toBeGreaterThan(0);
      expect(Object.keys(analysis.result?.fit ?? {}).length, "gap/fit result is empty").toBeGreaterThan(0);
      expect(Object.keys(analysis.result?.roadmapProposal ?? {}).length, "roadmap proposal is empty").toBeGreaterThan(0);
      console.log(`[live-smoke] analysis=${analysis.id} posting=${analysis.postingId} required=${analysis.result.postingReview.requiredRequirements.length}`);

      const gapReply = await sendChat(page, conversationId,
        "선택한 공고와 확정된 커리어 자료를 비교해서 보유 근거와 부족 역량을 구분한 갭 분석을 해줘.",
        { mode: "POSTING_QA", postingIds: [analysis.postingId], careerSourceIds: [careerId] },
        "gap analysis chat",
      );
      expect(JSON.stringify(gapReply.result).length).toBeGreaterThan(100);

      const alternativeReply = await sendChat(page, conversationId,
        "이 공고가 맞지 않을 때 지원할 수 있는 대안 공고를 최대 5개 추천해줘. 회사명·직무·매칭 근거·URL을 포함해줘.",
        { mode: "JOB_DISCOVERY", postingIds: [analysis.postingId], careerSourceIds: [careerId] },
        "alternative posting chat",
      );
      const alternativePayload = JSON.stringify(alternativeReply.result ?? {});
      expect(alternativePayload, "alternative recommendation response has no URL").toMatch(/https?:\/\//);
      let alternativeCount = 0;
      try {
        const alternatives = await api<JsonObject[]>(page, `/api/job-postings/${analysis.postingId}/alternatives?limit=5`);
        expect(Array.isArray(alternatives)).toBeTruthy();
        alternativeCount = alternatives.length;
      } catch (error) {
        featureFailures.push(`alternative-api: ${String(error)}`);
        console.log(`[live-smoke] alternative-api FAILED; chat recommendation completed: ${String(error)}`);
      }
      console.log(`[live-smoke] alternatives chat=SUCCEEDED api-count=${alternativeCount}`);

      const roadmapReply = await sendChat(page, conversationId,
        "이 공고의 부족 역량을 기준으로 회사 맞춤 프로젝트와 준비 로드맵을 설명해줘. 공고·역량·프로젝트·지원 기회의 연결 관계도 포함해줘.",
        { mode: "APPLICATION_PLAN", postingIds: [analysis.postingId], careerSourceIds: [careerId] },
        "roadmap chat",
      );
      const unfulfilled = (roadmapReply.result?.warnings ?? []).filter(
        (warning: JsonObject) => warning.code === "request_not_fulfilled",
      );
      if (unfulfilled.length > 0) {
        featureFailures.push(`roadmap-chat: ${unfulfilled.map((warning: JsonObject) => warning.message).join(" | ")}`);
        console.log(`[live-smoke] roadmap-chat FAILED requested agent was not fulfilled`);
      }
      const roadmap = await api<JsonObject>(page, "/api/v3/roadmap");
      expect(roadmap.draftProposal, "roadmap draft proposal was not persisted").toBeTruthy();
      const preview = roadmap.draftProposal.preview
        ?? await api<JsonObject>(page, `/api/v3/roadmap/proposals/${roadmap.draftProposal.id}/preview`, { method: "POST" }).then((value) => value.preview);
      expect(preview.snapshot.nodes.length, "roadmap preview has no nodes").toBeGreaterThan(0);
      expect(preview.snapshot.relations.length, "roadmap preview is not a graph").toBeGreaterThan(0);
      const nodeKinds = new Set(preview.snapshot.nodes.map((item: JsonObject) => item.nodeKind));
      expect(nodeKinds.has("CAPABILITY")).toBeTruthy();
      expect(nodeKinds.has("TARGET_PROJECT")).toBeTruthy();
      console.log(`[live-smoke] roadmap proposal=${roadmap.draftProposal.id} nodes=${preview.snapshot.nodes.length} relations=${preview.snapshot.relations.length} kinds=${[...nodeKinds].join(",")}`);

      expect(featureFailures, `feature failures:\n${featureFailures.join("\n")}`).toEqual([]);
    } finally {
      if (ownsAccount && process.env.E2E_LIVE_KEEP_ACCOUNT !== "1") {
        await api(page, "/api/account", { method: "DELETE", data: { password } }).catch((error) => {
          console.warn(`[live-smoke] cleanup failed: ${String(error)}`);
        });
      }
    }
  });
});

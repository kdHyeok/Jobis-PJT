import { expect, test } from "@playwright/test";

import { mockAuthenticatedApi } from "./helpers";


test("진입 회사와 경력직 회사를 하나의 프로젝트 중심 커리어 지도에서 보여준다", async ({ page }) => {
  const entryPostingId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const experiencedPostingId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  const currentRoadmap = {
    roadmapVersion: 2,
    nodes: [
      {
        nodeId: "java", nodeKind: "CAPABILITY", canonicalKey: "java.classes-objects",
        title: "Java 객체 모델링", sectionKey: "section.web_backend",
        sectionMemberships: [{ sectionKey: "section.web_backend", chapterKey: "chapter.language-framework", chapterTitle: "언어 · 프레임워크", targetRef: "stage.entry", reason: "프로젝트에 필요한 역량" }],
        progressState: "NOT_STARTED", displayRank: 10,
      },
      {
        nodeId: "est-project", nodeKind: "TARGET_PROJECT", targetRef: `project:opportunity:${entryPostingId}`,
        title: "이스트게임즈 맞춤 프로젝트", sectionKey: "section.web_backend", progressState: "NOT_STARTED", displayRank: 20,
        projectSpec: {
          objective: "게임 구매 흐름을 구현하고 정합성을 검증한다.", domainContext: "게임 결제",
          deliverables: ["실행 가능한 저장소"], verificationCriteria: ["자동화 테스트가 통과한다."],
          requiredCapabilityKeys: ["java.classes-objects"], preferredCapabilityKeys: [],
          requiredProvisionalCandidateIds: [], preferredProvisionalCandidateIds: [],
          tasks: [{ taskKey: "task.domain-model", necessity: "REQUIRED", title: "게임 구매 API 구현", objective: "구매 상태를 구현한다.", acceptanceCriteria: ["상태를 구현한다.", "테스트를 통과한다."], capabilityKeys: ["java.classes-objects"], requirementIds: ["req-java"], dependsOnTaskKeys: [] }],
        },
      },
      {
        nodeId: "est-opportunity", nodeKind: "OPPORTUNITY", targetRef: `opportunity:${entryPostingId}`,
        title: "이스트게임즈 신입 지원", sectionKey: "section.web_backend", progressState: "NOT_STARTED", displayRank: 30,
        opportunitySpec: { opportunityId: `opportunity:${entryPostingId}`, companyName: "이스트게임즈", positionTitle: "백엔드 개발자", minimumExperienceMonths: 0, maximumExperienceMonths: null, postingStatus: "ACTIVE", goalMode: "ACTIVE_APPLICATION" },
      },
      { nodeId: "employment", nodeKind: "EMPLOYMENT_EVENT", title: "관련 백엔드 취업", sectionKey: "section.web_backend", progressState: "NOT_STARTED", displayRank: 40, employmentSpec: { evidenceState: "UNKNOWN" } },
      { nodeId: "experience", nodeKind: "EXPERIENCE_INTERVAL", title: "관련 실무 경력 2~4년", sectionKey: "section.web_backend", progressState: "NOT_STARTED", displayRank: 50, experienceIntervalSpec: { minimumMonths: 24, maximumMonths: 48, accruedMonths: null, evidenceState: "UNKNOWN" } },
      {
        nodeId: "naver-project", nodeKind: "TARGET_PROJECT", targetRef: `project:opportunity:${experiencedPostingId}`,
        title: "네이버웹툰 맞춤 프로젝트", sectionKey: "section.web_backend", progressState: "NOT_STARTED", displayRank: 60,
        projectSpec: { objective: "글로벌 유료 콘텐츠 백엔드를 구현한다.", domainContext: "유료 콘텐츠", deliverables: ["실행 가능한 저장소"], verificationCriteria: ["부하 테스트를 통과한다."], requiredCapabilityKeys: ["java.classes-objects"], preferredCapabilityKeys: [], requiredProvisionalCandidateIds: [], preferredProvisionalCandidateIds: [], tasks: [] },
      },
      {
        nodeId: "naver-opportunity", nodeKind: "OPPORTUNITY", targetRef: `opportunity:${experiencedPostingId}`,
        title: "네이버웹툰 경력 지원", sectionKey: "section.web_backend", progressState: "NOT_STARTED", displayRank: 70,
        opportunitySpec: { opportunityId: `opportunity:${experiencedPostingId}`, companyName: "네이버웹툰", positionTitle: "백엔드 서버 개발", minimumExperienceMonths: 24, maximumExperienceMonths: 48, postingStatus: "ACTIVE", goalMode: "REFERENCE_TARGET" },
      },
    ],
    relations: [
      { relationId: "r1", fromNodeId: "java", toNodeId: "est-project", relationType: "UNLOCKS_PROJECT", reason: "필수" },
      { relationId: "r2", fromNodeId: "est-project", toNodeId: "est-opportunity", relationType: "UNLOCKS_OPPORTUNITY", reason: "완료" },
      { relationId: "r3", fromNodeId: "est-opportunity", toNodeId: "employment", relationType: "POTENTIAL_CAREER_ENTRY", reason: "진입" },
      { relationId: "r4", fromNodeId: "employment", toNodeId: "experience", relationType: "STARTS_EXPERIENCE", reason: "경력 시작" },
      { relationId: "r5", fromNodeId: "naver-project", toNodeId: "naver-opportunity", relationType: "UNLOCKS_OPPORTUNITY", reason: "완료" },
      { relationId: "r6", fromNodeId: "experience", toNodeId: "naver-opportunity", relationType: "SATISFIES_EXPERIENCE_GATE", reason: "24~48개월" },
    ],
  };

  await mockAuthenticatedApi(page, async (route, path) => {
    if (path === "/api/v3/roadmap") {
      await route.fulfill({ json: { currentRoadmap, draftProposal: null } });
      return true;
    }
    if (path === "/api/roadmap") {
      await route.fulfill({ json: { current: { version: 0, title: "", nodes: [], edges: [], targets: [] }, draft: null, targetCount: 0 } });
      return true;
    }
    if (path === "/api/v3/roadmap/versions" || path === "/api/roadmap/versions") {
      await route.fulfill({ json: [] });
      return true;
    }
    if (path === "/api/career-goals") {
      await route.fulfill({ json: { currentPostingId: null, currentCompanyName: null, currentRoleTitle: null, finalPostingId: null, finalCompanyName: null, finalRoleTitle: null, finalGoalText: null } });
      return true;
    }
    return false;
  });

  await page.goto("/app/map");
  await expect(page.getByText("백엔드 성장 여정")).toBeVisible();
  await expect(page.getByText("이스트게임즈 맞춤 프로젝트")).toBeVisible();
  await expect(page.getByText("관련 백엔드 취업")).toBeVisible();
  await expect(page.getByText("관련 실무 경력 2~4년")).toBeVisible();
  await expect(page.getByText("네이버웹툰 맞춤 프로젝트")).toBeVisible();
  await expect(page.getByText("게임 구매 API 구현")).toHaveCount(0);

  await page.getByRole("button", { name: /이스트게임즈 맞춤 프로젝트/ }).click();
  await expect(page.getByText("게임 구매 API 구현")).toBeVisible();
  await expect(page.getByText("이 과제에서 직접 사용하는 역량")).toBeVisible();
});

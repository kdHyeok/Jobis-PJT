import { expect, test } from "@playwright/test";

import { mockAuthenticatedApi } from "./helpers";

const postingId = "44444444-4444-4444-8444-444444444444";

const snapshot = {
  version: 1,
  title: "나의 커리어 지도",
  nodes: [{
    id: "opportunity-1",
    type: "OPPORTUNITY",
    title: "이스트게임즈 백엔드",
    subtitle: "신입 지원 기회",
    domain: "BACKEND",
    stage: "OPPORTUNITY",
    rank: 1,
    optional: false,
    postingIds: [postingId],
    competencies: [],
    project: null,
    postingId,
    status: "NOT_STARTED",
    careerNodeId: null,
  }],
  edges: [],
  targets: [{
    postingId,
    companyName: "이스트게임즈",
    roleTitle: "백엔드 개발자",
    completedRequired: 0,
    required: 1,
    completedPreferred: 0,
    preferred: 0,
  }],
};

test("사용자가 선택한 공고를 현재 목표로 저장한다", async ({ page }) => {
  let currentPostingId: string | null = null;
  await mockAuthenticatedApi(page, async (route, path) => {
    if (path === "/api/career-goals") {
      if (route.request().method() === "PUT") {
        currentPostingId = route.request().postDataJSON().currentPostingId;
      }
      await route.fulfill({ json: {
        currentPostingId,
        currentCompanyName: currentPostingId ? "이스트게임즈" : null,
        currentRoleTitle: currentPostingId ? "백엔드 개발자" : null,
        finalPostingId: null,
        finalCompanyName: null,
        finalRoleTitle: null,
        finalGoalText: null,
      } });
      return true;
    }
    if (path === "/api/v3/roadmap") {
      await route.fulfill({ json: {
        currentRoadmap: { roadmapVersion: 0, nodes: [], relations: [] },
        draftProposal: null,
      } });
      return true;
    }
    if (path === "/api/roadmap") {
      await route.fulfill({ json: { current: snapshot, draft: null, targetCount: 1 } });
      return true;
    }
    if (path === "/api/roadmap/versions" || path === "/api/v3/roadmap/versions") {
      await route.fulfill({ json: [] });
      return true;
    }
    return false;
  });

  await page.goto("/app/map");
  await page.getByRole("button", { name: "이스트게임즈 0/1 필수" }).click();
  await page.getByRole("button", { name: "현재 목표로" }).click();

  await expect(page.getByText("현재 목표").first()).toBeVisible();
  await expect(page.getByText("이스트게임즈", { exact: true }).first()).toBeVisible();
  expect(currentPostingId).toBe(postingId);
});

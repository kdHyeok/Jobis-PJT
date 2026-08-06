import { expect, test } from "@playwright/test";

import { conversation, mockAuthenticatedApi } from "./helpers";

test("공고 URL을 제출하면 모달을 닫고 저장된 사용자 메시지로 이어간다", async ({ page }) => {
  const url = "https://example.com/jobs/backend-123";
  await mockAuthenticatedApi(page, async (route, path) => {
    if (path === `/api/conversations/${conversation.id}/messages`) {
      const payload = route.request().postDataJSON();
      await route.fulfill({ json: {
        userMessage: {
          id: "33333333-3333-4333-8333-333333333333",
          role: "USER",
          kind: "TEXT",
          content: payload.content,
          postingId: null,
          analysisJobId: null,
          metadata: {},
          createdAt: "2026-08-06T10:01:00+09:00",
        },
        assistantMessage: null,
        analysisJobId: null,
        chatReplyJobId: null,
        aiAvailable: true,
      } });
      return true;
    }
    return false;
  });

  await page.goto("/app/chat");
  await page.getByRole("button", { name: "공고 분석 URL 또는 원문으로 확실하게 시작" }).click();
  await page.getByRole("button", { name: /URL로 가져오기/ }).click();
  await page.getByLabel("공고 상세 페이지 URL").fill(url);
  await page.getByRole("button", { name: /에이전트로 공고 정리하기/ }).click();

  await expect(page.getByRole("dialog", { name: "분석할 채용 공고" })).toBeHidden();
  await expect(page.getByText(url, { exact: false })).toBeVisible();
});

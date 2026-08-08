import type { Page, Route } from "@playwright/test";

const now = "2026-08-06T10:00:00+09:00";

export const user = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "e2e@ssafy.com",
  displayName: "E2E 사용자",
  status: "ACTIVE",
  accountRole: "USER",
  createdAt: now,
};

export const conversation = {
  id: "22222222-2222-4222-8222-222222222222",
  title: "공고 분석 대화",
  status: "ACTIVE",
  messages: [],
  hasOlderMessages: false,
  lastMessageAt: now,
  createdAt: now,
};

export async function mockAuthenticatedApi(
  page: Page,
  overrides: (route: Route, path: string) => Promise<boolean> | boolean = () => false,
) {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (await overrides(route, path)) return;
    if (path === "/api/auth/me") {
      await route.fulfill({ json: { user } });
    } else if (path === "/api/auth/csrf") {
      await route.fulfill({ json: { headerName: "X-XSRF-TOKEN", token: "e2e-csrf" } });
    } else if (path === "/api/conversations/search") {
      await route.fulfill({ json: {
        items: [{
          id: conversation.id,
          title: conversation.title,
          status: "ACTIVE",
          lastMessage: "",
          lastMessageAt: now,
          createdAt: now,
        }],
        page: 0,
        size: 30,
        total: 1,
      } });
    } else if (path === `/api/conversations/${conversation.id}`) {
      await route.fulfill({ json: conversation });
    } else if (path === `/api/chat-reply-jobs/conversation/${conversation.id}`) {
      await route.fulfill({ json: [] });
    } else if (path === "/api/job-postings" || path === "/api/career-sources") {
      await route.fulfill({ json: [] });
    } else if (path.startsWith("/api/notifications")) {
      await route.fulfill({ json: { items: [], unreadCount: 0, hasMore: false } });
    } else {
      await route.fulfill({ json: {} });
    }
  });
}

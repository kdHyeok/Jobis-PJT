import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginView from "@/views/LoginView.vue";

const { login, push } = vi.hoisted(() => ({
  login: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { login, register: vi.fn() },
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push }),
}));

describe("LoginView", () => {
  beforeEach(() => {
    login.mockReset();
    push.mockReset();
    login.mockResolvedValue({
      id: "user-1",
      email: "user@example.com",
      displayName: "사용자",
      status: "ACTIVE",
      accountRole: "USER",
      createdAt: "2026-08-06T00:00:00Z",
    });
  });

  it("로그인 유지 선택을 인증 API에 명시적으로 전달한다", async () => {
    const wrapper = mount(LoginView, {
      global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
    });
    const inputs = wrapper.findAll("input");
    await inputs.find((input) => input.attributes("type") === "email")!.setValue("user@example.com");
    await inputs.find((input) => input.attributes("type") === "password")!.setValue("correct-password");
    await inputs.find((input) => input.attributes("type") === "checkbox")!.setValue(true);
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(login).toHaveBeenCalledWith("user@example.com", "correct-password", true);
    expect(push).toHaveBeenCalledWith("/app");
  });
});

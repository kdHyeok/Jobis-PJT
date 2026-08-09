import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuthModal from "@/components/AuthModal.vue";

const { login, register, push } = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { login, register },
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push }),
}));

describe("AuthModal", () => {
  beforeEach(() => {
    login.mockReset();
    register.mockReset();
    push.mockReset();
    login.mockResolvedValue({
      id: "user-1",
      email: "user@example.com",
      displayName: "사용자",
      status: "ACTIVE",
      accountRole: "USER",
      createdAt: "2026-08-06T00:00:00Z",
    });
    register.mockResolvedValue({
      id: "user-2",
      email: "new@example.com",
      displayName: "새 사용자",
      status: "ACTIVE",
      accountRole: "USER",
      createdAt: "2026-08-09T00:00:00Z",
    });
  });

  it("로그인 유지 선택을 인증 API에 명시적으로 전달한다", async () => {
    const wrapper = mount(AuthModal, {
      props: { mode: "login" },
      global: {
        stubs: { Teleport: true },
        directives: { dialogFocus: {} },
      },
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

  it("회원가입은 약관과 개인정보 처리 안내에 모두 동의해야 제출된다", async () => {
    const wrapper = mount(AuthModal, {
      props: { mode: "register" },
      global: {
        stubs: { Teleport: true },
        directives: { dialogFocus: {} },
      },
    });
    const inputs = wrapper.findAll("input");
    await inputs.find((input) => input.attributes("autocomplete") === "name")!.setValue("새 사용자");
    await inputs.find((input) => input.attributes("type") === "email")!.setValue("new@example.com");
    await inputs.find((input) => input.attributes("type") === "password")!.setValue("secure-password-123");

    const submit = wrapper.find<HTMLButtonElement>("button.auth-submit");
    expect(submit.element.disabled).toBe(true);

    const consents = inputs.filter((input) => input.attributes("type") === "checkbox");
    await consents[0].setValue(true);
    await flushPromises();
    expect(submit.element.disabled).toBe(true);
    await consents[1].setValue(true);
    await flushPromises();
    expect(wrapper.find<HTMLButtonElement>("button.auth-submit").element.disabled).toBe(false);

    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(register).toHaveBeenCalledWith(
      "new@example.com",
      "secure-password-123",
      "새 사용자",
      true,
      true,
    );
    expect(push).toHaveBeenCalledWith("/app");
  });
});

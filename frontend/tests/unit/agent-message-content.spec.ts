import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import AgentMessageContent from "@/components/AgentMessageContent.vue";
import AgentWorkProductCard from "@/components/AgentWorkProductCard.vue";

describe("AgentMessageContent", () => {
  it("강조, 불릿, 번호 목록과 구분선을 마크다운 구조로 표시한다", () => {
    const wrapper = mount(AgentMessageContent, {
      props: {
        content: [
          "**핵심 정리**",
          "- **필수 역량**을 먼저 확인하세요.",
          "1. 공고를 읽습니다.",
          "2. 근거를 연결합니다.",
          "****",
          "일반 문단입니다.",
        ].join("\n"),
      },
    });

    expect(wrapper.get("h4").text()).toBe("핵심 정리");
    expect(wrapper.get("ul li strong").text()).toBe("필수 역량");
    expect(wrapper.findAll("ol li").map((item) => item.text())).toEqual([
      "공고를 읽습니다.",
      "근거를 연결합니다.",
    ]);
    expect(wrapper.find("hr").exists()).toBe(true);
    expect(wrapper.text()).not.toContain("**");
  });
});

describe("AgentWorkProductCard", () => {
  it("추천 공고 URL을 클릭 가능한 안전한 링크로 표시한다", () => {
    const wrapper = mount(AgentWorkProductCard, {
      props: {
        product: {
          agentId: "job_recommend",
          productType: "JOB_RECOMMENDATIONS",
          title: "공고 추천",
          reply: null,
          summary: "1. 예시기업 — https://example.com/jobs/1",
          findings: [],
          recommendations: [],
          followUpQuestions: [],
          replySources: [],
          suggestedActions: [],
          proposedActions: [],
          pendingConfirmation: null,
          artifact: null,
          data: {
            recommendations: [
              {
                companyName: "예시기업",
                title: "백엔드 개발자",
                url: "https://example.com/jobs/1",
              },
            ],
          },
        },
      },
    });

    const links = wrapper.findAll('a[href="https://example.com/jobs/1"]');
    expect(links.length).toBeGreaterThanOrEqual(2);
    expect(links.every((link) => link.attributes("target") === "_blank")).toBe(true);
    expect(links.every((link) => link.attributes("rel") === "noopener noreferrer")).toBe(true);
  });
});

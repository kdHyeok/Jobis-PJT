import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import AnalysisProgressWheel from "@/components/AnalysisProgressWheel.vue";
import type { AnalysisProgressEvent } from "@/types";

function skippedCriteriaEvent(): AnalysisProgressEvent {
  return {
    type: "PROGRESS",
    sequence: 1,
    progress: {
      contractVersion: "jobis.ai.v3alpha1",
      eventId: "event-criteria-skipped",
      jobId: "job-one",
      sequence: 1,
      stage: "AWAITING_POSTING_CONFIRMATION",
      status: "SKIPPED",
      label: "분석 기준 확인을 자동으로 통과했어요",
      detail: "AUTO_CONFIRMED: 확인한 분석 기준과 현재 공고 검토가 일치합니다.",
      occurredAt: "2026-08-09T00:00:00Z",
      elapsedMs: 1,
      warnings: [],
    },
  };
}

describe("AnalysisProgressWheel", () => {
  it("실행하지 않은 분석 기준을 완료가 아니라 자동 확인으로 표시한다", () => {
    const wrapper = mount(AnalysisProgressWheel, {
      props: {
        status: "SUCCEEDED",
        stage: "SUCCEEDED",
        compact: true,
        events: [skippedCriteriaEvent()],
      },
    });

    const rows = wrapper.findAll(".analysis-wheel__compact-details li");
    expect(rows[1].text()).toContain("분석 기준 확인");
    expect(rows[1].text()).toContain("자동 확인");
    expect(rows[1].classes()).toContain("skipped");
    expect(rows[0].text()).not.toContain("완료");
  });
});

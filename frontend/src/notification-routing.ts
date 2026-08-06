import type { RouteLocationRaw } from "vue-router";

import type { NotificationItem } from "@/types";

export function notificationDestination(item: NotificationItem): RouteLocationRaw {
  const analysisJobId =
    typeof item.payload.analysisJobId === "string" ? item.payload.analysisJobId : null;
  const postingId =
    typeof item.payload.postingId === "string" ? item.payload.postingId : null;
  const careerSourceId =
    typeof item.payload.careerSourceId === "string"
      ? item.payload.careerSourceId
      : null;
  const conversationId =
    typeof item.payload.conversationId === "string"
      ? item.payload.conversationId
      : null;
  const careerNodeId =
    typeof item.payload.careerNodeId === "string"
      ? item.payload.careerNodeId
      : null;

  if (careerSourceId) {
    return { name: "career-source-review", params: { sourceId: careerSourceId } };
  }
  if (postingId) {
    return { name: "posting-detail", params: { postingId } };
  }
  if (conversationId) {
    return { name: "chat", query: { conversationId } };
  }
  if (careerNodeId) {
    return { name: "map", query: { node: careerNodeId } };
  }
  if (item.type === "ANALYSIS_COMPLETED" && analysisJobId) {
    return { name: "chat", query: { analysisJobId } };
  }
  if (
    [
      "CAREER_MAP_UPDATED",
      "ROADMAP_UPDATED",
      "EVIDENCE_VERIFIED",
      "EVIDENCE_REJECTED",
      "EVIDENCE_VERIFICATION_FAILED",
      "COMPETENCY_ASSESSMENT_COMPLETED",
      "ASSESSMENT_REVIEW_RESOLVED",
    ].includes(
      item.type,
    )
  ) {
    return { name: "map" };
  }
  return { name: "activity" };
}

export function notificationTypeLabel(type: string) {
  const labels: Record<string, string> = {
    ANALYSIS_COMPLETED: "공고 분석 완료",
    ANALYSIS_FAILED: "공고 분석 실패",
    ANALYSIS_INPUT_REQUIRED: "추가 답변 필요",
    CAREER_MAP_UPDATED: "커리어 지도 변경",
    EVIDENCE_VERIFIED: "증거 검증 완료",
    EVIDENCE_REJECTED: "증거 보완 필요",
    CAREER_SOURCE_READY: "커리어 자료 검토",
    CAREER_SOURCE_FAILED: "커리어 자료 분석 실패",
    CHAT_REPLY_COMPLETED: "AI 답변 완료",
    CHAT_REPLY_FAILED: "AI 답변 실패",
    ROADMAP_UPDATED: "커리어 지도 적용",
    COMPETENCY_ASSESSMENT_COMPLETED: "역량 검증 결과",
    ASSESSMENT_REVIEW_RESOLVED: "검증 이의 처리",
    EVIDENCE_VERIFICATION_FAILED: "증거 검증 실패",
  };
  return labels[type] ?? "JOBIS 알림";
}

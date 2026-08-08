import assert from "node:assert/strict";
import test from "node:test";

import { buildJourneyModel } from "../src/roadmap/journey.ts";
import { adaptV3Snapshot } from "../src/roadmap/v3-adapter.ts";
import type { V3RoadmapNode, V3RoadmapSnapshot } from "../src/types.ts";


test("이스트게임즈 진입 기회와 네이버웹툰 경력 기회를 한 커리어 여정으로 투영한다", () => {
  const entryPostingId = "11111111-1111-4111-8111-111111111111";
  const experiencedPostingId = "22222222-2222-4222-8222-222222222222";
  const capability = (
    nodeId: string,
    canonicalKey: string,
    title: string,
    chapterKey: string,
    chapterTitle: string,
    targetRef: string,
    rank: number,
  ): V3RoadmapNode => ({
    nodeId,
    nodeKind: "CAPABILITY",
    canonicalKey,
    title,
    sectionKey: "section.web_backend",
    sectionMemberships: [{
      sectionKey: "section.web_backend",
      chapterKey,
      chapterTitle,
      targetRef,
      reason: "회사 프로젝트를 수행하기 위한 학습 범위입니다.",
    }],
    progressState: "NOT_STARTED",
    displayRank: rank,
  });
  const project = (
    nodeId: string,
    postingId: string,
    title: string,
    taskTitle: string,
    rank: number,
  ): V3RoadmapNode => ({
    nodeId,
    nodeKind: "TARGET_PROJECT",
    targetRef: `project:opportunity:${postingId}`,
    title,
    sectionKey: "section.web_backend",
    progressState: "NOT_STARTED",
    displayRank: rank,
    projectSpec: {
      objective: `${title}를 완성한다.`,
      domainContext: "웹 백엔드",
      deliverables: ["실행 가능한 저장소"],
      verificationCriteria: ["자동화 테스트가 통과한다."],
      requiredCapabilityKeys: ["java.classes-objects"],
      preferredCapabilityKeys: [],
      requiredProvisionalCandidateIds: [],
      preferredProvisionalCandidateIds: [],
      tasks: [{
        taskKey: `${nodeId}.task`,
        necessity: "REQUIRED",
        title: taskTitle,
        objective: "도메인 요구를 구현한다.",
        acceptanceCriteria: ["구현한다.", "테스트한다."],
        capabilityKeys: ["java.classes-objects"],
        requirementIds: ["req-java"],
        dependsOnTaskKeys: [],
      }],
    },
  });
  const opportunity = (
    nodeId: string,
    postingId: string,
    companyName: string,
    minimumExperienceMonths: number,
    maximumExperienceMonths: number | null,
    rank: number,
  ): V3RoadmapNode => ({
    nodeId,
    nodeKind: "OPPORTUNITY",
    targetRef: `opportunity:${postingId}`,
    title: `${companyName} 백엔드 지원`,
    sectionKey: "section.web_backend",
    progressState: "NOT_STARTED",
    displayRank: rank,
    opportunitySpec: {
      opportunityId: `opportunity:${postingId}`,
      companyName,
      positionTitle: "백엔드 개발자",
      minimumExperienceMonths,
      maximumExperienceMonths,
      postingStatus: "ACTIVE",
      goalMode: "ACTIVE_APPLICATION",
    },
  });

  const nodes: V3RoadmapNode[] = [
    capability("java", "java.classes-objects", "Java 객체 모델링", "chapter.language-framework", "언어 · 프레임워크", "stage.entry", 10),
    project("est-project", entryPostingId, "이스트게임즈 맞춤 프로젝트", "게임 구매 API 구현", 20),
    opportunity("est-opportunity", entryPostingId, "이스트게임즈", 0, null, 30),
    {
      nodeId: "employment", nodeKind: "EMPLOYMENT_EVENT", title: "관련 백엔드 취업",
      sectionKey: "section.web_backend", progressState: "NOT_STARTED", displayRank: 40,
      employmentSpec: { evidenceState: "UNKNOWN" },
    },
    {
      nodeId: "experience", nodeKind: "EXPERIENCE_INTERVAL", title: "관련 실무 경력 2~4년",
      sectionKey: "section.web_backend", progressState: "NOT_STARTED", displayRank: 50,
      experienceIntervalSpec: {
        minimumMonths: 24, maximumMonths: 48, accruedMonths: null, evidenceState: "UNKNOWN",
      },
    },
    capability("operations", "backend.incident-response", "장애 대응 심화", "chapter.engineering-depth", "설계 · 운영 심화", "stage.experience-24-48", 60),
    project("naver-project", experiencedPostingId, "네이버웹툰 맞춤 프로젝트", "유료 콘텐츠 정합성 구현", 70),
    opportunity("naver-opportunity", experiencedPostingId, "네이버웹툰", 24, 48, 80),
  ];
  const snapshot: V3RoadmapSnapshot = {
    roadmapVersion: 3,
    nodes,
    relations: [
      { relationId: "java-est", fromNodeId: "java", toNodeId: "est-project", relationType: "UNLOCKS_PROJECT", reason: "필수" },
      { relationId: "est-open", fromNodeId: "est-project", toNodeId: "est-opportunity", relationType: "UNLOCKS_OPPORTUNITY", reason: "완료" },
      { relationId: "est-employment", fromNodeId: "est-opportunity", toNodeId: "employment", relationType: "POTENTIAL_CAREER_ENTRY", reason: "진입 기회" },
      { relationId: "employment-experience", fromNodeId: "employment", toNodeId: "experience", relationType: "STARTS_EXPERIENCE", reason: "경력 시작" },
      { relationId: "operations-naver", fromNodeId: "operations", toNodeId: "naver-project", relationType: "UNLOCKS_PROJECT", reason: "필수" },
      { relationId: "naver-open", fromNodeId: "naver-project", toNodeId: "naver-opportunity", relationType: "UNLOCKS_OPPORTUNITY", reason: "완료" },
      { relationId: "experience-naver", fromNodeId: "experience", toNodeId: "naver-opportunity", relationType: "SATISFIES_EXPERIENCE_GATE", reason: "24~48개월" },
    ],
  };

  const adapted = adaptV3Snapshot(snapshot);
  const journey = buildJourneyModel(adapted.nodes, (node) => node.optional);
  const backend = journey.tracks.find((track) => track.domain === "BACKEND");

  assert.ok(backend);
  assert.deepEqual(backend.entry.branches.map((branch) => branch.opportunity.title), ["이스트게임즈 백엔드 지원"]);
  assert.equal(backend.experienceChapters.length, 1);
  assert.deepEqual(
    backend.experienceChapters[0].branches.map((branch) => branch.opportunity.title),
    ["네이버웹툰 백엔드 지원"],
  );
  assert.equal(adapted.nodes.some((node) => node.title === "게임 구매 API 구현"), false);
  assert.equal(adapted.nodes.find((node) => node.id === "est-project")?.project?.tasks[0].title, "게임 구매 API 구현");
});


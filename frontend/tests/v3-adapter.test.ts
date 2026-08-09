import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { adaptV3Snapshot, adaptV3Workspace } from "../src/roadmap/v3-adapter.ts";
import type { V3RoadmapNode, V3RoadmapSnapshot } from "../src/types.ts";

const postingId = "8b9c1a3e-1111-4222-8333-123456789abc";
const provisionalIds = [
  "candidate-network-security",
  "candidate-system-security",
  "candidate-vulnerability-analysis",
  "candidate-malware-analysis",
  "candidate-secure-c",
];

const careerJourneyFixture = JSON.parse(readFileSync(
  new URL("../../contract-fixtures/d047/career-journey-acceptance.json", import.meta.url),
  "utf8",
));
const d048Fixture = JSON.parse(readFileSync(
  new URL("../../contract-fixtures/scenarios/d048-estgames-naver-career-journey.json", import.meta.url),
  "utf8",
));

function capability(
  nodeId: string,
  title: string,
  options: { canonicalKey?: string; provisionalCandidateId?: string },
): V3RoadmapNode {
  return {
    nodeId,
    nodeKind: "CAPABILITY",
    title,
    ...options,
    sectionKey: "section.security",
    progressState: "NOT_STARTED",
    scopeDefinition: `${title} 원자 역량 범위`,
    displayRank: 0,
  };
}

function securitySnapshot(): V3RoadmapSnapshot {
  const provisionalNodes = provisionalIds.map((candidateId, index) => capability(
    `node-security-${index + 1}`,
    ["네트워크 보안", "시스템 보안", "취약점 분석", "악성코드 분석", "C 보안 개발"][index],
    { provisionalCandidateId: candidateId },
  ));
  const docker = capability("node-docker", "Docker", { canonicalKey: "docker.container-basics" });
  const project: V3RoadmapNode = {
    nodeId: "node-project",
    nodeKind: "TARGET_PROJECT",
    title: "보안 제품 분석 프로젝트",
    targetRef: `project:opportunity:${postingId}`,
    sectionKey: "section.security",
    progressState: "NOT_STARTED",
    displayRank: 1,
    projectSpec: {
      objective: "보안 공고의 필수 역량을 검증한다.",
      deliverables: ["분석 보고서", "실행 가능한 코드"],
      verificationCriteria: ["위협을 식별한다.", "대응 결과를 검증한다."],
      requiredCapabilityKeys: [],
      preferredCapabilityKeys: ["docker.container-basics"],
      requiredProvisionalCandidateIds: provisionalIds,
      preferredProvisionalCandidateIds: [],
      domainContext: "보안 제품",
      tasks: [],
    },
  };
  const opportunity: V3RoadmapNode = {
    nodeId: "node-opportunity",
    nodeKind: "OPPORTUNITY",
    title: "보안 개발자",
    targetRef: `opportunity:${postingId}`,
    sectionKey: "section.security",
    progressState: "NOT_STARTED",
    displayRank: 2,
    opportunitySpec: {
      opportunityId: `opportunity:${postingId}`,
      companyName: "보안회사",
      positionTitle: "보안 개발자",
      postingStatus: "ACTIVE",
      goalMode: "ACTIVE_APPLICATION",
    },
  };
  const relations = [
    ...provisionalNodes.map((node, index) => ({
      relationId: `edge-required-${index}`,
      fromNodeId: node.nodeId,
      toNodeId: project.nodeId,
      relationType: "UNLOCKS_PROJECT",
      reason: "필수 역량",
    })),
    {
      relationId: "edge-docker",
      fromNodeId: docker.nodeId,
      toNodeId: project.nodeId,
      relationType: "BONUS_SUPPORTS_PROJECT",
      reason: "우대 역량",
    },
    {
      relationId: "edge-opportunity",
      fromNodeId: project.nodeId,
      toNodeId: opportunity.nodeId,
      relationType: "UNLOCKS_OPPORTUNITY",
      reason: "프로젝트 완료 후 지원",
    },
  ];
  return {
    roadmapVersion: 2,
    nodes: [...provisionalNodes, docker, project, opportunity],
    relations,
  };
}

test("임시 필수 역량도 준비도와 회사 경로에 포함한다", () => {
  const adapted = adaptV3Snapshot(securitySnapshot());
  assert.equal(adapted.targets.length, 1);
  assert.deepEqual(adapted.targets[0], {
    postingId,
    companyName: "보안회사",
    roleTitle: "보안 개발자",
    completedRequired: 0,
    required: 5,
    completedPreferred: 0,
    preferred: 1,
    goalMode: "ACTIVE_APPLICATION",
    lifecycleStatus: "ACTIVE",
    closesAt: null,
  });

  const pendingGroup = adapted.nodes.find((node) =>
    node.id === "v3-chapter:SECURITY:chapter.pending-review:section.security");
  assert.ok(pendingGroup);
  assert.equal(pendingGroup.competencies.length, 5);
  assert.ok(pendingGroup.competencies.every((item) => item.catalogStatus === "PENDING_REVIEW"));
  assert.ok(pendingGroup.competencies.every(
    (item) => item.assessmentAvailability === "PENDING_REVIEW",
  ));
  assert.deepEqual(pendingGroup.postingIds, [postingId]);
  assert.equal(pendingGroup.requirementKinds?.[postingId], "REQUIRED");

  const broadDocker = adapted.nodes
    .flatMap((node) => node.competencies)
    .find((item) => item.canonicalKey === "docker.container-basics");
  assert.equal(broadDocker?.assessmentAvailability, "NOT_ATOMIC");
});

test("사용자 원자 역량으로 등록된 승인 노드만 검증 가능 상태로 노출한다", () => {
  const snapshot = securitySnapshot();
  const docker = snapshot.nodes.find((node) => node.canonicalKey === "docker.container-basics");
  assert.ok(docker);
  docker.technologyKey = "container.docker";
  docker.graphNodeVersion = 1;
  docker.verificationMethods = ["IMPLEMENT", "DEBUG"];
  docker.completionPolicy = "ASSESSMENT";
  docker.atomicAssessmentAvailable = true;

  const adapted = adaptV3Snapshot(snapshot);
  const approvedAtomic = adapted.nodes
    .flatMap((node) => node.competencies)
    .find((item) => item.canonicalKey === "docker.container-basics");

  assert.equal(approvedAtomic?.catalogStatus, "APPROVED");
  assert.equal(approvedAtomic?.assessmentAvailability, "AVAILABLE");
  assert.deepEqual(approvedAtomic?.verificationMethods, ["IMPLEMENT", "DEBUG"]);
});

test("V3가 전달한 필수·우대·기회 관계를 화면 관계로 보존한다", () => {
  const adapted = adaptV3Snapshot(securitySnapshot());
  assert.ok(adapted.edges.some((edge) =>
    edge.fromId === "v3-chapter:SECURITY:chapter.pending-review:section.security"
      && edge.toId === "node-project"
      && edge.kind === "PROJECT_PATH"));
  assert.ok(adapted.edges.some((edge) =>
    edge.fromId === "v3-chapter:SECURITY:chapter.legacy-core:section.security"
      && edge.toId === "node-project"
      && edge.kind === "OPTIONAL"));
  assert.ok(adapted.edges.some((edge) =>
    edge.fromId === "node-project"
      && edge.toId === "node-opportunity"
      && edge.kind === "OPPORTUNITY_PATH"));
});

test("변경 목록에는 내부 node ID 대신 제목과 검토 상태를 표시한다", () => {
  const snapshot = securitySnapshot();
  const workspace = adaptV3Workspace({
    currentRoadmap: { roadmapVersion: 1, nodes: [], relations: [] },
    draftProposal: {
      id: "proposal-db-id",
      analysisJobId: "analysis-id",
      contractProposalId: "proposal-contract-id",
      basedOnRoadmapVersion: 1,
      proposedRoadmapVersion: 2,
      status: "DRAFT",
      proposal: {},
      preview: {
        proposedRoadmapVersion: 2,
        snapshot,
        createdNodeIds: ["node-security-1", "node-project"],
        reusedNodeIds: [],
        createdRelationIds: [],
      },
      createdAt: "2026-08-05T00:00:00Z",
      updatedAt: "2026-08-05T00:00:00Z",
    },
  });
  assert.deepEqual(workspace.draft?.changes.added, [
    "네트워크 보안 · 검토 대기",
    "보안 제품 분석 프로젝트",
  ]);
});

test("신입 기회와 경력직 기회를 하나의 그래프에서 실제 취업·경력 구간으로 연결한다", () => {
  const entryPostingId = "11111111-1111-4111-8111-111111111111";
  const experiencedPostingId = "22222222-2222-4222-8222-222222222222";
  const snapshot: V3RoadmapSnapshot = {
    roadmapVersion: 3,
    nodes: [
      {
        nodeId: "entry-opportunity",
        nodeKind: "OPPORTUNITY",
        title: "Entry backend opportunity",
        targetRef: `opportunity:${entryPostingId}`,
        sectionKey: "section.web_backend",
        progressState: "NOT_STARTED",
        displayRank: 1,
        opportunitySpec: {
          opportunityId: `opportunity:${entryPostingId}`,
          companyName: "Entry Company",
          positionTitle: "Backend newcomer",
          postingStatus: "ACTIVE",
          goalMode: "ACTIVE_APPLICATION",
        },
      },
      {
        nodeId: "employment",
        nodeKind: "EMPLOYMENT_EVENT",
        title: "Related backend employment",
        sectionKey: "section.web_backend",
        progressState: "NOT_STARTED",
        displayRank: 2,
        employmentSpec: { evidenceState: "UNKNOWN" },
      },
      {
        nodeId: "experience-24-48",
        nodeKind: "EXPERIENCE_INTERVAL",
        title: "Related experience 2-4 years",
        sectionKey: "section.web_backend",
        progressState: "NOT_STARTED",
        displayRank: 3,
        experienceIntervalSpec: {
          minimumMonths: 24,
          maximumMonths: 48,
          accruedMonths: null,
          evidenceState: "UNKNOWN",
        },
      },
      {
        nodeId: "experienced-opportunity",
        nodeKind: "OPPORTUNITY",
        title: "Experienced backend opportunity",
        targetRef: `opportunity:${experiencedPostingId}`,
        sectionKey: "section.web_backend",
        progressState: "NOT_STARTED",
        displayRank: 4,
        opportunitySpec: {
          opportunityId: `opportunity:${experiencedPostingId}`,
          companyName: "Experienced Company",
          positionTitle: "Backend 2-4 years",
          postingStatus: "ACTIVE",
          goalMode: "ACTIVE_APPLICATION",
        },
      },
    ],
    relations: [
      {
        relationId: "entry-to-employment",
        fromNodeId: "entry-opportunity",
        toNodeId: "employment",
        relationType: "POTENTIAL_CAREER_ENTRY",
        reason: "A related entry role can start the experience clock.",
      },
      {
        relationId: "employment-to-experience",
        fromNodeId: "employment",
        toNodeId: "experience-24-48",
        relationType: "STARTS_EXPERIENCE",
        reason: "Verified employment starts related experience.",
      },
      {
        relationId: "experience-to-opportunity",
        fromNodeId: "experience-24-48",
        toNodeId: "experienced-opportunity",
        relationType: "SATISFIES_EXPERIENCE_GATE",
        reason: "Two to four years of related experience is required.",
      },
    ],
  };

  const adapted = adaptV3Snapshot(snapshot);
  assert.equal(adapted.targets.length, 2);
  assert.equal(adapted.nodes.find((node) => node.id === "employment")?.type, "EMPLOYMENT");
  const interval = adapted.nodes.find((node) => node.id === "experience-24-48");
  assert.equal(interval?.type, "EXPERIENCE");
  assert.match(interval?.subtitle ?? "", /24~48/);
  assert.deepEqual(
    adapted.edges.filter((edge) => edge.kind === "CAREER_PATH").map((edge) => [edge.fromId, edge.toId]),
    [
      ["entry-opportunity", "employment"],
      ["employment", "experience-24-48"],
      ["experience-24-48", "experienced-opportunity"],
    ],
  );
});

test("커리어 그래프 수용 fixture의 경력 범위와 보안 섹션을 보존한다", () => {
  const backend = careerJourneyFixture.scenarios.entryToExperiencedBackend;
  const security = careerJourneyFixture.scenarios.experiencedSecurity;

  assert.equal(backend.expectedJourney.experienceGate.minimumMonths, 24);
  assert.equal(backend.expectedJourney.experienceGate.maximumMonths, 48);
  assert.equal(security.expectedJourney.sectionKey, "section.security_engineering");
  assert.equal(security.expectedJourney.projectBeforeOpportunity, true);
});

test("프로젝트 과제 이름은 메인 학습 챕터 제목으로 사용하지 않는다", () => {
  const snapshot = securitySnapshot();
  snapshot.nodes[0].sectionMemberships = [{
    sectionKey: "section.security",
    chapterKey: "chapter.task:task.game-purchase",
    chapterTitle: "게임 구매 REST API 개발",
    targetRef: "stage.entry",
    reason: "프로젝트 과제에 필요합니다.",
  }];

  const adapted = adaptV3Snapshot(snapshot);

  assert.equal(adapted.nodes.some((node) => node.title === "게임 구매 REST API 개발"), false);
  assert.equal(adapted.nodes.some((node) => node.title === "직무 핵심 역량"), true);
  assert.equal(d048Fixture.expectedJourneyProjection.projectTasksRenderedOnOverview, false);
});

test("같은 원자 역량은 같은 직무 레인에서 가장 이른 경력 챕터에 한 번만 표시한다", () => {
  const snapshot = securitySnapshot();
  const docker = snapshot.nodes.find((node) => node.nodeId === "node-docker")!;
  docker.sectionMemberships = [
    {
      sectionKey: "section.security",
      chapterKey: "chapter.quality-delivery",
      chapterTitle: "테스트 · 품질 · 전달",
      targetRef: "stage.entry",
      reason: "신입 프로젝트에 필요합니다.",
    },
    {
      sectionKey: "section.security",
      chapterKey: "chapter.operations",
      chapterTitle: "운영 · 확장 · 메시징",
      targetRef: "stage.experience-48-plus",
      reason: "경력직 프로젝트에서도 재사용합니다.",
    },
  ];

  const adapted = adaptV3Snapshot(snapshot);
  const occurrences = adapted.nodes.flatMap((node) => node.competencies)
    .filter((competency) => competency.canonicalKey === "docker.container-basics");
  assert.equal(occurrences.length, 1);
  assert.equal(d048Fixture.sharedProgress.canonicalCapabilityStateCountPerUser, 1);
});

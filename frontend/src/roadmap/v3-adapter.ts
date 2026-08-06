import type {
  RoadmapCompetency,
  RoadmapNode,
  RoadmapSnapshot,
  RoadmapWorkspace,
  V3RoadmapNode,
  V3RoadmapSnapshot,
  V3RoadmapWorkspace,
} from "@/types";

type CapabilityMembership = NonNullable<V3RoadmapNode["sectionMemberships"]>[number];

function domainOf(sectionKey: string) {
  const normalized = sectionKey.replace(/^section\./, "").toUpperCase();
  if (normalized === "WEB_BACKEND") return "BACKEND";
  if (normalized === "WEB_FRONTEND") return "FRONTEND";
  if (normalized === "COMMON") return "COMMON";
  return normalized || "COMMON";
}

function membershipsOf(node: V3RoadmapNode): CapabilityMembership[] {
  if (node.sectionMemberships?.length) return node.sectionMemberships;
  const pending = Boolean(node.provisionalCandidateId);
  return [{
    sectionKey: node.sectionKey,
    chapterKey: pending ? "chapter.pending-review" : "chapter.legacy-core",
    chapterTitle: pending ? "검토 대기 역량" : "직무 기반 역량",
    targetRef: node.targetRef ?? node.sectionKey,
    reason: pending
      ? "공용 역량 사전 승인 전 사용자 범위에서 보존한 역량입니다."
      : "이전 지도에서 가져온 역량입니다.",
  }];
}

function provisionalRef(candidateId: string) {
  return `provisional.${candidateId}`;
}

function capabilityRef(node: V3RoadmapNode) {
  if (node.canonicalKey) return node.canonicalKey;
  if (node.provisionalCandidateId) return provisionalRef(node.provisionalCandidateId);
  return node.nodeId;
}

function progressStatus(value: V3RoadmapNode["progressState"]) {
  if (value === "VERIFIED") return "COMPLETED";
  if (value === "EVIDENCED" || value === "CLAIMED") return "IN_PROGRESS";
  return "AVAILABLE";
}

function postingIdOf(node: V3RoadmapNode) {
  const opportunity = node.opportunitySpec as Record<string, unknown> | undefined;
  const opportunityId = typeof opportunity?.opportunityId === "string"
    ? opportunity.opportunityId
    : node.targetRef;
  const match = opportunityId?.match(/([0-9a-f]{8}-[0-9a-f-]{27,})$/i);
  return match?.[1] ?? node.nodeId;
}

function competencyOf(node: V3RoadmapNode): RoadmapCompetency {
  return {
    id: node.nodeId,
    canonicalKey: capabilityRef(node),
    title: node.title,
    kind: "SKILL",
    scopeDefinition: node.scopeDefinition ?? node.objective ?? "세부 학습 범위가 아직 정의되지 않았습니다.",
    requiredLevel: node.level ?? 1,
    relation: "REQUIRED",
    progressStatus: progressStatus(node.progressState),
    verifiedLevel: node.progressState === "VERIFIED" ? node.level ?? 1 : 0,
    careerNodeId: null,
    source: "UNIFIED",
    v3NodeId: node.nodeId,
    completionPolicy: node.completionPolicy,
    verificationMethods: node.verificationMethods ?? [],
    excludedScope: node.excludedScope ?? [],
    provisionalCandidateId: node.provisionalCandidateId,
    catalogStatus: node.provisionalCandidateId ? "PENDING_REVIEW" : "APPROVED",
  };
}

function projectNode(node: V3RoadmapNode, postingId: string): RoadmapNode {
  const spec = node.projectSpec;
  return {
    id: node.nodeId,
    type: "PROJECT",
    title: node.title,
    subtitle: node.scopeDefinition ?? spec?.objective ?? null,
    domain: domainOf(node.sectionKey),
    stage: "PROJECT",
    rank: node.displayRank,
    optional: false,
    postingIds: [postingId],
    competencies: [],
    project: spec
      ? {
          title: node.title,
          objective: spec.objective,
          domainContext: spec.domainContext,
          requiredCompetencyKeys: [
            ...spec.requiredCapabilityKeys,
            ...(spec.requiredProvisionalCandidateIds ?? []).map(provisionalRef),
          ],
          optionalCompetencyKeys: [
            ...spec.preferredCapabilityKeys,
            ...(spec.preferredProvisionalCandidateIds ?? []).map(provisionalRef),
          ],
          deliverables: spec.deliverables,
          acceptanceCriteria: spec.verificationCriteria,
          tasks: spec.tasks ?? [],
        }
      : null,
    postingId,
    status: progressStatus(node.progressState),
    careerNodeId: node.careerNodeId ?? null,
    source: "UNIFIED",
    v3NodeId: node.nodeId,
  };
}

function opportunityNode(node: V3RoadmapNode, postingId: string): RoadmapNode {
  const spec = node.opportunitySpec as Record<string, unknown> | undefined;
  const goalMode = typeof spec?.goalMode === "string"
    ? spec.goalMode as RoadmapNode["goalMode"]
    : "REFERENCE_TARGET";
  const postingLifecycleStatus = typeof spec?.postingStatus === "string"
    ? spec.postingStatus as RoadmapNode["postingLifecycleStatus"]
    : "UNKNOWN";
  return {
    id: node.nodeId,
    type: "OPPORTUNITY",
    title: node.title,
    subtitle: typeof spec?.postingTitle === "string" ? spec.postingTitle : null,
    domain: domainOf(node.sectionKey),
    stage: "OPPORTUNITY",
    rank: node.displayRank,
    optional: false,
    postingIds: [postingId],
    competencies: [],
    project: null,
    postingId,
    status: progressStatus(node.progressState),
    careerNodeId: null,
    source: "UNIFIED",
    v3NodeId: node.nodeId,
    goalMode,
    postingLifecycleStatus,
    applicationDeadline: typeof spec?.applicationDeadline === "string"
      ? spec.applicationDeadline
      : null,
  };
}

function gateNode(node: V3RoadmapNode, postingIds: string[]): RoadmapNode {
  const spec = node.gateSpec as Record<string, unknown> | undefined;
  const gateType = typeof spec?.gateType === "string" ? spec.gateType : "OTHER";
  const requiredMonths = typeof spec?.requiredMonths === "number" ? spec.requiredMonths : null;
  const maximumMonths = typeof spec?.maximumMonths === "number" ? spec.maximumMonths : null;
  return {
    id: node.nodeId,
    type: "GATE",
    title: node.title,
    subtitle: requiredMonths
      ? maximumMonths
        ? `${requiredMonths}~${maximumMonths}개월의 관련 실무 경력 조건입니다.`
        : `${requiredMonths}개월의 관련 실무 경력 조건입니다.`
      : node.scopeDefinition ?? null,
    domain: domainOf(node.sectionKey),
    stage: gateType,
    rank: node.displayRank,
    optional: false,
    postingIds,
    competencies: [],
    project: null,
    postingId: postingIds[0] ?? null,
    status: progressStatus(node.progressState),
    careerNodeId: null,
    source: "UNIFIED",
    v3NodeId: node.nodeId,
  };
}

function careerEvidenceNode(node: V3RoadmapNode): RoadmapNode {
  const employment = node.employmentSpec;
  const interval = node.experienceIntervalSpec;
  const isEmployment = node.nodeKind === "EMPLOYMENT_EVENT";
  const evidenceState = typeof (employment ?? interval)?.evidenceState === "string"
    ? String((employment ?? interval)?.evidenceState)
    : "UNKNOWN";
  const minimumMonths = typeof interval?.minimumMonths === "number"
    ? interval.minimumMonths
    : null;
  const maximumMonths = typeof interval?.maximumMonths === "number"
    ? interval.maximumMonths
    : null;
  const accruedMonths = typeof interval?.accruedMonths === "number"
    ? interval.accruedMonths
    : null;
  return {
    id: node.nodeId,
    type: isEmployment ? "EMPLOYMENT" : "EXPERIENCE",
    title: node.title,
    subtitle: isEmployment
      ? "실제 관련 직무 취업 증거가 확인되어야 경력이 시작됩니다."
      : accruedMonths === null
        ? minimumMonths === null
          ? "관련 경력 기간 조건을 확인 중입니다 · 현재 경력은 아직 확인되지 않았습니다."
          : maximumMonths === null
            ? `관련 경력 ${minimumMonths}개월 이상 · 현재 경력은 아직 확인되지 않았습니다.`
            : `관련 경력 ${minimumMonths}~${maximumMonths}개월 · 현재 경력은 아직 확인되지 않았습니다.`
        : `확인된 관련 경력 ${accruedMonths}개월`,
    domain: domainOf(node.sectionKey),
    stage: isEmployment ? "EMPLOYMENT" : "EXPERIENCE",
    rank: node.displayRank,
    optional: false,
    postingIds: [],
    competencies: [],
    project: null,
    postingId: null,
    status: evidenceState === "VERIFIED" || node.progressState === "VERIFIED"
      ? "COMPLETED"
      : evidenceState === "EVIDENCED" || node.progressState === "EVIDENCED"
        ? "IN_PROGRESS"
        : "LOCKED",
    careerNodeId: null,
    source: "UNIFIED",
    v3NodeId: node.nodeId,
  };
}

function edgeKind(relationType: string): RoadmapSnapshot["edges"][number]["kind"] {
  if (relationType === "BONUS_SUPPORTS_PROJECT" || relationType === "ALTERNATIVE_TO") {
    return "OPTIONAL";
  }
  if (relationType === "UNLOCKS_PROJECT") return "PROJECT_PATH";
  if (relationType === "UNLOCKS_OPPORTUNITY") return "OPPORTUNITY_PATH";
  if (
    relationType === "REQUIRES_GATE"
    || relationType === "CAREER_STAGE_ORDER"
    || relationType === "POTENTIAL_CAREER_ENTRY"
    || relationType === "STARTS_EXPERIENCE"
    || relationType === "SATISFIES_EXPERIENCE_GATE"
  ) {
    return "CAREER_PATH";
  }
  return "PREREQUISITE";
}

export function adaptV3Snapshot(snapshot: V3RoadmapSnapshot): RoadmapSnapshot {
  const opportunities = snapshot.nodes.filter((node) => node.nodeKind === "OPPORTUNITY");
  const opportunityIds = new Map(opportunities.map((node) => [node.targetRef, postingIdOf(node)]));
  const opportunityPostingByNodeId = new Map(
    opportunities.map((node) => [node.nodeId, postingIdOf(node)]),
  );
  const projects = snapshot.nodes.filter((node) => node.nodeKind === "TARGET_PROJECT");
  const gates = snapshot.nodes.filter((node) => node.nodeKind === "CAREER_GATE");
  const careerEvidenceNodes = snapshot.nodes.filter(
    (node) => node.nodeKind === "EMPLOYMENT_EVENT" || node.nodeKind === "EXPERIENCE_INTERVAL",
  );
  const projectPostingIds = new Map<string, string>();
  for (const project of projects) {
    const target = project.targetRef?.replace(/^project:/, "");
    projectPostingIds.set(
      project.nodeId,
      opportunityIds.get(target) ?? postingIdOf(project),
    );
  }

  const capabilityPostingIds = new Map<string, Set<string>>();
  const capabilityRequirementKinds = new Map<string, Record<string, "REQUIRED" | "PREFERRED">>();
  for (const project of projects) {
    const postingId = projectPostingIds.get(project.nodeId)!;
    for (const key of project.projectSpec?.requiredCapabilityKeys ?? []) {
      const ids = capabilityPostingIds.get(key) ?? new Set<string>();
      ids.add(postingId);
      capabilityPostingIds.set(key, ids);
      capabilityRequirementKinds.set(key, {
        ...(capabilityRequirementKinds.get(key) ?? {}),
        [postingId]: "REQUIRED",
      });
    }
    for (const key of project.projectSpec?.preferredCapabilityKeys ?? []) {
      const ids = capabilityPostingIds.get(key) ?? new Set<string>();
      ids.add(postingId);
      capabilityPostingIds.set(key, ids);
      capabilityRequirementKinds.set(key, {
        ...(capabilityRequirementKinds.get(key) ?? {}),
        [postingId]: "PREFERRED",
      });
    }
    for (const candidateId of project.projectSpec?.requiredProvisionalCandidateIds ?? []) {
      const key = provisionalRef(candidateId);
      const ids = capabilityPostingIds.get(key) ?? new Set<string>();
      ids.add(postingId);
      capabilityPostingIds.set(key, ids);
      capabilityRequirementKinds.set(key, {
        ...(capabilityRequirementKinds.get(key) ?? {}),
        [postingId]: "REQUIRED",
      });
    }
    for (const candidateId of project.projectSpec?.preferredProvisionalCandidateIds ?? []) {
      const key = provisionalRef(candidateId);
      const ids = capabilityPostingIds.get(key) ?? new Set<string>();
      ids.add(postingId);
      capabilityPostingIds.set(key, ids);
      capabilityRequirementKinds.set(key, {
        ...(capabilityRequirementKinds.get(key) ?? {}),
        [postingId]: "PREFERRED",
      });
    }
  }

  const result: RoadmapNode[] = [];
  const displayNodesBySourceNode = new Map<string, string[]>();
  const addDisplayProjection = (sourceNodeId: string, displayNodeId: string) => {
    const values = displayNodesBySourceNode.get(sourceNodeId) ?? [];
    if (!values.includes(displayNodeId)) values.push(displayNodeId);
    displayNodesBySourceNode.set(sourceNodeId, values);
  };
  const foundations = snapshot.nodes
    .filter((node) => node.nodeKind === "CAPABILITY" && domainOf(node.sectionKey) === "COMMON")
    .sort((left, right) => left.title.localeCompare(right.title, "ko"));
  foundations.forEach((node) => {
    result.push({
      id: node.nodeId,
      type: "MILESTONE",
      title: node.title,
      subtitle: node.scopeDefinition ?? null,
      domain: "COMMON",
      stage: "FOUNDATION",
      rank: node.displayRank,
      optional: false,
      postingIds: [],
      competencies: [competencyOf(node)],
      project: null,
      postingId: null,
      status: progressStatus(node.progressState),
      careerNodeId: null,
      source: "UNIFIED",
      v3NodeId: node.nodeId,
    });
    addDisplayProjection(node.nodeId, node.nodeId);
  });

  const grouped = new Map<string, {
    membership: CapabilityMembership;
    domain: string;
    nodes: V3RoadmapNode[];
  }>();
  for (const node of snapshot.nodes.filter((item) => item.nodeKind === "CAPABILITY")) {
    for (const membership of membershipsOf(node)) {
      const domain = domainOf(membership.sectionKey);
      // The primary COMMON node is already rendered as a foundation. Explicit
      // role memberships may still project the same canonical capability into
      // a backend/security project chapter without duplicating progress state.
      if (domain === "COMMON" && domainOf(node.sectionKey) === "COMMON") continue;
      const key = `${domain}:${membership.chapterKey}:${membership.targetRef}`;
      const bucket = grouped.get(key) ?? { membership, domain, nodes: [] };
      if (!bucket.nodes.some((item) => item.nodeId === node.nodeId)) bucket.nodes.push(node);
      grouped.set(key, bucket);
    }
  }

  [...grouped.values()]
    .sort((left, right) => {
      const leftRank = Math.min(...left.nodes.map((node) => node.displayRank));
      const rightRank = Math.min(...right.nodes.map((node) => node.displayRank));
      return leftRank - rightRank
        || left.membership.chapterTitle.localeCompare(right.membership.chapterTitle, "ko");
    })
    .forEach((bucket) => {
      const competencies = bucket.nodes
        .sort((left, right) => left.displayRank - right.displayRank || left.title.localeCompare(right.title, "ko"))
        .map(competencyOf);
      const postingIds = [...new Set(bucket.nodes.flatMap((node) => [
        ...(capabilityPostingIds.get(capabilityRef(node)) ?? []),
      ]))];
      const requirementKinds = Object.assign(
        {},
        ...bucket.nodes.map((node) => capabilityRequirementKinds.get(capabilityRef(node)) ?? {}),
      );
      const completed = competencies.every((item) => item.progressStatus === "COMPLETED");
      const started = competencies.some((item) => item.progressStatus !== "AVAILABLE");
      const groupId = `v3-chapter:${bucket.domain}:${bucket.membership.chapterKey}:${bucket.membership.targetRef}`;
      result.push({
        id: groupId,
        type: "MILESTONE",
        title: bucket.membership.chapterTitle,
        subtitle: `${bucket.membership.reason} · ${competencies.length}개 원자 역량`,
        domain: bucket.domain,
        stage: "SKILL",
        rank: Math.min(...bucket.nodes.map((node) => node.displayRank)),
        optional: Boolean(postingIds.length) && Object.values(requirementKinds).every((value) => value === "PREFERRED"),
        postingIds,
        competencies,
        project: null,
        postingId: null,
        status: completed ? "COMPLETED" : started ? "IN_PROGRESS" : "AVAILABLE",
        careerNodeId: null,
        requirementKinds,
        source: "UNIFIED",
      });
      bucket.nodes.forEach((node) => addDisplayProjection(node.nodeId, groupId));
    });

  for (const project of projects) {
    const node = projectNode(project, projectPostingIds.get(project.nodeId)!);
    result.push(node);
    addDisplayProjection(project.nodeId, node.id);
  }
  for (const gate of gates) {
    const postingIds = snapshot.relations
      .filter((relation) => relation.fromNodeId === gate.nodeId && relation.relationType === "REQUIRES_GATE")
      .map((relation) => opportunityPostingByNodeId.get(relation.toNodeId))
      .filter((value): value is string => Boolean(value));
    const node = gateNode(gate, [...new Set(postingIds)]);
    result.push(node);
    addDisplayProjection(gate.nodeId, node.id);
  }
  for (const source of careerEvidenceNodes) {
    const node = careerEvidenceNode(source);
    result.push(node);
    addDisplayProjection(source.nodeId, node.id);
  }
  for (const opportunity of opportunities) {
    const node = opportunityNode(opportunity, postingIdOf(opportunity));
    result.push(node);
    addDisplayProjection(opportunity.nodeId, node.id);
  }

  const edgeKeys = new Set<string>();
  const edges = snapshot.relations.flatMap((relation) => {
    const fromIds = displayNodesBySourceNode.get(relation.fromNodeId) ?? [];
    const toIds = displayNodesBySourceNode.get(relation.toNodeId) ?? [];
    const kind = edgeKind(relation.relationType);
    const candidates = fromIds.flatMap((fromId) => toIds.map((toId) => ({ fromId, toId })));
    const sameDomain = candidates.filter(({ fromId, toId }) => {
      const from = result.find((node) => node.id === fromId);
      const to = result.find((node) => node.id === toId);
      return from && to && from.domain === to.domain;
    });
    const selected = sameDomain.length ? sameDomain : candidates.slice(0, 1);
    return selected.flatMap(({ fromId, toId }) => {
      if (fromId === toId) return [];
      const key = `${fromId}|${toId}|${kind}`;
      if (edgeKeys.has(key)) return [];
      edgeKeys.add(key);
      return [{ fromId, toId, kind }];
    });
  });
  const targets = opportunities.map((node) => {
    const spec = node.opportunitySpec as Record<string, unknown> | undefined;
    const postingId = postingIdOf(node);
    const project = projects.find((item) => projectPostingIds.get(item.nodeId) === postingId);
    const requiredKeys = project?.projectSpec?.requiredCapabilityKeys ?? [];
    const preferredKeys = project?.projectSpec?.preferredCapabilityKeys ?? [];
    const requiredProvisional = (project?.projectSpec?.requiredProvisionalCandidateIds ?? [])
      .map(provisionalRef);
    const preferredProvisional = (project?.projectSpec?.preferredProvisionalCandidateIds ?? [])
      .map(provisionalRef);
    const requiredRefs = [...requiredKeys, ...requiredProvisional];
    const preferredRefs = [...preferredKeys, ...preferredProvisional];
    const verifiedKeys = new Set(
      snapshot.nodes
        .filter((item) => item.nodeKind === "CAPABILITY" && item.progressState === "VERIFIED")
        .map(capabilityRef),
    );
    return {
      postingId,
      companyName: typeof spec?.companyName === "string" ? spec.companyName : node.title,
      roleTitle: typeof spec?.positionTitle === "string" ? spec.positionTitle : node.title,
      completedRequired: requiredRefs.filter((key) => verifiedKeys.has(key)).length,
      required: requiredRefs.length,
      completedPreferred: preferredRefs.filter((key) => verifiedKeys.has(key)).length,
      preferred: preferredRefs.length,
      goalMode: typeof spec?.goalMode === "string"
        ? spec.goalMode as RoadmapSnapshot["targets"][number]["goalMode"]
        : "REFERENCE_TARGET",
      lifecycleStatus: typeof spec?.postingStatus === "string"
        ? spec.postingStatus as RoadmapSnapshot["targets"][number]["lifecycleStatus"]
        : "UNKNOWN",
      closesAt: typeof spec?.applicationDeadline === "string"
        ? spec.applicationDeadline
        : null,
    };
  });
  return {
    version: snapshot.roadmapVersion,
    title: "나의 통합 커리어 여정",
    nodes: result,
    edges,
    targets,
  };
}

export function adaptV3Workspace(workspace: V3RoadmapWorkspace): RoadmapWorkspace {
  const current = adaptV3Snapshot(workspace.currentRoadmap);
  const preview = workspace.draftProposal?.preview;
  const changeLabel = (nodeId: string) => {
    const node = preview?.snapshot.nodes.find((item) => item.nodeId === nodeId)
      ?? workspace.currentRoadmap.nodes.find((item) => item.nodeId === nodeId);
    if (!node) return nodeId;
    return node.provisionalCandidateId ? `${node.title} · 검토 대기` : node.title;
  };
  return {
    current,
    draft: workspace.draftProposal && preview
      ? {
          id: workspace.draftProposal.id,
          version: preview.proposedRoadmapVersion,
          changes: {
            added: preview.createdNodeIds.map(changeLabel),
            removed: (preview.removedNodeIds ?? []).map(changeLabel),
            retained: preview.reusedNodeIds.map(changeLabel),
          },
          snapshot: adaptV3Snapshot(preview.snapshot),
          createdAt: workspace.draftProposal.createdAt,
        }
      : null,
    targetCount: current.targets.length,
  };
}

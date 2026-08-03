import type { RoadmapNode } from "@/types";

export type JourneyBranch = {
  id: string;
  postingId: string;
  project: RoadmapNode | null;
  opportunity: RoadmapNode;
};

export type JourneyChapter = {
  id: string;
  title: string;
  eyebrow: string;
  rank: number;
  gateNode: RoadmapNode | null;
  requiredNodes: RoadmapNode[];
  bonusNodes: RoadmapNode[];
  branches: JourneyBranch[];
};

export type JourneyTrack = {
  domain: string;
  label: string;
  employmentGate: RoadmapNode | null;
  entry: JourneyChapter;
  experienceChapters: JourneyChapter[];
};

export type JourneyModel = {
  foundations: RoadmapNode[];
  tracks: JourneyTrack[];
};

const TRACK_LABELS: Record<string, string> = {
  BACKEND: "백엔드",
  FRONTEND: "프론트엔드",
  FULLSTACK: "풀스택",
  DATA: "데이터",
  AI: "AI",
  CLOUD: "클라우드",
  DEVOPS: "DevOps",
  SECURITY: "보안",
  GAME: "게임",
  MOBILE: "모바일",
  DOMAIN: "도메인",
  CAREER: "커리어",
};

function domainOf(node: RoadmapNode) {
  return node.domain?.trim().toUpperCase() || "COMMON";
}

function isExperienceGate(node: RoadmapNode) {
  return (
    node.type === "MILESTONE" &&
    node.stage === "EXPERIENCE" &&
    node.id.startsWith("career:")
  );
}

function chapterForRank(
  rank: number,
  experienceGates: RoadmapNode[],
) {
  return (
    [...experienceGates]
      .reverse()
      .find((gate) => gate.rank < rank) ?? null
  );
}

function ordered(nodes: RoadmapNode[]) {
  return [...nodes].sort(
    (left, right) =>
      left.rank - right.rank || left.title.localeCompare(right.title),
  );
}

function relationAwareGroups(
  nodes: RoadmapNode[],
  isOptional: (node: RoadmapNode) => boolean,
) {
  return {
    requiredNodes: ordered(nodes.filter((node) => !isOptional(node))),
    bonusNodes: ordered(nodes.filter((node) => isOptional(node))),
  };
}

function branchesForChapter(
  opportunities: RoadmapNode[],
  projectsByPosting: Map<string, RoadmapNode>,
  chapterGate: RoadmapNode | null,
  experienceGates: RoadmapNode[],
) {
  return opportunities
    .filter(
      (opportunity) =>
        chapterForRank(opportunity.rank, experienceGates)?.id ===
        chapterGate?.id,
    )
    .map((opportunity) => ({
      id: `branch:${opportunity.postingId ?? opportunity.id}`,
      postingId: opportunity.postingId ?? opportunity.id,
      project: opportunity.postingId
        ? projectsByPosting.get(opportunity.postingId) ?? null
        : null,
      opportunity,
    }))
    .sort(
      (left, right) =>
        left.opportunity.rank - right.opportunity.rank ||
        left.opportunity.title.localeCompare(right.opportunity.title),
    );
}

export function buildJourneyModel(
  nodes: RoadmapNode[],
  isOptional: (node: RoadmapNode) => boolean,
): JourneyModel {
  const foundations = ordered(
    nodes.filter(
      (node) =>
        domainOf(node) === "COMMON" && node.stage === "FOUNDATION",
    ),
  );
  const domains = [...new Set(
    nodes
      .map(domainOf)
      .filter((domain) => domain !== "COMMON"),
  )];

  const tracks = domains.map((domain): JourneyTrack => {
    const trackNodes = ordered(
      nodes.filter((node) => domainOf(node) === domain),
    );
    const employmentGate =
      trackNodes.find(
        (node) =>
          node.type === "GATE" && node.stage === "EMPLOYMENT",
      ) ?? null;
    const experienceGates = ordered(
      trackNodes.filter(isExperienceGate),
    );
    const questNodes = trackNodes.filter(
      (node) =>
        node.type === "MILESTONE" &&
        !isExperienceGate(node),
    );
    const opportunities = trackNodes.filter(
      (node) => node.type === "OPPORTUNITY",
    );
    const projectsByPosting = new Map(
      trackNodes
        .filter(
          (node): node is RoadmapNode & { postingId: string } =>
            node.type === "PROJECT" && Boolean(node.postingId),
        )
        .map((node) => [node.postingId, node]),
    );

    const entryQuestNodes = questNodes.filter(
      (node) => chapterForRank(node.rank, experienceGates) === null,
    );
    const entryGroups = relationAwareGroups(
      entryQuestNodes,
      isOptional,
    );
    const label = TRACK_LABELS[domain] ?? domain;
    const entry: JourneyChapter = {
      id: `${domain}:entry`,
      title: `${label} 진입 준비`,
      eyebrow: "ENTRY PATH",
      rank: entryQuestNodes[0]?.rank ?? employmentGate?.rank ?? 0,
      gateNode: null,
      ...entryGroups,
      branches: branchesForChapter(
        opportunities,
        projectsByPosting,
        null,
        experienceGates,
      ),
    };

    const experienceChapters = experienceGates.map(
      (gate, index): JourneyChapter => {
        const chapterQuestNodes = questNodes.filter(
          (node) =>
            chapterForRank(node.rank, experienceGates)?.id === gate.id,
        );
        return {
          id: `${domain}:experience:${gate.id}`,
          title: gate.title,
          eyebrow: `CAREER LEVEL ${index + 1}`,
          rank: gate.rank,
          gateNode: gate,
          ...relationAwareGroups(chapterQuestNodes, isOptional),
          branches: branchesForChapter(
            opportunities,
            projectsByPosting,
            gate,
            experienceGates,
          ),
        };
      },
    );

    return {
      domain,
      label,
      employmentGate,
      entry,
      experienceChapters,
    };
  });

  return { foundations, tracks };
}

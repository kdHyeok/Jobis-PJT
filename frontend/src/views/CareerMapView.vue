<script setup lang="ts">
import {
  BookOpen,
  BrainCircuit,
  Check,
  ChevronRight,
  CircleDot,
  Cloud,
  Code2,
  Database,
  Flag,
  Gamepad2,
  GitBranch,
  Globe2,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  Maximize2,
  Minus,
  Plus,
  RefreshCw,
  Rocket,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Target,
  Trash2,
  X,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { api } from "@/api";
import JourneyMap from "@/components/JourneyMap.vue";
import JobissGuide from "@/components/JobissGuide.vue";
import { buildJourneyModel } from "@/roadmap/journey";
import type {
  CompetencyAssessment,
  Evidence,
  RoadmapCompetency,
  RoadmapNode,
  RoadmapSnapshot,
  RoadmapWorkspace,
} from "@/types";

type PositionedNode = RoadmapNode & { x: number; y: number };
type DomainSection = {
  key: string;
  label: string;
  color: string;
  y: number;
  height: number;
  nodeCount: number;
};

const domainOrder = [
  "COMMON",
  "BACKEND",
  "FRONTEND",
  "FULLSTACK",
  "DATA",
  "AI",
  "CLOUD",
  "DEVOPS",
  "SECURITY",
  "GAME",
  "MOBILE",
  "DOMAIN",
  "CAREER",
];

const domainMeta: Record<
  string,
  { label: string; color: string; icon: typeof Code2 }
> = {
  COMMON: { label: "공통 역량", color: "#1cb0f6", icon: Globe2 },
  BACKEND: { label: "백엔드", color: "#58cc02", icon: ServerCog },
  FRONTEND: { label: "프론트엔드", color: "#ce82ff", icon: Code2 },
  FULLSTACK: { label: "풀스택", color: "#ff9600", icon: Layers3 },
  DATA: { label: "데이터", color: "#2b70c9", icon: Database },
  AI: { label: "AI", color: "#a560e8", icon: Sparkles },
  CLOUD: { label: "클라우드", color: "#00a6d7", icon: Cloud },
  DEVOPS: { label: "DevOps", color: "#ffc800", icon: GitBranch },
  SECURITY: { label: "보안", color: "#ff4b4b", icon: ShieldCheck },
  GAME: { label: "게임", color: "#ff6b9d", icon: Gamepad2 },
  MOBILE: { label: "모바일", color: "#6c7cff", icon: Code2 },
  DOMAIN: { label: "회사·도메인", color: "#ff6b9d", icon: Target },
  CAREER: { label: "경력·자격", color: "#ff9600", icon: Flag },
};

const route = useRoute();
const workspace = ref<RoadmapWorkspace | null>(null);
const previewDraft = ref(false);
const viewMode = ref<"JOURNEY" | "GRAPH">("JOURNEY");
const selectedNode = ref<RoadmapNode | null>(null);
const applyConfirmOpen = ref(false);
const selectedPostingId = ref<string | null>(
  typeof route.query.posting === "string" ? route.query.posting : null,
);
const loading = ref(true);
const actionLoading = ref(false);
const error = ref("");
const evidence = ref<Evidence[]>([]);
const evidenceCompetency = ref<RoadmapCompetency | null>(null);
const assessment = ref<CompetencyAssessment | null>(null);
const assessmentAnswer = ref("");
const assessmentReviewReason = ref("");
const evidenceTitle = ref("");
const evidenceUrl = ref("");
const evidenceDescription = ref("");
const canvasViewport = ref<HTMLElement | null>(null);
const zoom = ref(1);
const isPanning = ref(false);
let panPointerId: number | null = null;
let panStartX = 0;
let panStartY = 0;
let panStartScrollLeft = 0;
let panStartScrollTop = 0;

const snapshot = computed<RoadmapSnapshot | null>(() => {
  if (!workspace.value) return null;
  if (previewDraft.value && workspace.value.draft) {
    return workspace.value.draft.snapshot;
  }
  return workspace.value.current;
});

const visibleNodes = computed(() => {
  const nodes = snapshot.value?.nodes ?? [];
  if (!selectedPostingId.value) return nodes;
  return nodes.filter(
    (node) =>
      node.postingIds.length === 0 ||
      node.postingIds.includes(selectedPostingId.value!) ||
      node.postingId === selectedPostingId.value,
  );
});

const journeyModel = computed(() =>
  buildJourneyModel(visibleNodes.value, nodeIsOptional),
);

const nextJourneyNode = computed(() =>
  [...visibleNodes.value]
    .filter((node) => !nodeIsOptional(node))
    .filter((node) => node.type === "MILESTONE" || node.type === "PROJECT")
    .filter((node) => node.status !== "COMPLETED" && node.status !== "LOCKED")
    .sort(
      (left, right) =>
        left.rank - right.rank || left.title.localeCompare(right.title),
    )[0] ?? null,
);

function normalizedDomain(domain: string | null | undefined) {
  const value = domain?.trim().toUpperCase();
  return value || "COMMON";
}

function nodeIsOptional(node: RoadmapNode) {
  if (selectedPostingId.value) {
    const relation = node.requirementKinds?.[selectedPostingId.value];
    if (relation) return relation === "PREFERRED";
  }
  return node.optional;
}

function nodeLaneKey(node: RoadmapNode) {
  if (node.postingId) return `2:${node.postingId}`;
  if (node.postingIds.length) {
    return `1:${[...node.postingIds].sort().join(",")}:${node.id}`;
  }
  return `0:${node.id}`;
}

const mapLayout = computed<{
  nodes: PositionedNode[];
  sections: DomainSection[];
  height: number;
}>(() => {
  const domains = [...new Set(visibleNodes.value.map((node) => normalizedDomain(node.domain)))]
    .sort((left, right) => {
      const leftIndex = domainOrder.indexOf(left);
      const rightIndex = domainOrder.indexOf(right);
      if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
      if (leftIndex === -1) return 1;
      if (rightIndex === -1) return -1;
      return leftIndex - rightIndex;
    });

  const positioned: PositionedNode[] = [];
  const sections: DomainSection[] = [];
  let sectionTop = 24;

  domains.forEach((domain) => {
    const domainNodes = visibleNodes.value.filter(
      (node) => normalizedDomain(node.domain) === domain,
    );
    const nodesByRank = new Map<number, RoadmapNode[]>();
    domainNodes.forEach((node) => {
      const bucket = nodesByRank.get(node.rank) ?? [];
      bucket.push(node);
      nodesByRank.set(node.rank, bucket);
    });
    nodesByRank.forEach((bucket) => {
      bucket.sort((left, right) => {
        const leftOptional = nodeIsOptional(left);
        const rightOptional = nodeIsOptional(right);
        if (leftOptional !== rightOptional) return leftOptional ? 1 : -1;
        return nodeLaneKey(left).localeCompare(nodeLaneKey(right));
      });
    });
    let maximumLocalY = 82;
    const localPositions = domainNodes.map((node) => {
      const bucket = nodesByRank.get(node.rank) ?? [node];
      const lane = Math.max(0, bucket.findIndex((item) => item.id === node.id));
      const localY = 82 + lane * 180;
      maximumLocalY = Math.max(maximumLocalY, localY);
      return { node, localY };
    });
    const sectionHeight = Math.max(290, maximumLocalY + 168);
    const meta = domainMeta[domain] ?? {
      label: domain,
      color: "#777777",
      icon: Code2,
    };
    sections.push({
      key: domain,
      label: meta.label,
      color: meta.color,
      y: sectionTop,
      height: sectionHeight,
      nodeCount: domainNodes.length,
    });
    localPositions.forEach(({ node, localY }) => {
      positioned.push({
        ...node,
        x: 90 + node.rank * 210,
        y: sectionTop + localY,
      });
    });
    sectionTop += sectionHeight + 28;
  });

  return {
    nodes: positioned,
    sections,
    height: Math.max(460, sectionTop + 12),
  };
});

const positionedNodes = computed(() => mapLayout.value.nodes);
const domainSections = computed(() => mapLayout.value.sections);

const nodePositions = computed(
  () => new Map(positionedNodes.value.map((node) => [node.id, node])),
);

const visibleEdges = computed(() =>
  (snapshot.value?.edges ?? [])
    .map((edge) => {
      const from = nodePositions.value.get(edge.fromId);
      const to = nodePositions.value.get(edge.toId);
      if (!from || !to) return null;
      return {
        ...edge,
        x1: from.x + 90,
        y1: from.y + 43,
        x2: to.x + 90,
        y2: to.y + 43,
        completed:
          from.status === "COMPLETED" && to.status === "COMPLETED",
        available:
          from.status === "COMPLETED" &&
          ["AVAILABLE", "IN_PROGRESS", "NOT_STARTED"].includes(to.status),
      };
    })
    .filter((edge): edge is NonNullable<typeof edge> => Boolean(edge)),
);

const canvasWidth = computed(() => {
  const maxRank = Math.max(3, ...positionedNodes.value.map((node) => node.rank));
  return 320 + maxRank * 210;
});

const canvasHeight = computed(() => {
  return mapLayout.value.height;
});
const zoomPercent = computed(() => Math.round(zoom.value * 100));
const scaledCanvasWidth = computed(() => canvasWidth.value * zoom.value);
const scaledCanvasHeight = computed(() => canvasHeight.value * zoom.value);

const selectedTarget = computed(() =>
  snapshot.value?.targets.find(
    (target) => target.postingId === selectedNode.value?.postingId,
  ),
);

const guideMessage = computed(() => {
  if (!snapshot.value?.targets.length) {
    return "공고를 목표로 추가하면 첫 번째 퀘스트 경로를 만들어드릴게요.";
  }
  if (workspace.value?.draft && previewDraft.value) {
    return "새로운 경로가 발견됐어요! 달라진 가지를 확인해보세요.";
  }
  const completed = snapshot.value.nodes.filter(
    (node) => node.status === "COMPLETED",
  ).length;
  if (completed === 0) {
    return "가장 왼쪽의 기초 퀘스트부터 시작해볼까요?";
  }
  return `${completed}개 퀘스트를 완료했어요. 초록 경로를 따라 계속 가보세요!`;
});

function statusLabel(status: string) {
  if (status === "COMPLETED") return "완료";
  if (status === "IN_PROGRESS") return "진행 중";
  if (status === "AVAILABLE") return "지원 경로 열림";
  if (status === "LOCKED") return "준비 필요";
  return "미시작";
}

function nodeIcon(node: RoadmapNode) {
  if (node.type === "PROJECT") return Rocket;
  if (node.type === "OPPORTUNITY") return Flag;
  if (node.type === "GATE") return GitBranch;
  if (node.stage === "FOUNDATION") return BookOpen;
  return Code2;
}

function domainIcon(domain: string) {
  return domainMeta[domain]?.icon ?? Code2;
}

function clampZoom(value: number) {
  return Math.min(1.8, Math.max(0.3, value));
}

async function setZoom(
  nextZoom: number,
  focalX?: number,
  focalY?: number,
) {
  const viewport = canvasViewport.value;
  const normalized = clampZoom(nextZoom);
  if (!viewport || normalized === zoom.value) return;

  const localX = focalX ?? viewport.clientWidth / 2;
  const localY = focalY ?? viewport.clientHeight / 2;
  const worldX = (viewport.scrollLeft + localX) / zoom.value;
  const worldY = (viewport.scrollTop + localY) / zoom.value;
  zoom.value = normalized;
  await nextTick();
  viewport.scrollLeft = worldX * normalized - localX;
  viewport.scrollTop = worldY * normalized - localY;
}

function zoomIn() {
  void setZoom(zoom.value + 0.1);
}

function zoomOut() {
  void setZoom(zoom.value - 0.1);
}

function resetZoom() {
  void setZoom(1);
}

async function fitMap() {
  const viewport = canvasViewport.value;
  if (!viewport) return;
  const horizontalScale = (viewport.clientWidth - 48) / canvasWidth.value;
  const verticalScale = (viewport.clientHeight - 48) / canvasHeight.value;
  zoom.value = clampZoom(Math.min(horizontalScale, verticalScale));
  await nextTick();
  viewport.scrollLeft = Math.max(
    0,
    (scaledCanvasWidth.value - viewport.clientWidth) / 2,
  );
  viewport.scrollTop = Math.max(
    0,
    (scaledCanvasHeight.value - viewport.clientHeight) / 2,
  );
}

function handleCanvasWheel(event: WheelEvent) {
  if (!event.ctrlKey) return;
  event.preventDefault();
  const viewport = canvasViewport.value;
  if (!viewport) return;
  const bounds = viewport.getBoundingClientRect();
  const direction = event.deltaY > 0 ? -0.1 : 0.1;
  void setZoom(
    zoom.value + direction,
    event.clientX - bounds.left,
    event.clientY - bounds.top,
  );
}

function startCanvasPan(event: PointerEvent) {
  if (event.button !== 0) return;
  const target = event.target as HTMLElement;
  if (target.closest("button, a, input, textarea, select")) return;
  const viewport = canvasViewport.value;
  if (!viewport) return;
  isPanning.value = true;
  panPointerId = event.pointerId;
  panStartX = event.clientX;
  panStartY = event.clientY;
  panStartScrollLeft = viewport.scrollLeft;
  panStartScrollTop = viewport.scrollTop;
  viewport.setPointerCapture(event.pointerId);
  event.preventDefault();
}

function moveCanvasPan(event: PointerEvent) {
  if (!isPanning.value || panPointerId !== event.pointerId) return;
  const viewport = canvasViewport.value;
  if (!viewport) return;
  viewport.scrollLeft = panStartScrollLeft - (event.clientX - panStartX);
  viewport.scrollTop = panStartScrollTop - (event.clientY - panStartY);
}

function endCanvasPan(event: PointerEvent) {
  if (panPointerId !== event.pointerId) return;
  const viewport = canvasViewport.value;
  if (viewport?.hasPointerCapture(event.pointerId)) {
    viewport.releasePointerCapture(event.pointerId);
  }
  isPanning.value = false;
  panPointerId = null;
}

async function load() {
  error.value = "";
  try {
    workspace.value = await api.roadmap();
    if (workspace.value.draft) previewDraft.value = true;
    if (selectedNode.value) {
      selectedNode.value =
        snapshot.value?.nodes.find((node) => node.id === selectedNode.value?.id) ??
        null;
    }
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "로드맵을 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function regenerate() {
  // **가능 여부를 미리 따지지 않는다.** 로드맵은 적합도 분석이 끝나면 생기는 결과이고,
  // 화면이 매 순간 "지금은 안 됩니다"를 계산해 알리는 것은 사용자의 자율성을 깎는다.
  // 눌렀을 때 재료가 없으면 서버가 그 이유를 답하고, 아래 catch 가 그 문장을 그대로 보여준다.
  actionLoading.value = true;
  error.value = "";
  try {
    await api.regenerateRoadmap();
    await load();
    previewDraft.value = true;
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "새 로드맵 초안을 만들지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function removeSelectedTarget() {
  if (!selectedPostingId.value) return;
  const target = snapshot.value?.targets.find(
    (item) => item.postingId === selectedPostingId.value,
  );
  if (!window.confirm(`${target?.companyName ?? "선택한 공고"}를 목표 경로에서 제거할까요? 완료 기록은 유지됩니다.`)) {
    return;
  }
  actionLoading.value = true;
  error.value = "";
  try {
    await api.removeRoadmapTarget(selectedPostingId.value);
    selectedPostingId.value = null;
    await load();
    previewDraft.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "목표 공고를 제거하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function resetTargets() {
  if (!window.confirm("모든 목표 공고를 경로에서 제거할까요? 완료한 역량과 공고 분석 기록은 삭제되지 않습니다.")) {
    return;
  }
  actionLoading.value = true;
  error.value = "";
  try {
    await api.resetRoadmapTargets();
    selectedPostingId.value = null;
    await load();
    previewDraft.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "로드맵 초기화 초안을 만들지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function applyDraft() {
  if (!workspace.value?.draft) return;
  const expectedDraftId = workspace.value.draft.id;
  const expectedVersion = workspace.value.draft.version;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.applyRoadmapDraft();
    const refreshed = await api.roadmap();
    workspace.value = refreshed;
    applyConfirmOpen.value = false;
    previewDraft.value = false;
    selectedNode.value = null;
  } catch (cause) {
    try {
      const reconciled = await api.roadmap();
      const wasApplied =
        reconciled.current.version >= expectedVersion &&
        reconciled.draft?.id !== expectedDraftId;
      if (wasApplied) {
        workspace.value = reconciled;
        applyConfirmOpen.value = false;
        previewDraft.value = false;
        selectedNode.value = null;
      } else {
        throw cause;
      }
    } catch {
      error.value =
        cause instanceof Error ? cause.message : "새 로드맵을 적용하지 못했습니다.";
    }
  } finally {
    actionLoading.value = false;
  }
}

async function selectNode(node: RoadmapNode) {
  selectedNode.value = node;
  evidenceCompetency.value = null;
  assessment.value = null;
  assessmentAnswer.value = "";
  evidence.value = [];
  if (node.type === "PROJECT" && node.careerNodeId) {
    try {
      evidence.value = await api.evidence(node.careerNodeId);
    } catch (cause) {
      error.value =
        cause instanceof Error ? cause.message : "프로젝트 증거를 불러오지 못했습니다.";
    }
  }
}

async function chooseCompetency(competency: RoadmapCompetency) {
  evidenceCompetency.value = competency;
  assessment.value = null;
  assessmentAnswer.value = "";
  evidence.value = [];
  if (!competency.careerNodeId) return;
  if (!competency.canonicalKey.startsWith("foundation.")) {
    try {
      assessment.value =
        (await api.latestAssessment(competency.careerNodeId)) ?? null;
    } catch (cause) {
      error.value =
        cause instanceof Error ? cause.message : "검증 상태를 불러오지 못했습니다.";
    }
  }
}

async function selfConfirm(competency: RoadmapCompetency) {
  if (!competency.careerNodeId) return;
  actionLoading.value = true;
  try {
    await api.selfConfirm(competency.careerNodeId);
    const competencyId = competency.id;
    await load();
    evidenceCompetency.value =
      selectedNode.value?.competencies.find((item) => item.id === competencyId) ??
      null;
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "완료 상태를 반영하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function startAssessment() {
  const competency = evidenceCompetency.value;
  if (!competency?.careerNodeId) return;
  actionLoading.value = true;
  error.value = "";
  try {
    const targetPostingId =
      selectedPostingId.value ?? selectedNode.value?.postingIds[0] ?? null;
    assessment.value = await api.startAssessment(
      competency.careerNodeId,
      targetPostingId,
    );
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "AI 검증을 시작하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function answerAssessment() {
  if (!assessment.value || !assessmentAnswer.value.trim()) return;
  actionLoading.value = true;
  error.value = "";
  try {
    assessment.value = await api.answerAssessment(
      assessment.value.id,
      assessmentAnswer.value.trim(),
    );
    assessmentAnswer.value = "";
    if (assessment.value.status === "PASSED") {
      const competencyId = evidenceCompetency.value?.id;
      await load();
      evidenceCompetency.value =
        selectedNode.value?.competencies.find(
          (item) => item.id === competencyId,
        ) ?? null;
    }
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "답변을 평가하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function requestAssessmentReview() {
  if (!assessment.value || !assessmentReviewReason.value.trim()) return;
  actionLoading.value = true;
  error.value = "";
  try {
    assessment.value = await api.requestAssessmentReview(
      assessment.value.id,
      assessmentReviewReason.value.trim(),
    );
    assessmentReviewReason.value = "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "운영자 검토를 요청하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

function assessmentKindLabel(kind: string) {
  if (kind === "CONCEPT") return "개념 이해";
  if (kind === "CODE") return "코드 판단";
  if (kind === "SCENARIO") return "상황 적용";
  return "맞춤 후속 질문";
}

async function submitProjectEvidence() {
  const node = selectedNode.value;
  if (
    node?.type !== "PROJECT" ||
    !node.careerNodeId ||
    !evidenceTitle.value.trim()
  ) {
    return;
  }
  actionLoading.value = true;
  try {
    await api.submitEvidence(node.careerNodeId, {
      evidenceType: "PROJECT",
      title: evidenceTitle.value.trim(),
      sourceUrl: evidenceUrl.value.trim() || null,
      content: { description: evidenceDescription.value.trim() },
    });
    evidenceTitle.value = "";
    evidenceUrl.value = "";
    evidenceDescription.value = "";
    evidence.value = await api.evidence(node.careerNodeId);
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "프로젝트 증거를 제출하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

function closeNode() {
  selectedNode.value = null;
  evidenceCompetency.value = null;
  assessment.value = null;
  assessmentAnswer.value = "";
  evidence.value = [];
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  if (applyConfirmOpen.value) {
    applyConfirmOpen.value = false;
    return;
  }
  closeNode();
}

onMounted(() => {
  void load();
  window.addEventListener("keydown", handleKeydown);
});
onBeforeUnmount(() => window.removeEventListener("keydown", handleKeydown));
</script>

<template>
  <main class="workspace roadmap-v2-workspace">
    <section class="roadmap-v2-hero">
      <div>
        <p class="eyebrow">MY QUEST MAP</p>
        <h1>{{ snapshot?.title ?? "나의 커리어 로드맵" }}</h1>
        <p>
          퀘스트를 완료하고 초록 경로를 이어가세요. 새 목표가 생기면 완료
          기록은 그대로 둔 채 하나의 직무 여정에 새 기회가 연결됩니다.
        </p>
      </div>
      <div class="roadmap-v2-meta">
        <span>버전 {{ snapshot?.version ?? 1 }}</span>
        <span>목표 {{ workspace?.targetCount ?? 0 }}개</span>
      </div>
    </section>

    <div v-if="error" class="inline-error">{{ error }}</div>
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" /> 로드맵을 불러오는 중입니다.
    </div>

    <template v-else-if="workspace && snapshot">
      <section v-if="workspace.draft" class="roadmap-update-banner">
        <div class="roadmap-update-icon">
          <Sparkles :size="24" />
        </div>
        <div>
          <p class="eyebrow">UPDATE READY</p>
          <h2>새 로드맵 초안이 준비됐어요</h2>
          <p>
            새 단계 {{ workspace.draft.changes.added.length }}개 · 유지
            {{ workspace.draft.changes.retained.length }}개 · 제외
            {{ workspace.draft.changes.removed.length }}개
          </p>
        </div>
        <div class="roadmap-update-actions">
          <button
            class="press-button press-button--ghost"
            type="button"
            @click="previewDraft = !previewDraft"
          >
            <Layers3 :size="17" />
            {{ previewDraft ? "현재 버전 보기" : "변경 미리보기" }}
          </button>
          <button
            class="press-button press-button--primary"
            type="button"
            :disabled="actionLoading"
            @click="applyConfirmOpen = true"
          >
            <Check :size="18" /> 새 지도 적용하기
          </button>
        </div>
      </section>

      <section v-if="workspace.draft && previewDraft" class="roadmap-change-strip">
        <div>
          <strong>추가</strong>
          <span v-for="item in workspace.draft.changes.added.slice(0, 6)" :key="item">
            {{ item }}
          </span>
          <small v-if="!workspace.draft.changes.added.length">새 단계 없음</small>
        </div>
        <div>
          <strong>유지</strong>
          <span
            v-for="item in workspace.draft.changes.retained.slice(0, 6)"
            :key="item"
          >
            {{ item }}
          </span>
        </div>
        <div>
          <strong>제외</strong>
          <span
            v-for="item in workspace.draft.changes.removed.slice(0, 6)"
            :key="item"
          >
            {{ item }}
          </span>
          <small v-if="!workspace.draft.changes.removed.length">제외 단계 없음</small>
        </div>
      </section>

      <section class="roadmap-toolbar">
        <div class="roadmap-target-filters">
          <button
            type="button"
            :class="{ active: selectedPostingId === null }"
            @click="selectedPostingId = null"
          >
            전체 경로
          </button>
          <button
            v-for="target in snapshot.targets"
            :key="target.postingId"
            type="button"
            :class="{ active: selectedPostingId === target.postingId }"
            @click="selectedPostingId = target.postingId"
          >
            {{ target.companyName }}
            <small>{{ target.completedRequired }}/{{ target.required }} 필수</small>
          </button>
        </div>
        <button
          v-if="workspace.targetCount > 0"
          class="icon-button"
          type="button"
          title="현재 목표로 초안 다시 만들기"
          :disabled="actionLoading"
          @click="regenerate"
        >
          <RefreshCw :size="18" />
        </button>
        <button
          v-if="selectedPostingId"
          class="icon-button roadmap-target-remove"
          type="button"
          title="선택한 목표 제거"
          :disabled="actionLoading"
          @click="removeSelectedTarget"
        >
          <Trash2 :size="18" />
        </button>
        <button
          v-if="workspace.targetCount > 0"
          class="text-action roadmap-reset-action"
          type="button"
          :disabled="actionLoading"
          @click="resetTargets"
        >
          전체 목표 초기화
        </button>
      </section>

      <section class="roadmap-map-shell">
        <header>
          <div>
            <span :class="{ draft: previewDraft && workspace.draft }">
              {{ previewDraft && workspace.draft ? "초안 미리보기" : "현재 적용 버전" }}
            </span>
            <p>
              {{
                viewMode === "JOURNEY"
                  ? "굵은 경력 축을 따라가고, 각 단계의 필수·보너스 퀘스트를 펼쳐보세요."
                  : "실선은 필수, 점선은 선택 퀘스트입니다. 빈 공간을 드래그하고 Ctrl+휠로 확대할 수 있어요."
              }}
            </p>
          </div>
          <div class="roadmap-view-switch" aria-label="로드맵 보기 방식">
            <button
              type="button"
              :class="{ active: viewMode === 'JOURNEY' }"
              @click="viewMode = 'JOURNEY'"
            >
              <Target :size="16" />
              여정 보기
            </button>
            <button
              type="button"
              :class="{ active: viewMode === 'GRAPH' }"
              @click="viewMode = 'GRAPH'"
            >
              <GitBranch :size="16" />
              상세 관계 보기
            </button>
          </div>
          <div
            v-if="viewMode === 'GRAPH'"
            class="roadmap-zoom-controls"
            aria-label="로드맵 확대 및 축소"
          >
            <button
              type="button"
              title="축소"
              :disabled="zoom <= 0.3"
              @click="zoomOut"
            >
              <Minus :size="16" stroke-width="3" />
            </button>
            <button type="button" title="100%로 초기화" @click="resetZoom">
              {{ zoomPercent }}%
            </button>
            <button
              type="button"
              title="확대"
              :disabled="zoom >= 1.8"
              @click="zoomIn"
            >
              <Plus :size="16" stroke-width="3" />
            </button>
            <button type="button" title="전체 지도 보기" @click="fitMap">
              <Maximize2 :size="16" />
              전체 보기
            </button>
          </div>
          <div class="roadmap-legend">
            <span><i class="done"></i> 완료</span>
            <span><i class="active"></i> 진행 가능</span>
            <span><i class="optional"></i> 보너스</span>
          </div>
        </header>

        <JourneyMap
          v-if="viewMode === 'JOURNEY'"
          :model="journeyModel"
          :selected-node-id="selectedNode?.id ?? null"
          :next-node="nextJourneyNode"
          @select="selectNode"
        />

        <div
          v-else
          ref="canvasViewport"
          class="roadmap-canvas-scroll"
          :class="{ 'is-panning': isPanning }"
          @wheel="handleCanvasWheel"
          @pointerdown="startCanvasPan"
          @pointermove="moveCanvasPan"
          @pointerup="endCanvasPan"
          @pointercancel="endCanvasPan"
        >
          <div
            class="roadmap-canvas-stage"
            :style="{
              width: `${scaledCanvasWidth}px`,
              height: `${scaledCanvasHeight}px`,
            }"
          >
            <div
              class="roadmap-v2-canvas"
              :style="{
                width: `${canvasWidth}px`,
                height: `${canvasHeight}px`,
                transform: `scale(${zoom})`,
              }"
            >
            <section
              v-for="section in domainSections"
              :key="section.key"
              class="roadmap-domain-section"
              :style="{
                top: `${section.y}px`,
                height: `${section.height}px`,
                '--domain-color': section.color,
              }"
              :aria-label="`${section.label} 영역, 퀘스트 ${section.nodeCount}개`"
            >
              <header class="roadmap-domain-section__label">
                <span>
                  <component :is="domainIcon(section.key)" :size="18" stroke-width="2.8" />
                </span>
                <strong>{{ section.label }}</strong>
                <small>{{ section.nodeCount }}개 퀘스트</small>
              </header>
            </section>

            <svg
              class="roadmap-v2-edges"
              :width="canvasWidth"
              :height="canvasHeight"
              aria-hidden="true"
            >
              <line
                v-for="edge in visibleEdges"
                :key="`${edge.fromId}-${edge.toId}-${edge.kind}`"
                :x1="edge.x1"
                :y1="edge.y1"
                :x2="edge.x2"
                :y2="edge.y2"
                :class="{
                  optional: edge.kind === 'OPTIONAL',
                  completed: edge.completed,
                  available: edge.available,
                }"
              />
            </svg>

            <button
              v-for="node in positionedNodes"
              :key="node.id"
              class="quest-map-node"
              :class="[
                `quest-map-node--${node.type.toLowerCase()}`,
                `quest-map-node--${node.status.toLowerCase()}`,
                {
                  optional: nodeIsOptional(node),
                  selected: selectedNode?.id === node.id,
                },
              ]"
              :style="{ left: `${node.x}px`, top: `${node.y}px` }"
              type="button"
              :aria-label="`${node.title}, ${statusLabel(node.status)}`"
              @click="selectNode(node)"
            >
              <span class="quest-map-node__disc">
                <component :is="nodeIcon(node)" :size="27" />
                <span
                  v-if="node.status === 'COMPLETED'"
                  class="quest-map-node__badge quest-map-node__badge--done"
                >
                  <Check :size="15" stroke-width="4" />
                </span>
                <span
                  v-else-if="node.status === 'LOCKED'"
                  class="quest-map-node__badge quest-map-node__badge--locked"
                >
                  <LockKeyhole :size="13" stroke-width="3" />
                </span>
              </span>
              <span class="quest-map-node__label">
                <small>
                  {{
                    nodeIsOptional(node)
                      ? "보너스 퀘스트"
                      : node.type === "PROJECT"
                        ? "회사 맞춤 프로젝트"
                        : node.type === "OPPORTUNITY"
                          ? "지원 기회"
                          : node.type === "GATE"
                            ? "경력 합류점"
                          : node.stage
                  }}
                </small>
                <strong>{{ node.title }}</strong>
                <em>{{ statusLabel(node.status) }}</em>
              </span>
            </button>

            <div v-if="!positionedNodes.length" class="roadmap-empty-map">
              <Target :size="32" />
              <h3>아직 목표 공고가 없습니다</h3>
              <p>공고를 분석하고 목표에 추가하면 관련 직무 경로가 확장됩니다.</p>
            </div>
            </div>
          </div>
        </div>
      </section>
      <JobissGuide :message="guideMessage" />
    </template>

    <button
      v-if="selectedNode"
      class="drawer-backdrop"
      type="button"
      aria-label="퀘스트 상세 닫기"
      @click="closeNode"
    />
    <aside
      v-if="selectedNode"
      class="detail-drawer quest-detail-drawer"
      role="dialog"
      aria-modal="true"
      aria-label="퀘스트 상세"
    >
      <div class="drawer-top">
        <span
          class="drawer-icon"
          :class="`drawer-icon--${selectedNode.status.toLowerCase()}`"
        >
          <component :is="nodeIcon(selectedNode)" :size="24" />
        </span>
        <button
          class="icon-button quest-drawer-close"
          type="button"
          aria-label="상세 닫기"
          @click="closeNode"
        >
          <X :size="20" />
        </button>
      </div>
      <p class="eyebrow">{{ selectedNode.domain }} · {{ selectedNode.stage }}</p>
      <h2>{{ selectedNode.title }}</h2>
      <p class="drawer-subtitle">{{ selectedNode.subtitle }}</p>
      <section class="quest-status-card">
        <div>
          <small>현재 상태</small>
          <strong>{{ statusLabel(selectedNode.status) }}</strong>
        </div>
        <span :class="`status-chip status-chip--${selectedNode.status.toLowerCase()}`">
          <Check v-if="selectedNode.status === 'COMPLETED'" :size="14" />
          <LockKeyhole v-else-if="selectedNode.status === 'LOCKED'" :size="14" />
          <CircleDot v-else :size="14" />
          {{ statusLabel(selectedNode.status) }}
        </span>
      </section>

      <template v-if="selectedNode.type === 'MILESTONE'">
        <section class="roadmap-drawer-section">
          <h3>포함된 역량</h3>
          <button
            v-for="competency in selectedNode.competencies"
            :key="competency.id"
            class="roadmap-competency-row"
            type="button"
            @click="chooseCompetency(competency)"
          >
            <span
              :class="[
                'competency-state',
                { done: competency.progressStatus === 'COMPLETED' },
              ]"
            >
              <Check
                v-if="
                  competency.progressStatus === 'COMPLETED' &&
                  competency.verifiedLevel >= competency.requiredLevel
                "
                :size="14"
              />
              <CircleDot v-else :size="14" />
            </span>
            <span>
              <strong>{{ competency.title }}</strong>
              <small>
                요구 {{ competency.requiredLevel }} · 검증
                {{ competency.verifiedLevel }}
              </small>
            </span>
            <ChevronRight :size="16" />
          </button>
        </section>

        <section v-if="evidenceCompetency" class="roadmap-drawer-section">
          <h3>{{ evidenceCompetency.title }}</h3>
          <p>{{ evidenceCompetency.scopeDefinition }}</p>
          <button
            v-if="
              evidenceCompetency.canonicalKey.startsWith('foundation.') &&
              evidenceCompetency.progressStatus !== 'COMPLETED'
            "
            class="press-button press-button--primary"
            type="button"
            :disabled="actionLoading || !evidenceCompetency.careerNodeId"
            @click="selfConfirm(evidenceCompetency)"
          >
            <Check :size="16" /> 이해했어요
          </button>
          <p v-else-if="!evidenceCompetency.careerNodeId" class="drawer-hint">
            새 로드맵 버전을 적용하면 이 역량을 검증할 수 있습니다.
          </p>
          <div v-else-if="!assessment" class="assessment-start-card">
            <BrainCircuit :size="28" />
            <div>
              <strong>AI 역량 검증</strong>
              <p>
                개념, 코드 판단, 실제 적용 문제를 3~5회에 걸쳐 확인합니다.
                문제는 현재 목표 공고의 맥락에 맞춰 달라집니다.
              </p>
            </div>
            <button
              class="press-button press-button--primary"
              type="button"
              :disabled="actionLoading"
              @click="startAssessment"
            >
              <BrainCircuit :size="16" />
              {{ actionLoading ? "문제를 준비하고 있어요" : "AI 검증 시작" }}
            </button>
          </div>
          <div v-else class="assessment-session">
            <header class="assessment-session__header">
              <span
                class="status-chip"
                :class="`assessment-status--${assessment.status.toLowerCase()}`"
              >
                {{
                  assessment.status === "IN_PROGRESS"
                    ? `검증 ${assessment.questionCount}/5`
                    : assessment.status === "PASSED"
                      ? "검증 통과"
                      : "학습 보완 필요"
                }}
              </span>
              <small v-if="assessment.companyName">
                {{ assessment.companyName }} · {{ assessment.roleTitle }}
              </small>
            </header>

            <div
              v-if="Object.keys(assessment.retainedScores).length"
              class="assessment-retained"
            >
              <strong>이전 도전에서 통과한 영역</strong>
              <span
                v-for="(score, kind) in assessment.retainedScores"
                :key="kind"
              >
                {{ assessmentKindLabel(kind) }} {{ score }}점
              </span>
              <small>이번에는 부족한 영역만 새 문제로 확인합니다.</small>
            </div>

            <article
              v-for="turn in assessment.turns.filter((item) => item.answerText)"
              :key="turn.id"
              class="assessment-result-card"
            >
              <div>
                <strong>{{ assessmentKindLabel(turn.questionKind) }}</strong>
                <span>{{ turn.score }}점</span>
              </div>
              <p>{{ turn.feedback }}</p>
              <div v-if="turn.coreCriteria.length" class="assessment-criteria">
                <small>핵심 통과 기준</small>
                <span v-for="criterion in turn.coreCriteria" :key="criterion">
                  {{ criterion }}
                </span>
              </div>
              <details v-if="turn.futureExtensions.length" class="assessment-extensions">
                <summary>다음 수준에서 확장할 내용</summary>
                <ul>
                  <li v-for="item in turn.futureExtensions" :key="item">{{ item }}</li>
                </ul>
              </details>
            </article>

            <template v-if="assessment.status === 'IN_PROGRESS'">
              <article
                v-for="turn in assessment.turns.filter((item) => !item.answerText)"
                :key="turn.id"
                class="assessment-question-card"
              >
                <p class="eyebrow">
                  {{ assessmentKindLabel(turn.questionKind) }}
                </p>
                <h4>{{ turn.prompt }}</h4>
                <pre v-if="turn.codeSnippet"><code>{{ turn.codeSnippet }}</code></pre>
                <div v-if="turn.coreCriteria.length" class="assessment-criteria">
                  <small>이 문제의 핵심 확인 범위</small>
                  <span v-for="criterion in turn.coreCriteria" :key="criterion">
                    {{ criterion }}
                  </span>
                </div>
              </article>
              <form
                class="assessment-answer-form"
                @submit.prevent="answerAssessment"
              >
                <textarea
                  v-model="assessmentAnswer"
                  placeholder="정답뿐 아니라 그렇게 판단한 이유를 함께 설명해 주세요."
                  rows="7"
                  maxlength="12000"
                ></textarea>
                <button
                  class="press-button press-button--primary"
                  type="submit"
                  :disabled="actionLoading || !assessmentAnswer.trim()"
                >
                  <BrainCircuit :size="16" />
                  {{ actionLoading ? "답변을 평가하고 있어요" : "답변 제출" }}
                </button>
              </form>
            </template>

            <section
              v-else
              class="assessment-final-card"
              :class="{ passed: assessment.status === 'PASSED' }"
            >
              <strong>
                {{
                  assessment.status === "PASSED"
                    ? `수준 ${assessment.achievedLevel} 인증 완료`
                    : "조금 더 공부한 뒤 다시 도전해 보세요"
                }}
              </strong>
              <p>{{ assessment.summary }}</p>
              <small v-if="assessment.averageScore !== null">
                평균 {{ Math.round(assessment.averageScore) }}점
              </small>
              <ul v-if="assessment.gaps.length">
                <li v-for="gap in assessment.gaps" :key="gap">{{ gap }}</li>
              </ul>
              <div v-if="assessment.nextActions.length" class="assessment-learning-guide">
                <strong>다음 학습 가이드</strong>
                <ul>
                  <li v-for="item in assessment.nextActions" :key="item">{{ item }}</li>
                </ul>
              </div>
              <button
                v-if="assessment.status === 'NEEDS_STUDY'"
                class="press-button press-button--secondary"
                type="button"
                :disabled="actionLoading"
                @click="startAssessment"
              >
                <RefreshCw :size="16" /> 다시 검증하기
              </button>
              <div
                v-if="
                  assessment.status === 'NEEDS_STUDY' &&
                  ['NONE', 'REJECTED'].includes(assessment.reviewStatus)
                "
                class="assessment-review-request"
              >
                <textarea
                  v-model="assessmentReviewReason"
                  rows="3"
                  maxlength="4000"
                  placeholder="채점에서 다시 확인받고 싶은 근거를 구체적으로 적어 주세요."
                />
                <button
                  class="press-button press-button--ghost"
                  type="button"
                  :disabled="actionLoading || !assessmentReviewReason.trim()"
                  @click="requestAssessmentReview"
                >
                  운영자 검토 요청
                </button>
              </div>
              <p
                v-else-if="assessment.reviewStatus === 'REQUESTED'"
                class="assessment-review-pending"
              >
                운영자 검토를 요청했습니다. 판정이 끝나면 상태에 반영됩니다.
              </p>
            </section>
          </div>
        </section>
      </template>

      <template v-else-if="selectedNode.type === 'GATE'">
        <section class="roadmap-drawer-section">
          <h3>경력 경로 합류점</h3>
          <p>{{ selectedNode.subtitle }}</p>
          <small>
            특정 회사 입사가 필수라는 뜻이 아니라, 같은 직무의 관련 취업과
            실무 경험으로 다음 경력 단계가 열립니다.
          </small>
        </section>
      </template>

      <template v-else-if="selectedNode.project">
        <section class="roadmap-drawer-section">
          <h3>프로젝트 목표</h3>
          <p>{{ selectedNode.project.objective }}</p>
          <small>{{ selectedNode.project.domainContext }}</small>
        </section>
        <section class="roadmap-drawer-section">
          <h3>필수 결과물</h3>
          <ul>
            <li v-for="item in selectedNode.project.deliverables" :key="item">
              {{ item }}
            </li>
          </ul>
        </section>
        <section class="roadmap-drawer-section">
          <h3>완료 기준</h3>
          <ul>
            <li
              v-for="item in selectedNode.project.acceptanceCriteria"
              :key="item"
            >
              {{ item }}
            </li>
          </ul>
        </section>
        <section class="roadmap-drawer-section">
          <h3>프로젝트 검증</h3>
          <p v-if="!selectedNode.careerNodeId" class="drawer-hint">
            새 로드맵 버전을 적용하면 프로젝트 결과물을 제출할 수 있습니다.
          </p>
          <form
            v-else
            class="roadmap-evidence-form"
            @submit.prevent="submitProjectEvidence"
          >
            <input v-model="evidenceTitle" placeholder="프로젝트 결과물 제목" maxlength="180" />
            <input v-model="evidenceUrl" placeholder="Git 저장소 또는 배포 URL" />
            <textarea
              v-model="evidenceDescription"
              placeholder="구현 기능, 테스트, 측정 결과를 설명해 주세요."
              rows="4"
            ></textarea>
            <button
              class="press-button press-button--primary"
              type="submit"
              :disabled="actionLoading || !evidenceTitle.trim()"
            >
              <Rocket :size="16" /> 프로젝트 검증 요청
            </button>
          </form>
          <article v-for="item in evidence" :key="item.id" class="evidence-mini-card">
            <strong>{{ item.title }}</strong>
            <small>{{ item.verificationStatus }}</small>
          </article>
        </section>
      </template>

      <template v-else-if="selectedTarget">
        <section class="roadmap-drawer-section target-readiness">
          <h3>지원 준비도</h3>
          <p>
            필수 {{ selectedTarget.completedRequired }}/{{ selectedTarget.required }}
          </p>
          <p>
            우대 {{ selectedTarget.completedPreferred }}/{{ selectedTarget.preferred }}
          </p>
          <small>우대사항은 회사 노드를 잠그지 않습니다.</small>
        </section>
      </template>
    </aside>

    <button
      v-if="applyConfirmOpen"
      class="quest-dialog-backdrop"
      type="button"
      aria-label="새 지도 적용 취소"
      @click="applyConfirmOpen = false"
    />
    <section
      v-if="applyConfirmOpen"
      class="quest-confirm-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="roadmap-apply-title"
    >
      <div class="quest-confirm-character" aria-hidden="true">
        <span class="quest-confirm-character__antenna" />
        <span class="quest-confirm-character__eye quest-confirm-character__eye--left" />
        <span class="quest-confirm-character__eye quest-confirm-character__eye--right" />
        <span class="quest-confirm-character__smile" />
      </div>
      <p class="eyebrow">READY TO EXPLORE?</p>
      <h2 id="roadmap-apply-title">새로운 경로로 출발할까요?</h2>
      <p>
        지금까지 완료한 퀘스트는 그대로 유지되고, 새 공고에서 발견한
        경로만 추가됩니다.
      </p>
      <div class="quest-confirm-dialog__actions">
        <button
          class="press-button press-button--ghost"
          type="button"
          :disabled="actionLoading"
          @click="applyConfirmOpen = false"
        >
          조금 더 볼게요
        </button>
        <button
          class="press-button press-button--primary"
          type="button"
          :disabled="actionLoading"
          @click="applyDraft"
        >
          <LoaderCircle v-if="actionLoading" class="spin" :size="18" />
          <Check v-else :size="18" />
          새 지도 적용하기
        </button>
      </div>
    </section>
  </main>
</template>

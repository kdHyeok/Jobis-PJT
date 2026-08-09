<script setup lang="ts">
import {
  BookOpen,
  BriefcaseBusiness,
  BrainCircuit,
  Check,
  ChevronRight,
  CircleDot,
  Cloud,
  Code2,
  Database,
  Flag,
  History,
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
  RotateCcw,
  Rocket,
  Search,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Target,
  TimerReset,
  Trash2,
  X,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { productDialog } from "@/product-dialog";
import JourneyMap from "@/components/JourneyMap.vue";
import JobissGuide from "@/components/JobissGuide.vue";
import { buildJourneyModel } from "@/roadmap/journey";
import { adaptV3Workspace } from "@/roadmap/v3-adapter";
import type {
  CompetencyAssessment,
  CompetencyLearning,
  CareerGoals,
  Evidence,
  RoadmapCompetency,
  RoadmapNode,
  RoadmapSnapshot,
  RoadmapVersion,
  RoadmapWorkspace,
  V3AtomicAssessment,
  V3RoadmapNode,
  V3ProjectTask,
  V3RoadmapVersion,
  V3RoadmapWorkspace,
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
  "QA",
  "EMBEDDED",
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
  QA: { label: "QA·테스트 자동화", color: "#00b8a9", icon: Check },
  EMBEDDED: { label: "임베디드·펌웨어", color: "#7c6f64", icon: BrainCircuit },
  DOMAIN: { label: "회사·도메인", color: "#ff6b9d", icon: Target },
  CAREER: { label: "경력·자격", color: "#ff9600", icon: Flag },
};

const route = useRoute();
const router = useRouter();
const workspace = ref<RoadmapWorkspace | null>(null);
const careerGoals = ref<CareerGoals | null>(null);
const finalGoalText = ref("");
const goalSaving = ref(false);
const v3Workspace = ref<V3RoadmapWorkspace | null>(null);
const v3Mode = computed(() => v3Workspace.value !== null);
const previewDraft = ref(
  route.query.preview === "draft" || typeof route.query.proposal === "string",
);
const viewMode = ref<"JOURNEY" | "GRAPH">("JOURNEY");
const selectedNode = ref<RoadmapNode | null>(null);
const applyConfirmOpen = ref(false);
const discardConfirmOpen = ref(false);
const diffOpen = ref(false);
const historyOpen = ref(false);
const roadmapVersions = ref<RoadmapVersion[]>([]);
const v3RoadmapVersions = ref<V3RoadmapVersion[]>([]);
const historyError = ref("");
const nodeSearch = ref("");
const selectedPostingId = ref<string | null>(
  typeof route.query.posting === "string" ? route.query.posting : null,
);
const loading = ref(true);
const actionLoading = ref(false);
const error = ref("");
const assessmentLoadError = ref("");
const learningLoadError = ref("");
const evidence = ref<Evidence[]>([]);
const evidenceCompetency = ref<RoadmapCompetency | null>(null);
const assessment = ref<CompetencyAssessment | null>(null);
const learning = ref<CompetencyLearning | null>(null);
const assessmentAnswer = ref("");
const assessmentReviewReason = ref("");
const v3Assessment = ref<V3AtomicAssessment | null>(null);
const v3AssessmentLoading = ref(false);
const v3AssessmentError = ref("");
const v3AssessmentAnswer = ref("");
const v3AssessmentReviewReason = ref("");
const v3OpenAssessmentTurn = computed(() =>
  v3Assessment.value?.turns.find((turn) => !turn.answerText) ?? null,
);
const evidenceTitle = ref("");
const evidenceUrl = ref("");
const evidenceDescription = ref("");
const taskEvidenceKey = ref<string | null>(null);
const taskEvidenceTitle = ref("");
const taskEvidenceUrl = ref("");
const taskEvidenceDescription = ref("");
const employmentEmployer = ref("");
const employmentRoleTitle = ref("");
const employmentStartedOn = ref("");
const employmentEndedOn = ref("");
const employmentEvidenceUrl = ref("");
const employmentDescription = ref("");
const canvasViewport = ref<HTMLElement | null>(null);
const diffDialog = ref<HTMLElement | null>(null);
const applyDialog = ref<HTMLElement | null>(null);
const discardDialog = ref<HTMLElement | null>(null);
const detailDrawer = ref<HTMLElement | null>(null);
const zoom = ref(1);
const canvasScrollLeft = ref(0);
const canvasScrollTop = ref(0);
const canvasClientWidth = ref(0);
const canvasClientHeight = ref(0);
const isPanning = ref(false);
let panPointerId: number | null = null;
let panStartX = 0;
let panStartY = 0;
let panStartScrollLeft = 0;
let panStartScrollTop = 0;

watch(previewDraft, (value) => {
  const query = { ...route.query };
  if (value) query.preview = "draft";
  else delete query.preview;
  void router.replace({ query });
});

watch(
  () => route.query.preview,
  (value) => {
    previewDraft.value = value === "draft";
  },
);

const snapshot = computed<RoadmapSnapshot | null>(() => {
  if (!workspace.value) return null;
  if (previewDraft.value && workspace.value.draft) {
    return workspace.value.draft.snapshot;
  }
  return workspace.value.current;
});

const activeV3Snapshot = computed(() => {
  if (!v3Workspace.value) return null;
  const preview = v3Workspace.value.draftProposal?.preview;
  if (previewDraft.value && preview) return preview.snapshot;
  return v3Workspace.value.currentRoadmap;
});

const selectedV3Node = computed(() => activeV3Snapshot.value?.nodes.find(
  (node) => node.nodeId === selectedNode.value?.v3NodeId,
) ?? null);

async function submitEmploymentEvidence() {
  const node = selectedV3Node.value;
  const spec = node?.employmentSpec;
  if (!node || !spec || !employmentEmployer.value.trim() || !employmentStartedOn.value
      || !employmentEvidenceUrl.value.trim() || !employmentDescription.value.trim()) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.submitV3Employment({
      canonicalRoleId: typeof spec.canonicalRoleId === "string" ? spec.canonicalRoleId : null,
      roleFamily: String(spec.roleFamily ?? ""),
      roleSpecialization: String(spec.roleSpecialization ?? ""),
      employer: employmentEmployer.value.trim(),
      roleTitle: employmentRoleTitle.value.trim() || String(spec.roleSpecialization ?? ""),
      startedOn: employmentStartedOn.value,
      endedOn: employmentEndedOn.value || null,
      evidenceUrl: employmentEvidenceUrl.value.trim(),
      description: employmentDescription.value.trim(),
    });
    employmentEmployer.value = "";
    employmentRoleTitle.value = "";
    employmentStartedOn.value = "";
    employmentEndedOn.value = "";
    employmentEvidenceUrl.value = "";
    employmentDescription.value = "";
    await reloadV3Workspace();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "경력 증거를 등록하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

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

const nodeSearchResults = computed(() => {
  const query = nodeSearch.value.trim().toLocaleLowerCase("ko-KR");
  if (!query) return [];
  return visibleNodes.value
    .filter((node) =>
      [
        node.title,
        node.subtitle,
        ...node.competencies.map((item) => item.title),
      ]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase("ko-KR").includes(query)),
    )
    .slice(0, 8);
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
const minimapViewport = computed(() => ({
  x: canvasScrollLeft.value / zoom.value,
  y: canvasScrollTop.value / zoom.value,
  width: canvasClientWidth.value / zoom.value,
  height: canvasClientHeight.value / zoom.value,
}));

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
  if (node.type === "EMPLOYMENT") return BriefcaseBusiness;
  if (node.type === "EXPERIENCE") return TimerReset;
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
  updateCanvasViewportState();
}

function updateCanvasViewportState() {
  const viewport = canvasViewport.value;
  if (!viewport) return;
  canvasScrollLeft.value = viewport.scrollLeft;
  canvasScrollTop.value = viewport.scrollTop;
  canvasClientWidth.value = viewport.clientWidth;
  canvasClientHeight.value = viewport.clientHeight;
}

async function focusNode(node: RoadmapNode) {
  nodeSearch.value = "";
  await selectNode(node);
  viewMode.value = "GRAPH";
  await nextTick();
  const positioned = positionedNodes.value.find((item) => item.id === node.id);
  const viewport = canvasViewport.value;
  if (!positioned || !viewport) return;
  viewport.scrollTo({
    left: Math.max(0, positioned.x * zoom.value - viewport.clientWidth / 2),
    top: Math.max(0, positioned.y * zoom.value - viewport.clientHeight / 2),
    behavior: "smooth",
  });
}

function navigateFromMinimap(event: MouseEvent) {
  const viewport = canvasViewport.value;
  const target = event.currentTarget as SVGElement;
  if (!viewport) return;
  const rect = target.getBoundingClientRect();
  const worldX = ((event.clientX - rect.left) / rect.width) * canvasWidth.value;
  const worldY = ((event.clientY - rect.top) / rect.height) * canvasHeight.value;
  viewport.scrollTo({
    left: Math.max(0, worldX * zoom.value - viewport.clientWidth / 2),
    top: Math.max(0, worldY * zoom.value - viewport.clientHeight / 2),
    behavior: "smooth",
  });
}

function trapFocus(event: KeyboardEvent) {
  const container = event.currentTarget as HTMLElement;
  const focusable = [...container.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((item) => !item.hasAttribute("hidden"));
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
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
  updateCanvasViewportState();
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

async function saveCareerGoals(patch: Partial<{
  currentPostingId: string | null;
  finalPostingId: string | null;
  finalGoalText: string | null;
}>) {
  if (goalSaving.value) return;
  goalSaving.value = true;
  error.value = "";
  try {
    const current = careerGoals.value;
    careerGoals.value = await api.updateCareerGoals({
      currentPostingId: patch.currentPostingId !== undefined
        ? patch.currentPostingId
        : current?.currentPostingId ?? null,
      finalPostingId: patch.finalPostingId !== undefined
        ? patch.finalPostingId
        : current?.finalPostingId ?? null,
      finalGoalText: patch.finalGoalText !== undefined
        ? patch.finalGoalText
        : current?.finalGoalText ?? null,
    });
    finalGoalText.value = careerGoals.value.finalGoalText ?? "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "목표를 저장하지 못했습니다.";
  } finally {
    goalSaving.value = false;
  }
}

function setSelectedAsCurrentGoal() {
  if (!selectedPostingId.value) return;
  void saveCareerGoals({ currentPostingId: selectedPostingId.value });
}

function setSelectedAsFinalGoal() {
  if (!selectedPostingId.value) return;
  void saveCareerGoals({ finalPostingId: selectedPostingId.value, finalGoalText: null });
}

function saveFinalGoalText() {
  void saveCareerGoals({
    finalPostingId: null,
    finalGoalText: finalGoalText.value.trim() || null,
  });
}

async function load() {
  error.value = "";
  historyError.value = "";
  try {
    try {
      careerGoals.value = await api.careerGoals();
      finalGoalText.value = careerGoals.value.finalGoalText ?? "";
    } catch {
      careerGoals.value = null;
    }
    let [v3Result] = await Promise.allSettled([api.v3Roadmap()] as const);
    let previewRecoveryError = "";
    if (
      v3Result.status === "fulfilled" &&
      v3Result.value.draftProposal &&
      !v3Result.value.draftProposal.preview
    ) {
      try {
        await api.previewV3Roadmap(v3Result.value.draftProposal.id);
        v3Result = {
          status: "fulfilled",
          value: await api.v3Roadmap(),
        };
      } catch (cause) {
        previewRecoveryError = cause instanceof Error
          ? cause.message
          : "저장된 로드맵 초안의 미리보기를 만들지 못했습니다.";
      }
    }
    const requestedV3 = route.query.provider === "unified" || route.query.provider === "v3";
    const hasV3Journey =
      v3Result.status === "fulfilled" &&
      (v3Result.value.draftProposal !== null ||
        v3Result.value.currentRoadmap.nodes.some(
          (node) =>
            node.nodeKind !== "CAPABILITY" ||
            !node.canonicalKey?.startsWith("foundation."),
        ));

    if (v3Result.status === "fulfilled" && (requestedV3 || hasV3Journey)) {
      v3Workspace.value = v3Result.value;
      workspace.value = adaptV3Workspace(v3Result.value);
      roadmapVersions.value = [];
      try {
        v3RoadmapVersions.value = await api.v3RoadmapVersions();
      } catch (cause) {
        historyError.value = cause instanceof Error
          ? cause.message
          : "로드맵 버전 이력을 불러오지 못했습니다.";
      }
    } else {
      v3Workspace.value = null;
      v3RoadmapVersions.value = [];
      const [roadmapResult, versionsResult] = await Promise.allSettled([
        api.roadmap(),
        api.roadmapVersions(),
      ] as const);
      if (roadmapResult.status === "rejected") throw roadmapResult.reason;
      workspace.value = roadmapResult.value;
      if (versionsResult.status === "fulfilled") {
        roadmapVersions.value = versionsResult.value;
      } else {
        historyError.value =
          versionsResult.reason instanceof Error
            ? versionsResult.reason.message
            : "버전 이력을 불러오지 못했습니다.";
      }
    }
    if (!workspace.value.draft && previewDraft.value) {
      previewDraft.value = false;
    }
    if (previewRecoveryError) {
      error.value = previewRecoveryError;
    }
    if (selectedNode.value) {
      selectedNode.value =
        snapshot.value?.nodes.find((node) => node.id === selectedNode.value?.id) ??
        null;
    }
    const requestedNodeId =
      typeof route.query.node === "string" ? route.query.node : null;
    if (requestedNodeId && !selectedNode.value) {
      const requestedNode = snapshot.value?.nodes.find(
        (node) =>
          node.id === requestedNodeId ||
          node.careerNodeId === requestedNodeId ||
          node.competencies.some(
            (competency) => competency.careerNodeId === requestedNodeId,
          ),
      );
      if (requestedNode) {
        await nextTick();
        await selectNode(requestedNode);
      }
    }
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "로드맵을 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function restoreVersion(version: RoadmapVersion) {
  if (!await productDialog.confirm({ title: "과거 로드맵 복원", message: `로드맵 v${version.version}을 새 초안으로 복원할까요? 현재 지도는 적용 전까지 유지됩니다.`, confirmLabel: "복원 초안 만들기" })) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.restoreRoadmapVersion(version.id);
    historyOpen.value = false;
    await load();
    previewDraft.value = true;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "선택한 버전을 복원하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function restoreV3Version(version: V3RoadmapVersion) {
  if (!await productDialog.confirm({ title: "과거 로드맵 복원", message: `로드맵 v${version.versionNumber}을 새 현재 버전으로 복원할까요? 복원 전 지도도 이력에 남습니다.`, confirmLabel: "버전 복원" })) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.restoreV3RoadmapVersion(version.id);
    historyOpen.value = false;
    await load();
    previewDraft.value = false;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "선택한 로드맵 버전을 복원하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

function formatVersionDate(value: string | null) {
  if (!value) return "적용 시각 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function regenerate() {
  if (
    workspace.value?.draft &&
    !await productDialog.confirm({ title: "초안 다시 계산", message: "현재 검토 중인 초안을 새 계산 결과로 교체할까요?", confirmLabel: "다시 계산" })
  ) {
    return;
  }
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
  if (!await productDialog.confirm({ title: "목표 경로에서 제거", message: `${target?.companyName ?? "선택한 공고"}를 목표 경로에서 제거할까요? 완료 기록은 유지됩니다.`, confirmLabel: "제거", danger: true })) {
    return;
  }
  actionLoading.value = true;
  error.value = "";
  try {
    if (v3Mode.value) {
      await api.createV3TargetRemovalDraft(selectedPostingId.value);
    } else {
      await api.removeRoadmapTarget(selectedPostingId.value);
    }
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
  if (!await productDialog.confirm({ title: "전체 목표 초기화", message: "모든 목표 공고를 경로에서 제거할까요? 완료한 역량과 공고 분석 기록은 삭제되지 않습니다.", confirmLabel: "목표 초기화", danger: true })) {
    return;
  }
  actionLoading.value = true;
  error.value = "";
  try {
    if (v3Mode.value) {
      await api.createV3ResetDraft();
    } else {
      await api.resetRoadmapTargets();
    }
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
    if (v3Mode.value && v3Workspace.value) {
      await api.applyV3Roadmap(
        expectedDraftId,
        v3Workspace.value.currentRoadmap.roadmapVersion,
      );
      v3Workspace.value = await api.v3Roadmap();
      workspace.value = adaptV3Workspace(v3Workspace.value);
      applyConfirmOpen.value = false;
      previewDraft.value = false;
      selectedNode.value = null;
      return;
    }
    await api.applyRoadmapDraft(expectedDraftId, expectedVersion);
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

async function discardDraft() {
  if (!workspace.value?.draft) return;
  const expectedDraftId = workspace.value.draft.id;
  const expectedVersion = workspace.value.draft.version;
  actionLoading.value = true;
  error.value = "";
  try {
    if (v3Mode.value && v3Workspace.value) {
      await api.cancelV3Roadmap(expectedDraftId);
      v3Workspace.value = await api.v3Roadmap();
      workspace.value = adaptV3Workspace(v3Workspace.value);
      discardConfirmOpen.value = false;
      previewDraft.value = false;
      selectedNode.value = null;
      return;
    }
    await api.discardRoadmapDraft(expectedDraftId, expectedVersion);
    workspace.value = await api.roadmap();
    discardConfirmOpen.value = false;
    previewDraft.value = false;
    selectedNode.value = null;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "로드맵 초안을 취소하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

function selectedV3Capability(competency: RoadmapCompetency | null) {
  if (!competency || competency.source !== "UNIFIED") return null;
  return activeV3Snapshot.value?.nodes.find(
    (node) =>
      node.nodeKind === "CAPABILITY" &&
      (competency.provisionalCandidateId
        ? node.provisionalCandidateId === competency.provisionalCandidateId
        : node.canonicalKey === competency.canonicalKey),
  ) ?? null;
}

function v3AssessmentTarget(node: V3RoadmapNode) {
  const nodes = activeV3Snapshot.value?.nodes ?? [];
  const project = nodes.find((item) =>
    item.nodeKind === "TARGET_PROJECT" &&
    item.projectSpec?.tasks?.some((task) =>
      task.capabilityKeys.includes(node.canonicalKey ?? ""),
    ),
  );
  const task = project?.projectSpec?.tasks?.find((item) =>
    item.capabilityKeys.includes(node.canonicalKey ?? ""),
  );
  const opportunity = nodes.find((item) => item.nodeKind === "OPPORTUNITY");
  const opportunitySpec = opportunity?.opportunitySpec as Record<string, string> | undefined;
  return {
    companyName: opportunitySpec?.companyName ?? null,
    roleTitle: opportunitySpec?.positionTitle ?? null,
    projectTaskTitle: task?.title ?? null,
    projectTaskObjective: task?.objective ?? null,
    currentGoal: opportunity?.title ?? null,
    finalGoal: null,
  };
}

async function reloadV3Workspace(canonicalKey?: string) {
  v3Workspace.value = await api.v3Roadmap();
  workspace.value = adaptV3Workspace(v3Workspace.value);
  if (!canonicalKey || !selectedNode.value) return;
  const refreshed = snapshot.value?.nodes.find((node) =>
    node.competencies.some((item) => item.canonicalKey === canonicalKey),
  );
  if (refreshed) {
    selectedNode.value = refreshed;
    evidenceCompetency.value = refreshed.competencies.find(
      (item) => item.canonicalKey === canonicalKey,
    ) ?? null;
  }
}

function projectTaskStateLabel(task: V3ProjectTask) {
  if (task.progressState === "VERIFIED") return "검증 완료";
  if (task.progressState === "EVIDENCED") return `근거 제출${task.evidenceCount ? ` ${task.evidenceCount}건` : ""}`;
  if (task.progressState === "CLAIMED") return "진행 중";
  return "시작 전";
}

function projectTaskDependencyTitles(task: V3ProjectTask) {
  const tasks = selectedNode.value?.project?.tasks ?? [];
  return (task.dependsOnTaskKeys ?? []).map((key) =>
    tasks.find((item) => item.taskKey === key)?.title ?? key,
  );
}

function projectTaskDirectCapabilities(task: V3ProjectTask) {
  const nodes = activeV3Snapshot.value?.nodes ?? [];
  return task.capabilityKeys.map((key) => {
    const node = nodes.find((item) => item.nodeKind === "CAPABILITY" && item.canonicalKey === key);
    return {
      key,
      title: node?.title ?? key,
      scope: node?.scopeDefinition ?? node?.objective ?? "",
    };
  });
}

function projectTaskPrerequisiteCapabilities(task: V3ProjectTask) {
  const raw = activeV3Snapshot.value;
  if (!raw) return [];
  const directKeys = new Set(task.capabilityKeys);
  const nodesById = new Map(raw.nodes.map((node) => [node.nodeId, node]));
  const targetIds = raw.nodes
    .filter((node) => node.nodeKind === "CAPABILITY" && node.canonicalKey && directKeys.has(node.canonicalKey))
    .map((node) => node.nodeId);
  const prerequisiteTypes = new Set([
    "HARD_PREREQUISITE",
    "RECOMMENDED_FOUNDATION",
    "CONDITIONAL_PREREQUISITE",
  ]);
  const incoming = new Map<string, string[]>();
  for (const relation of raw.relations) {
    if (!prerequisiteTypes.has(relation.relationType)) continue;
    const values = incoming.get(relation.toNodeId) ?? [];
    values.push(relation.fromNodeId);
    incoming.set(relation.toNodeId, values);
  }
  const pending = [...targetIds];
  const visited = new Set(targetIds);
  const result = new Map<string, { key: string; title: string; scope: string }>();
  while (pending.length) {
    const targetId = pending.shift()!;
    for (const sourceId of incoming.get(targetId) ?? []) {
      if (visited.has(sourceId)) continue;
      visited.add(sourceId);
      pending.push(sourceId);
      const node = nodesById.get(sourceId);
      if (!node || node.nodeKind !== "CAPABILITY" || !node.canonicalKey || directKeys.has(node.canonicalKey)) continue;
      result.set(node.canonicalKey, {
        key: node.canonicalKey,
        title: node.title,
        scope: node.scopeDefinition ?? node.objective ?? "",
      });
    }
  }
  return [...result.values()].sort((left, right) => left.title.localeCompare(right.title, "ko"));
}

async function reloadSelectedV3Project(nodeId: string) {
  v3Workspace.value = await api.v3Roadmap();
  workspace.value = adaptV3Workspace(v3Workspace.value);
  selectedNode.value = snapshot.value?.nodes.find((node) => node.id === nodeId) ?? null;
}

async function setProjectTaskState(task: V3ProjectTask, state: "NOT_STARTED" | "CLAIMED") {
  if (!selectedNode.value?.careerNodeId || previewDraft.value) return;
  const nodeId = selectedNode.value.id;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.updateV3ProjectTaskState(selectedNode.value.careerNodeId, task.taskKey, state);
    await reloadSelectedV3Project(nodeId);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "프로젝트 과제 상태를 바꾸지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

function openProjectTaskEvidence(task: V3ProjectTask) {
  taskEvidenceKey.value = taskEvidenceKey.value === task.taskKey ? null : task.taskKey;
  taskEvidenceTitle.value = task.title;
  taskEvidenceUrl.value = "";
  taskEvidenceDescription.value = "";
}

async function submitProjectTaskEvidence(task: V3ProjectTask) {
  if (!selectedNode.value?.careerNodeId || previewDraft.value) return;
  const nodeId = selectedNode.value.id;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.addV3ProjectTaskEvidence(selectedNode.value.careerNodeId, task.taskKey, {
      title: taskEvidenceTitle.value.trim(),
      evidenceUrl: taskEvidenceUrl.value.trim(),
      description: taskEvidenceDescription.value.trim(),
    });
    taskEvidenceKey.value = null;
    await reloadSelectedV3Project(nodeId);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "프로젝트 과제 근거를 저장하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function startV3Assessment() {
  const node = selectedV3Capability(evidenceCompetency.value);
  if (
    !node?.canonicalKey ||
    previewDraft.value ||
    evidenceCompetency.value?.assessmentAvailability !== "AVAILABLE"
  ) return;
  v3AssessmentLoading.value = true;
  v3AssessmentError.value = "";
  try {
    v3Assessment.value = await api.startV3AtomicAssessment(
      node.canonicalKey,
      v3AssessmentTarget(node),
    );
  } catch (cause) {
    v3AssessmentError.value = cause instanceof Error
      ? cause.message
      : "검증 문제를 준비하지 못했습니다.";
  } finally {
    v3AssessmentLoading.value = false;
  }
}

async function selfConfirmV3Capability() {
  const node = selectedV3Capability(evidenceCompetency.value);
  if (
    !node?.canonicalKey ||
    node.completionPolicy !== "SELF_CONFIRM" ||
    previewDraft.value ||
    evidenceCompetency.value?.assessmentAvailability !== "AVAILABLE"
  ) return;
  v3AssessmentLoading.value = true;
  v3AssessmentError.value = "";
  try {
    await api.selfConfirmV3AtomicCapability(node.canonicalKey);
    await reloadV3Workspace(node.canonicalKey);
  } catch (cause) {
    v3AssessmentError.value = cause instanceof Error
      ? cause.message
      : "기초 역량 완료 상태를 반영하지 못했습니다.";
  } finally {
    v3AssessmentLoading.value = false;
  }
}

async function answerV3Assessment() {
  if (!v3Assessment.value || !v3AssessmentAnswer.value.trim()) return;
  v3AssessmentLoading.value = true;
  v3AssessmentError.value = "";
  try {
    v3Assessment.value = await api.answerV3AtomicAssessment(
      v3Assessment.value.id,
      v3AssessmentAnswer.value.trim(),
    );
    v3AssessmentAnswer.value = "";
    if (v3Assessment.value.status === "PASSED") {
      await reloadV3Workspace(evidenceCompetency.value?.canonicalKey);
    }
  } catch (cause) {
    v3AssessmentError.value = cause instanceof Error
      ? cause.message
      : "답변을 채점하지 못했습니다.";
  } finally {
    v3AssessmentLoading.value = false;
  }
}

async function abandonV3Assessment() {
  if (!v3Assessment.value) return;
  v3AssessmentLoading.value = true;
  try {
    v3Assessment.value = await api.abandonV3AtomicAssessment(v3Assessment.value.id);
  } catch (cause) {
    v3AssessmentError.value = cause instanceof Error
      ? cause.message
      : "검증을 중단하지 못했습니다.";
  } finally {
    v3AssessmentLoading.value = false;
  }
}

async function requestV3AssessmentReview() {
  if (!v3Assessment.value || !v3AssessmentReviewReason.value.trim()) return;
  v3AssessmentLoading.value = true;
  try {
    v3Assessment.value = await api.reviewV3AtomicAssessment(
      v3Assessment.value.id,
      v3AssessmentReviewReason.value.trim(),
    );
    v3AssessmentReviewReason.value = "";
  } catch (cause) {
    v3AssessmentError.value = cause instanceof Error
      ? cause.message
      : "운영 검토를 요청하지 못했습니다.";
  } finally {
    v3AssessmentLoading.value = false;
  }
}

async function selectNode(node: RoadmapNode) {
  selectedNode.value = node;
  evidenceCompetency.value = null;
  assessment.value = null;
  learning.value = null;
  assessmentAnswer.value = "";
  evidence.value = [];
  v3Assessment.value = null;
  v3AssessmentError.value = "";
  v3AssessmentAnswer.value = "";
  v3AssessmentReviewReason.value = "";
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
  learning.value = null;
  assessmentAnswer.value = "";
  evidence.value = [];
  assessmentLoadError.value = "";
  learningLoadError.value = "";
  v3Assessment.value = null;
  v3AssessmentError.value = "";
  v3AssessmentAnswer.value = "";
  v3AssessmentReviewReason.value = "";
  if (competency.source === "UNIFIED") {
    if (previewDraft.value || competency.assessmentAvailability !== "AVAILABLE") return;
    v3AssessmentLoading.value = true;
    try {
      v3Assessment.value = await api.latestV3AtomicAssessment(competency.canonicalKey);
    } catch (cause) {
      v3AssessmentError.value = cause instanceof Error
        ? cause.message
        : "최근 검증 상태를 불러오지 못했습니다.";
    } finally {
      v3AssessmentLoading.value = false;
    }
    return;
  }
  if (!competency.careerNodeId) return;
  if (!competency.canonicalKey.startsWith("foundation.")) {
    const targetPostingId =
      selectedPostingId.value ?? selectedNode.value?.postingIds[0] ?? null;
    const [assessmentResult, learningResult] = await Promise.allSettled([
      api.latestAssessment(competency.careerNodeId),
      api.latestLearning(competency.careerNodeId, targetPostingId),
    ] as const);
    if (assessmentResult.status === "fulfilled") {
      assessment.value = assessmentResult.value ?? null;
    } else {
      assessmentLoadError.value = "최근 검증 상태를 불러오지 못했습니다.";
    }
    if (learningResult.status === "fulfilled") {
      learning.value = learningResult.value ?? null;
    } else {
      learningLoadError.value = "학습 가이드를 불러오지 못했습니다.";
    }
  }
}

async function retryEvidenceVerification(item: Evidence) {
  actionLoading.value = true;
  error.value = "";
  try {
    await api.retryEvidence(item.id);
    if (selectedNode.value?.careerNodeId) {
      evidence.value = await api.evidence(selectedNode.value.careerNodeId);
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "증거 검증을 다시 시작하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function generateLearning(refresh = false) {
  const competency = evidenceCompetency.value;
  if (!competency?.careerNodeId) return;
  actionLoading.value = true;
  error.value = "";
  try {
    const targetPostingId =
      selectedPostingId.value ?? selectedNode.value?.postingIds[0] ?? null;
    learning.value = await api.generateLearning(
      competency.careerNodeId,
      targetPostingId,
      refresh,
    );
  } catch (cause) {
    error.value = cause instanceof Error
      ? cause.message
      : "AI 학습 가이드를 만들지 못했습니다.";
  } finally {
    actionLoading.value = false;
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

async function abandonAssessment() {
  if (!assessment.value || assessment.value.status !== "IN_PROGRESS") return;
  if (!await productDialog.confirm({ title: "역량 검증 중단", message: "현재 검증을 중단할까요? 제출한 답변은 통과 점수로 이어지지 않습니다.", confirmLabel: "검증 중단", danger: true })) {
    return;
  }
  actionLoading.value = true;
  error.value = "";
  try {
    assessment.value = await api.abandonAssessment(assessment.value.id);
    assessmentAnswer.value = "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "검증을 중단하지 못했습니다.";
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
  learning.value = null;
  assessmentAnswer.value = "";
  evidence.value = [];
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  if (diffOpen.value) {
    diffOpen.value = false;
    return;
  }
  if (applyConfirmOpen.value) {
    applyConfirmOpen.value = false;
    return;
  }
  if (discardConfirmOpen.value) {
    discardConfirmOpen.value = false;
    return;
  }
  closeNode();
}

watch(diffOpen, async (open) => {
  if (!open) return;
  await nextTick();
  diffDialog.value?.focus();
});

watch(applyConfirmOpen, async (open) => {
  if (!open) return;
  await nextTick();
  applyDialog.value?.focus();
});

watch(discardConfirmOpen, async (open) => {
  if (!open) return;
  await nextTick();
  discardDialog.value?.focus();
});

watch(selectedNode, async (node) => {
  if (!node) return;
  await nextTick();
  detailDrawer.value?.focus();
});

watch(viewMode, async (mode) => {
  if (mode !== "GRAPH") return;
  await nextTick();
  updateCanvasViewportState();
});

onMounted(() => {
  void load();
  window.addEventListener("keydown", handleKeydown);
  window.addEventListener("resize", updateCanvasViewportState);
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleKeydown);
  window.removeEventListener("resize", updateCanvasViewportState);
});
</script>

<template>
  <main class="workspace roadmap-v2-workspace">
    <Teleport defer to="#app-topbar-center">
      <h1 class="app-page-title">커리어 지도</h1>
    </Teleport>
    <Teleport defer to="#app-topbar-actions">
      <div class="app-page-meta">
        <span title="현재 적용된 로드맵 스냅샷 번호">버전 <strong>{{ snapshot?.version ?? 1 }}</strong></span>
        <span title="현재 지도에 연결된 목표 공고 수">목표 <strong>{{ workspace?.targetCount ?? 0 }}</strong>개</span>
      </div>
    </Teleport>

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
            class="press-button press-button--ghost roadmap-draft-discard"
            type="button"
            :disabled="actionLoading"
            @click="discardConfirmOpen = true"
          >
            <X :size="17" /> 초안 취소
          </button>
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
        <button class="text-action roadmap-diff-open" type="button" @click="diffOpen = true">
          전체 변경 {{ workspace.draft.changes.added.length + workspace.draft.changes.removed.length + workspace.draft.changes.retained.length }}개 보기
        </button>
      </section>

      <section class="roadmap-goal-controls" aria-label="커리어 목표 설정">
        <div class="roadmap-goal-controls__summary">
          <span>
            <small>현재 목표</small>
            <strong>{{ careerGoals?.currentCompanyName ?? "선택하지 않음" }}</strong>
          </span>
          <span>
            <small>최종 목표</small>
            <strong>{{ careerGoals?.finalCompanyName ?? careerGoals?.finalGoalText ?? "선택하지 않음" }}</strong>
          </span>
        </div>
        <form class="roadmap-goal-controls__custom" @submit.prevent="saveFinalGoalText">
          <label for="final-career-goal">직접 입력한 최종 목표</label>
          <input
            id="final-career-goal"
            v-model="finalGoalText"
            type="text"
            maxlength="240"
            placeholder="예: 글로벌 콘텐츠 플랫폼 백엔드 개발자"
          />
          <button class="press-button press-button--ghost" type="submit" :disabled="goalSaving">
            저장
          </button>
        </form>
      </section>

      <section class="roadmap-toolbar">
        <div class="roadmap-target-filters" aria-label="목표 경로 선택">
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
            <small v-if="careerGoals?.currentPostingId === target.postingId">현재 목표</small>
            <small v-if="careerGoals?.finalPostingId === target.postingId">최종 목표</small>
            <small
              v-if="target.goalMode === 'REOPENING_PREPARATION'"
              class="roadmap-target-goal-mode"
            >
              재오픈 대비
            </small>
          </button>
        </div>
        <div class="roadmap-toolbar__actions">
          <button
            v-if="selectedPostingId"
            class="press-button press-button--ghost roadmap-toolbar__button"
            type="button"
            :disabled="goalSaving"
            @click="setSelectedAsCurrentGoal"
          >
            <CircleDot :size="17" /> 현재 목표로
          </button>
          <button
            v-if="selectedPostingId"
            class="press-button press-button--ghost roadmap-toolbar__button"
            type="button"
            :disabled="goalSaving"
            @click="setSelectedAsFinalGoal"
          >
            <Flag :size="17" /> 최종 목표로
          </button>
          <button
            v-if="!v3Mode && workspace.targetCount > 0"
            class="press-button press-button--ghost roadmap-toolbar__button"
            type="button"
            title="현재 목표로 초안 다시 만들기"
            :disabled="actionLoading"
            @click="regenerate"
          >
            <RefreshCw :size="17" /> 경로 다시 계산
          </button>
          <button
            v-if="selectedPostingId"
            class="press-button press-button--ghost roadmap-toolbar__button roadmap-toolbar__button--danger"
            type="button"
            title="선택한 목표 제거"
            :disabled="actionLoading"
            @click="removeSelectedTarget"
          >
            <Trash2 :size="17" /> 선택 목표 제거
          </button>
          <button
            v-if="workspace.targetCount > 0"
            class="press-button press-button--ghost roadmap-reset-action roadmap-toolbar__button--danger"
            type="button"
            :disabled="actionLoading"
            @click="resetTargets"
          >
            <Trash2 :size="17" /> 전체 목표 초기화
          </button>
          <button
            class="press-button press-button--ghost roadmap-toolbar__button"
            type="button"
            @click="historyOpen = !historyOpen"
          >
            <History :size="17" /> 버전 이력
          </button>
        </div>
      </section>

      <section v-if="historyOpen" class="roadmap-version-panel">
        <header><div><p class="eyebrow">VERSION HISTORY</p><h2>적용한 지도 이력</h2></div><button class="icon-button" type="button" aria-label="버전 이력 닫기" @click="historyOpen = false"><X :size="17" /></button></header>
        <p v-if="historyError" class="inline-error">{{ historyError }}</p>
        <div v-else-if="v3Mode && v3RoadmapVersions.length" class="roadmap-version-list">
          <article v-for="version in v3RoadmapVersions" :key="version.id">
            <span><strong>v{{ version.versionNumber }}</strong><small>{{ version.status === 'PUBLISHED' ? '현재 적용' : '이전 버전' }}</small></span>
            <div><strong>목표 {{ version.targetCount }}개</strong><small>{{ formatVersionDate(version.publishedAt) }}</small></div>
            <button v-if="version.status !== 'PUBLISHED'" class="press-button press-button--ghost" type="button" :disabled="actionLoading" @click="restoreV3Version(version)"><RotateCcw :size="15" /> 이 버전 복원</button>
          </article>
        </div>
        <div v-else-if="!v3Mode && roadmapVersions.length" class="roadmap-version-list">
          <article v-for="version in roadmapVersions" :key="version.id">
            <span><strong>v{{ version.version }}</strong><small>{{ version.status === 'PUBLISHED' ? '현재 적용' : '이전 버전' }}</small></span>
            <div><strong>목표 {{ version.targetCount }}개</strong><small>{{ formatVersionDate(version.publishedAt) }} · 추가 {{ version.changes.added.length }} · 제외 {{ version.changes.removed.length }}</small></div>
            <button v-if="version.status !== 'PUBLISHED'" class="press-button press-button--ghost" type="button" :disabled="actionLoading" @click="restoreVersion(version)"><RotateCcw :size="15" /> 초안으로 복원</button>
          </article>
        </div>
        <p v-else class="notification-empty">아직 적용한 지도 이력이 없습니다.</p>
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
          <div class="roadmap-node-search">
            <label>
              <Search :size="16" />
              <input v-model="nodeSearch" type="search" placeholder="기술·회사·퀘스트 검색" aria-label="로드맵 노드 검색" />
            </label>
            <div v-if="nodeSearch.trim()" class="roadmap-node-search__results">
              <button v-for="node in nodeSearchResults" :key="node.id" type="button" @click="focusNode(node)">
                <strong>{{ node.title }}</strong><small>{{ domainMeta[normalizedDomain(node.domain)]?.label || normalizedDomain(node.domain) }} · {{ statusLabel(node.status) }}</small>
              </button>
              <p v-if="!nodeSearchResults.length">일치하는 퀘스트가 없습니다.</p>
            </div>
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
          @scroll="updateCanvasViewportState"
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
                          ? node.goalMode === "REOPENING_PREPARATION"
                            ? "재오픈 대비 목표"
                            : "지원 기회"
                          : node.type === "GATE"
                            ? "지원 조건"
                          : node.type === "EMPLOYMENT"
                            ? "실제 취업 확인"
                          : node.type === "EXPERIENCE"
                            ? "관련 경력 구간"
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
        <svg
          v-if="viewMode === 'GRAPH'"
          class="roadmap-minimap"
          :viewBox="`0 0 ${canvasWidth} ${canvasHeight}`"
          role="img"
          aria-label="로드맵 미니맵. 클릭하면 해당 위치로 이동합니다."
          @click="navigateFromMinimap"
        >
          <rect v-for="section in domainSections" :key="section.key" x="0" :y="section.y" :width="canvasWidth" :height="section.height" :fill="section.color" opacity="0.1" />
          <circle v-for="node in positionedNodes" :key="node.id" :cx="node.x + 90" :cy="node.y + 43" r="22" :class="{ completed: node.status === 'COMPLETED' }" />
          <rect class="roadmap-minimap__viewport" :x="minimapViewport.x" :y="minimapViewport.y" :width="Math.min(minimapViewport.width, canvasWidth)" :height="Math.min(minimapViewport.height, canvasHeight)" />
        </svg>
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
      ref="detailDrawer"
      class="detail-drawer quest-detail-drawer"
      role="dialog"
      aria-modal="true"
      aria-label="퀘스트 상세"
      tabindex="-1"
      @keydown.tab="trapFocus"
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
              <small
                v-if="competency.catalogStatus === 'PENDING_REVIEW'"
                class="catalog-review-badge"
              >
                공용 역량 사전 검토 대기
              </small>
            </span>
            <ChevronRight :size="16" />
          </button>
        </section>

        <section v-if="evidenceCompetency" class="roadmap-drawer-section">
          <h3>{{ evidenceCompetency.title }}</h3>
          <p>{{ evidenceCompetency.scopeDefinition }}</p>
          <p v-if="assessmentLoadError" class="inline-error">{{ assessmentLoadError }}</p>
          <p v-if="learningLoadError" class="inline-error">{{ learningLoadError }}</p>
          <div
            v-if="evidenceCompetency.source === 'UNIFIED'"
            class="v3-atomic-assessment unified-v3-assessment"
          >
            <div v-if="evidenceCompetency.verificationMethods?.length" class="v3-atomic-assessment__methods">
              <span v-for="method in evidenceCompetency.verificationMethods" :key="method">
                {{ method }}
              </span>
            </div>
            <p v-if="previewDraft" class="v3-atomic-assessment__notice">
              미리보기 역량입니다. 새 지도를 적용하면 검증을 시작할 수 있습니다.
            </p>
            <p
              v-if="evidenceCompetency.catalogStatus === 'PENDING_REVIEW'"
              class="v3-atomic-assessment__notice v3-atomic-assessment__notice--pending"
            >
              이 공고에서 새로 발견된 임시 역량입니다. 로드맵에는 포함되지만 공용 역량 사전 검토가
              끝난 뒤 학습·검증을 시작할 수 있습니다.
            </p>
            <p
              v-else-if="evidenceCompetency.assessmentAvailability === 'NOT_ATOMIC'"
              class="v3-atomic-assessment__notice"
            >
              기존 로드맵의 넓은 범위 역량입니다. 공용 역량 사전에서 검증 범위가 승인된 원자 역량으로
              연결된 뒤 검증을 시작할 수 있습니다.
            </p>
            <div v-else-if="v3AssessmentLoading" class="v3-atomic-assessment__loading">
              <LoaderCircle class="spin" :size="18" /> 검증 상태를 확인하고 있습니다.
            </div>
            <p v-if="v3AssessmentError" class="inline-error">{{ v3AssessmentError }}</p>
            <button
              v-if="
                !previewDraft &&
                evidenceCompetency.assessmentAvailability === 'AVAILABLE' &&
                evidenceCompetency.completionPolicy === 'SELF_CONFIRM' &&
                evidenceCompetency.progressStatus !== 'COMPLETED'
              "
              class="press-button press-button--primary"
              type="button"
              :disabled="v3AssessmentLoading"
              @click="selfConfirmV3Capability"
            >
              <Check :size="16" /> 이해했어요
            </button>
            <p
              v-else-if="
                evidenceCompetency.completionPolicy === 'SELF_CONFIRM' &&
                evidenceCompetency.progressStatus === 'COMPLETED'
              "
              class="v3-atomic-assessment__notice"
            >
              완료를 확인한 공통 기초 역량입니다.
            </p>
            <button
              v-if="
                !previewDraft &&
                evidenceCompetency.assessmentAvailability === 'AVAILABLE' &&
                evidenceCompetency.completionPolicy !== 'SELF_CONFIRM' &&
                evidenceCompetency.progressStatus !== 'COMPLETED' &&
                !v3Assessment &&
                !v3AssessmentLoading
              "
              class="press-button press-button--primary"
              type="button"
              @click="startV3Assessment"
            >
              <Sparkles :size="16" /> 원자 역량 검증 시작
            </button>
            <template v-if="v3Assessment">
              <div class="v3-atomic-assessment__status" :data-status="v3Assessment.status">
                <strong>{{ v3Assessment.status }}</strong>
                <span v-if="v3Assessment.averageScore !== null">평균 {{ v3Assessment.averageScore }}점</span>
              </div>
              <article
                v-for="turn in v3Assessment.turns.filter((item) => item.answerText)"
                :key="turn.id"
                class="v3-atomic-assessment__result"
              >
                <header><span>{{ turn.method }}</span><strong>{{ turn.score }}점</strong></header>
                <p>{{ turn.grade?.feedback }}</p>
              </article>
              <article v-if="v3OpenAssessmentTurn" class="v3-atomic-assessment__question">
                <small>{{ v3OpenAssessmentTurn.method }} · {{ v3OpenAssessmentTurn.ordinal }}번째 문제</small>
                <h4>{{ v3OpenAssessmentTurn.question.prompt }}</h4>
                <pre v-if="v3OpenAssessmentTurn.question.starterCode"><code>{{ v3OpenAssessmentTurn.question.starterCode }}</code></pre>
                <p>{{ v3OpenAssessmentTurn.question.answerInstructions }}</p>
                <textarea v-model="v3AssessmentAnswer" rows="7" placeholder="답변과 근거를 작성해주세요." />
                <div class="v3-atomic-assessment__actions">
                  <button class="press-button press-button--ghost" type="button" @click="abandonV3Assessment">나중에 하기</button>
                  <button
                    class="press-button press-button--primary"
                    type="button"
                    :disabled="v3AssessmentLoading || !v3AssessmentAnswer.trim()"
                    @click="answerV3Assessment"
                  >
                    답변 제출
                  </button>
                </div>
              </article>
              <div v-if="['NEEDS_STUDY', 'ABANDONED'].includes(v3Assessment.status)" class="v3-atomic-assessment__retry">
                <button class="press-button press-button--secondary" type="button" @click="startV3Assessment">새 문제로 재도전</button>
                <textarea v-model="v3AssessmentReviewReason" rows="3" placeholder="운영 검토가 필요한 이유" />
                <button
                  class="press-button press-button--ghost"
                  type="button"
                  :disabled="!v3AssessmentReviewReason.trim()"
                  @click="requestV3AssessmentReview"
                >
                  운영 검토 요청
                </button>
              </div>
            </template>
          </div>
          <button
            v-if="
              evidenceCompetency.source !== 'UNIFIED' &&
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
          <p
            v-else-if="evidenceCompetency.source !== 'UNIFIED' && !evidenceCompetency.careerNodeId"
            class="drawer-hint"
          >
            새 로드맵 버전을 적용하면 이 역량을 검증할 수 있습니다.
          </p>

          <section
            v-if="
              !evidenceCompetency.canonicalKey.startsWith('foundation.') &&
              evidenceCompetency.source !== 'UNIFIED' &&
              evidenceCompetency.careerNodeId
            "
            class="competency-learning-card"
          >
            <header>
              <span><BookOpen :size="20" /></span>
              <div>
                <strong>먼저 학습하기</strong>
                <small>공통 역량 범위는 유지하고 목표 공고의 사례만 반영합니다.</small>
              </div>
              <button
                v-if="learning"
                class="icon-button"
                type="button"
                title="학습 가이드 다시 만들기"
                :disabled="actionLoading"
                @click="generateLearning(true)"
              >
                <RefreshCw :size="15" />
              </button>
            </header>
            <button
              v-if="!learning"
              class="press-button press-button--secondary"
              type="button"
              :disabled="actionLoading"
              @click="generateLearning(false)"
            >
              <BookOpen :size="16" />
              {{ actionLoading ? "가이드를 만들고 있어요" : "학습 가이드 만들기" }}
            </button>
            <div v-else class="competency-learning-content">
              <h4>{{ learning.title }}</h4>
              <p>{{ learning.summary }}</p>
              <small>{{ learning.scopeReminder }}</small>
              <details
                v-for="(module, moduleIndex) in learning.modules"
                :key="`${module.title}-${moduleIndex}`"
                :open="moduleIndex === 0"
              >
                <summary>
                  <span>{{ moduleIndex + 1 }}</span>
                  <strong>{{ module.title }}</strong>
                  <ChevronRight :size="15" />
                </summary>
                <p>{{ module.objective }}</p>
                <div class="learning-concepts">
                  <span v-for="concept in module.concepts" :key="concept">
                    {{ concept }}
                  </span>
                </div>
                <article v-if="module.example">
                  <small>예시</small>
                  <p>{{ module.example }}</p>
                </article>
                <article>
                  <small>직접 해보기</small>
                  <p>{{ module.practice }}</p>
                </article>
                <ul>
                  <li v-for="criterion in module.completionCriteria" :key="criterion">
                    {{ criterion }}
                  </li>
                </ul>
              </details>
              <div v-if="learning.assessmentReadiness.length" class="learning-readiness">
                <strong>검증 전 확인</strong>
                <span v-for="item in learning.assessmentReadiness" :key="item">
                  <Check :size="13" /> {{ item }}
                </span>
              </div>
              <div v-if="learning.recommendedResources.length" class="learning-resources">
                <strong>찾아볼 자료 유형</strong>
                <span v-for="resource in learning.recommendedResources" :key="resource">
                  <BookOpen :size="13" /> {{ resource }}
                </span>
                <small>확인되지 않은 강의·책 URL은 자동으로 만들지 않습니다.</small>
              </div>
            </div>
          </section>

          <div
            v-if="
              !evidenceCompetency.canonicalKey.startsWith('foundation.') &&
              evidenceCompetency.careerNodeId &&
              !assessment
            "
            class="assessment-start-card"
          >
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
          <div
            v-else-if="
              !evidenceCompetency.canonicalKey.startsWith('foundation.') &&
              evidenceCompetency.careerNodeId &&
              assessment
            "
            class="assessment-session"
          >
            <header class="assessment-session__header">
              <span
                class="status-chip"
                :class="`assessment-status--${assessment.status.toLowerCase()}`"
              >
                {{
                  assessment.status === "IN_PROGRESS"
                    ? `검증 ${assessment.questionCount + 1}번째 문제`
                    : assessment.status === "PASSED"
                      ? "검증 통과"
                      : assessment.status === "ABANDONED"
                        ? "사용자가 중단"
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
                <button
                  class="press-button press-button--ghost"
                  type="button"
                  :disabled="actionLoading"
                  @click="abandonAssessment"
                >
                  검증 중단
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
                    : assessment.status === "ABANDONED"
                      ? "이 검증은 중단되었습니다"
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
                v-if="['NEEDS_STUDY', 'ABANDONED'].includes(assessment.status)"
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

      <template v-else-if="selectedNode.type === 'EMPLOYMENT'">
        <section class="roadmap-drawer-section">
          <h3>관련 직무 취업 증거</h3>
          <p>프로젝트 완료와 실제 재직 경력은 구분됩니다. 재직 증거가 검토된 날부터 해당 직무의 경력 구간에 반영됩니다.</p>
          <form class="roadmap-evidence-form employment-evidence-form" @submit.prevent="submitEmploymentEvidence">
            <input v-model="employmentEmployer" maxlength="200" placeholder="회사명" />
            <input v-model="employmentRoleTitle" maxlength="200" placeholder="실제 직무명" />
            <label>근무 시작일<input v-model="employmentStartedOn" type="date" /></label>
            <label>근무 종료일<input v-model="employmentEndedOn" type="date" /></label>
            <input v-model="employmentEvidenceUrl" maxlength="2000" placeholder="재직·경력 증거 URL" />
            <textarea v-model="employmentDescription" rows="4" maxlength="4000" placeholder="담당 업무와 이 경력이 목표 직무와 관련된 이유" />
            <button
              class="press-button press-button--primary"
              type="submit"
              :disabled="actionLoading || !employmentEmployer.trim() || !employmentStartedOn || !employmentEvidenceUrl.trim() || !employmentDescription.trim()"
            >
              <BriefcaseBusiness :size="16" /> 운영 검토 요청
            </button>
          </form>
        </section>
      </template>

      <template v-else-if="selectedNode.type === 'EXPERIENCE'">
        <section class="roadmap-drawer-section">
          <h3>검증된 관련 경력</h3>
          <p>{{ selectedNode.subtitle }}</p>
          <small>프로젝트 기간이나 자기 신고만으로는 경력이 증가하지 않습니다. 검증된 관련 직무 근무 기간만 중복 없이 합산합니다.</small>
        </section>
      </template>

      <template v-else-if="selectedNode.project">
        <section class="roadmap-drawer-section">
          <h3>프로젝트 목표</h3>
          <p>{{ selectedNode.project.objective }}</p>
          <small>{{ selectedNode.project.domainContext }}</small>
        </section>
        <section v-if="selectedNode.project.tasks?.length" class="roadmap-drawer-section">
          <h3>프로젝트 구현 단계</h3>
          <article
            v-for="(task, index) in selectedNode.project.tasks"
            :key="task.taskKey"
            class="v3-project-task"
          >
            <header>
              <span>{{ index + 1 }}</span>
              <div>
                <small>{{ task.necessity }} · {{ projectTaskStateLabel(task) }}</small>
                <h4>{{ task.title }}</h4>
              </div>
            </header>
            <p>{{ task.objective }}</p>
            <p v-if="projectTaskDependencyTitles(task).length" class="v3-project-task__dependencies">
              먼저 완료: {{ projectTaskDependencyTitles(task).join(" · ") }}
            </p>
            <div v-if="projectTaskDirectCapabilities(task).length" class="v3-project-task__capability-group">
              <small>이 과제에서 직접 사용하는 역량</small>
              <div class="v3-project-task__capability-list">
                <span
                  v-for="capability in projectTaskDirectCapabilities(task)"
                  :key="capability.key"
                  :title="capability.scope"
                  class="v3-project-task__capability"
                >
                  {{ capability.title }}
                </span>
              </div>
            </div>
            <details
              v-if="projectTaskPrerequisiteCapabilities(task).length"
              class="v3-project-task__prerequisites"
            >
              <summary>선수 역량 {{ projectTaskPrerequisiteCapabilities(task).length }}개</summary>
              <div class="v3-project-task__capability-list">
                <span
                  v-for="capability in projectTaskPrerequisiteCapabilities(task)"
                  :key="capability.key"
                  :title="capability.scope"
                  class="v3-project-task__capability v3-project-task__capability--prerequisite"
                >
                  {{ capability.title }}
                </span>
              </div>
            </details>
            <ul>
              <li v-for="criterion in task.acceptanceCriteria" :key="criterion">
                {{ criterion }}
              </li>
            </ul>
            <div
              v-if="selectedNode.source === 'UNIFIED' && selectedNode.careerNodeId && !previewDraft"
              class="v3-project-task__actions"
            >
              <button
                class="press-button press-button--ghost"
                type="button"
                :disabled="actionLoading || task.progressState === 'VERIFIED'"
                @click="setProjectTaskState(task, task.progressState === 'CLAIMED' ? 'NOT_STARTED' : 'CLAIMED')"
              >
                {{ task.progressState === "CLAIMED" ? "시작 전으로" : "과제 시작" }}
              </button>
              <button
                class="press-button press-button--primary"
                type="button"
                :disabled="actionLoading || task.progressState === 'VERIFIED'"
                @click="openProjectTaskEvidence(task)"
              >
                근거 연결
              </button>
            </div>
            <form
              v-if="taskEvidenceKey === task.taskKey"
              class="v3-project-task__evidence"
              @submit.prevent="submitProjectTaskEvidence(task)"
            >
              <input v-model="taskEvidenceTitle" required maxlength="240" placeholder="근거 제목" />
              <input v-model="taskEvidenceUrl" required type="url" placeholder="https://github.com/owner/repository" />
              <textarea v-model="taskEvidenceDescription" required rows="3" placeholder="이 과제를 충족한 구현과 검증 결과" />
              <button class="press-button press-button--primary" type="submit" :disabled="actionLoading">
                근거 저장
              </button>
            </form>
          </article>
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
          <p v-if="selectedNode.source === 'UNIFIED'" class="drawer-hint">
            프로젝트 과제와 완료 기준을 모두 충족한 뒤 저장소 근거를 연결해 검증합니다.
          </p>
          <p v-else-if="!selectedNode.careerNodeId" class="drawer-hint">
            새 로드맵 버전을 적용하면 프로젝트 결과물을 제출할 수 있습니다.
          </p>
          <form
            v-else
            class="roadmap-evidence-form"
            @submit.prevent="submitProjectEvidence"
          >
            <input v-model="evidenceTitle" placeholder="프로젝트 결과물 제목" maxlength="180" />
            <input
              v-model="evidenceUrl"
              type="url"
              required
              placeholder="https://github.com/owner/repository"
            />
            <small class="evidence-repository-note">
              프로젝트는 GitHub 또는 설정된 GitLab의 실제 커밋을 읽어 검증합니다.
              비공개 저장소는 <RouterLink :to="{ name: 'settings' }">설정에서 읽기 전용 연결</RouterLink>이 필요합니다.
            </small>
            <textarea
              v-model="evidenceDescription"
              placeholder="구현 기능, 테스트, 측정 결과를 설명해 주세요."
              rows="4"
            ></textarea>
            <button
              class="press-button press-button--primary"
              type="submit"
              :disabled="actionLoading || !evidenceTitle.trim() || !evidenceUrl.trim()"
            >
              <Rocket :size="16" /> 프로젝트 검증 요청
            </button>
          </form>
          <article v-for="item in evidence" :key="item.id" class="evidence-mini-card">
            <div>
              <strong>{{ item.title }}</strong>
              <small>{{ item.verificationStatus }}</small>
              <p v-if="item.errorMessage">{{ item.errorMessage }}</p>
            </div>
            <button
              v-if="item.verificationStatus === 'FAILED'"
              class="press-button press-button--ghost"
              type="button"
              :disabled="actionLoading"
              @click="retryEvidenceVerification(item)"
            >
              <RefreshCw :size="14" /> 재시도
            </button>
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
      v-if="diffOpen"
      class="quest-dialog-backdrop"
      type="button"
      aria-label="전체 변경 내역 닫기"
      @click="diffOpen = false"
    />
    <section v-if="diffOpen && workspace?.draft" ref="diffDialog" class="roadmap-diff-dialog" role="dialog" aria-modal="true" aria-labelledby="roadmap-diff-title" tabindex="-1" @keydown.esc="diffOpen = false" @keydown.tab="trapFocus">
      <header><div><p class="eyebrow">COMPLETE DIFF</p><h2 id="roadmap-diff-title">로드맵 전체 변경 내역</h2></div><button class="icon-button" type="button" aria-label="닫기" @click="diffOpen = false"><X :size="18" /></button></header>
      <div class="roadmap-diff-columns">
        <section><h3>추가 {{ workspace.draft.changes.added.length }}</h3><ul><li v-for="item in workspace.draft.changes.added" :key="`add:${item}`">{{ item }}</li></ul><p v-if="!workspace.draft.changes.added.length">없음</p></section>
        <section><h3>제외 {{ workspace.draft.changes.removed.length }}</h3><ul><li v-for="item in workspace.draft.changes.removed" :key="`remove:${item}`">{{ item }}</li></ul><p v-if="!workspace.draft.changes.removed.length">없음</p></section>
        <section><h3>유지 {{ workspace.draft.changes.retained.length }}</h3><ul><li v-for="item in workspace.draft.changes.retained" :key="`keep:${item}`">{{ item }}</li></ul><p v-if="!workspace.draft.changes.retained.length">없음</p></section>
      </div>
    </section>

    <button
      v-if="discardConfirmOpen"
      class="quest-dialog-backdrop"
      type="button"
      aria-label="로드맵 초안 취소 창 닫기"
      @click="discardConfirmOpen = false"
    />
    <section
      v-if="discardConfirmOpen"
      ref="discardDialog"
      class="quest-confirm-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="roadmap-discard-title"
      tabindex="-1"
      @keydown.esc="discardConfirmOpen = false"
      @keydown.tab="trapFocus"
    >
      <div class="quest-confirm-character quest-confirm-character--muted" aria-hidden="true">
        <span class="quest-confirm-character__antenna" />
        <span class="quest-confirm-character__eye quest-confirm-character__eye--left" />
        <span class="quest-confirm-character__eye quest-confirm-character__eye--right" />
        <span class="quest-confirm-character__smile" />
      </div>
      <p class="eyebrow">DISCARD DRAFT</p>
      <h2 id="roadmap-discard-title">이 초안을 취소할까요?</h2>
      <p>현재 적용된 지도와 완료 기록은 유지되고, 검토 중인 새 초안만 삭제됩니다.</p>
      <div class="quest-confirm-dialog__actions">
        <button
          class="press-button press-button--ghost"
          type="button"
          :disabled="actionLoading"
          @click="discardConfirmOpen = false"
        >
          계속 검토하기
        </button>
        <button
          class="press-button press-button--danger"
          type="button"
          :disabled="actionLoading"
          @click="discardDraft"
        >
          <LoaderCircle v-if="actionLoading" class="spin" :size="18" />
          <X v-else :size="18" />
          초안 취소
        </button>
      </div>
    </section>

    <button
      v-if="applyConfirmOpen"
      ref="applyDialog"
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
      tabindex="-1"
      @keydown.tab="trapFocus"
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

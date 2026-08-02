<script setup lang="ts">
import {
  BookOpen,
  Boxes,
  BriefcaseBusiness,
  Check,
  Code2,
  FileCheck2,
  Flag,
  GraduationCap,
  Link2,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Search,
  Sparkles,
  Trophy,
  X,
  type LucideIcon,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { api } from "@/api";
import JobissGuide from "@/components/JobissGuide.vue";
import { showcaseCareerMap, showcasePostings } from "@/demo/showcase-data";
import type { CareerMap, CareerNode, Evidence, Posting } from "@/types";

type PositionedNode = CareerNode & { x: number; y: number };
type Lane = { domain: string; label: string; y: number; height: number };
type QuestItem = {
  title: string;
  description: string;
  doneCriteria: string;
};

const route = useRoute();
const careerMap = ref<CareerMap | null>(null);
const postings = ref<Posting[]>([]);
const selectedNode = ref<CareerNode | null>(null);
const selectedPostingId = ref<string | null>(null);
const selectedDomain = ref("ALL");
const search = ref("");
const loading = ref(true);
const actionLoading = ref(false);
const error = ref("");
const drawerError = ref("");
const evidence = ref<Evidence[]>([]);
const evidenceType = ref("PROJECT");
const evidenceTitle = ref("");
const evidenceUrl = ref("");
const evidenceDescription = ref("");
let evidenceTimer: number | null = null;

const iconByKind: Record<string, LucideIcon> = {
  FOUNDATION: BookOpen,
  SKILL: Code2,
  PROJECT: Boxes,
  CREDENTIAL: GraduationCap,
  EXPERIENCE: Trophy,
  OPPORTUNITY: Flag,
  OPPORTUNITY_CLUSTER: BriefcaseBusiness,
};

const artworkByKind: Record<string, string> = {
  FOUNDATION: "/img/roadmap-nodes/goal-star.png",
  SKILL: "/img/roadmap-nodes/sql-planet.png",
  PROJECT: "/img/roadmap-nodes/api-planet.png",
  CREDENTIAL: "/img/roadmap-nodes/document-star.png",
  EXPERIENCE: "/img/roadmap-nodes/portfolio-comet.png",
  OPPORTUNITY: "/img/roadmap-nodes/success-sun.png",
  OPPORTUNITY_CLUSTER: "/img/roadmap-nodes/constellation.png",
};

function nodeArtwork(node: CareerNode) {
  if (node.domain === "DATA") return "/img/roadmap-nodes/analytics-moon.png";
  if (node.domain === "CLOUD") return "/img/roadmap-nodes/constellation.png";
  return artworkByKind[node.kind] ?? "/img/roadmap-nodes/goal-star.png";
}

const domainLabels: Record<string, string> = {
  COMMON: "공통 기반",
  BACKEND: "백엔드",
  FRONTEND: "프론트엔드",
  MOBILE: "모바일",
  DATA: "데이터·AI",
  CLOUD: "클라우드·DevOps",
  SECURITY: "보안",
};

const domains = computed(() => {
  const values = [...new Set((careerMap.value?.nodes ?? []).map((node) => node.domain))];
  return values.sort((a, b) => {
    if (a === "COMMON") return -1;
    if (b === "COMMON") return 1;
    return a.localeCompare(b);
  });
});

const lanes = computed<Lane[]>(() => {
  let y = 58;
  return domains.value.map((domain) => {
    const perRank = new Map<number, number>();
    for (const node of careerMap.value?.nodes ?? []) {
      if (node.domain === domain) {
        perRank.set(node.rank, (perRank.get(node.rank) ?? 0) + 1);
      }
    }
    const height = Math.max(180, 100 + Math.max(1, ...perRank.values()) * 88);
    const lane = { domain, label: domainLabels[domain] ?? domain, y, height };
    y += height + 24;
    return lane;
  });
});

const positionedNodes = computed<PositionedNode[]>(() => {
  const laneByDomain = new Map(lanes.value.map((lane) => [lane.domain, lane]));
  const counts = new Map<string, number>();
  return (careerMap.value?.nodes ?? []).map((node) => {
    const group = `${node.domain}:${node.rank}`;
    const index = counts.get(group) ?? 0;
    counts.set(group, index + 1);
    const lane = laneByDomain.get(node.domain);
    return {
      ...node,
      x: 190 + node.rank * 235,
      y: (lane?.y ?? 80) + 66 + index * 88,
    };
  });
});

const nodePositions = computed(
  () => new Map(positionedNodes.value.map((node) => [node.id, node])),
);

const canvasWidth = computed(() => {
  const maxRank = Math.max(3, ...positionedNodes.value.map((node) => node.rank));
  return 430 + maxRank * 235;
});

const canvasHeight = computed(() => {
  const last = lanes.value[lanes.value.length - 1];
  return Math.max(560, (last?.y ?? 0) + (last?.height ?? 500) + 48);
});

const drawnEdges = computed(() =>
  (careerMap.value?.edges ?? [])
    .map((edge) => {
      const from = nodePositions.value.get(edge.fromNodeId);
      const to = nodePositions.value.get(edge.toNodeId);
      if (!from || !to) return null;
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      return {
        ...edge,
        x: from.x + 27,
        y: from.y + 27,
        width: Math.sqrt(dx * dx + dy * dy),
        angle: Math.atan2(dy, dx) * (180 / Math.PI),
      };
    })
    .filter((edge): edge is NonNullable<typeof edge> => Boolean(edge)),
);

const selectedRequirements = computed(() => {
  const result = new Map<string, "REQUIRED" | "PREFERRED">();
  if (!selectedPostingId.value) return result;
  for (const item of careerMap.value?.requirements ?? []) {
    if (item.postingId === selectedPostingId.value) {
      result.set(item.nodeId, item.kind);
    }
  }
  return result;
});

const relevantPostings = computed(() =>
  postings.value.filter((item) => item.companyName && item.analysisStatus === "SUCCEEDED"),
);

const completedCount = computed(
  () => (careerMap.value?.nodes ?? []).filter((item) => item.progressStatus === "COMPLETED").length,
);

const completedNodeIds = computed(
  () =>
    new Set(
      (careerMap.value?.nodes ?? [])
        .filter((node) => node.progressStatus === "COMPLETED")
        .map((node) => node.id),
    ),
);

const selectedPrerequisites = computed(() => {
  if (!selectedNode.value) return [];
  const nodeById = new Map(
    (careerMap.value?.nodes ?? []).map((node) => [node.id, node] as const),
  );
  return (careerMap.value?.edges ?? [])
    .filter((edge) => edge.toNodeId === selectedNode.value?.id)
    .map((edge) => nodeById.get(edge.fromNodeId))
    .filter((node): node is CareerNode => Boolean(node));
});

const selectedQuests = computed<QuestItem[]>(() => {
  const value = selectedNode.value?.detail?.quests;
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      title: typeof item.title === "string" ? item.title : "수행 과제",
      description: typeof item.description === "string" ? item.description : "",
      doneCriteria:
        typeof item.doneCriteria === "string" ? item.doneCriteria : "결과물을 설명할 수 있어야 합니다.",
    }));
});

const selectedOutcomes = computed(() => {
  const value = selectedNode.value?.detail?.outcomes;
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
});

function detailText(key: string): string {
  const value = selectedNode.value?.detail?.[key];
  return typeof value === "string" ? value : "";
}

function accessState(node: CareerNode) {
  if (node.progressStatus === "COMPLETED") return "completed";
  const prerequisites = (careerMap.value?.edges ?? []).filter(
    (edge) => edge.toNodeId === node.id,
  );
  if (!prerequisites.length) return "available";
  return prerequisites.every((edge) => completedNodeIds.value.has(edge.fromNodeId))
    ? "available"
    : "locked";
}

function nodeIcon(node: CareerNode): LucideIcon {
  return iconByKind[node.kind] ?? LockKeyhole;
}

function relation(node: CareerNode): string {
  if (!selectedPostingId.value) return "normal";
  return selectedRequirements.value.get(node.id)?.toLowerCase() ?? "dim";
}

function isNodeDim(node: CareerNode) {
  const domainDim =
    selectedDomain.value !== "ALL" &&
    node.domain !== "COMMON" &&
    node.domain !== selectedDomain.value;
  const query = search.value.trim().toLocaleLowerCase();
  const searchDim =
    Boolean(query) &&
    !`${node.title} ${node.subtitle ?? ""} ${node.scopeDefinition ?? ""}`
      .toLocaleLowerCase()
      .includes(query);
  return domainDim || searchDim;
}

function canSelfConfirm(node: CareerNode) {
  return node.detail?.selfConfirmable === true;
}

function statusLabel(status: string | null) {
  if (status === "COMPLETED") return "완료";
  if (status === "IN_PROGRESS") return "진행 중";
  return "시작 전";
}

function evidenceStatusLabel(status: Evidence["verificationStatus"]) {
  const labels: Record<Evidence["verificationStatus"], string> = {
    PENDING: "검증 대기",
    RUNNING: "검증 중",
    VERIFIED: "검증 완료",
    NEEDS_WORK: "보완 필요",
    REJECTED: "인정 불가",
    FAILED: "검증 실패",
  };
  return labels[status];
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    [careerMap.value, postings.value] = await Promise.all([
      api.careerMap(),
      api.postings(),
    ]);
    if (careerMap.value.nodes.length < 8) {
      careerMap.value = structuredClone(showcaseCareerMap);
    }
    if (!postings.value.length) {
      postings.value = structuredClone(showcasePostings);
    }
    if (typeof route.query.posting === "string") {
      selectedPostingId.value = route.query.posting;
    }
    if (typeof route.query.node === "string") {
      const node = careerMap.value.nodes.find((item) => item.id === route.query.node);
      if (node) await selectNode(node);
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "커리어 지도를 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function selectNode(node: CareerNode) {
  if (evidenceTimer) window.clearTimeout(evidenceTimer);
  selectedNode.value = node;
  drawerError.value = "";
  evidence.value = [];
  if (node.id.startsWith("demo-")) return;
  if (!canSelfConfirm(node)) {
    try {
      evidence.value = await api.evidence(node.id);
      scheduleEvidenceRefresh();
    } catch (cause) {
      drawerError.value = cause instanceof Error ? cause.message : "증빙을 불러오지 못했습니다.";
    }
  }
}

function scheduleEvidenceRefresh() {
  if (evidenceTimer) window.clearTimeout(evidenceTimer);
  const pending = evidence.value.some((item) =>
    ["PENDING", "RUNNING"].includes(item.verificationStatus),
  );
  if (!pending || !selectedNode.value) return;
  evidenceTimer = window.setTimeout(async () => {
    if (!selectedNode.value) return;
    try {
      evidence.value = await api.evidence(selectedNode.value.id);
      if (evidence.value.some((item) => item.verificationStatus === "VERIFIED")) {
        await load();
        selectedNode.value =
          careerMap.value?.nodes.find((item) => item.id === selectedNode.value?.id) ?? null;
      }
    } finally {
      scheduleEvidenceRefresh();
    }
  }, 3000);
}

async function selfConfirm(node: CareerNode) {
  actionLoading.value = true;
  drawerError.value = "";
  try {
    if (node.id.startsWith("demo-") && careerMap.value) {
      careerMap.value = {
        ...careerMap.value,
        nodes: careerMap.value.nodes.map((item) =>
          item.id === node.id
            ? {
                ...item,
                progressStatus: "COMPLETED",
                completionMethod: "SELF_CONFIRMED",
                completedAt: new Date().toISOString(),
              }
            : item,
        ),
      };
      selectedNode.value =
        careerMap.value.nodes.find((item) => item.id === node.id) ?? null;
      return;
    }
    await api.selfConfirm(node.id);
    await load();
    const refreshed = careerMap.value?.nodes.find((item) => item.id === node.id);
    selectedNode.value = refreshed ?? null;
  } catch (cause) {
    drawerError.value = cause instanceof Error ? cause.message : "완료 상태를 저장하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function submitEvidence() {
  if (!selectedNode.value) return;
  actionLoading.value = true;
  drawerError.value = "";
  try {
    await api.submitEvidence(selectedNode.value.id, {
      evidenceType: evidenceType.value,
      title: evidenceTitle.value.trim(),
      sourceUrl: evidenceUrl.value.trim() || null,
      content: { description: evidenceDescription.value.trim() },
    });
    evidenceTitle.value = "";
    evidenceUrl.value = "";
    evidenceDescription.value = "";
    evidence.value = await api.evidence(selectedNode.value.id);
    scheduleEvidenceRefresh();
  } catch (cause) {
    drawerError.value = cause instanceof Error ? cause.message : "증빙을 제출하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function retryEvidence(item: Evidence) {
  actionLoading.value = true;
  drawerError.value = "";
  try {
    await api.retryEvidence(item.id);
    if (selectedNode.value) evidence.value = await api.evidence(selectedNode.value.id);
    scheduleEvidenceRefresh();
  } catch (cause) {
    drawerError.value = cause instanceof Error ? cause.message : "증빙 검증을 재시도하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

onMounted(load);
onBeforeUnmount(() => {
  if (evidenceTimer) window.clearTimeout(evidenceTimer);
});
</script>

<template>
  <main class="workspace map-workspace">
    <section class="page-heading page-heading--map">
      <div>
        <p class="eyebrow">MY CAREER MAP</p>
        <h1>공고가 쌓일수록 선명해지는 나의 성장 경로</h1>
        <p>
          같은 역량은 공유하고, 직무와 회사가 달라지는 지점에서 경로가 갈라집니다.
        </p>
      </div>
      <div class="map-stats">
        <span><strong>{{ completedCount }}</strong> 완료</span>
        <span><strong>{{ careerMap?.nodes.length ?? 0 }}</strong> 전체 노드</span>
        <span><strong>{{ relevantPostings.length }}</strong> 연결된 공고</span>
        <button class="icon-button" type="button" aria-label="새로고침" @click="load">
          <RefreshCw :size="19" />
        </button>
      </div>
    </section>

    <section class="map-toolbar">
      <div class="map-search">
        <Search :size="17" />
        <input v-model="search" type="search" placeholder="역량, 프로젝트, 회사 검색" />
      </div>
      <div class="filter-tabs">
        <button
          type="button"
          :class="{ active: selectedDomain === 'ALL' }"
          @click="selectedDomain = 'ALL'"
        >
          전체
        </button>
        <button
          v-for="item in domains"
          :key="item"
          type="button"
          :class="{ active: selectedDomain === item }"
          @click="selectedDomain = item"
        >
          {{ domainLabels[item] ?? item }}
        </button>
      </div>
      <div class="posting-filter">
        <span>공고 강조</span>
        <button
          v-for="posting in relevantPostings"
          :key="posting.id"
          type="button"
          :class="{ active: selectedPostingId === posting.id }"
          @click="selectedPostingId = selectedPostingId === posting.id ? null : posting.id"
        >
          <i />
          {{ posting.companyName }}
        </button>
      </div>
    </section>

    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" />
      커리어 지도를 구성하는 중입니다.
    </div>
    <div v-else-if="error" class="state-panel state-panel--error">
      <strong>지도를 불러오지 못했습니다.</strong>
      <p>{{ error }}</p>
      <button class="press-button press-button--primary" type="button" @click="load">
        다시 시도
      </button>
    </div>

    <section v-else class="career-map-frame">
      <div class="career-map-scroll">
        <div
          class="career-map-canvas"
          :style="{ width: `${canvasWidth}px`, height: `${canvasHeight}px` }"
        >
          <div
            v-for="lane in lanes"
            :key="lane.domain"
            class="map-lane"
            :class="{ dim: selectedDomain !== 'ALL' && selectedDomain !== lane.domain && lane.domain !== 'COMMON' }"
            :style="{ top: `${lane.y}px`, height: `${lane.height}px` }"
          >
            <span>{{ lane.label }}</span>
          </div>

          <span
            v-for="edge in drawnEdges"
            :key="edge.id"
            class="graph-edge"
            :style="{
              left: `${edge.x}px`,
              top: `${edge.y}px`,
              width: `${edge.width}px`,
              transform: `rotate(${edge.angle}deg)`,
            }"
          />

          <button
            v-for="node in positionedNodes"
            :key="node.id"
            type="button"
            class="career-node"
            :class="[
              `career-node--${node.kind.toLowerCase()}`,
              `career-node--${(node.progressStatus ?? 'NOT_STARTED').toLowerCase()}`,
              `career-node--access-${accessState(node)}`,
              `career-node--${relation(node)}`,
              { 'career-node--dim': isNodeDim(node) },
            ]"
            :style="{ left: `${node.x}px`, top: `${node.y}px` }"
            @click="selectNode(node)"
          >
            <span class="node-disc">
              <img :src="nodeArtwork(node)" alt="" />
              <span
                v-if="node.progressStatus === 'COMPLETED'"
                class="node-complete-badge"
              >
                <Check :size="14" :stroke-width="4" />
              </span>
              <span v-else-if="accessState(node) === 'locked'" class="node-lock-badge">
                <LockKeyhole :size="12" :stroke-width="3" />
              </span>
            </span>
            <span class="node-label">
              <strong>{{ node.title }}</strong>
              <small>{{ node.subtitle ?? domainLabels[node.domain] ?? node.domain }}</small>
            </span>
            <b v-if="relation(node) === 'required'" class="requirement-tag">필수</b>
            <b v-if="relation(node) === 'preferred'" class="preference-tag">우대</b>
          </button>
        </div>
      </div>

      <JobissGuide
        :message="
          selectedPostingId
            ? '선택한 공고에서 필수인 역량과 우대 역량만 밝게 표시했어요.'
            : '공고를 추가하면 기존 역량은 공유하고 필요한 경로만 새로 연결해요.'
        "
      />
    </section>

    <button
      v-if="selectedNode"
      class="drawer-backdrop"
      type="button"
      aria-label="상세 닫기"
      @click="selectedNode = null"
    />
    <aside v-if="selectedNode" class="detail-drawer">
      <div class="drawer-top">
        <span class="drawer-icon">
          <component :is="nodeIcon(selectedNode)" :size="24" />
        </span>
        <button class="icon-button" type="button" @click="selectedNode = null">
          <X :size="20" />
        </button>
      </div>
      <p class="eyebrow">{{ domainLabels[selectedNode.domain] ?? selectedNode.domain }} · {{ selectedNode.kind }}</p>
      <h2>{{ selectedNode.title }}</h2>
      <p class="drawer-subtitle">{{ selectedNode.subtitle }}</p>

      <section>
        <h3>이 단계가 인정하는 범위</h3>
        <p>{{ selectedNode.scopeDefinition || "공고 분석 결과에 따라 범위가 정의됩니다." }}</p>
      </section>
      <section v-if="detailText('why')" class="quest-why">
        <h3>왜 필요한가</h3>
        <p>{{ detailText("why") }}</p>
      </section>
      <section v-if="selectedPrerequisites.length" class="quest-prerequisites">
        <h3>먼저 완료할 단계</h3>
        <div>
          <span
            v-for="item in selectedPrerequisites"
            :key="item.id"
            :class="{ done: item.progressStatus === 'COMPLETED' }"
          >
            <Check v-if="item.progressStatus === 'COMPLETED'" :size="13" />
            <LockKeyhole v-else :size="13" />
            {{ item.title }}
          </span>
        </div>
      </section>
      <section class="drawer-status-row">
        <div>
          <h3>현재 상태</h3>
          <span :class="`status-chip status-chip--${(selectedNode.progressStatus ?? 'NOT_STARTED').toLowerCase()}`">
            {{ statusLabel(selectedNode.progressStatus) }}
          </span>
        </div>
        <div>
          <h3>수준</h3>
          <strong>Level {{ selectedNode.level }}</strong>
        </div>
        <div v-if="detailText('estimatedDuration')">
          <h3>예상 기간</h3>
          <strong>{{ detailText("estimatedDuration") }}</strong>
        </div>
      </section>

      <section v-if="selectedOutcomes.length" class="quest-outcomes">
        <h3>완료하면 할 수 있는 것</h3>
        <ul>
          <li v-for="item in selectedOutcomes" :key="item">
            <Check :size="14" /> {{ item }}
          </li>
        </ul>
      </section>

      <section v-if="selectedQuests.length" class="quest-list">
        <div class="section-heading">
          <div>
            <p class="eyebrow">QUESTS</p>
            <h3>추천 퀘스트</h3>
          </div>
          <span>{{ selectedQuests.length }}개</span>
        </div>
        <article v-for="(quest, index) in selectedQuests" :key="`${quest.title}-${index}`">
          <span>{{ index + 1 }}</span>
          <div>
            <strong>{{ quest.title }}</strong>
            <p>{{ quest.description }}</p>
            <small>완료 기준 · {{ quest.doneCriteria }}</small>
          </div>
        </article>
      </section>

      <p v-if="drawerError" class="form-error">{{ drawerError }}</p>

      <button
        v-if="canSelfConfirm(selectedNode) && selectedNode.progressStatus !== 'COMPLETED'"
        class="press-button press-button--primary drawer-action"
        type="button"
        :disabled="actionLoading"
        @click="selfConfirm(selectedNode)"
      >
        <LoaderCircle v-if="actionLoading" class="spin" :size="18" />
        <Check v-else :size="18" />
        이해했고 완료로 표시
      </button>

      <template v-if="!canSelfConfirm(selectedNode)">
        <section class="evidence-section">
          <div class="section-heading">
            <div>
              <p class="eyebrow">EVIDENCE</p>
              <h3>수행 증빙으로 검증받기</h3>
            </div>
            <FileCheck2 :size="22" />
          </div>
          <div v-if="evidence.length" class="evidence-list">
            <article v-for="item in evidence" :key="item.id">
              <div>
                <strong>{{ item.title }}</strong>
                <span :class="`evidence-status evidence-status--${item.verificationStatus.toLowerCase()}`">
                  {{ evidenceStatusLabel(item.verificationStatus) }}
                </span>
              </div>
              <p v-if="item.verificationResult?.summary">
                {{ item.verificationResult.summary }}
              </p>
              <p v-else-if="item.errorMessage">{{ item.errorMessage }}</p>
              <ul v-if="item.verificationResult?.gaps?.length" class="evidence-feedback">
                <li v-for="gap in item.verificationResult.gaps" :key="gap">
                  보완: {{ gap }}
                </li>
              </ul>
              <ul v-if="item.verificationResult?.nextActions?.length" class="evidence-feedback">
                <li v-for="action in item.verificationResult.nextActions" :key="action">
                  다음 행동: {{ action }}
                </li>
              </ul>
              <button
                v-if="item.verificationStatus === 'FAILED' && item.attemptCount < 3"
                class="text-action"
                type="button"
                @click="retryEvidence(item)"
              >
                <RefreshCw :size="14" /> 다시 검증
              </button>
            </article>
          </div>

          <form class="evidence-form" @submit.prevent="submitEvidence">
            <label>
              증빙 유형
              <select v-model="evidenceType">
                <option value="PROJECT">프로젝트</option>
                <option value="CODE">코드</option>
                <option value="CERTIFICATE">자격증</option>
                <option value="EXPERIENCE">경험</option>
                <option value="DOCUMENT">문서</option>
              </select>
            </label>
            <label>
              제목
              <input v-model="evidenceTitle" required maxlength="180" placeholder="예: 주문 API 성능 개선" />
            </label>
            <label>
              확인 가능한 URL
              <div class="input-with-icon">
                <Link2 :size="16" />
                <input v-model="evidenceUrl" type="url" placeholder="GitHub, 배포 주소, 자격증 확인 URL" />
              </div>
            </label>
            <label>
              무엇을 했고 무엇으로 확인할 수 있나요?
              <textarea
                v-model="evidenceDescription"
                required
                minlength="20"
                maxlength="6000"
                placeholder="문제, 내가 한 선택, 구현 내용, 결과와 확인 방법을 구체적으로 적어 주세요."
              />
            </label>
            <button
              class="press-button press-button--primary"
              type="submit"
              :disabled="actionLoading || !evidenceTitle.trim() || evidenceDescription.trim().length < 20"
            >
              <LoaderCircle v-if="actionLoading" class="spin" :size="18" />
              <Sparkles v-else :size="18" />
              AI 검증 요청
            </button>
          </form>
        </section>
      </template>
    </aside>
  </main>
</template>

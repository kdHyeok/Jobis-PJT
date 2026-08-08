<script setup lang="ts">
import {
  Check,
  CirclePause,
  BookOpenCheck,
  GitMerge,
  History,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Split,
  UserRoundCheck,
  X,
} from "@lucide/vue";
import { nextTick, onMounted, ref, watch } from "vue";

import { api } from "@/api";
import { productDialog } from "@/product-dialog";
import type {
  AssessmentReviewItem,
  CapabilityReviewCandidate,
  CompetencyAssessment,
  OperatorAuditItem,
  OperatorEmploymentReview,
  PostingDuplicateCandidate,
  RoleReviewCandidate,
  V3AtomicAssessment,
  V3AtomicAssessmentReviewItem,
} from "@/types";

const tab = ref<"POSTINGS" | "CAPABILITIES" | "ASSESSMENTS" | "HISTORY">("POSTINGS");
const duplicates = ref<PostingDuplicateCandidate[]>([]);
const capabilityReviews = ref<CapabilityReviewCandidate[]>([]);
const stagedCapabilities = ref<CapabilityReviewCandidate[]>([]);
const roleReviews = ref<RoleReviewCandidate[]>([]);
const employmentReviews = ref<OperatorEmploymentReview[]>([]);
const reviews = ref<AssessmentReviewItem[]>([]);
const atomicReviews = ref<V3AtomicAssessmentReviewItem[]>([]);
const auditItems = ref<OperatorAuditItem[]>([]);
const loading = ref(true);
const actionId = ref<string | null>(null);
const error = ref("");
const decisionOpen = ref(false);
const decisionReason = ref("");
const decisionLabel = ref("");
const decisionKind = ref<"DUPLICATE" | "ASSESSMENT" | "ATOMIC_ASSESSMENT" | "ROLLBACK" | null>(null);
const decisionAction = ref<"MERGE" | "SEPARATE" | "HOLD" | "APPROVE" | "REJECT" | null>(null);
const decisionDuplicate = ref<PostingDuplicateCandidate | null>(null);
const decisionReview = ref<AssessmentReviewItem | null>(null);
const decisionAtomicReview = ref<V3AtomicAssessmentReviewItem | null>(null);
const canonicalPostingId = ref<string | null>(null);
const reviewDetail = ref<CompetencyAssessment | null>(null);
const atomicReviewDetail = ref<V3AtomicAssessment | null>(null);
const decisionAudit = ref<OperatorAuditItem | null>(null);
const decisionDialog = ref<HTMLElement | null>(null);

async function load() {
  loading.value = true;
  error.value = "";
  const results = await Promise.allSettled([
      api.operatorPostingDuplicates(),
      api.operatorCapabilityReviews(),
      api.operatorCapabilityReviews("APPROVED_STAGED"),
      api.operatorRoleReviews(),
      api.operatorEmploymentReviews(),
      api.operatorAssessmentReviews(),
      api.operatorV3AtomicAssessmentReviews(),
      api.operatorPostingAudit(),
    ] as const);
  if (results[0].status === "fulfilled") duplicates.value = results[0].value;
  if (results[1].status === "fulfilled") capabilityReviews.value = results[1].value;
  if (results[2].status === "fulfilled") stagedCapabilities.value = results[2].value;
  if (results[3].status === "fulfilled") roleReviews.value = results[3].value;
  if (results[4].status === "fulfilled") employmentReviews.value = results[4].value;
  if (results[5].status === "fulfilled") reviews.value = results[5].value;
  if (results[6].status === "fulfilled") atomicReviews.value = results[6].value;
  if (results[7].status === "fulfilled") auditItems.value = results[7].value;
  const failed = results.filter((result) => result.status === "rejected").length;
  if (failed) error.value = `검토 큐 일부(${failed}개)를 불러오지 못했습니다.`;
  loading.value = false;
}

async function resolveEmployment(item: OperatorEmploymentReview, action: "VERIFIED" | "REJECTED") {
  const reason = await productDialog.prompt({
    title: action === "VERIFIED" ? "경력 증거 승인" : "경력 증거 반려",
    message: `${item.employer} · ${item.roleTitle}\n${item.startedOn} ~ ${item.endedOn || "재직 중"}`,
    confirmLabel: "결정 저장",
    input: { label: "판정 근거", value: "", maxLength: 4000 },
  });
  if (!reason) return;
  actionId.value = item.id;
  try {
    await api.resolveOperatorEmploymentReview(item.id, { action, reason });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "경력 증거를 판정하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

function suggestedCanonicalKey(item: CapabilityReviewCandidate) {
  const normalized = item.displayName.toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, ".")
    .replace(/^\.+|\.+$/g, "");
  return normalized.length >= 3 ? `capability.${normalized}` : "capability.reviewed";
}

async function resolveCapability(
  item: CapabilityReviewCandidate,
  action: "APPROVE_NEW" | "LINK_EXISTING" | "SPLIT" | "REJECT" | "HOLD",
) {
  let canonicalKey: string | null = null;
  if (["APPROVE_NEW", "LINK_EXISTING"].includes(action)) {
    canonicalKey = await productDialog.prompt({
      title: action === "APPROVE_NEW" ? "새 원자 역량 승인" : "기존 원자 역량에 연결",
      message: "표시명이 아니라 수행 범위가 같은지 확인한 뒤 canonical key를 입력해 주세요.",
      confirmLabel: "다음",
      input: { label: "Canonical key", value: action === "APPROVE_NEW" ? suggestedCanonicalKey(item) : "", maxLength: 160 },
    });
    if (!canonicalKey) return;
  }
  const reason = await productDialog.prompt({
    title: "판정 근거 기록",
    message: `${item.displayName}\n${item.scopeDefinition || item.reason}`,
    confirmLabel: "판정 확정",
    input: { label: "운영 판정 근거", value: "", maxLength: 4000 },
  });
  if (!reason) return;
  actionId.value = item.id;
  try {
    await api.resolveOperatorCapabilityReview(item.id, { action, canonicalKey, reason });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "역량 후보를 판정하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

async function resolveRole(
  item: RoleReviewCandidate,
  action: "APPROVE_NEW" | "LINK_EXISTING" | "REJECT" | "HOLD",
) {
  let canonicalRoleId: string | null = null;
  if (["APPROVE_NEW", "LINK_EXISTING"].includes(action)) {
    canonicalRoleId = await productDialog.prompt({
      title: action === "APPROVE_NEW" ? "새 직무 분류 승인" : "기존 직무 분류에 연결",
      message: `${item.sourceTitle}\n${item.proposedFamily} · ${item.proposedSpecialization}`,
      confirmLabel: "다음",
      input: {
        label: "Canonical role ID",
        value: action === "APPROVE_NEW"
          ? `role.${item.proposedFamily.toLowerCase().replace(/[^a-z0-9]+/g, ".")}`
          : "",
        maxLength: 160,
      },
    });
    if (!canonicalRoleId) return;
  }
  const reason = await productDialog.prompt({
    title: "직무 판정 근거",
    message: "직무 이름뿐 아니라 실제 담당 업무와 전문 분야가 같은지 확인해 주세요.",
    confirmLabel: "판정 확정",
    input: { label: "운영 판정 근거", value: "", maxLength: 4000 },
  });
  if (!reason) return;
  actionId.value = item.id;
  try {
    await api.resolveOperatorRoleReview(item.id, { action, canonicalRoleId, reason });
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "직무 후보를 판정하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

async function publishRoles() {
  const notes = await productDialog.prompt({
    title: "신규 직무 사전 발행",
    message: "운영자가 승인해 대기 중인 직무를 새 사전 버전으로 발행합니다. 발행 이후 분석부터 사용할 수 있습니다.",
    confirmLabel: "발행",
    input: { label: "발행 메모", value: "신규 직무 검토 반영", maxLength: 4000 },
  });
  if (!notes) return;
  try {
    await api.publishOperatorRoleCatalog(notes);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "직무 사전을 발행하지 못했습니다.";
  }
}

async function publishCapabilities() {
  const graphVersion = await productDialog.prompt({
    title: "역량 그래프 배포 묶음 발행",
    message: `승인 대기 중인 새 역량 ${stagedCapabilities.value.length}개를 불변 버전 묶음으로 발행합니다.`,
    confirmLabel: "다음",
    input: { label: "새 그래프 버전 (SemVer)", value: "0.2.0", maxLength: 80 },
  });
  if (!graphVersion) return;
  const notes = await productDialog.prompt({
    title: "배포 기록",
    message: "이 버전에 포함된 검토 내용과 변경 이유를 남겨 주세요.",
    confirmLabel: "버전 발행",
    input: { label: "릴리스 노트", value: "", maxLength: 4000 },
  });
  if (!notes) return;
  try {
    await api.publishCapabilityGraphRelease(graphVersion, notes);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "역량 그래프 배포 묶음을 발행하지 못했습니다.";
  }
}

function openDuplicateDecision(
  item: PostingDuplicateCandidate,
  action: "MERGE" | "SEPARATE" | "HOLD",
  canonicalId: string | null = null,
) {
  decisionKind.value = "DUPLICATE";
  decisionAction.value = action;
  decisionDuplicate.value = item;
  decisionReview.value = null;
  decisionAtomicReview.value = null;
  decisionAudit.value = null;
  decisionReason.value = item.proposalReason;
  decisionLabel.value = action === "MERGE" ? "중복 공고 합치기" : action === "SEPARATE" ? "서로 다른 공고로 확정" : "판정 보류";
  reviewDetail.value = null;
  atomicReviewDetail.value = null;
  canonicalPostingId.value = canonicalId;
  decisionOpen.value = true;
}

async function openReviewDecision(
  item: AssessmentReviewItem,
  action: "APPROVE" | "REJECT",
) {
  decisionKind.value = "ASSESSMENT";
  decisionAction.value = action;
  decisionDuplicate.value = null;
  decisionReview.value = item;
  decisionAtomicReview.value = null;
  decisionAudit.value = null;
  decisionReason.value = "";
  decisionLabel.value = action === "APPROVE" ? "검증 통과 승인" : "원판정 유지";
  decisionOpen.value = true;
  reviewDetail.value = null;
  atomicReviewDetail.value = null;
  try {
    reviewDetail.value = await api.operatorAssessmentReview(item.sessionId);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "검증 상세를 불러오지 못했습니다.";
  }
}

async function openAtomicReviewDecision(
  item: V3AtomicAssessmentReviewItem,
  action: "APPROVE" | "REJECT",
) {
  decisionKind.value = "ATOMIC_ASSESSMENT";
  decisionAction.value = action;
  decisionDuplicate.value = null;
  decisionReview.value = null;
  decisionAtomicReview.value = item;
  decisionAudit.value = null;
  decisionReason.value = "";
  decisionLabel.value = action === "APPROVE" ? "원자 역량 통과 승인" : "재학습 판정 유지";
  decisionOpen.value = true;
  atomicReviewDetail.value = null;
  try {
    atomicReviewDetail.value = await api.operatorV3AtomicAssessmentReview(item.sessionId);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "원자 역량 검증 상세를 불러오지 못했습니다.";
  }
}

function openRollback(item: OperatorAuditItem) {
  decisionKind.value = "ROLLBACK";
  decisionAction.value = null;
  decisionDuplicate.value = null;
  decisionReview.value = null;
  decisionAtomicReview.value = null;
  decisionAudit.value = item;
  decisionReason.value = "";
  decisionLabel.value = "공고 병합 되돌리기";
  reviewDetail.value = null;
  atomicReviewDetail.value = null;
  decisionOpen.value = true;
}

function closeDecision() {
  decisionOpen.value = false;
  decisionKind.value = null;
  decisionAction.value = null;
  decisionDuplicate.value = null;
  decisionReview.value = null;
  decisionAtomicReview.value = null;
  decisionAudit.value = null;
  canonicalPostingId.value = null;
  reviewDetail.value = null;
  atomicReviewDetail.value = null;
}

async function confirmDecision() {
  if (!decisionReason.value.trim()) return;
  const id = decisionDuplicate.value?.id
    ?? decisionReview.value?.sessionId
    ?? decisionAtomicReview.value?.sessionId
    ?? decisionAudit.value?.id;
  if (!id) return;
  actionId.value = id;
  try {
    if (decisionKind.value === "ROLLBACK" && decisionAudit.value) {
      await api.rollbackOperatorAction(decisionAudit.value.id, decisionReason.value.trim());
    } else if (decisionKind.value === "DUPLICATE" && decisionDuplicate.value && decisionAction.value) {
      await api.resolvePostingDuplicate(
        decisionDuplicate.value.id,
        decisionAction.value as "MERGE" | "SEPARATE" | "HOLD",
        canonicalPostingId.value,
        decisionReason.value.trim(),
      );
    } else if (decisionKind.value === "ASSESSMENT" && decisionReview.value) {
      await api.resolveAssessmentReview(
        decisionReview.value.sessionId,
        decisionAction.value as "APPROVE" | "REJECT",
        decisionReason.value.trim(),
      );
    } else if (decisionKind.value === "ATOMIC_ASSESSMENT" && decisionAtomicReview.value) {
      await api.resolveV3AtomicAssessmentReview(
        decisionAtomicReview.value.sessionId,
        decisionAction.value as "APPROVE" | "REJECT",
        decisionReason.value.trim(),
      );
    }
    closeDecision();
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "운영 판정을 저장하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

function formatDate(value: string | null) {
  if (!value) return "정보 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function trapFocus(event: KeyboardEvent) {
  const container = event.currentTarget as HTMLElement;
  const focusable = [...container.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
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

watch(decisionOpen, async (open) => {
  if (!open) return;
  await nextTick();
  decisionDialog.value?.focus();
});

onMounted(load);
</script>

<template>
  <main class="workspace operator-workspace">
    <section class="operator-hero">
      <div>
        <p class="eyebrow">HUMAN REVIEW GATE</p>
        <h1>운영 검토함</h1>
        <p>AI와 규칙이 제안한 판정을 사람이 최종 확정하고 기록합니다.</p>
      </div>
      <button class="icon-button" type="button" title="새로고침" @click="load">
        <RefreshCw :size="18" />
      </button>
    </section>

    <div class="operator-tabs">
      <button :class="{ active: tab === 'POSTINGS' }" @click="tab = 'POSTINGS'">
        공고 중복 {{ duplicates.length }}
      </button>
      <button :class="{ active: tab === 'ASSESSMENTS' }" @click="tab = 'ASSESSMENTS'">
        검증 이의신청 {{ reviews.length + atomicReviews.length }}
      </button>
      <button :class="{ active: tab === 'CAPABILITIES' }" @click="tab = 'CAPABILITIES'">
        <BookOpenCheck :size="15" /> 사전·경력 검토 {{ capabilityReviews.length + roleReviews.length + employmentReviews.length }}
      </button>
      <button :class="{ active: tab === 'HISTORY' }" @click="tab = 'HISTORY'">
        <History :size="15" /> 운영 이력 {{ auditItems.length }}
      </button>
    </div>

    <p v-if="error" class="inline-error">{{ error }}</p>
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="22" /> 검토 항목을 불러오는 중입니다.
    </div>

    <section v-else-if="tab === 'POSTINGS'" class="operator-list">
      <article v-for="item in duplicates" :key="item.id" class="operator-card">
        <header>
          <span>{{ item.matchKind }}</span>
          <strong>유사도 {{ Math.round(item.similarityScore * 100) }}%</strong>
        </header>
        <div class="operator-comparison">
          <section>
            <small>왼쪽 정본 후보</small>
            <strong>{{ item.left.companyName }}</strong>
            <p>{{ item.left.roleTitle }}</p>
            <small>{{ item.left.primaryTrack }} · {{ item.left.experienceText || "경력 정보 없음" }}</small>
            <small>관찰 {{ item.left.observationCount }}회 · 요건 {{ item.left.requirementCount }}개</small>
            <small>최근 확인 {{ formatDate(item.left.lastSeenAt) }}</small>
          </section>
          <GitMerge :size="20" />
          <section>
            <small>오른쪽 정본 후보</small>
            <strong>{{ item.right.companyName }}</strong>
            <p>{{ item.right.roleTitle }}</p>
            <small>{{ item.right.primaryTrack }} · {{ item.right.experienceText || "경력 정보 없음" }}</small>
            <small>관찰 {{ item.right.observationCount }}회 · 요건 {{ item.right.requirementCount }}개</small>
            <small>최근 확인 {{ formatDate(item.right.lastSeenAt) }}</small>
          </section>
        </div>
        <p>{{ item.proposalReason }}</p>
        <div class="operator-actions">
          <button
            class="press-button press-button--primary"
            :disabled="actionId === item.id"
            @click="openDuplicateDecision(item, 'MERGE', item.left.id)"
          >
            <GitMerge :size="15" /> 왼쪽으로 합치기
          </button>
          <button
            class="press-button press-button--primary"
            :disabled="actionId === item.id"
            @click="openDuplicateDecision(item, 'MERGE', item.right.id)"
          >
            <GitMerge :size="15" /> 오른쪽으로 합치기
          </button>
          <button
            class="press-button press-button--ghost"
            :disabled="actionId === item.id"
            @click="openDuplicateDecision(item, 'SEPARATE')"
          >
            <Split :size="15" /> 서로 다른 공고
          </button>
          <button
            class="press-button press-button--ghost"
            :disabled="actionId === item.id"
            @click="openDuplicateDecision(item, 'HOLD')"
          >
            <CirclePause :size="15" /> 보류
          </button>
        </div>
      </article>
      <p v-if="!duplicates.length" class="notification-empty">대기 중인 중복 후보가 없습니다.</p>
    </section>

    <section v-else-if="tab === 'ASSESSMENTS'" class="operator-list">
      <article v-for="item in reviews" :key="item.sessionId" class="operator-card">
        <header>
          <span><UserRoundCheck :size="15" /> 역량 검증</span>
          <strong>{{ item.averageScore === null ? "점수 없음" : `${Math.round(item.averageScore)}점` }}</strong>
        </header>
        <h2>{{ item.competencyTitle }} · 수준 {{ item.requiredLevel }}</h2>
        <small>{{ item.userEmail }}</small>
        <p>{{ item.appealText }}</p>
        <div class="operator-actions">
          <button
            class="press-button press-button--primary"
            :disabled="actionId === item.sessionId"
            @click="openReviewDecision(item, 'APPROVE')"
          >
            <Check :size="15" /> 통과 승인
          </button>
          <button
            class="press-button press-button--ghost"
            :disabled="actionId === item.sessionId"
            @click="openReviewDecision(item, 'REJECT')"
          >
            <X :size="15" /> 원판정 유지
          </button>
        </div>
      </article>
      <article v-for="item in atomicReviews" :key="item.sessionId" class="operator-card operator-card--atomic">
        <header>
          <span><UserRoundCheck :size="15" /> 원자 역량 검증</span>
          <strong>{{ item.averageScore === null ? "점수 없음" : `${item.averageScore}점` }}</strong>
        </header>
        <h2>{{ item.title }}</h2>
        <small>{{ item.userLabel }} · {{ item.capabilityKey }}</small>
        <p>{{ item.reason }}</p>
        <div class="operator-actions">
          <button
            class="press-button press-button--primary"
            :disabled="actionId === item.sessionId"
            @click="openAtomicReviewDecision(item, 'APPROVE')"
          >
            <Check :size="15" /> 통과 승인
          </button>
          <button
            class="press-button press-button--ghost"
            :disabled="actionId === item.sessionId"
            @click="openAtomicReviewDecision(item, 'REJECT')"
          >
            <X :size="15" /> 재학습 유지
          </button>
        </div>
      </article>
      <p v-if="!reviews.length && !atomicReviews.length" class="notification-empty">대기 중인 이의신청이 없습니다.</p>
    </section>

    <section v-else-if="tab === 'CAPABILITIES'" class="operator-list">
      <article class="operator-shadow-mode">
        <div><p class="eyebrow">ROLE CATALOG RELEASE</p><h2>승인된 신규 직무를 분석 사전에 반영</h2><p>개별 승인만으로는 분석 규칙이 바뀌지 않습니다. 검토가 끝난 묶음을 명시적으로 발행합니다.</p></div>
        <button class="press-button press-button--primary" type="button" @click="publishRoles">직무 사전 발행</button>
      </article>
      <article v-for="item in employmentReviews" :key="`employment:${item.id}`" class="operator-card">
        <header><span>관련 직무 경력 증거</span><strong>운영 검토 대기</strong></header>
        <h2>{{ item.employer }} · {{ item.roleTitle }}</h2>
        <p>{{ item.roleFamily }} · {{ item.roleSpecialization }}</p>
        <small>{{ item.startedOn }} ~ {{ item.endedOn || '재직 중' }}</small>
        <p>{{ item.description }}</p>
        <a :href="item.evidenceUrl" target="_blank" rel="noreferrer">증거 열기</a>
        <div class="operator-actions">
          <button class="press-button press-button--primary" :disabled="actionId === item.id" @click="resolveEmployment(item, 'VERIFIED')"><Check :size="15" /> 경력 승인</button>
          <button class="press-button press-button--danger" :disabled="actionId === item.id" @click="resolveEmployment(item, 'REJECTED')"><X :size="15" /> 반려</button>
        </div>
      </article>
      <article v-for="item in roleReviews" :key="`role:${item.id}`" class="operator-card">
        <header>
          <span>신규 직무 후보</span>
          <strong>신뢰도 {{ Math.round(item.confidence * 100) }}%</strong>
        </header>
        <h2>{{ item.sourceTitle }}</h2>
        <p>{{ item.proposedFamily }} · {{ item.proposedSpecialization }}</p>
        <small>분석 위치 {{ item.positionId }} · 운영자 승인 전 공용 직무로 사용하지 않음</small>
        <div class="operator-actions">
          <button class="press-button press-button--primary" :disabled="actionId === item.id" @click="resolveRole(item, 'APPROVE_NEW')"><Check :size="15" /> 새 직무 승인</button>
          <button class="press-button press-button--ghost" :disabled="actionId === item.id" @click="resolveRole(item, 'LINK_EXISTING')"><GitMerge :size="15" /> 기존 직무 연결</button>
          <button class="press-button press-button--ghost" :disabled="actionId === item.id" @click="resolveRole(item, 'HOLD')"><CirclePause :size="15" /> 보류</button>
          <button class="press-button press-button--danger" :disabled="actionId === item.id" @click="resolveRole(item, 'REJECT')"><X :size="15" /> 거절</button>
        </div>
      </article>
      <article v-if="stagedCapabilities.length" class="operator-shadow-mode">
        <div>
          <p class="eyebrow">VERSIONED RELEASE</p>
          <h2>승인된 새 역량 {{ stagedCapabilities.length }}개가 배포 대기 중입니다</h2>
          <p>발행 전까지 사용자 초안의 검토 후보로만 남으며 공용 정답으로 사용되지 않습니다.</p>
        </div>
        <button class="press-button press-button--primary" type="button" @click="publishCapabilities">그래프 버전 묶음 발행</button>
      </article>
      <article v-for="item in capabilityReviews" :key="item.id" class="operator-card">
        <header>
          <span>{{ item.decisionKind }}</span>
          <strong>{{ item.confidence === null ? '신뢰도 미제공' : `신뢰도 ${Math.round(item.confidence * 100)}%` }}</strong>
        </header>
        <h2>{{ item.displayName }}</h2>
        <p>{{ item.scopeDefinition || '새 범위가 아니라 기존 후보 중 연결 대상을 검토해야 합니다.' }}</p>
        <small>요건 {{ item.requirementId }} · {{ item.proposedKind || '종류 검토 필요' }}</small>
        <p>{{ item.reason }}</p>
        <details v-if="item.matchCandidates !== '[]'"><summary>유사한 기존 역량 후보</summary><pre>{{ item.matchCandidates }}</pre></details>
        <div class="operator-actions">
          <button class="press-button press-button--primary" :disabled="actionId === item.id" @click="resolveCapability(item, 'APPROVE_NEW')"><Check :size="15" /> 새 역량 승인</button>
          <button class="press-button press-button--ghost" :disabled="actionId === item.id" @click="resolveCapability(item, 'LINK_EXISTING')"><GitMerge :size="15" /> 기존 역량 연결</button>
          <button class="press-button press-button--ghost" :disabled="actionId === item.id" @click="resolveCapability(item, 'SPLIT')"><Split :size="15" /> 범위 분리</button>
          <button class="press-button press-button--ghost" :disabled="actionId === item.id" @click="resolveCapability(item, 'HOLD')"><CirclePause :size="15" /> 보류</button>
          <button class="press-button press-button--danger" :disabled="actionId === item.id" @click="resolveCapability(item, 'REJECT')"><X :size="15" /> 거절</button>
        </div>
      </article>
      <p v-if="!capabilityReviews.length && !stagedCapabilities.length && !roleReviews.length && !employmentReviews.length" class="notification-empty">검토할 신규·유사 역량, 직무 또는 경력 증거가 없습니다.</p>
    </section>

    <section v-else-if="tab === 'HISTORY'" class="operator-list operator-audit-list">
      <article v-for="item in auditItems" :key="item.id" class="operator-card">
        <header>
          <span>{{ item.actionKind }}</span>
          <strong>{{ item.rolledBackAt ? "되돌림 완료" : "적용됨" }}</strong>
        </header>
        <h2>{{ item.targetLabel || item.targetType }}</h2>
        <p>{{ item.reason || "기록된 사유가 없습니다." }}</p>
        <small>{{ item.operatorName }} · {{ formatDate(item.createdAt) }}</small>
        <small v-if="item.rolledBackAt">되돌린 시각 {{ formatDate(item.rolledBackAt) }}</small>
        <div v-if="item.rollbackable" class="operator-actions">
          <button class="press-button press-button--ghost" type="button" :disabled="actionId === item.id" @click="openRollback(item)">
            <RotateCcw :size="15" /> 병합 되돌리기
          </button>
        </div>
      </article>
      <p v-if="!auditItems.length" class="notification-empty">아직 운영 판정 이력이 없습니다.</p>
    </section>

    <button v-if="decisionOpen" class="quest-dialog-backdrop" type="button" aria-label="운영 판정 취소" @click="closeDecision" />
    <section v-if="decisionOpen" ref="decisionDialog" class="operator-decision-dialog" role="dialog" aria-modal="true" aria-labelledby="operator-decision-title" tabindex="-1" @keydown.esc="closeDecision" @keydown.tab="trapFocus">
      <header><div><p class="eyebrow">HUMAN CONFIRMATION</p><h2 id="operator-decision-title">{{ decisionLabel }}</h2></div><button class="icon-button" type="button" aria-label="닫기" @click="closeDecision"><X :size="18" /></button></header>
      <template v-if="decisionDuplicate">
        <div class="operator-comparison operator-comparison--dialog">
          <section><small>왼쪽</small><strong>{{ decisionDuplicate.left.companyName }}</strong><p>{{ decisionDuplicate.left.roleTitle }}</p><a v-if="decisionDuplicate.left.sourceUrl" :href="decisionDuplicate.left.sourceUrl" target="_blank" rel="noopener">원문 보기</a></section>
          <GitMerge :size="20" />
          <section><small>오른쪽</small><strong>{{ decisionDuplicate.right.companyName }}</strong><p>{{ decisionDuplicate.right.roleTitle }}</p><a v-if="decisionDuplicate.right.sourceUrl" :href="decisionDuplicate.right.sourceUrl" target="_blank" rel="noopener">원문 보기</a></section>
        </div>
        <p>유사도 {{ Math.round(decisionDuplicate.similarityScore * 100) }}% · {{ decisionDuplicate.proposalReason }}</p>
      </template>
      <template v-if="decisionReview">
        <div class="operator-review-evidence">
          <strong>{{ decisionReview.competencyTitle }} · 요구 수준 {{ decisionReview.requiredLevel }}</strong>
          <p>사용자 이의: {{ decisionReview.appealText }}</p>
          <div v-if="reviewDetail">
            <article v-for="turn in reviewDetail.turns" :key="turn.id"><small>{{ turn.questionKind }} · {{ turn.score ?? '미채점' }}점</small><strong>{{ turn.prompt }}</strong><p v-if="turn.answerText">답변: {{ turn.answerText }}</p><p v-if="turn.feedback">피드백: {{ turn.feedback }}</p></article>
          </div>
          <p v-else>평가 상세를 불러오는 중입니다.</p>
        </div>
      </template>
      <template v-if="decisionAtomicReview">
        <div class="operator-review-evidence">
          <strong>{{ decisionAtomicReview.title }} · {{ decisionAtomicReview.capabilityKey }}</strong>
          <p>사용자 이의: {{ decisionAtomicReview.reason }}</p>
          <div v-if="atomicReviewDetail">
            <p>검증 범위: {{ atomicReviewDetail.scopeDefinition }}</p>
            <article v-for="turn in atomicReviewDetail.turns" :key="turn.id">
              <small>{{ turn.method }} · {{ turn.score ?? '미채점' }}점</small>
              <strong>{{ turn.question.prompt }}</strong>
              <p v-if="turn.answerText">답변: {{ turn.answerText }}</p>
              <p v-if="turn.grade?.feedback">피드백: {{ turn.grade.feedback }}</p>
              <p v-if="turn.grade?.scopeViolationDetected">범위 이탈 감지: 운영자 확인이 필요합니다.</p>
            </article>
          </div>
          <p v-else>원자 역량 검증 상세를 불러오는 중입니다.</p>
        </div>
      </template>
      <template v-if="decisionAudit">
        <div class="operator-review-evidence">
          <strong>{{ decisionAudit.targetLabel || "공고 병합 기록" }}</strong>
          <p>병합 전 관찰 데이터와 사용자 공고 연결을 복원합니다. 이후 중복 후보는 다시 검토 대기 상태가 됩니다.</p>
          <small>원래 판정: {{ decisionAudit.reason || "사유 없음" }}</small>
        </div>
      </template>
      <label class="operator-decision-reason">판정 근거<textarea v-model="decisionReason" rows="4" maxlength="4000" placeholder="다른 운영자가 다시 확인할 수 있도록 근거를 남겨 주세요." autofocus /></label>
      <footer><button class="press-button press-button--ghost" type="button" @click="closeDecision">취소</button><button class="press-button press-button--primary" type="button" :disabled="actionId !== null || !decisionReason.trim()" @click="confirmDecision"><Check :size="16" /> {{ decisionKind === 'ROLLBACK' ? '되돌리기 확정' : '판정 확정' }}</button></footer>
    </section>
  </main>
</template>

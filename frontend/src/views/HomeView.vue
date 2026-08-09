<script setup lang="ts">
import {
  ArrowRight,
  BookOpen,
  BriefcaseBusiness,
  CheckCircle2,
  CircleHelp,
  LoaderCircle,
  Map,
  Paperclip,
  Send,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import JobissGuide from "@/components/JobissGuide.vue";
import { adaptV3Workspace } from "@/roadmap/v3-adapter";
import type {
  AnalysisJob,
  CareerSourceSummary,
  GoalProfile,
  Posting,
  RoadmapNode,
  RoadmapWorkspace,
} from "@/types";

const route = useRoute();
const router = useRouter();
const roadmap = ref<RoadmapWorkspace | null>(null);
const goals = ref<GoalProfile | null>(null);
const postings = ref<Posting[]>([]);
const jobs = ref<AnalysisJob[]>([]);
const sources = ref<CareerSourceSummary[]>([]);
const homeMessage = ref("");
const homeComposer = ref<HTMLTextAreaElement | null>(null);
const homeResumeFileInput = ref<HTMLInputElement | null>(null);
const loading = ref(true);
const error = ref("");
let refreshTimer: number | null = null;

const actionableNodes = computed(() =>
  (roadmap.value?.current.nodes ?? []).filter(
    (node) => node.type === "MILESTONE" || node.type === "PROJECT",
  ),
);

const completedCount = computed(
  () => actionableNodes.value.filter((node) => node.status === "COMPLETED").length,
);

const progressPercent = computed(() =>
  actionableNodes.value.length
    ? Math.round((completedCount.value / actionableNodes.value.length) * 100)
    : 0,
);

const nextNode = computed<RoadmapNode | undefined>(() =>
  [...actionableNodes.value]
    .sort((a, b) => a.rank - b.rank)
    .find(
      (node) =>
        node.status !== "COMPLETED" &&
        node.status !== "LOCKED" &&
        !node.optional,
    ),
);

const currentTarget = computed(() =>
  roadmap.value?.current.targets.find(
    (target) => target.postingId === goals.value?.currentGoalPostingId,
  ) ?? roadmap.value?.current.targets[0] ?? null,
);

const activeWork = computed(() => [
  ...jobs.value
    .filter((job) => ["QUEUED", "RUNNING", "WAITING_FOR_INPUT"].includes(job.status))
    .map((job) => ({
      id: job.id,
      type: "공고 분석",
      title:
        postings.value.find((posting) => posting.id === job.postingId)?.companyName ??
        "채용 공고",
      message: job.stageMessage,
      needsInput: job.status === "WAITING_FOR_INPUT",
      to: { name: "posting-detail", params: { postingId: job.postingId } },
    })),
  ...sources.value
    .filter((source) => ["QUEUED", "RUNNING"].includes(source.status))
    .map((source) => ({
      id: source.id,
      type: "커리어 자료",
      title: source.title,
      message: source.stageMessage,
      needsInput: false,
      to: { name: "career-source-review", params: { sourceId: source.id } },
    })),
]);

async function startConversation() {
  const prompt = homeMessage.value.trim();
  if (!prompt) {
    homeComposer.value?.focus();
    return;
  }
  await router.push({
    name: "chat",
    query: { new: Date.now().toString(), prompt },
  });
}

async function startPostingConversation() {
  await router.push({
    name: "chat",
    query: { new: Date.now().toString(), action: "posting" },
  });
}

async function attachResumeFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    error.value = "파일은 5MB 이하만 보낼 수 있습니다.";
    return;
  }
  if (!/\.(docx|txt|md)$/i.test(file.name)) {
    error.value = "TXT, MD, DOCX 파일만 보낼 수 있습니다.";
    return;
  }
  error.value = "";
  let text = "";
  try {
    text = /\.docx$/i.test(file.name)
      ? ((await api.uploadCareerSource(
          file,
          file.name.replace(/\.[^.]+$/, ""),
        )).rawText || "").trim()
      : (await file.text()).trim();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "파일을 읽지 못했습니다.";
    return;
  }
  if (text.length < 20) {
    error.value = "파일에서 읽은 내용이 너무 짧습니다.";
    return;
  }
  await router.push({
    name: "chat",
    query: { new: Date.now().toString(), prompt: text.slice(0, 12_000) },
  });
}

async function load(showLoader = true) {
  if (showLoader) loading.value = true;
  error.value = "";
  const results = await Promise.allSettled([
    api.v3Roadmap(),
    api.roadmap(),
    api.goalProfile(),
    api.postings(),
    api.analysisJobs("", 20),
    api.careerSources(),
  ] as const);
  const v3 = results[0].status === "fulfilled" ? results[0].value : null;
  const hasV3Journey = Boolean(
    v3 &&
      (v3.draftProposal ||
        v3.currentRoadmap.nodes.some(
          (node) =>
            node.nodeKind !== "CAPABILITY" ||
            !node.canonicalKey?.startsWith("foundation."),
        )),
  );
  if (hasV3Journey && v3) roadmap.value = adaptV3Workspace(v3);
  else if (results[1].status === "fulfilled") roadmap.value = results[1].value;
  if (results[2].status === "fulfilled") goals.value = results[2].value;
  if (results[3].status === "fulfilled") postings.value = results[3].value;
  if (results[4].status === "fulfilled") jobs.value = results[4].value;
  if (results[5].status === "fulfilled") sources.value = results[5].value;

  const failed = results.filter((result) => result.status === "rejected").length;
  if (failed) {
    error.value = `일부 정보(${failed}개)를 불러오지 못했습니다. 나머지 정보는 정상적으로 표시합니다.`;
  }
  loading.value = false;
}

onMounted(async () => {
  void load();
  refreshTimer = window.setInterval(() => void load(false), 15000);
  if (route.query.focus === "chat") {
    await nextTick();
    homeComposer.value?.focus();
  }
});

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});
</script>

<template>
  <main class="workspace home-workspace">
    <section class="home-chat-start" aria-labelledby="home-chat-title">
      <JobissGuide
        class="home-chat-guide"
        message="지금 상황이나 궁금한 공고부터 편하게 이야기해 주세요."
      />
      <div class="home-chat-start__copy">
        <h1 id="home-chat-title">무엇을 준비하고 있는지 들려주세요</h1>
        <p>새로운 대화는 여기서 시작하고, 이어진 대화는 왼쪽 목록에서 다시 열 수 있어요.</p>
      </div>
      <form class="home-chat-composer" @submit.prevent="startConversation">
        <button
          class="home-chat-tool"
          type="button"
          aria-label="공고 분석 시작"
          title="공고 분석 시작"
          @click="startPostingConversation"
        >
          <BriefcaseBusiness :size="19" />
        </button>
        <button
          class="home-chat-tool"
          type="button"
          aria-label="이력서 파일 첨부 (TXT·MD·DOCX)"
          title="이력서 파일 첨부 (TXT·MD·DOCX)"
          @click="homeResumeFileInput?.click()"
        >
          <Paperclip :size="19" />
        </button>
        <input
          ref="homeResumeFileInput"
          type="file"
          hidden
          accept=".docx,.txt,.md,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
          @change="attachResumeFile"
        />
        <textarea
          ref="homeComposer"
          v-model="homeMessage"
          rows="1"
          maxlength="12000"
          aria-label="새 대화 내용"
          placeholder="현재 상황, 목표, 공고 URL을 입력하세요"
          @keydown.enter.exact.prevent="startConversation"
        />
        <button type="submit" aria-label="새 대화 시작" :disabled="!homeMessage.trim()">
          <Send :size="20" />
        </button>
      </form>
    </section>

    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" /> 오늘의 경로를 불러오는 중입니다.
    </div>
    <template v-else>
      <p v-if="error" class="form-error">{{ error }}</p>
      <RouterLink
        v-if="roadmap?.draft"
        class="home-roadmap-draft-notice"
        :to="{ name: 'map', query: { preview: 'draft' } }"
      >
        <Map :size="18" />
        <span>
          <strong>적용 대기 중인 로드맵 v{{ roadmap.draft.version }}이 있습니다</strong>
          <small>활성 목표 {{ roadmap.targetCount }}개를 기준으로 만든 변경안을 확인해 주세요.</small>
        </span>
        <ArrowRight :size="17" />
      </RouterLink>

      <section class="home-grid">
        <article class="next-quest-card">
          <header>
            <div>
              <p class="eyebrow">NEXT QUEST</p>
              <h2>다음으로 이어갈 단계</h2>
            </div>
            <BookOpen :size="22" />
          </header>
          <template v-if="nextNode">
            <span>{{ nextNode.domain }} · {{ nextNode.stage }}</span>
            <h3>{{ nextNode.title }}</h3>
            <p>{{ nextNode.subtitle || nextNode.competencies[0]?.scopeDefinition }}</p>
            <small v-if="currentTarget" class="next-quest-card__reason">
              {{ currentTarget.companyName }} {{ currentTarget.roleTitle }} 준비에 필요한 필수 단계
            </small>
            <RouterLink
              class="press-button press-button--primary"
              :to="{ name: 'map', query: { node: nextNode.id } }"
            >
              단계 열기 <ArrowRight :size="17" />
            </RouterLink>
          </template>
          <template v-else>
            <CheckCircle2 :size="30" />
            <h3>현재 열린 단계를 모두 완료했어요</h3>
            <p>새 공고를 등록하면 필요한 경로가 이어집니다.</p>
            <RouterLink class="press-button press-button--primary" :to="{ name: 'posting-new' }">
              공고 추가 <ArrowRight :size="17" />
            </RouterLink>
          </template>
        </article>

        <article class="home-progress-card">
          <p class="eyebrow">CAREER PROGRESS</p>
          <div
            class="home-stat-ring"
            role="progressbar"
            aria-label="학습 및 프로젝트 진행률"
            :aria-valuenow="progressPercent"
            aria-valuemin="0"
            aria-valuemax="100"
            :style="{ '--progress': `${progressPercent * 3.6}deg` }"
          >
            <strong>{{ completedCount }}</strong>
            <span>/ {{ actionableNodes.length }}</span>
          </div>
          <p>완료한 학습·프로젝트 단계 · {{ progressPercent }}%</p>
          <RouterLink class="text-action" :to="{ name: 'map' }">
            전체 지도 보기 <ArrowRight :size="14" />
          </RouterLink>
        </article>
      </section>

      <section v-if="activeWork.length" class="home-section home-active-work">
        <header>
          <div>
            <p class="eyebrow">BACKGROUND WORK</p>
            <h2>백그라운드에서 진행 중</h2>
          </div>
          <LoaderCircle class="spin" :size="20" />
        </header>
        <div class="active-work-list">
          <RouterLink v-for="work in activeWork" :key="work.id" :to="work.to">
            <span class="active-work-icon">
              <CircleHelp v-if="work.needsInput" :size="18" />
              <LoaderCircle v-else class="spin" :size="18" />
            </span>
            <span>
              <small>{{ work.type }}</small>
              <strong>{{ work.title }}</strong>
              <p>{{ work.message }}</p>
            </span>
            <ArrowRight :size="17" />
          </RouterLink>
        </div>
      </section>
    </template>
  </main>
</template>

<script setup lang="ts">
import {
  ArrowRight,
  Bell,
  BookOpen,
  BriefcaseBusiness,
  CheckCircle2,
  CircleHelp,
  FileText,
  LoaderCircle,
  Map,
  MessageCircle,
} from "@lucide/vue";
import { computed, onMounted, ref } from "vue";

import { api } from "@/api";
import {
  showcaseCareerMap,
  showcaseNotifications,
  showcasePostings,
} from "@/demo/showcase-data";
import { session } from "@/session";
import type {
  AnalysisJob,
  CareerMap,
  CareerSourceSummary,
  NotificationItem,
  Posting,
} from "@/types";

const careerMap = ref<CareerMap | null>(null);
const postings = ref<Posting[]>([]);
const jobs = ref<AnalysisJob[]>([]);
const sources = ref<CareerSourceSummary[]>([]);
const notifications = ref<NotificationItem[]>([]);
const loading = ref(true);
const error = ref("");

const completedCount = computed(
  () =>
    careerMap.value?.nodes.filter((node) => node.progressStatus === "COMPLETED")
      .length ?? 0,
);

const nextNode = computed(() =>
  [...(careerMap.value?.nodes ?? [])]
    .sort((a, b) => a.rank - b.rank)
    .find(
      (node) =>
        node.progressStatus !== "COMPLETED" &&
        !["OPPORTUNITY", "OPPORTUNITY_CLUSTER"].includes(node.kind),
    ),
);

const activeWork = computed(() => [
  ...jobs.value
    .filter((job) =>
      ["QUEUED", "RUNNING", "WAITING_FOR_INPUT"].includes(job.status),
    )
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
      type: "커리어 파편화",
      title: source.title,
      message: source.stageMessage,
      needsInput: false,
      to: { name: "career-source-review", params: { sourceId: source.id } },
    })),
]);

async function load() {
  loading.value = true;
  try {
    const [map, postingItems, analysisItems, sourceItems, notificationPage] =
      await Promise.all([
        api.careerMap(),
        api.postings(),
        api.analysisJobs("", 20),
        api.careerSources(),
        api.notifications(false),
      ]);
    careerMap.value = map;
    postings.value = postingItems;
    jobs.value = analysisItems;
    sources.value = sourceItems;
    notifications.value = notificationPage.items.slice(0, 5);
    if (map.nodes.length < 8) {
      careerMap.value = structuredClone(showcaseCareerMap);
    }
    if (!postingItems.length) {
      postings.value = structuredClone(showcasePostings);
    }
    if (notifications.value.length < 3) {
      notifications.value = structuredClone(showcaseNotifications);
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "홈을 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <main class="workspace home-workspace">
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" /> 오늘의 경로를 불러오는 중입니다.
    </div>
    <template v-else>
      <section class="home-hero">
        <div>
          <p class="eyebrow">TODAY'S JOURNEY</p>
          <h1>{{ session.user.value?.displayName }}님, 오늘도 한 칸 이어가 볼까요?</h1>
          <p v-if="careerMap?.nodes.length">
            지금까지 {{ completedCount }}개 단계를 완료했고
            {{ postings.length }}개 공고가 커리어에 연결되어 있습니다.
          </p>
          <p v-else>
            AI와 대화하거나 커리어 자료를 등록해 첫 성장 경로를 만들어 보세요.
          </p>
        </div>
        <div class="home-hero__mark">
          <img src="/img/jobi-mascot.png" alt="J.O.B.I.S AI 커리어 도우미 자비" />
        </div>
      </section>

      <p v-if="error" class="form-error">{{ error }}</p>

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
            <span>{{ nextNode.domain }} · Level {{ nextNode.level }}</span>
            <h3>{{ nextNode.title }}</h3>
            <p>{{ nextNode.scopeDefinition }}</p>
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
          <div class="home-stat-ring">
            <strong>{{ completedCount }}</strong>
            <span>/ {{ careerMap?.nodes.length ?? 0 }}</span>
          </div>
          <p>완료한 커리어 노드</p>
          <RouterLink class="text-action" :to="{ name: 'map' }">
            전체 지도 보기 <ArrowRight :size="14" />
          </RouterLink>
        </article>
      </section>

      <section v-if="activeWork.length" class="home-section">
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

      <section class="home-section quick-start-section">
        <header>
          <div>
            <p class="eyebrow">QUICK START</p>
            <h2>무엇부터 할까요?</h2>
          </div>
        </header>
        <div class="quick-start-grid">
          <RouterLink :to="{ name: 'chat' }">
            <MessageCircle :size="23" />
            <strong>AI와 대화</strong>
            <p>현재 상황과 목표부터 자유롭게 이야기해요.</p>
          </RouterLink>
          <RouterLink :to="{ name: 'storage', query: { add: '1' } }">
            <FileText :size="23" />
            <strong>이력서 등록</strong>
            <p>경험을 검토 가능한 커리어 조각으로 나눠요.</p>
          </RouterLink>
          <RouterLink :to="{ name: 'posting-new' }">
            <BriefcaseBusiness :size="23" />
            <strong>공고 분석</strong>
            <p>공고와 내 증거를 비교해 경로를 연결해요.</p>
          </RouterLink>
          <RouterLink :to="{ name: 'map' }">
            <Map :size="23" />
            <strong>지도 보기</strong>
            <p>공통 역량과 회사별 분기를 확인해요.</p>
          </RouterLink>
        </div>
      </section>

      <section class="home-section activity-preview">
        <header>
          <div>
            <p class="eyebrow">RECENT ACTIVITY</p>
            <h2>최근 변화</h2>
          </div>
          <RouterLink class="text-action" :to="{ name: 'activity' }">
            전체 보기 <ArrowRight :size="14" />
          </RouterLink>
        </header>
        <div v-if="notifications.length" class="activity-preview__list">
          <article v-for="item in notifications" :key="item.id">
            <span><Bell :size="17" /></span>
            <div>
              <strong>{{ item.title }}</strong>
              <p>{{ item.body }}</p>
            </div>
          </article>
        </div>
        <p v-else class="notification-empty">아직 기록된 활동이 없습니다.</p>
      </section>
    </template>
  </main>
</template>

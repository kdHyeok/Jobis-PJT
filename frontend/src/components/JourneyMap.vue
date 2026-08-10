<script setup lang="ts">
import {
  BookOpen,
  Check,
  ChevronRight,
  Code2,
  Flag,
  Gift,
  GitBranch,
  GraduationCap,
  PencilLine,
  Plus,
  RefreshCw,
  Rocket,
  Sparkles,
  Target,
} from "@lucide/vue";
import { computed, ref } from "vue";

import type { JourneyChapter, JourneyModel, JourneyTrack } from "@/roadmap/journey";
import type { RoadmapNode } from "@/types";
import { learningPlan } from "@/learning-plan";

const props = defineProps<{
  model: JourneyModel;
  selectedNodeId: string | null;
  nextNode: RoadmapNode | null;
}>();

const emit = defineEmits<{
  select: [node: RoadmapNode];
  learn: [node: RoadmapNode];
  customize: [payload: { track: JourneyTrack; chapter: JourneyChapter; mode: "EDIT" | "REGENERATE" }];
}>();

const showAll = ref<Set<string>>(new Set());
const showBonus = ref<Set<string>>(new Set());

const allNodes = computed(() => [
  ...props.model.foundations,
  ...props.model.tracks.flatMap((track) => [
    ...track.entry.requiredNodes,
    ...track.entry.bonusNodes,
    ...track.entry.branches.flatMap((branch) => [
      ...(branch.project ? [branch.project] : []),
      branch.opportunity,
    ]),
    ...track.experienceChapters.flatMap((chapter) => [
      ...chapter.requiredNodes,
      ...chapter.bonusNodes,
      ...chapter.branches.flatMap((branch) => [
        ...(branch.project ? [branch.project] : []),
        branch.opportunity,
      ]),
    ]),
  ]),
]);

function isCompleted(node: RoadmapNode) {
  return node.status === "COMPLETED"
    || node.competencies.some((item) => learningPlan.completedCompetencyIds.value.has(item.id));
}

const completedCount = computed(() =>
  new Set(allNodes.value.filter(isCompleted).map((node) => node.id)).size,
);

const totalCount = computed(() => new Set(allNodes.value.map((node) => node.id)).size);

function toggle(set: Set<string>, id: string) {
  const next = new Set(set);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

function visibleNodes(chapter: JourneyChapter) {
  return showAll.value.has(chapter.id)
    ? chapter.requiredNodes
    : chapter.requiredNodes.slice(0, 4);
}

function countCompleted(nodes: RoadmapNode[]) {
  return nodes.filter(isCompleted).length;
}

function statusLabel(status: string) {
  if (status === "COMPLETED") return "완료";
  if (status === "IN_PROGRESS") return "학습 중";
  if (status === "AVAILABLE") return "바로 시작";
  if (status === "LOCKED") return "선행 학습 필요";
  return "준비 전";
}

function chapterMinutes(chapter: JourneyChapter) {
  return Math.max(2, chapter.requiredNodes.length * 2);
}

function chapterNumber(track: JourneyTrack, chapter: JourneyChapter) {
  if (chapter.id === track.entry.id) return 1;
  return track.experienceChapters.findIndex((item) => item.id === chapter.id) + 2;
}

function select(node: RoadmapNode) {
  emit("select", node);
}
</script>

<template>
  <div class="focus-journey">
    <header class="focus-journey__overview">
      <div class="focus-journey__progress">
        <span><Target :size="22" /></span>
        <div>
          <small>전체 준비 현황</small>
          <strong>{{ completedCount }}/{{ totalCount }}개 완료</strong>
          <p>필수 준비를 먼저 보고, 원하는 학습만 플랜에 담아보세요.</p>
        </div>
      </div>
      <button v-if="nextNode" type="button" class="focus-journey__next" @click="select(nextNode)">
        <Sparkles :size="19" />
        <span><small>지금 시작하면 좋은 항목</small><strong>{{ nextNode.title }}</strong></span>
        <ChevronRight :size="18" />
      </button>
    </header>

    <section v-if="model.foundations.length" class="focus-stage focus-stage--foundation">
      <header class="focus-stage__heading">
        <span class="focus-stage__number">1</span>
        <span class="focus-stage__icon"><BookOpen :size="20" /></span>
        <div>
          <small>모든 직무의 공통 기반</small>
          <h2>먼저 준비할 기초</h2>
        </div>
        <strong>{{ countCompleted(model.foundations) }}/{{ model.foundations.length }} 완료</strong>
      </header>
      <div class="focus-node-grid">
        <article
          v-for="node in model.foundations"
          :key="node.id"
          class="focus-node-card"
          :class="{ completed: isCompleted(node), selected: selectedNodeId === node.id }"
        >
          <button type="button" class="focus-node-card__body" @click="select(node)">
            <span class="focus-node-card__state"><Check v-if="isCompleted(node)" :size="15" /><Code2 v-else :size="15" /></span>
            <span><strong>{{ node.title }}</strong><small>{{ statusLabel(node.status) }}</small></span>
            <ChevronRight :size="16" />
          </button>
          <button v-if="!isCompleted(node)" type="button" class="focus-node-card__add" @click="emit('learn', node)">
            <Plus :size="14" /> 학습 플랜
          </button>
        </article>
      </div>
    </section>

    <div v-if="model.tracks.length" class="focus-journey__split">
      <GitBranch :size="18" /> 목표 직무에 맞는 준비 경로 {{ model.tracks.length }}개
    </div>

    <section v-for="track in model.tracks" :key="track.domain" class="focus-track">
      <header class="focus-track__heading">
        <span><Code2 :size="20" /></span>
        <div><small>{{ track.domain }} CAREER PATH</small><h2>{{ track.label }} 준비 경로</h2></div>
        <p>필수 역량부터 실전 프로젝트와 지원 기회까지 순서대로 준비합니다.</p>
      </header>

      <div class="focus-track__flow">
        <article
          v-for="chapter in [track.entry, ...track.experienceChapters]"
          :key="chapter.id"
          class="focus-stage focus-stage--track"
        >
          <header class="focus-stage__heading">
            <span class="focus-stage__number">{{ chapterNumber(track, chapter) + 1 }}</span>
            <span class="focus-stage__icon"><GraduationCap :size="20" /></span>
            <div>
              <small>{{ chapter.eyebrow }}</small>
              <h2>{{ chapter.title }}</h2>
              <p>예상 {{ chapterMinutes(chapter) }}시간 · 필수 {{ countCompleted(chapter.requiredNodes) }}/{{ chapter.requiredNodes.length }}</p>
            </div>
            <div class="focus-stage__actions">
              <button type="button" title="이 경로의 구성과 우선순위 수정" @click="emit('customize', { track, chapter, mode: 'EDIT' })"><PencilLine :size="16" /> 경로 수정</button>
              <button type="button" title="관심사에 맞게 이 경로 다시 생성" @click="emit('customize', { track, chapter, mode: 'REGENERATE' })"><RefreshCw :size="16" /> 다시 생성</button>
            </div>
          </header>

          <div class="focus-stage__content">
            <div class="focus-stage__required">
              <div class="focus-stage__label"><strong>필수 준비</strong><span>위에서 아래 순서로 진행</span></div>
              <div class="focus-node-list">
                <article
                  v-for="node in visibleNodes(chapter)"
                  :key="node.id"
                  class="focus-node-row"
                  :class="{ completed: isCompleted(node), selected: selectedNodeId === node.id }"
                >
                  <button type="button" class="focus-node-row__main" @click="select(node)">
                    <span><Check v-if="isCompleted(node)" :size="15" /><Code2 v-else :size="15" /></span>
                    <strong>{{ node.title }}</strong>
                    <small>{{ statusLabel(node.status) }}</small>
                    <ChevronRight :size="16" />
                  </button>
                  <button v-if="!isCompleted(node)" type="button" class="focus-node-row__add" @click="emit('learn', node)"><Plus :size="14" /> 담기</button>
                </article>
              </div>
              <button v-if="chapter.requiredNodes.length > 4" type="button" class="focus-stage__more" @click="showAll = toggle(showAll, chapter.id)">
                {{ showAll.has(chapter.id) ? '핵심만 보기' : `나머지 ${chapter.requiredNodes.length - 4}개 보기` }}
              </button>
            </div>

            <aside class="focus-stage__optional">
              <button v-if="chapter.bonusNodes.length" type="button" class="focus-bonus-toggle" @click="showBonus = toggle(showBonus, chapter.id)">
                <Gift :size="16" /><span><strong>선택 학습 {{ chapter.bonusNodes.length }}개</strong><small>관심 있는 것만 담아도 돼요</small></span><ChevronRight :size="16" />
              </button>
              <div v-if="showBonus.has(chapter.id)" class="focus-bonus-list">
                <button v-for="node in chapter.bonusNodes" :key="node.id" type="button" @click="select(node)">{{ node.title }}</button>
              </div>

              <div v-for="branch in chapter.branches" :key="branch.id" class="focus-outcome">
                <span><Rocket v-if="branch.project" :size="17" /><Flag v-else :size="17" /></span>
                <div><small>{{ branch.project ? '실전 결과물' : '지원 목표' }}</small><strong>{{ branch.project?.title ?? branch.opportunity.title }}</strong></div>
                <button type="button" @click="select(branch.project ?? branch.opportunity)">보기</button>
              </div>
            </aside>
          </div>
        </article>
      </div>
    </section>

    <div v-if="!model.tracks.length" class="focus-journey__empty">
      <Target :size="30" />
      <h3>아직 목표 직무 경로가 없어요</h3>
      <p>공고 분석 결과를 지도에 반영하면 준비 순서와 학습 가지가 만들어집니다.</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  BookOpen,
  Check,
  ChevronDown,
  Code2,
  Flag,
  Gift,
  GitBranch,
  LockKeyhole,
  Rocket,
  Sparkles,
  Target,
} from "@lucide/vue";
import { computed, ref } from "vue";

import type {
  JourneyChapter,
  JourneyModel,
  JourneyTrack,
} from "@/roadmap/journey";
import type { RoadmapNode } from "@/types";

const props = defineProps<{
  model: JourneyModel;
  selectedNodeId: string | null;
  nextNode: RoadmapNode | null;
}>();

const emit = defineEmits<{
  select: [node: RoadmapNode];
}>();

const expandedChapters = ref<Set<string>>(new Set());
const expandedBonuses = ref<Set<string>>(new Set());
const foundationsExpanded = ref(false);

const totalNodes = computed(() => {
  const foundationCount = props.model.foundations.length;
  const trackCount = props.model.tracks.reduce((sum, track) => {
    const chapters = [track.entry, ...track.experienceChapters];
    return (
      sum +
      (track.employmentGate ? 1 : 0) +
      chapters.reduce(
        (chapterSum, chapter) =>
          chapterSum +
          chapter.requiredNodes.length +
          chapter.bonusNodes.length +
          chapter.branches.reduce(
            (branchSum, branch) =>
              branchSum + (branch.project ? 2 : 1),
            0,
          ),
        0,
      )
    );
  }, 0);
  return foundationCount + trackCount;
});

const completedNodes = computed(() => {
  const nodes = [
    ...props.model.foundations,
    ...props.model.tracks.flatMap((track) => [
      ...(track.employmentGate ? [track.employmentGate] : []),
      ...[track.entry, ...track.experienceChapters].flatMap(
        (chapter) => [
          ...chapter.requiredNodes,
          ...chapter.bonusNodes,
          ...chapter.branches.flatMap((branch) => [
            ...(branch.project ? [branch.project] : []),
            branch.opportunity,
          ]),
          ...(chapter.gateNode ? [chapter.gateNode] : []),
        ],
      ),
    ]),
  ];
  return new Set(
    nodes
      .filter((node) => node.status === "COMPLETED")
      .map((node) => node.id),
  ).size;
});

function toggleSet(source: Set<string>, id: string) {
  const next = new Set(source);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

function toggleChapter(id: string) {
  expandedChapters.value = toggleSet(expandedChapters.value, id);
}

function toggleBonuses(id: string) {
  expandedBonuses.value = toggleSet(expandedBonuses.value, id);
}

function isExpanded(chapter: JourneyChapter) {
  return expandedChapters.value.has(chapter.id);
}

function visibleRequired(chapter: JourneyChapter) {
  return isExpanded(chapter)
    ? chapter.requiredNodes
    : chapter.requiredNodes.slice(0, 3);
}

function completedCount(nodes: RoadmapNode[]) {
  return nodes.filter((node) => node.status === "COMPLETED").length;
}

function statusLabel(status: string) {
  if (status === "COMPLETED") return "완료";
  if (status === "IN_PROGRESS") return "진행 중";
  if (status === "AVAILABLE") return "진행 가능";
  if (status === "LOCKED") return "준비 필요";
  return "미시작";
}

function trackIcon(track: JourneyTrack) {
  if (track.domain === "SECURITY") return LockKeyhole;
  if (track.domain === "CAREER") return Flag;
  return Code2;
}

function select(node: RoadmapNode) {
  emit("select", node);
}
</script>

<template>
  <div class="journey-map">
    <header class="journey-map__summary">
      <div>
        <span class="journey-map__summary-icon">
          <Target :size="22" stroke-width="2.8" />
        </span>
        <div>
          <small>전체 여정</small>
          <strong>{{ completedNodes }}/{{ totalNodes }}개 완료</strong>
        </div>
      </div>
      <button
        v-if="nextNode"
        class="journey-next-quest"
        type="button"
        @click="select(nextNode)"
      >
        <span><Sparkles :size="18" /></span>
        <div>
          <small>다음 추천 퀘스트</small>
          <strong>{{ nextNode.title }}</strong>
        </div>
        <em>시작하기</em>
      </button>
    </header>

    <section
      v-for="track in model.tracks"
      :key="track.domain"
      class="journey-track"
      :class="`journey-track--${track.domain.toLowerCase()}`"
    >
      <header class="journey-track__heading">
        <span><component :is="trackIcon(track)" :size="19" /></span>
        <div>
          <p>{{ track.label }} CAREER PATH</p>
          <h2>{{ track.label }} 성장 여정</h2>
        </div>
      </header>

      <div class="journey-track__scroll">
        <div class="journey-track__timeline">
          <div class="journey-track__main-line" aria-hidden="true" />

          <article class="journey-stop journey-stop--foundation">
            <button
              class="journey-stop__node"
              type="button"
              :class="{
                completed: model.foundations.every(
                  (node) => node.status === 'COMPLETED',
                ),
              }"
              @click="foundationsExpanded = !foundationsExpanded"
            >
              <span class="journey-stop__disc">
                <BookOpen :size="25" />
                <Check
                  v-if="
                    model.foundations.length &&
                    model.foundations.every(
                      (node) => node.status === 'COMPLETED',
                    )
                  "
                  class="journey-stop__check"
                  :size="15"
                  stroke-width="4"
                />
              </span>
              <small>SHARED START</small>
              <strong>공통 기반</strong>
              <em>
                {{ completedCount(model.foundations) }}/{{ model.foundations.length }}
                완료
              </em>
            </button>
            <div
              v-if="foundationsExpanded"
              class="journey-cluster journey-cluster--foundation"
            >
              <button
                v-for="node in model.foundations"
                :key="node.id"
                class="journey-quest-row"
                :class="{
                  completed: node.status === 'COMPLETED',
                  selected: selectedNodeId === node.id,
                  'is-next': nextNode?.id === node.id,
                }"
                type="button"
                @click="select(node)"
              >
                <span>
                  <Check v-if="node.status === 'COMPLETED'" :size="14" />
                  <BookOpen v-else :size="15" />
                </span>
                <strong>{{ node.title }}</strong>
                <small>{{ statusLabel(node.status) }}</small>
              </button>
            </div>
          </article>

          <article class="journey-stop journey-stop--chapter">
            <button
              class="journey-stop__node"
              type="button"
              :class="{
                completed:
                  track.entry.requiredNodes.length > 0 &&
                  track.entry.requiredNodes.every(
                    (node) => node.status === 'COMPLETED',
                  ),
                'is-next': track.entry.requiredNodes.some(
                  (node) => node.id === nextNode?.id,
                ),
              }"
              @click="toggleChapter(track.entry.id)"
            >
              <span class="journey-stop__disc"><Code2 :size="26" /></span>
              <small>{{ track.entry.eyebrow }}</small>
              <strong>{{ track.entry.title }}</strong>
              <em>
                필수 {{ completedCount(track.entry.requiredNodes) }}/{{
                  track.entry.requiredNodes.length
                }}
              </em>
            </button>
            <div class="journey-cluster">
              <header>
                <div>
                  <small>필수 퀘스트</small>
                  <strong>
                    {{ completedCount(track.entry.requiredNodes) }}/{{
                      track.entry.requiredNodes.length
                    }}
                  </strong>
                </div>
                <button
                  v-if="track.entry.requiredNodes.length > 3"
                  type="button"
                  @click="toggleChapter(track.entry.id)"
                >
                  {{ isExpanded(track.entry) ? "접기" : "전체 보기" }}
                  <ChevronDown
                    :size="15"
                    :class="{ rotated: isExpanded(track.entry) }"
                  />
                </button>
              </header>
              <button
                v-for="node in visibleRequired(track.entry)"
                :key="node.id"
                class="journey-quest-row"
                :class="{
                  completed: node.status === 'COMPLETED',
                  selected: selectedNodeId === node.id,
                  'is-next': nextNode?.id === node.id,
                }"
                type="button"
                @click="select(node)"
              >
                <span>
                  <Check v-if="node.status === 'COMPLETED'" :size="14" />
                  <Code2 v-else :size="15" />
                </span>
                <strong>{{ node.title }}</strong>
                <small>{{ statusLabel(node.status) }}</small>
              </button>
              <button
                v-if="track.entry.bonusNodes.length"
                class="journey-bonus-toggle"
                type="button"
                @click="toggleBonuses(track.entry.id)"
              >
                <span><Gift :size="16" /></span>
                <strong>보너스 {{ track.entry.bonusNodes.length }}개</strong>
                <ChevronDown
                  :size="16"
                  :class="{
                    rotated: expandedBonuses.has(track.entry.id),
                  }"
                />
              </button>
              <div
                v-if="expandedBonuses.has(track.entry.id)"
                class="journey-bonus-list"
              >
                <button
                  v-for="node in track.entry.bonusNodes"
                  :key="node.id"
                  class="journey-quest-row optional"
                  :class="{
                    completed: node.status === 'COMPLETED',
                    selected: selectedNodeId === node.id,
                  }"
                  type="button"
                  @click="select(node)"
                >
                  <span><Gift :size="14" /></span>
                  <strong>{{ node.title }}</strong>
                  <small>{{ statusLabel(node.status) }}</small>
                </button>
              </div>
            </div>

            <div
              v-if="track.entry.branches.length"
              class="journey-opportunity-list"
            >
              <div
                v-for="branch in track.entry.branches"
                :key="branch.id"
                class="journey-opportunity-branch"
              >
                <button
                  v-if="branch.project"
                  class="journey-special-node journey-special-node--project"
                  :class="{
                    selected: selectedNodeId === branch.project.id,
                    completed: branch.project.status === 'COMPLETED',
                    'is-next': nextNode?.id === branch.project.id,
                  }"
                  type="button"
                  @click="select(branch.project)"
                >
                  <span><Rocket :size="20" /></span>
                  <div>
                    <small>회사 맞춤 프로젝트</small>
                    <strong>{{ branch.project.title }}</strong>
                  </div>
                </button>
                <span v-if="branch.project" class="journey-local-arrow">→</span>
                <button
                  class="journey-special-node journey-special-node--opportunity"
                  :class="{
                    selected: selectedNodeId === branch.opportunity.id,
                    available: branch.opportunity.status === 'AVAILABLE',
                  }"
                  type="button"
                  @click="select(branch.opportunity)"
                >
                  <span><Flag :size="19" /></span>
                  <div>
                    <small>지원 기회</small>
                    <strong>{{ branch.opportunity.title }}</strong>
                  </div>
                </button>
              </div>
            </div>
          </article>

          <article
            v-if="track.employmentGate"
            class="journey-stop journey-stop--gate"
          >
            <button
              class="journey-stop__node journey-stop__node--gate"
              :class="{
                selected: selectedNodeId === track.employmentGate.id,
              }"
              type="button"
              @click="select(track.employmentGate)"
            >
              <span class="journey-stop__disc"><GitBranch :size="25" /></span>
              <small>CAREER GATE</small>
              <strong>{{ track.employmentGate.title }}</strong>
              <em>{{ statusLabel(track.employmentGate.status) }}</em>
            </button>
            <p class="journey-gate-note">
              특정 회사가 아닌 관련 직무 취업으로 다음 경력 단계가 열립니다.
            </p>
          </article>

          <article
            v-for="chapter in track.experienceChapters"
            :key="chapter.id"
            class="journey-stop journey-stop--chapter journey-stop--experience"
          >
            <button
              class="journey-stop__node journey-stop__node--experience"
              :class="{
                selected: selectedNodeId === chapter.gateNode?.id,
                completed: chapter.gateNode?.status === 'COMPLETED',
              }"
              type="button"
              @click="chapter.gateNode && select(chapter.gateNode)"
            >
              <span class="journey-stop__disc"><Target :size="25" /></span>
              <small>{{ chapter.eyebrow }}</small>
              <strong>{{ chapter.title }}</strong>
              <em>{{ statusLabel(chapter.gateNode?.status ?? 'NOT_STARTED') }}</em>
            </button>

            <div
              v-if="
                chapter.requiredNodes.length ||
                chapter.bonusNodes.length
              "
              class="journey-cluster"
            >
              <header>
                <div>
                  <small>이 단계 준비 퀘스트</small>
                  <strong>
                    {{ completedCount(chapter.requiredNodes) }}/{{
                      chapter.requiredNodes.length
                    }}
                  </strong>
                </div>
                <button
                  v-if="chapter.requiredNodes.length > 3"
                  type="button"
                  @click="toggleChapter(chapter.id)"
                >
                  {{ isExpanded(chapter) ? "접기" : "전체 보기" }}
                  <ChevronDown
                    :size="15"
                    :class="{ rotated: isExpanded(chapter) }"
                  />
                </button>
              </header>
              <button
                v-for="node in visibleRequired(chapter)"
                :key="node.id"
                class="journey-quest-row"
                :class="{
                  completed: node.status === 'COMPLETED',
                  selected: selectedNodeId === node.id,
                  'is-next': nextNode?.id === node.id,
                }"
                type="button"
                @click="select(node)"
              >
                <span>
                  <Check v-if="node.status === 'COMPLETED'" :size="14" />
                  <Code2 v-else :size="15" />
                </span>
                <strong>{{ node.title }}</strong>
                <small>{{ statusLabel(node.status) }}</small>
              </button>
              <button
                v-if="chapter.bonusNodes.length"
                class="journey-bonus-toggle"
                type="button"
                @click="toggleBonuses(chapter.id)"
              >
                <span><Gift :size="16" /></span>
                <strong>보너스 {{ chapter.bonusNodes.length }}개</strong>
                <ChevronDown
                  :size="16"
                  :class="{
                    rotated: expandedBonuses.has(chapter.id),
                  }"
                />
              </button>
              <div
                v-if="expandedBonuses.has(chapter.id)"
                class="journey-bonus-list"
              >
                <button
                  v-for="node in chapter.bonusNodes"
                  :key="node.id"
                  class="journey-quest-row optional"
                  :class="{
                    completed: node.status === 'COMPLETED',
                    selected: selectedNodeId === node.id,
                  }"
                  type="button"
                  @click="select(node)"
                >
                  <span><Gift :size="14" /></span>
                  <strong>{{ node.title }}</strong>
                  <small>{{ statusLabel(node.status) }}</small>
                </button>
              </div>
            </div>

            <div
              v-if="chapter.branches.length"
              class="journey-opportunity-list"
            >
              <div
                v-for="branch in chapter.branches"
                :key="branch.id"
                class="journey-opportunity-branch"
              >
                <button
                  v-if="branch.project"
                  class="journey-special-node journey-special-node--project"
                  :class="{
                    selected: selectedNodeId === branch.project.id,
                    completed: branch.project.status === 'COMPLETED',
                    'is-next': nextNode?.id === branch.project.id,
                  }"
                  type="button"
                  @click="select(branch.project)"
                >
                  <span><Rocket :size="20" /></span>
                  <div>
                    <small>회사 맞춤 프로젝트</small>
                    <strong>{{ branch.project.title }}</strong>
                  </div>
                </button>
                <span v-if="branch.project" class="journey-local-arrow">→</span>
                <button
                  class="journey-special-node journey-special-node--opportunity"
                  :class="{
                    selected: selectedNodeId === branch.opportunity.id,
                    available: branch.opportunity.status === 'AVAILABLE',
                  }"
                  type="button"
                  @click="select(branch.opportunity)"
                >
                  <span><Flag :size="19" /></span>
                  <div>
                    <small>지원 기회</small>
                    <strong>{{ branch.opportunity.title }}</strong>
                  </div>
                </button>
              </div>
            </div>
          </article>
        </div>
      </div>
    </section>

    <div v-if="!model.tracks.length" class="journey-empty">
      <Target :size="32" />
      <h3>아직 목표 공고가 없습니다</h3>
      <p>공고를 분석하고 지도에 반영하면 첫 여정이 만들어집니다.</p>
    </div>
  </div>
</template>

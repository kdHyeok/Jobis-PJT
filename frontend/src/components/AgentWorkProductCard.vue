<script setup lang="ts">
import { ChevronDown, FileText, ListChecks, MessagesSquare, Route } from "@lucide/vue";
import { computed, ref } from "vue";

import type { AgentWorkProduct } from "@/types";

const props = defineProps<{ product: AgentWorkProduct }>();

type SummaryBlock =
  | { type: "heading" | "paragraph"; text: string }
  | { type: "list"; items: string[] };

function cleanMarkdown(value: string) {
  return value
    .replace(/^#{1,6}\s+/, "")
    .replace(/\*\*/g, "")
    .replace(/__/g, "")
    .trim();
}

const summaryBlocks = computed<SummaryBlock[]>(() => {
  const blocks: SummaryBlock[] = [];
  let list: string[] = [];
  const flushList = () => {
    if (list.length) blocks.push({ type: "list", items: list });
    list = [];
  };
  for (const rawLine of props.product.summary.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
    if (bullet) {
      list.push(cleanMarkdown(bullet[1] ?? ""));
      continue;
    }
    flushList();
    const heading = /^#{1,6}\s+/.test(line) || /^\*\*.+\*\*$/.test(line);
    blocks.push({
      type: heading ? "heading" : "paragraph",
      text: cleanMarkdown(line),
    });
  }
  flushList();
  return blocks;
});
const visibleSummaryBlocks = computed(() => summaryBlocks.value.slice(0, 6));
const remainingSummaryBlocks = computed(() => summaryBlocks.value.slice(6));
const summaryExpanded = ref(false);
const renderedSummaryBlocks = computed(() =>
  summaryExpanded.value ? summaryBlocks.value : visibleSummaryBlocks.value,
);

const questions = computed(() => {
  const direct = props.product.data.questions;
  const interview = (props.product.data.interview as Record<string, unknown> | undefined)?.questions;
  const values = Array.isArray(direct) ? direct : Array.isArray(interview) ? interview : [];
  return values.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"));
});

const routes = computed(() => {
  const plan = props.product.data.applicationPlan;
  if (!plan || typeof plan !== "object") return [];
  const values = (plan as Record<string, unknown>).routes;
  return Array.isArray(values)
    ? values.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    : [];
});

const recommendations = computed(() => {
  const candidates = [
    props.product.data.recommendations,
    props.product.data.postings,
    props.product.data.jobs,
  ];
  const values = candidates.find(Array.isArray) ?? [];
  return values.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"));
});

const details = computed(() =>
  Object.entries(props.product.data)
    .filter(([key, value]) =>
      !["questions", "interview", "applicationPlan", "recommendations", "postings", "jobs"].includes(key)
      && (typeof value === "string" || typeof value === "number" || Array.isArray(value)),
    )
    .slice(0, 8)
    .map(([key, value]) => ({
      key,
      value: Array.isArray(value) ? value.map(String).join(" · ") : String(value),
    })),
);

function text(item: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return "";
}

type LinkPart = { text: string; url?: string };

function linkParts(value: string): LinkPart[] {
  const parts: LinkPart[] = [];
  const pattern = /https?:\/\/[^\s<>()]+/g;
  let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push({ text: value.slice(cursor, index) });
    parts.push({ text: match[0], url: match[0] });
    cursor = index + match[0].length;
  }
  if (cursor < value.length) parts.push({ text: value.slice(cursor) });
  return parts.length ? parts : [{ text: value }];
}

function jobUrl(item: Record<string, unknown>) {
  const value = text(item, "url", "sourceUrl", "postingUrl", "link");
  return /^https?:\/\//i.test(value) ? value : "";
}

function productLabel(type: AgentWorkProduct["productType"]) {
  return {
    DIAGNOSIS: "진단",
    COMPARISON: "비교",
    INTERVIEW_SET: "면접 질문",
    COVER_LETTER_DRAFT: "자소서 초안",
    APPLICATION_PLAN: "지원 계획",
    JOB_RECOMMENDATIONS: "추천 공고",
    PREFERENCES: "희망 조건",
    ROADMAP_VIEW: "로드맵 해설",
    POSTING_ANALYSIS: "대화 결과",
  }[type];
}

const displayTitle = computed(() =>
  props.product.productType === "POSTING_ANALYSIS"
    ? "공고 핵심 정리"
    : props.product.title,
);
</script>

<template>
  <article class="agent-product" :class="`agent-product--${product.productType.toLowerCase()}`">
    <header>
      <span>
        <MessagesSquare v-if="product.productType === 'INTERVIEW_SET'" :size="18" />
        <Route v-else-if="product.productType === 'APPLICATION_PLAN'" :size="18" />
        <ListChecks v-else-if="product.productType === 'JOB_RECOMMENDATIONS'" :size="18" />
        <FileText v-else :size="18" />
      </span>
      <div>
        <small>{{ productLabel(product.productType) }}</small>
        <strong>{{ displayTitle }}</strong>
      </div>
    </header>
    <div class="agent-product__summary">
      <template v-for="(block, index) in renderedSummaryBlocks" :key="index">
        <h4 v-if="block.type === 'heading'">
          <template v-for="(part, partIndex) in linkParts(block.text)" :key="partIndex">
            <a v-if="part.url" :href="part.url" target="_blank" rel="noopener noreferrer">{{ part.text }}</a>
            <template v-else>{{ part.text }}</template>
          </template>
        </h4>
        <ul v-else-if="block.type === 'list'">
          <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
            <template v-for="(part, partIndex) in linkParts(item)" :key="partIndex">
              <a v-if="part.url" :href="part.url" target="_blank" rel="noopener noreferrer">{{ part.text }}</a>
              <template v-else>{{ part.text }}</template>
            </template>
          </li>
        </ul>
        <p v-else>
          <template v-for="(part, partIndex) in linkParts(block.text)" :key="partIndex">
            <a v-if="part.url" :href="part.url" target="_blank" rel="noopener noreferrer">{{ part.text }}</a>
            <template v-else>{{ part.text }}</template>
          </template>
        </p>
      </template>
      <button
        v-if="remainingSummaryBlocks.length"
        class="agent-product__summary-more"
        type="button"
        :aria-expanded="summaryExpanded"
        @click="summaryExpanded = !summaryExpanded"
      >
        {{ summaryExpanded ? "내용 접기" : "전체 내용 보기" }}
        <ChevronDown :size="15" />
      </button>
    </div>

    <ol v-if="questions.length" class="agent-product__questions">
      <li v-for="(question, index) in questions" :key="index">
        <small>{{ text(question, 'topic', 'type') || `질문 ${index + 1}` }}</small>
        <strong>{{ text(question, 'question', 'prompt') }}</strong>
        <p v-if="text(question, 'basis', 'reason')">
          근거 · {{ text(question, "basis", "reason") }}
        </p>
      </li>
    </ol>

    <div v-if="routes.length" class="agent-product__routes">
      <article v-for="(route, index) in routes" :key="index">
        <small>경로 {{ index + 1 }}</small>
        <strong>{{ text(route, "title", "id") }}</strong>
        <p>{{ text(route, "summary") }}</p>
      </article>
    </div>

    <div v-if="recommendations.length" class="agent-product__recommendations">
      <component
        :is="jobUrl(job) ? 'a' : 'article'"
        v-for="(job, index) in recommendations.slice(0, 6)"
        :key="index"
        :href="jobUrl(job) || undefined"
        :target="jobUrl(job) ? '_blank' : undefined"
        :rel="jobUrl(job) ? 'noopener noreferrer' : undefined"
      >
        <strong>{{ text(job, "companyName", "company") }}</strong>
        <span>{{ text(job, "title", "jobTitle", "roleTitle") }}</span>
        <small>{{ text(job, "reason", "summary") }}</small>
      </component>
    </div>

    <details v-if="details.length" class="agent-product__details">
      <summary>구조화된 결과 <ChevronDown :size="15" /></summary>
      <dl>
        <template v-for="detail in details" :key="detail.key">
          <dt>{{ detail.key }}</dt>
          <dd>{{ detail.value }}</dd>
        </template>
      </dl>
    </details>
  </article>
</template>

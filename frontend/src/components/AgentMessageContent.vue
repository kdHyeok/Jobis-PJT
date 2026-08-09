<script setup lang="ts">
import { computed } from "vue";

// 에이전트 답변을 구조대로 렌더링한다 — 섹션 헤더(**…**), 불릿(·/-), 문단.
// 섹션 헤더가 2개 이상이면(공고 정리·이력서 진단 등 체계화 답변) 카드 스타일을 입힌다.
const props = defineProps<{ content: string }>();

type Block =
  | { type: "heading"; text: string }
  | { type: "list"; items: string[]; ordered: boolean }
  | { type: "divider" }
  | { type: "paragraph"; text: string };

const HEADING_RE = /^\*\*([^*]+)\*\*$/;
const BULLET_RE = /^[·•-]\s+/;
const ORDERED_RE = /^\d+[.)]\s+/;
const MARKDOWN_HEADING_RE = /^#{1,4}\s+/;
const DIVIDER_RE = /^(?:\*{3,}|-{3,}|_{3,})$/;

const blocks = computed<Block[]>(() => {
  const out: Block[] = [];
  for (const rawLine of props.content.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    if (DIVIDER_RE.test(line)) {
      out.push({ type: "divider" });
      continue;
    }
    const heading = line.match(HEADING_RE);
    if (heading) {
      out.push({ type: "heading", text: heading[1] });
      continue;
    }
    if (MARKDOWN_HEADING_RE.test(line)) {
      out.push({ type: "heading", text: line.replace(MARKDOWN_HEADING_RE, "") });
      continue;
    }
    if (BULLET_RE.test(line)) {
      const item = line.replace(BULLET_RE, "");
      const last = out[out.length - 1];
      if (last?.type === "list" && !last.ordered) last.items.push(item);
      else out.push({ type: "list", items: [item], ordered: false });
      continue;
    }
    if (ORDERED_RE.test(line)) {
      const item = line.replace(ORDERED_RE, "");
      const last = out[out.length - 1];
      if (last?.type === "list" && last.ordered) last.items.push(item);
      else out.push({ type: "list", items: [item], ordered: true });
      continue;
    }
    out.push({ type: "paragraph", text: line });
  }
  return out;
});

const structured = computed(
  () => blocks.value.filter((block) => block.type === "heading").length >= 2,
);

// tsconfig의 lib이 ES2020으로 고정돼 있어 replaceAll(ES2021)을 쓸 수 없다.
// 정규식 전역 치환은 같은 결과를 내면서 lib 경계를 넘지 않는다.
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function inline(text: string): string {
  return escapeHtml(text).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}
</script>

<template>
  <div class="agent-rich" :class="{ 'agent-rich--card': structured }">
    <template v-for="(block, index) in blocks" :key="index">
      <h4 v-if="block.type === 'heading'" v-html="inline(block.text)" />
      <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.type === 'list'">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex" v-html="inline(item)" />
      </component>
      <hr v-else-if="block.type === 'divider'" />
      <p v-else v-html="inline(block.text)" />
    </template>
  </div>
</template>

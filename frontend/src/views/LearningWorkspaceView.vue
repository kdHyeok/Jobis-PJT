<script setup lang="ts">
import { BookOpen, Check, Clock3, ExternalLink, Library, Link2, Menu, MessageCircle, Plus, RefreshCw, Send, Sparkles, Trash2, Upload, X } from "@lucide/vue";
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { learningChats, learningPlan, type LearningResource } from "@/learning-plan";

type LearningMessage = { id: string; role: "USER" | "ASSISTANT"; content: string };

const route = useRoute();
const router = useRouter();
const memoryOpen = ref(false);
const syllabusOpen = ref(true);
const resourceTitle = ref("");
const resourceUrl = ref("");
const resourceText = ref("");
const resourceMode = ref<"URL" | "TEXT" | "FILE">("URL");
const resourceFile = ref<File | null>(null);
const minutes = ref(30);
const currentModule = ref(0);
const draft = ref("");
const sending = ref(false);
const liveStatus = ref("");
const error = ref("");
const messages = ref<LearningMessage[]>([]);
const conversationId = ref<string | null>(null);
const chatLog = ref<HTMLElement | null>(null);
const item = computed(() => learningPlan.find(String(route.params.planId)));
const enabledResources = computed(() => item.value?.resources.filter((resource) => resource.enabled) ?? []);
const module = computed(() => item.value?.modules[currentModule.value]);

watch(item, (value) => {
  if (!value) void router.replace({ name: "learning-plan" });
  else {
    conversationId.value = learningChats.forPlan(value.id)?.conversationId ?? null;
    if (!messages.value.length) messages.value = [{
      id: crypto.randomUUID(),
      role: "ASSISTANT",
      content: `${value.title} 학습 세션입니다. 개념을 질문하거나 아래에서 과제·퀴즈를 선택해 시작하세요.`,
    }];
  }
}, { immediate: true });

function updateResource(resource: LearningResource, patch: Partial<LearningResource>) {
  if (!item.value) return;
  learningPlan.update(item.value.id, { resources: item.value.resources.map((entry) => entry.id === resource.id ? { ...entry, ...patch } : entry) });
}

function addResource() {
  if (!item.value || !resourceTitle.value.trim()) return;
  if (resourceMode.value === "URL" && !resourceUrl.value.trim()) return;
  const content = resourceMode.value === "URL" ? null : resourceText.value.trim();
  if (resourceMode.value !== "URL" && !content) return;
  learningPlan.update(item.value.id, { resources: [...item.value.resources, {
    id: crypto.randomUUID(), title: resourceTitle.value.trim(),
    url: resourceMode.value === "URL" ? resourceUrl.value.trim() || null : null,
    content, kind: "PERSONAL", enabled: true, sourceType: resourceMode.value,
    fileName: resourceFile.value?.name ?? null,
  }] });
  resourceTitle.value = "";
  resourceUrl.value = "";
  resourceText.value = "";
  resourceFile.value = null;
}

async function selectResourceFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  input.value = "";
  if (!file) return;
  if (!/\.(txt|md)$/i.test(file.name)) {
    error.value = "학습 자료 파일은 TXT 또는 MD만 추가할 수 있어요.";
    return;
  }
  if (file.size > 200_000) {
    error.value = "학습 자료 파일은 200KB 이하만 추가할 수 있어요.";
    return;
  }
  resourceFile.value = file;
  resourceTitle.value ||= file.name.replace(/\.(txt|md)$/i, "");
  resourceText.value = await file.text();
  error.value = "";
}

function removeResource(resourceId: string) {
  if (!item.value) return;
  learningPlan.update(item.value.id, { resources: item.value.resources.filter((resource) => resource.id !== resourceId) });
}

function recordStudy() {
  if (!item.value) return;
  learningPlan.update(item.value.id, { spentMinutes: item.value.spentMinutes + Math.max(0, minutes.value) });
}

function complete() {
  if (!item.value) return;
  learningPlan.update(item.value.id, { completed: true });
}

function restart() {
  if (!item.value) return;
  learningPlan.restart(item.value.id);
  currentModule.value = 0;
}

function learningPrompt(question: string) {
  let remaining = 12_000;
  const resources = enabledResources.value.map((resource) => {
    const header = `[자료: ${resource.title} / ${resource.sourceType ?? (resource.url ? "URL" : "TEXT")}]`;
    const raw = resource.content?.trim() || (resource.url ? `참고 URL: ${resource.url}` : "본문 없음");
    const excerpt = raw.slice(0, Math.max(0, Math.min(remaining, 4_000)));
    remaining -= excerpt.length;
    return `${header}\n${excerpt}`;
  }).filter((resource) => resource.trim()).join("\n\n") || "등록된 자료 없음";
  return [
    "[JOBIS_LEARNING_SESSION]",
    `[학습 세션: ${item.value?.title}]`,
    `학습 범위: ${module.value?.objective ?? item.value?.description}`,
    `사용자가 선택한 학습 자료: ${resources}`,
    "선택한 자료의 범위를 우선하고, 확인하지 못한 내용을 지어내지 마세요. 짧게 설명한 뒤 학습자가 직접 생각할 질문을 하나 포함하세요.",
    `요청: ${question}`,
  ].join("\n");
}

function isCompletionStatus(value: string | null | undefined) {
  return /^완료(?:\s*[·-]\s*\d+(?:\.\d+)?초)?$/.test(value?.trim() ?? "");
}

function learningAnswer(
  result: Awaited<ReturnType<typeof api.chatReplyJob>>["result"],
  conversationMessages: Array<{ role: string; content: string }>,
) {
  const productReply = result.workProducts
    ?.map((product) => product.reply?.trim())
    .find((reply): reply is string => Boolean(reply) && !isCompletionStatus(reply));
  const attributedReply = result.replyAttributions
    ?.map((attribution) => attribution.text.trim())
    .find((reply) => reply && !isCompletionStatus(reply));
  const conversationReply = [...conversationMessages].reverse().find((message) =>
    message.role === "ASSISTANT" && message.content.trim() &&
    !isCompletionStatus(message.content) &&
    !message.content.includes("발화의 URL 을 공고 자산으로 등록")
  )?.content;
  const resultMessage = result.message?.trim();
  return productReply || attributedReply || conversationReply ||
    (resultMessage && !isCompletionStatus(resultMessage) ? resultMessage : null);
}

async function scrollToLatest() {
  await nextTick();
  chatLog.value?.scrollTo({ top: chatLog.value.scrollHeight, behavior: "smooth" });
}

async function submit(text = draft.value) {
  const question = text.trim();
  if (!question || sending.value || !item.value) return;
  messages.value.push({ id: crypto.randomUUID(), role: "USER", content: question });
  draft.value = "";
  sending.value = true;
  error.value = "";
  liveStatus.value = "학습 자료와 현재 범위를 확인하고 있어요";
  await scrollToLatest();
  try {
    if (!conversationId.value) {
      const created = await api.createConversation();
      conversationId.value = created.id;
      learningChats.register({
        conversationId: created.id,
        planId: item.value.id,
        title: item.value.title,
      });
    }
    const sent = await api.sendMessage(conversationId.value, learningPrompt(question));
    if (!sent.chatReplyJobId) throw new Error("학습 답변 작업을 시작하지 못했습니다.");
    let job = await api.chatReplyJob(sent.chatReplyJobId);
    while (["QUEUED", "RUNNING"].includes(job.status)) {
      liveStatus.value = job.stageMessage || "답변을 구성하고 있어요";
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      job = await api.chatReplyJob(job.id);
    }
    if (job.status !== "SUCCEEDED") throw new Error(job.errorMessage || "학습 답변을 만들지 못했습니다.");
    const conversation = await api.conversation(conversationId.value);
    const answer = learningAnswer(job.result, conversation.messages);
    messages.value.push({
      id: crypto.randomUUID(),
      role: "ASSISTANT",
      content: answer || "답변이 완료됐지만 표시할 내용이 없습니다.",
    });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "학습 답변을 만들지 못했습니다.";
  } finally {
    liveStatus.value = "";
    sending.value = false;
    await scrollToLatest();
  }
}
</script>

<template>
  <main v-if="item" class="workspace learning-workspace learning-session">
    <Teleport to="#app-topbar-center"><h1 class="app-page-title learning-page-title">{{ item.title }}</h1></Teleport>

    <aside class="learning-session__syllabus" :class="{ collapsed: !syllabusOpen }">
      <button class="learning-session__collapse" type="button" @click="syllabusOpen = !syllabusOpen"><Menu :size="18" /></button>
      <template v-if="syllabusOpen">
        <header><small>학습 과정</small><h2>{{ item.title }}</h2><p>{{ item.description }}</p></header>
        <nav>
          <button v-for="(entry, index) in item.modules" :key="`${entry.title}-${index}`" :class="{ active: index === currentModule }" type="button" @click="currentModule = index">
            <span>{{ index + 1 }}</span><div><strong>{{ entry.title }}</strong><small>{{ index < currentModule ? '완료' : index === currentModule ? '학습 중' : '예정' }}</small></div>
          </button>
        </nav>
        <div class="learning-session__time"><Clock3 :size="16" /><span>누적 {{ item.spentMinutes }}분</span><input v-model.number="minutes" type="number" min="0" step="5" /><button type="button" @click="recordStudy">기록</button></div>
      </template>
    </aside>

    <section class="learning-session__chat">
      <header>
        <div><small>오늘의 학습</small><h1>{{ module?.title ?? item.title }}</h1><p>{{ module?.objective ?? item.description }}</p></div>
        <div>
          <button type="button" @click="memoryOpen = true"><Library :size="17" /> 자료 {{ enabledResources.length }}</button>
          <button v-if="item.completed" type="button" @click="restart"><RefreshCw :size="17" /> 다시 학습</button>
          <button v-else class="complete" type="button" @click="complete"><Check :size="17" /> 완료</button>
        </div>
      </header>

      <div class="learning-session__actions">
        <button type="button" @click="submit(`${module?.title ?? item.title}의 핵심 개념을 예시와 함께 설명해줘.`)"><MessageCircle :size="18" /><span><strong>개념 질문</strong><small>모르는 부분부터 대화로 확인</small></span></button>
        <button type="button" @click="submit(`${module?.practice ?? item.title} 범위에서 30분 안에 할 수 있는 실습 과제를 제안해줘. 제출 형식과 완료 기준도 포함해줘.`)"><Sparkles :size="18" /><span><strong>과제 제안</strong><small>자료 기반 실습과 완료 기준</small></span></button>
        <button type="button" @click="submit(`${module?.title ?? item.title} 이해도를 확인하는 객관식 3문제를 한 문제씩 출제해줘. 정답은 내가 답한 뒤 알려줘.`)"><BookOpen :size="18" /><span><strong>퀴즈 시작</strong><small>한 문제씩 풀며 바로 피드백</small></span></button>
      </div>

      <div ref="chatLog" class="learning-session__messages" aria-live="polite">
        <article v-for="message in messages" :key="message.id" :class="`is-${message.role.toLowerCase()}`"><span>{{ message.role === 'ASSISTANT' ? 'JOBIS' : '나' }}</span><p>{{ message.content }}</p></article>
        <article v-if="sending" class="is-assistant is-live"><span>JOBIS</span><p>{{ liveStatus }}</p><i><b /><b /><b /></i></article>
        <p v-if="error" class="inline-error">{{ error }}</p>
      </div>

      <form class="learning-session__composer" @submit.prevent="submit()">
        <textarea v-model="draft" rows="2" :placeholder="`${module?.title ?? item.title}에서 궁금한 내용을 물어보세요`" />
        <button type="submit" :disabled="sending || !draft.trim()"><Send :size="19" /></button>
      </form>
    </section>

    <div v-if="memoryOpen" class="learning-memory-backdrop" @click="memoryOpen = false" />
    <aside v-if="memoryOpen" class="learning-memory-drawer" role="dialog" aria-modal="true">
      <header><div><small>LEARNING MEMORY</small><h2>학습 자료</h2><p>켜 둔 자료와 학습 범위를 질문·과제·퀴즈의 컨텍스트로 전달합니다.</p></div><button type="button" @click="memoryOpen = false"><X :size="20" /></button></header>
      <form @submit.prevent="addResource">
        <input v-model="resourceTitle" placeholder="자료 이름" />
        <div class="learning-memory-modes">
          <button v-for="mode in (['URL', 'TEXT', 'FILE'] as const)" :key="mode" type="button" :class="{ active: resourceMode === mode }" @click="resourceMode = mode">{{ mode === 'URL' ? 'URL' : mode === 'TEXT' ? '직접 입력' : 'TXT · MD' }}</button>
        </div>
        <div v-if="resourceMode === 'URL'"><Link2 :size="16" /><input v-model="resourceUrl" type="url" placeholder="학습 자료 URL" /></div>
        <textarea v-else-if="resourceMode === 'TEXT'" v-model="resourceText" rows="7" placeholder="추가로 학습할 내용을 직접 입력하세요." />
        <label v-else class="learning-memory-file"><Upload :size="18" /><span>{{ resourceFile?.name ?? 'TXT 또는 MD 파일 선택' }}</span><input type="file" accept=".txt,.md,text/plain,text/markdown" @change="selectResourceFile" /></label>
        <button type="submit"><Plus :size="16" /> 자료 추가</button>
      </form>
      <article v-for="resource in item.resources" :key="resource.id">
        <button class="resource-toggle" :class="{ active: resource.enabled }" type="button" @click="updateResource(resource, { enabled: !resource.enabled })"><span /></button>
        <div><strong>{{ resource.title }}</strong><small>{{ resource.kind === 'PERSONAL' ? `${resource.sourceType === 'FILE' ? '파일' : resource.sourceType === 'TEXT' ? '직접 입력' : '사용자 URL'} 자료` : '추천 자료' }}</small></div>
        <a v-if="resource.url" :href="resource.url" target="_blank" rel="noreferrer"><ExternalLink :size="16" /></a>
        <button type="button" @click="removeResource(resource.id)"><Trash2 :size="16" /></button>
      </article>
    </aside>
  </main>
</template>

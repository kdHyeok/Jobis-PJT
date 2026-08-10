import { computed, ref } from "vue";

import { curatedLearningResources } from "@/learning-sources";

export type LearningResource = {
  id: string;
  title: string;
  url: string | null;
  kind: "OFFICIAL" | "COMMUNITY" | "PERSONAL";
  enabled: boolean;
  content?: string | null;
  sourceType?: "URL" | "TEXT" | "FILE";
  fileName?: string | null;
};

export type LearningPlanItem = {
  id: string;
  competencyId: string;
  canonicalKey: string;
  title: string;
  description: string;
  startDate: string;
  endDate: string;
  estimatedMinutes: number;
  spentMinutes: number;
  completed: boolean;
  modules: Array<{ title: string; objective: string; practice: string }>;
  resources: LearningResource[];
  updatedAt: string;
};

const STORAGE_KEY = "jobiss:learning-plan:v1";
const LEARNING_CHATS_KEY = "jobiss:learning-chats:v1";

export type LearningChatReference = {
  conversationId: string;
  planId: string;
  title: string;
  updatedAt: string;
};

type LearningConversationSignal = {
  id: string;
  title?: string | null;
  lastMessage?: string | null;
};

function readLearningChats(): LearningChatReference[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LEARNING_CHATS_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export const learningChats = {
  all() {
    return readLearningChats();
  },
  has(conversationId: string) {
    return readLearningChats().some((chat) => chat.conversationId === conversationId);
  },
  find(conversationId: string) {
    return readLearningChats().find((chat) => chat.conversationId === conversationId) ?? null;
  },
  forPlan(planId: string) {
    return readLearningChats().find((chat) => chat.planId === planId) ?? null;
  },
  isLearning(conversation: LearningConversationSignal) {
    if (this.has(conversation.id)) return true;
    const signal = `${conversation.title ?? ""}\n${conversation.lastMessage ?? ""}`;
    return signal.includes("[JOBIS_LEARNING_SESSION]") || signal.includes("[학습 세션:");
  },
  planIdFor(conversation: LearningConversationSignal) {
    const registered = this.find(conversation.id);
    if (registered) return registered.planId;
    const signal = `${conversation.title ?? ""}\n${conversation.lastMessage ?? ""}`;
    return readItems().find((item) => signal.includes(`[학습 세션: ${item.title}]`))?.id ?? null;
  },
  titleFor(conversation: LearningConversationSignal) {
    const registered = this.find(conversation.id);
    if (registered?.title) return registered.title;
    const signal = `${conversation.title ?? ""}\n${conversation.lastMessage ?? ""}`;
    const plan = readItems().find((item) => signal.includes(`[학습 세션: ${item.title}]`));
    if (plan) return plan.title;
    return signal.match(/\[학습 세션:\s*([^\]]+)\]/)?.[1]?.trim() || "학습 세션";
  },
  register(reference: Omit<LearningChatReference, "updatedAt">) {
    const chats = readLearningChats().filter((chat) =>
      chat.conversationId !== reference.conversationId && chat.planId !== reference.planId
    );
    chats.unshift({ ...reference, updatedAt: new Date().toISOString() });
    window.localStorage.setItem(LEARNING_CHATS_KEY, JSON.stringify(chats));
    window.dispatchEvent(new CustomEvent("jobiss:learning-chats-changed"));
  },
};

function readItems(): LearningPlanItem[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

const items = ref<LearningPlanItem[]>(readItems());

function persist() {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.value));
}

function defaultResources(canonicalKey: string, title: string): LearningResource[] {
  return curatedLearningResources(canonicalKey, title);
}

export const learningPlan = {
  items,
  active: computed(() => items.value.filter((item) => !item.completed)),
  completedCompetencyIds: computed(() => new Set(items.value.filter((item) => item.completed).map((item) => item.competencyId))),
  upsert(input: Omit<LearningPlanItem, "id" | "spentMinutes" | "completed" | "resources" | "updatedAt">) {
    const index = items.value.findIndex((item) => item.competencyId === input.competencyId);
    if (index >= 0) {
      items.value[index] = {
        ...items.value[index],
        ...input,
        updatedAt: new Date().toISOString(),
      };
    } else {
      items.value.push({
        ...input,
        id: crypto.randomUUID(),
        spentMinutes: 0,
        completed: false,
        resources: defaultResources(input.canonicalKey, input.title),
        updatedAt: new Date().toISOString(),
      });
    }
    persist();
    return items.value.find((item) => item.competencyId === input.competencyId)!;
  },
  findByCompetency(competencyId: string) {
    return items.value.find((item) => item.competencyId === competencyId) ?? null;
  },
  find(id: string) {
    return items.value.find((item) => item.id === id) ?? null;
  },
  update(id: string, patch: Partial<LearningPlanItem>) {
    const index = items.value.findIndex((item) => item.id === id);
    if (index < 0) return;
    items.value[index] = { ...items.value[index], ...patch, updatedAt: new Date().toISOString() };
    persist();
  },
  restart(id: string) {
    const index = items.value.findIndex((item) => item.id === id);
    if (index < 0) return;
    items.value[index] = { ...items.value[index], completed: false, spentMinutes: 0, updatedAt: new Date().toISOString() };
    persist();
  },
  remove(id: string) {
    items.value = items.value.filter((item) => item.id !== id);
    persist();
  },
};

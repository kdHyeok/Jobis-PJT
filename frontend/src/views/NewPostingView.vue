<script setup lang="ts">
import { ArrowLeft, BriefcaseBusiness, LoaderCircle, Sparkles } from "@lucide/vue";
import { ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";

const router = useRouter();
const sourceType = ref<"TEXT" | "URL">("TEXT");
const sourceUrl = ref("");
const rawText = ref("");
const loading = ref(false);
const error = ref("");

async function submit() {
  if (rawText.value.trim().length < 20) return;
  loading.value = true;
  error.value = "";
  try {
    const result = await api.createPosting(
      sourceType.value,
      sourceType.value === "URL" ? sourceUrl.value.trim() : null,
      rawText.value.trim(),
    );
    await router.push({
      name: "posting-detail",
      params: { postingId: result.postingId },
      query: result.reusedAnalysis
        ? { reused: "1", reuseMessage: result.reuseMessage ?? undefined }
        : undefined,
    });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 등록하지 못했습니다.";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="workspace posting-new-workspace">
    <RouterLink class="back-link" :to="{ name: 'postings' }">
      <ArrowLeft :size="17" /> 채용 공고
    </RouterLink>
    <section class="posting-new-card">
      <header>
        <span><BriefcaseBusiness :size="24" /></span>
        <div>
          <p class="eyebrow">NEW JOB POSTING</p>
          <h1>새 채용 공고 분석</h1>
          <p>원문을 저장한 뒤 백그라운드에서 커리어 자료와 비교합니다.</p>
        </div>
      </header>
      <div class="source-tabs">
        <button
          type="button"
          :class="{ active: sourceType === 'TEXT' }"
          @click="sourceType = 'TEXT'"
        >
          공고문 붙여넣기
        </button>
        <button
          type="button"
          :class="{ active: sourceType === 'URL' }"
          @click="sourceType = 'URL'"
        >
          URL과 원문
        </button>
      </div>
      <label v-if="sourceType === 'URL'">
        공고 URL
        <input v-model="sourceUrl" type="url" placeholder="https://…" />
      </label>
      <label>
        공고 원문
        <textarea
          v-model="rawText"
          minlength="20"
          maxlength="100000"
          placeholder="회사, 직무, 필수 조건과 우대 사항이 포함된 원문을 붙여넣어 주세요."
        />
        <small>{{ rawText.length.toLocaleString() }} / 100,000자</small>
      </label>
      <p v-if="error" class="form-error">{{ error }}</p>
      <button
        class="press-button press-button--primary"
        type="button"
        :disabled="
          loading ||
          rawText.trim().length < 20 ||
          (sourceType === 'URL' && !sourceUrl.trim())
        "
        @click="submit"
      >
        <LoaderCircle v-if="loading" class="spin" :size="18" />
        <Sparkles v-else :size="18" /> 저장하고 분석 시작
      </button>
    </section>
  </main>
</template>

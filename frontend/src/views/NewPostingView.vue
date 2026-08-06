<script setup lang="ts">
import {
  ArrowLeft,
  BriefcaseBusiness,
  CheckCircle2,
  FileImage,
  FileText,
  Globe2,
  LoaderCircle,
  RotateCcw,
  Sparkles,
} from "@lucide/vue";
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import type { V3SourceView } from "@/types";

const router = useRouter();
const sourceType = ref<"TEXT" | "URL" | "IMAGE">("TEXT");
const sourceUrl = ref("");
const rawText = ref("");
const imageBase64 = ref("");
const imageMediaType = ref("");
const imageFilename = ref("");
const imagePreview = ref("");
const source = ref<V3SourceView | null>(null);
const loading = ref(false);
const error = ref("");
const draftRestored = ref(false);
const DRAFT_KEY = "jobis:v3-posting-draft";
const POSTING_TEXT_MAX_CHARS = 20_000;

function postingLengthMessage(length: number) {
  return `공고 내용이 너무 길어요. 현재 ${length.toLocaleString()}자이며 최대 ${POSTING_TEXT_MAX_CHARS.toLocaleString()}자까지 분석할 수 있어요. 회사 소개, 복리후생, 채용 절차와 중복 안내를 줄이고 직무·업무·경력·필수·우대사항은 남겨주세요.`;
}

onMounted(async () => {
  try {
    const stored = JSON.parse(window.localStorage.getItem(DRAFT_KEY) ?? "null") as {
      sourceType?: "TEXT" | "URL" | "IMAGE";
      sourceUrl?: string;
      rawText?: string;
      sourceId?: string;
    } | null;
    if (stored?.rawText || stored?.sourceUrl) {
      sourceType.value = stored.sourceType ?? "TEXT";
      sourceUrl.value = stored.sourceUrl ?? "";
      rawText.value = stored.rawText ?? "";
      draftRestored.value = true;
    }
    if (stored?.sourceId) {
      const restored = await api.v3Source(stored.sourceId);
      source.value = restored;
      rawText.value = stored.rawText
        ?? restored.sourceDocument.rawText;
    }
  } catch {
    source.value = null;
  }
});

watch([sourceType, sourceUrl, rawText, source], () => {
  if (sourceType.value === "IMAGE") return;
  window.localStorage.setItem(DRAFT_KEY, JSON.stringify({
    sourceType: sourceType.value,
    sourceUrl: sourceUrl.value,
    rawText: rawText.value,
    sourceId: source.value?.id ?? null,
  }));
});

function chooseType(type: "TEXT" | "URL" | "IMAGE") {
  sourceType.value = type;
  resetExtraction();
}

function resetExtraction() {
  source.value = null;
  error.value = "";
}

async function selectImage(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    error.value = "PNG, JPG, WEBP 이미지 공고만 등록할 수 있습니다.";
    return;
  }
  if (file.size > 14_000_000) {
    error.value = "이미지는 14MB 이하로 올려주세요.";
    return;
  }
  const dataUrl = await readFile(file);
  imagePreview.value = dataUrl;
  imageBase64.value = dataUrl.split(",", 2)[1] ?? "";
  imageMediaType.value = file.type;
  imageFilename.value = file.name;
  resetExtraction();
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("이미지를 읽지 못했습니다."));
    reader.readAsDataURL(file);
  });
}

async function acquireSource() {
  if (sourceType.value === "TEXT" && rawText.value.trim().length > POSTING_TEXT_MAX_CHARS) {
    error.value = postingLengthMessage(rawText.value.trim().length);
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const requestedSourceType = sourceType.value;
    const acquired = await api.acquireV3Source({
      inputType: requestedSourceType,
      entryPoint: "POSTINGS_PAGE",
      extractionRevision: 1,
      text: requestedSourceType === "TEXT" ? rawText.value.trim() : null,
      url: requestedSourceType === "URL" ? sourceUrl.value.trim() : null,
      imageBase64: requestedSourceType === "IMAGE" ? imageBase64.value : null,
      imageMediaType: requestedSourceType === "IMAGE" ? imageMediaType.value : null,
      originalFilename: requestedSourceType === "IMAGE" ? imageFilename.value : null,
    });
    source.value = acquired;
    rawText.value = acquired.sourceDocument.rawText;
    draftRestored.value = false;
    if (requestedSourceType === "TEXT") {
      await confirmAndAnalyze();
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고 원문을 가져오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function confirmAndAnalyze() {
  if (!source.value || rawText.value.trim().length < 20) return;
  if (rawText.value.trim().length > POSTING_TEXT_MAX_CHARS) {
    error.value = postingLengthMessage(rawText.value.trim().length);
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const verifiedText = rawText.value.trim();
    const extractedText = source.value.sourceDocument.rawText.trim();
    const changed = verifiedText !== extractedText;
    await api.verifyV3Source(source.value.id, {
      verifiedText,
      corrections: changed
        ? [{
            field: "verifiedText",
            before: source.value.sourceDocument.rawText,
            after: verifiedText,
            reason: sourceType.value === "IMAGE"
              ? "OCR_CORRECTION"
              : "OTHER",
          }]
        : [],
      verifiedBy: "USER",
    });
    const result = await api.startV3Analysis(source.value.id);
    window.localStorage.removeItem(DRAFT_KEY);
    await router.push({
      name: "posting-detail",
      params: { postingId: result.postingId },
      query: { provider: "unified" },
    });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "확인한 공고를 분석하지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

function canAcquire() {
  if (sourceType.value === "URL") return sourceUrl.value.trim().length > 8;
  if (sourceType.value === "IMAGE") return Boolean(imageBase64.value);
  return rawText.value.trim().length >= 20
    && rawText.value.trim().length <= POSTING_TEXT_MAX_CHARS;
}
</script>

<template>
  <main class="workspace posting-new-workspace">
    <RouterLink class="back-link" :to="{ name: 'postings' }">
      <ArrowLeft :size="17" /> 채용 공고
    </RouterLink>

    <section class="posting-new-card posting-v3-intake">
      <header>
        <span><BriefcaseBusiness :size="24" /></span>
        <div>
          <p class="eyebrow">VERIFIED JOB POSTING</p>
          <h1>새 채용 공고 분석</h1>
          <p>JOBIS가 읽은 원문을 먼저 보여드려요. 내용이 맞는지 확인한 뒤에만 분석을 시작합니다.</p>
        </div>
      </header>

      <ol class="posting-v3-steps" aria-label="공고 등록 단계">
        <li class="active"><b>1</b><span>공고 입력</span></li>
        <li :class="{ active: source || loading }"><b>2</b><span>원문 확인</span></li>
        <li><b>3</b><span>확인 후 분석</span></li>
      </ol>

      <div class="source-tabs source-tabs--three">
        <button type="button" :class="{ active: sourceType === 'TEXT' }" @click="chooseType('TEXT')">
          <FileText :size="17" /> 공고문 붙여넣기
        </button>
        <button type="button" :class="{ active: sourceType === 'URL' }" @click="chooseType('URL')">
          <Globe2 :size="17" /> URL 가져오기
        </button>
        <button type="button" :class="{ active: sourceType === 'IMAGE' }" @click="chooseType('IMAGE')">
          <FileImage :size="17" /> 이미지 공고
        </button>
      </div>

      <template v-if="!source">
        <label v-if="sourceType === 'URL'">
          공고 상세 페이지 URL
          <input v-model="sourceUrl" type="url" placeholder="https://…" />
          <small>목록이나 검색 결과가 아닌 공고 상세 페이지 주소를 넣어주세요.</small>
        </label>

        <label v-else-if="sourceType === 'IMAGE'" class="posting-image-drop">
          이미지 공고 선택
          <input type="file" accept="image/png,image/jpeg,image/webp" @change="selectImage" />
          <span v-if="imagePreview" class="posting-image-preview">
            <img :src="imagePreview" alt="분석할 채용 공고 미리보기" />
            <strong>{{ imageFilename }}</strong>
          </span>
          <span v-else><FileImage :size="28" /> PNG, JPG, WEBP · 최대 14MB</span>
        </label>

        <label v-else>
          공고 원문
          <textarea
            v-model="rawText"
            minlength="20"
            rows="14"
            placeholder="회사, 직무, 필수 조건과 우대 사항이 포함된 원문을 붙여넣어 주세요."
          />
          <small :class="{ 'input-length-error': rawText.trim().length > POSTING_TEXT_MAX_CHARS }">
            {{ rawText.length.toLocaleString() }} / {{ POSTING_TEXT_MAX_CHARS.toLocaleString() }}자
          </small>
          <span v-if="rawText.trim().length > POSTING_TEXT_MAX_CHARS" class="input-length-help">
            회사 소개, 복리후생, 채용 절차와 중복 안내를 줄여주세요. 직무·업무·경력·필수·우대사항은 남겨주세요.
          </span>
        </label>

        <p v-if="draftRestored" class="posting-draft-notice">
          이전에 작성하던 초안을 복구했습니다.
        </p>
        <button
          class="press-button press-button--primary"
          type="button"
          :disabled="loading || !canAcquire()"
          @click="acquireSource"
        >
          <LoaderCircle v-if="loading" class="spin" :size="18" />
          <Sparkles v-else :size="18" />
          {{
            loading
              ? sourceType === 'TEXT'
                ? '직무와 조건을 구조화하고 있어요'
                : sourceType === 'URL'
                  ? '공고 원문을 읽고 있어요'
                  : '공고 원문을 읽고 있어요'
              : sourceType === 'TEXT'
                ? '직무·경력 확인 시작하기'
                : sourceType === 'URL'
                  ? '원문 추출하고 확인하기'
                  : '원문 추출하고 확인하기'
          }}
        </button>
      </template>

      <template v-else>
        <section class="posting-source-confirmation">
          <header>
            <span><CheckCircle2 :size="22" /></span>
            <div>
              <p class="eyebrow">SOURCE CHECK</p>
              <h2>가져온 원문이 공고와 같은가요?</h2>
              <p v-if="sourceType === 'URL'">
                이 단계에서는 원문 추출 오류만 고쳐주세요. 확인한 내용으로 직무와 경력을 분석합니다.
              </p>
              <p v-else>이 단계에서는 이미지 추출 오류를 고쳐주세요. 확인한 내용으로 직무와 경력을 분석합니다.</p>
            </div>
          </header>

          <div v-if="source.sourceDocument.warnings?.length" class="posting-source-warnings">
            <strong>추출 중 확인이 필요한 내용 {{ source.sourceDocument.warnings.length }}개</strong>
            <ul>
              <li v-for="warning in source.sourceDocument.warnings" :key="`${warning.code}:${warning.message}`">
                {{ warning.message }}
              </li>
            </ul>
          </div>

          <div :class="{ 'posting-source-comparison': sourceType === 'IMAGE' && imagePreview }">
            <figure v-if="sourceType === 'IMAGE' && imagePreview" class="posting-source-comparison__original">
              <figcaption>원본 이미지</figcaption>
              <div><img :src="imagePreview" alt="사용자가 올린 채용 공고 원본" /></div>
              <small>{{ imageFilename }}</small>
            </figure>
            <label class="posting-source-comparison__text">
              확인할 공고 원문
              <textarea v-model="rawText" rows="18" />
              <small :class="{ 'input-length-error': rawText.trim().length > POSTING_TEXT_MAX_CHARS }">
                {{ rawText.length.toLocaleString() }} / {{ POSTING_TEXT_MAX_CHARS.toLocaleString() }}자 · 수정 내용은 검증 기록으로 남습니다.
              </small>
              <span v-if="rawText.trim().length > POSTING_TEXT_MAX_CHARS" class="input-length-help">
                분석을 시작하려면 회사 소개, 복리후생, 채용 절차와 중복 안내를 줄여주세요.
              </span>
            </label>
          </div>

          <details class="posting-extraction-details">
            <summary>
              추출 근거 보기
              · {{ source.sourceDocument.segments?.length ?? 0 }}개
            </summary>
            <ol>
              <li v-for="segment in source.sourceDocument.segments" :key="segment.segmentId">
                <span>{{ segment.method }}</span>
                <p>{{ segment.text }}</p>
              </li>
            </ol>
          </details>

          <div class="posting-source-confirmation__actions">
            <button class="press-button press-button--ghost" type="button" :disabled="loading" @click="resetExtraction">
              <RotateCcw :size="17" /> 다시 가져오기
            </button>
            <button
              class="press-button press-button--primary"
              type="button"
              :disabled="loading || rawText.trim().length < 20 || rawText.trim().length > POSTING_TEXT_MAX_CHARS"
              @click="confirmAndAnalyze"
            >
              <LoaderCircle v-if="loading" class="spin" :size="18" />
              <CheckCircle2 v-else :size="18" />
              {{ loading ? '확인 내용을 저장하고 있어요' : '내용이 맞아요 · 분석 시작' }}
            </button>
          </div>
        </section>
      </template>

      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    </section>
  </main>
</template>

<script setup lang="ts">
import {
  LockKeyhole,
  LogOut,
  Save,
  ShieldCheck,
  Target,
  UserRound,
} from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import { session } from "@/session";
import type { GoalProfile, Posting } from "@/types";

const router = useRouter();
const error = ref("");
const success = ref("");
const busy = ref(false);
const loadingGoals = ref(true);
const goalProfile = ref<GoalProfile | null>(null);
const postings = ref<Posting[]>([]);
const currentGoalPostingId = ref("");
const finalGoalText = ref("");

const selectablePostings = computed(() =>
  postings.value.filter(
    (posting) =>
      posting.analysisStatus === "SUCCEEDED" &&
      !posting.archivedAt &&
      (posting.companyName || posting.roleTitle),
  ),
);

onMounted(async () => {
  try {
    const [goals, postingItems] = await Promise.all([
      api.goalProfile(),
      api.postings(),
    ]);
    goalProfile.value = goals;
    postings.value = postingItems;
    currentGoalPostingId.value = goals.currentGoalPostingId ?? "";
    finalGoalText.value = goals.finalGoalText ?? "";
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "목표 정보를 불러오지 못했습니다.";
  } finally {
    loadingGoals.value = false;
  }
});

async function saveGoals() {
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    goalProfile.value = await api.updateGoalProfile(
      currentGoalPostingId.value || null,
      finalGoalText.value.trim() || null,
    );
    success.value = "커리어 목표를 저장했습니다.";
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "커리어 목표를 저장하지 못했습니다.";
  } finally {
    busy.value = false;
  }
}

async function logout() {
  busy.value = true;
  error.value = "";
  try {
    await api.logout();
    session.clear();
    await router.push({ name: "login" });
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "로그아웃하지 못했습니다.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="workspace settings-workspace">
    <section class="page-heading">
      <div>
        <p class="eyebrow">SETTINGS</p>
        <h1>계정과 커리어 목표</h1>
        <p>AI가 현재 준비 수준과 장기 방향을 구분할 수 있도록 목표를 관리합니다.</p>
      </div>
    </section>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="success" class="form-success">{{ success }}</p>

    <section class="goal-profile-card">
      <header>
        <span><Target :size="22" /></span>
        <div>
          <p class="eyebrow">CAREER GOALS</p>
          <h2>현재 목표와 최종 목표</h2>
          <p>
            현재 목표는 통과 문제의 실무 맥락에, 최종 목표는 선택 심화 방향에 사용됩니다.
          </p>
        </div>
      </header>

      <div class="goal-profile-form">
        <label>
          <span>현재 목표 공고</span>
          <select
            v-model="currentGoalPostingId"
            :disabled="loadingGoals || busy"
          >
            <option value="">아직 정하지 않음</option>
            <option
              v-for="posting in selectablePostings"
              :key="posting.id"
              :value="posting.id"
            >
              {{ posting.companyName || "회사 미정" }} ·
              {{ posting.roleTitle || "직무 미정" }}
            </option>
          </select>
          <small>
            분석이 완료된 활성 공고만 선택할 수 있습니다. 경력·자격 같은 실제 지원
            조건을 충족하는 공고를 선택하세요.
          </small>
        </label>

        <label>
          <span>최종 목표</span>
          <textarea
            v-model="finalGoalText"
            :disabled="loadingGoals || busy"
            maxlength="2000"
            rows="4"
            placeholder="예: 대규모 트래픽을 다루는 게임 플랫폼 백엔드 개발자"
          />
          <small>
            장기적으로 도달하고 싶은 역할이나 분야를 자유롭게 적을 수 있습니다.
          </small>
        </label>
      </div>

      <button
        class="press-button press-button--primary"
        type="button"
        :disabled="loadingGoals || busy"
        @click="saveGoals"
      >
        <Save :size="17" />
        목표 저장
      </button>
    </section>

    <section class="settings-grid">
      <article>
        <span><UserRound :size="22" /></span>
        <div>
          <small>PROFILE</small>
          <h2>{{ session.user.value?.displayName }}</h2>
          <p>{{ session.user.value?.email }}</p>
          <p>가입일 {{ session.user.value?.createdAt?.slice(0, 10) }}</p>
        </div>
      </article>
      <article>
        <span><ShieldCheck :size="22" /></span>
        <div>
          <small>DATA OWNERSHIP</small>
          <h2>사용자별 데이터 격리</h2>
          <p>
            모든 커리어 자료와 공고는 PostgreSQL RLS로 현재 계정에만 연결됩니다.
          </p>
        </div>
      </article>
      <article>
        <span><LockKeyhole :size="22" /></span>
        <div>
          <small>AI BOUNDARY</small>
          <h2>검토 후 반영</h2>
          <p>
            AI 제안은 자동 확정되지 않으며 자료 조각과 지도 변경안을 직접 승인합니다.
          </p>
        </div>
      </article>
    </section>

    <button
      class="press-button press-button--danger settings-logout"
      type="button"
      :disabled="busy"
      @click="logout"
    >
      <LogOut :size="17" />
      이 기기에서 로그아웃
    </button>
  </main>
</template>

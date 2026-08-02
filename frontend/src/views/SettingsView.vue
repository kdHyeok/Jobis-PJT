<script setup lang="ts">
import { LockKeyhole, LogOut, ShieldCheck, UserRound } from "@lucide/vue";
import { ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import { session } from "@/session";

const router = useRouter();
const error = ref("");
const busy = ref(false);

async function logout() {
  busy.value = true;
  error.value = "";
  try {
    await api.logout();
    session.clear();
    await router.push({ name: "login" });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "로그아웃하지 못했습니다.";
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
        <h1>계정과 데이터</h1>
        <p>현재 로그인 정보와 J.O.B.I.S의 데이터 처리 원칙을 확인합니다.</p>
      </div>
    </section>
    <p v-if="error" class="form-error">{{ error }}</p>
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
          <p>모든 커리어 자료와 공고는 PostgreSQL RLS로 현재 계정에만 연결됩니다.</p>
        </div>
      </article>
      <article>
        <span><LockKeyhole :size="22" /></span>
        <div>
          <small>AI BOUNDARY</small>
          <h2>검토 후 반영</h2>
          <p>AI 제안은 자동 확정되지 않으며 자료 조각과 지도 변경안을 직접 승인합니다.</p>
        </div>
      </article>
    </section>
    <button
      class="press-button press-button--danger settings-logout"
      type="button"
      :disabled="busy"
      @click="logout"
    >
      <LogOut :size="17" /> 이 기기에서 로그아웃
    </button>
  </main>
</template>

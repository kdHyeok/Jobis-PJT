<script setup lang="ts">
import { KeyRound } from "@lucide/vue";
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";

const route = useRoute();
const router = useRouter();
const token = computed(() => typeof route.query.token === "string" ? route.query.token : "");
const password = ref("");
const confirmation = ref("");
const busy = ref(false);
const error = ref("");

async function submit() {
  if (!token.value) {
    error.value = "재설정 토큰이 없습니다. 새 링크를 요청해 주세요.";
    return;
  }
  if (password.value !== confirmation.value) {
    error.value = "비밀번호 확인이 일치하지 않습니다.";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await api.confirmPasswordReset(token.value, password.value);
    await router.replace({ name: "login", query: { reset: "1" } });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "비밀번호를 재설정하지 못했습니다.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="auth-standalone-page">
    <form class="auth-card" @submit.prevent="submit">
      <span class="auth-standalone-icon"><KeyRound :size="25" /></span>
      <div><p class="eyebrow">NEW PASSWORD</p><h1>새 비밀번호 설정</h1><p>다른 서비스에서 사용하지 않는 12자 이상의 비밀번호를 입력해 주세요.</p></div>
      <label>새 비밀번호<input v-model="password" type="password" autocomplete="new-password" minlength="12" maxlength="100" required /></label>
      <label>새 비밀번호 확인<input v-model="confirmation" type="password" autocomplete="new-password" minlength="12" maxlength="100" required /></label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <button class="press-button press-button--primary" :disabled="busy || !token"><KeyRound :size="17" /> {{ busy ? '변경 중…' : '비밀번호 변경' }}</button>
      <RouterLink v-if="!token" class="text-button" to="/forgot-password">새 링크 요청하기</RouterLink>
    </form>
  </main>
</template>

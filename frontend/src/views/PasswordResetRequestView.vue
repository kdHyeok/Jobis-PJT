<script setup lang="ts">
import { ArrowLeft, Mail, Send } from "@lucide/vue";
import { ref } from "vue";

import { api } from "@/api";

const email = ref("");
const busy = ref(false);
const error = ref("");
const message = ref("");

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    const result = await api.requestPasswordReset(email.value);
    message.value = result.message;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "재설정 요청을 보내지 못했습니다.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="auth-standalone-page">
    <form class="auth-card" @submit.prevent="submit">
      <RouterLink class="back-link" to="/login"><ArrowLeft :size="16" /> 로그인으로 돌아가기</RouterLink>
      <span class="auth-standalone-icon"><Mail :size="25" /></span>
      <div><p class="eyebrow">ACCOUNT RECOVERY</p><h1>비밀번호 재설정</h1><p>가입할 때 사용한 이메일로 만료되는 재설정 링크를 보내드립니다.</p></div>
      <label>이메일<input v-model="email" type="email" autocomplete="email" required maxlength="320" /></label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <p v-if="message" class="form-success" role="status">{{ message }}</p>
      <button class="press-button press-button--primary" :disabled="busy || Boolean(message)"><Send :size="17" /> {{ busy ? '전송 중…' : '재설정 안내 보내기' }}</button>
    </form>
  </main>
</template>

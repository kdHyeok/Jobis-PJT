<script setup lang="ts">
import {
  Code2,
  Download,
  GitBranch,
  Link2,
  KeyRound,
  LockKeyhole,
  LogOut,
  Save,
  ShieldCheck,
  Target,
  Trash2,
  UserRound,
} from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { productDialog } from "@/product-dialog";
import { session } from "@/session";
import type { GoalProfile, Posting, RepositoryConnection } from "@/types";

const router = useRouter();
const route = useRoute();
const error = ref("");
const success = ref("");
const busy = ref(false);
const loadingGoals = ref(true);
const goalProfile = ref<GoalProfile | null>(null);
const postings = ref<Posting[]>([]);
const currentGoalPostingId = ref("");
const finalGoalText = ref("");
const repositoryConnections = ref<RepositoryConnection[]>([]);
const repositoryBusy = ref<"GITHUB" | "GITLAB" | "DISCONNECT" | "">("");
const profileEmail = ref(session.user.value?.email ?? "");
const profileDisplayName = ref(session.user.value?.displayName ?? "");
const currentPassword = ref("");
const newPassword = ref("");
const newPasswordConfirm = ref("");
const deletePassword = ref("");
const deleteConfirmation = ref("");
const dangerOpen = ref(false);

const selectablePostings = computed(() =>
  postings.value.filter(
    (posting) =>
      posting.analysisStatus === "SUCCEEDED" &&
      !posting.archivedAt &&
      (posting.companyName || posting.roleTitle),
  ),
);

onMounted(async () => {
  await completeRepositoryCallback();
  const results = await Promise.allSettled([
      api.goalProfile(),
      api.postings(),
      api.repositoryConnections(),
    ] as const);
  if (results[0].status === "fulfilled") {
    goalProfile.value = results[0].value;
    currentGoalPostingId.value = results[0].value.currentGoalPostingId ?? "";
    finalGoalText.value = results[0].value.finalGoalText ?? "";
  }
  if (results[1].status === "fulfilled") postings.value = results[1].value;
  if (results[2].status === "fulfilled") repositoryConnections.value = results[2].value;
  const failed = results.filter((result) => result.status === "rejected").length;
  if (failed) error.value = `설정의 일부 정보(${failed}개)를 불러오지 못했습니다.`;
  loadingGoals.value = false;
});

async function saveProfile() {
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    const user = await api.updateAccountProfile(profileEmail.value, profileDisplayName.value);
    session.setUser(user);
    success.value = "계정 정보를 저장했습니다.";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "계정 정보를 저장하지 못했습니다.";
  } finally {
    busy.value = false;
  }
}

async function changePassword() {
  if (newPassword.value !== newPasswordConfirm.value) {
    error.value = "새 비밀번호 확인이 일치하지 않습니다.";
    return;
  }
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    await api.changeAccountPassword(currentPassword.value, newPassword.value);
    currentPassword.value = "";
    newPassword.value = "";
    newPasswordConfirm.value = "";
    session.clear();
    await router.replace({ name: "login", query: { passwordChanged: "1" } });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "비밀번호를 변경하지 못했습니다.";
  } finally {
    busy.value = false;
  }
}

async function exportData() {
  busy.value = true;
  error.value = "";
  try {
    const payload = await api.exportAccountData();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `jobis-data-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "내 데이터를 내보내지 못했습니다.";
  } finally {
    busy.value = false;
  }
}

async function deleteAccount() {
  if (deleteConfirmation.value !== "JOBIS 탈퇴") return;
  busy.value = true;
  error.value = "";
  try {
    const receipt = await api.deleteAccount(deletePassword.value);
    sessionStorage.setItem("jobiss.account-deletion-receipt", JSON.stringify(receipt));
    session.clear();
    await router.replace({ name: "landing" });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "계정을 삭제하지 못했습니다.";
  } finally {
    busy.value = false;
  }
}

async function completeRepositoryCallback() {
  const state = typeof route.query.state === "string" ? route.query.state : "";
  const installationId = typeof route.query.installation_id === "string"
    ? route.query.installation_id
    : null;
  const code = typeof route.query.code === "string" ? route.query.code : null;
  if (!state || (!installationId && !code)) return;
  const provider: "GITHUB" | "GITLAB" = installationId ? "GITHUB" : "GITLAB";
  repositoryBusy.value = provider;
  try {
    await api.completeRepositoryConnection(provider, {
      state,
      code,
      installationId,
    });
    success.value = `${provider === "GITHUB" ? "GitHub" : "GitLab"} 읽기 전용 연결을 완료했습니다.`;
  } catch (cause) {
    error.value = cause instanceof Error
      ? cause.message
      : "저장소 연결을 완료하지 못했습니다.";
  } finally {
    repositoryBusy.value = "";
    await router.replace({ name: "settings" });
  }
}

function connectionFor(provider: "GITHUB" | "GITLAB") {
  return repositoryConnections.value.find((item) => item.provider === provider) ?? null;
}

async function connectRepository(provider: "GITHUB" | "GITLAB") {
  repositoryBusy.value = provider;
  error.value = "";
  try {
    const started = await api.startRepositoryConnection(provider);
    window.location.assign(started.authorizationUrl);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "저장소 연결을 시작하지 못했습니다.";
    repositoryBusy.value = "";
  }
}

async function disconnectRepository(connection: RepositoryConnection) {
  if (!await productDialog.confirm({ title: "저장소 연결 해제", message: `${connection.provider} 연결을 해제할까요? 이미 수집된 검증 스냅샷은 유지됩니다.`, confirmLabel: "연결 해제", danger: true })) {
    return;
  }
  repositoryBusy.value = "DISCONNECT";
  error.value = "";
  try {
    await api.disconnectRepository(connection.id);
    repositoryConnections.value = await api.repositoryConnections();
    success.value = "저장소 연결을 해제했습니다.";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "저장소 연결을 해제하지 못했습니다.";
  } finally {
    repositoryBusy.value = "";
  }
}

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
    <Teleport defer to="#app-topbar-center">
      <h1 class="app-page-title">계정과 커리어 목표</h1>
    </Teleport>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="success" class="form-success">{{ success }}</p>

    <section class="goal-profile-card account-profile-card">
      <header>
        <span><UserRound :size="22" /></span>
        <div><p class="eyebrow">ACCOUNT PROFILE</p><h2>계정 정보</h2><p>로그인과 알림에 사용하는 정보를 직접 관리합니다.</p></div>
      </header>
      <div class="goal-profile-form settings-two-column">
        <label><span>이름</span><input v-model="profileDisplayName" maxlength="80" autocomplete="name" /></label>
        <label><span>이메일</span><input v-model="profileEmail" type="email" maxlength="320" autocomplete="email" /></label>
      </div>
      <button class="press-button press-button--primary" type="button" :disabled="busy || !profileEmail || !profileDisplayName" @click="saveProfile"><Save :size="17" /> 계정 정보 저장</button>
    </section>

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

    <section class="repository-connections-card">
      <header>
        <span><Link2 :size="22" /></span>
        <div>
          <p class="eyebrow">REPOSITORY EVIDENCE</p>
          <h2>코드 저장소 연결</h2>
          <p>
            공개 URL 설명만 믿지 않고, 제출 시점의 실제 커밋과 선택된 코드 파일을
            읽기 전용으로 수집해 역량 근거를 검증합니다.
          </p>
        </div>
      </header>
      <div class="repository-provider-grid">
        <article v-for="provider in (['GITHUB', 'GITLAB'] as const)" :key="provider">
          <span>
            <GitBranch v-if="provider === 'GITHUB'" :size="24" />
            <Code2 v-else :size="24" />
          </span>
          <div>
            <strong>{{ provider === "GITHUB" ? "GitHub App" : "GitLab OAuth" }}</strong>
            <small v-if="connectionFor(provider)">
              {{ connectionFor(provider)?.accountName }} · 읽기 전용 연결됨
            </small>
            <small v-else>
              {{ provider === "GITHUB" ? "Contents / Metadata 읽기" : "read_api / read_repository" }}
            </small>
          </div>
          <button
            v-if="connectionFor(provider)"
            class="press-button press-button--ghost"
            type="button"
            :disabled="Boolean(repositoryBusy)"
            @click="disconnectRepository(connectionFor(provider)!)"
          >
            연결 해제
          </button>
          <button
            v-else
            class="press-button press-button--secondary"
            type="button"
            :disabled="Boolean(repositoryBusy)"
            @click="connectRepository(provider)"
          >
            {{ repositoryBusy === provider ? "연결 준비 중" : "읽기 전용 연결" }}
          </button>
        </article>
      </div>
      <small class="repository-privacy-note">
        액세스 토큰은 서버에서 AES-GCM으로 암호화하며 AI에는 전달하지 않습니다.
        AI에는 커밋 SHA와 제한된 텍스트 스냅샷만 전달됩니다.
      </small>
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

    <section class="settings-security-grid">
      <article class="settings-action-card">
        <header><span><KeyRound :size="21" /></span><div><p class="eyebrow">SECURITY</p><h2>비밀번호 변경</h2></div></header>
        <label>현재 비밀번호<input v-model="currentPassword" type="password" autocomplete="current-password" /></label>
        <label>새 비밀번호<input v-model="newPassword" type="password" minlength="12" maxlength="100" autocomplete="new-password" /></label>
        <label>새 비밀번호 확인<input v-model="newPasswordConfirm" type="password" minlength="12" maxlength="100" autocomplete="new-password" /></label>
        <button class="press-button press-button--secondary" type="button" :disabled="busy || !currentPassword || newPassword.length < 12 || !newPasswordConfirm" @click="changePassword">비밀번호 변경</button>
      </article>
      <article class="settings-action-card">
        <header><span><Download :size="21" /></span><div><p class="eyebrow">DATA EXPORT</p><h2>내 데이터 내보내기</h2></div></header>
        <p>공고, 대화, 커리어 자료와 로드맵 버전을 JSON 파일로 내려받습니다.</p>
        <button class="press-button press-button--secondary" type="button" :disabled="busy" @click="exportData"><Download :size="16" /> JSON 내려받기</button>
      </article>
    </section>

    <section class="settings-danger-zone">
      <header><span><Trash2 :size="21" /></span><div><p class="eyebrow">DANGER ZONE</p><h2>계정과 모든 데이터 삭제</h2><p>공고, 대화, 자료, 지도와 검증 기록을 영구 삭제합니다. 되돌릴 수 없습니다.</p></div></header>
      <button v-if="!dangerOpen" class="press-button press-button--danger" type="button" @click="dangerOpen = true">탈퇴 절차 열기</button>
      <div v-else class="settings-danger-confirm">
        <label>현재 비밀번호<input v-model="deletePassword" type="password" autocomplete="current-password" /></label>
        <label>확인을 위해 <strong>JOBIS 탈퇴</strong>를 입력하세요<input v-model="deleteConfirmation" /></label>
        <div><button class="press-button press-button--ghost" type="button" @click="dangerOpen = false">취소</button><button class="press-button press-button--danger" type="button" :disabled="busy || !deletePassword || deleteConfirmation !== 'JOBIS 탈퇴'" @click="deleteAccount">영구 삭제</button></div>
      </div>
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

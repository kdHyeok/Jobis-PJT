<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ArrowRight, BriefcaseBusiness, Check, GitBranch, MessageCircle, ShieldCheck, Sparkles, X } from "@lucide/vue";

import { session } from "@/session";

type DeletionReceipt = { status: string; purgeAfter: string };
const deletionReceipt = ref<DeletionReceipt | null>(null);

onMounted(() => {
  const stored = sessionStorage.getItem("jobiss.account-deletion-receipt");
  if (!stored) return;
  try {
    deletionReceipt.value = JSON.parse(stored) as DeletionReceipt;
  } catch {
    sessionStorage.removeItem("jobiss.account-deletion-receipt");
  }
});

function dismissDeletionReceipt() {
  deletionReceipt.value = null;
  sessionStorage.removeItem("jobiss.account-deletion-receipt");
}
</script>

<template>
  <main class="landing-page">
    <header class="landing-header">
      <RouterLink class="brand brand--large" to="/">
        <span class="brand-mark">J</span>
        <span>JOBIS</span>
      </RouterLink>
      <RouterLink class="press-button press-button--primary" :to="session.authenticated.value ? '/app' : '/login'">
        {{ session.authenticated.value ? '내 지도 계속하기' : '시작하기' }} <ArrowRight :size="18" />
      </RouterLink>
    </header>

    <section v-if="deletionReceipt" class="landing-deletion-receipt" role="status">
      <ShieldCheck :size="22" />
      <div>
        <strong>계정 탈퇴 요청이 접수됐습니다</strong>
        <p>로그인과 데이터 접근은 즉시 차단됐고, 운영 DB 삭제 작업은 {{ new Date(deletionReceipt.purgeAfter).toLocaleString('ko-KR') }} 이후 처리됩니다.</p>
      </div>
      <button type="button" aria-label="탈퇴 처리 안내 닫기" @click="dismissDeletionReceipt"><X :size="17" /></button>
    </section>

    <section class="landing-hero">
      <p class="eyebrow">ONE CAREER GRAPH, MANY OPPORTUNITIES</p>
      <h1>공고마다 다시 시작하지 않는 <span>나만의 커리어 지도</span></h1>
      <p>
        AI와 대화하며 목표를 찾고, 공고를 분석하고, 실제 증거로 단계를 완료하세요.
        이미 쌓은 역량은 다음 기회에서도 그대로 이어집니다.
      </p>
      <div class="landing-actions">
        <RouterLink class="press-button press-button--primary" :to="session.authenticated.value ? '/app' : '/login'">
          {{ session.authenticated.value ? '내 여정으로 돌아가기' : '무료로 시작하기' }} <ArrowRight :size="18" />
        </RouterLink>
        <a class="press-button" href="#how">어떻게 작동하나요?</a>
      </div>
    </section>

    <section class="landing-product-preview" aria-label="JOBIS 통합 커리어 지도 예시">
      <div class="landing-preview-copy">
        <p class="eyebrow">ONE MAP, GROWING WITH YOU</p>
        <h2>회사가 늘어도 준비는 하나로 이어집니다</h2>
        <p>공통 역량은 한 번만 학습하고, 회사마다 달라지는 기술과 프로젝트만 분기해 준비합니다.</p>
      </div>
      <div class="landing-map-demo" aria-hidden="true">
        <div class="landing-demo-node completed"><Check :size="18" /><span>프로그래밍 기초</span></div>
        <i class="landing-demo-line" />
        <div class="landing-demo-node completed"><Check :size="18" /><span>Java · Spring</span></div>
        <i class="landing-demo-line" />
        <div class="landing-demo-branches">
          <div><span class="landing-demo-node active"><Sparkles :size="18" />Kafka</span><b>이스트게임즈</b></div>
          <div><span class="landing-demo-node">GitBranch</span><b>네이버 · 경력 2년</b></div>
        </div>
      </div>
    </section>

    <section id="how" class="landing-features">
      <article>
        <MessageCircle :size="28" />
        <h2>대화로 시작</h2>
        <p>공고가 없어도 현재 상황과 목표부터 자유롭게 이야기합니다.</p>
      </article>
      <article>
        <BriefcaseBusiness :size="28" />
        <h2>공고 요건 분리</h2>
        <p>필수와 우대, 경력 조건을 구분해 현재 역량과 비교합니다.</p>
      </article>
      <article>
        <GitBranch :size="28" />
        <h2>하나의 누적 지도</h2>
        <p>여러 회사의 공통 경로와 갈라지는 조건을 한눈에 비교합니다.</p>
      </article>
      <article>
        <ShieldCheck :size="28" />
        <h2>증거로 완료</h2>
        <p>전문 단계는 코드·프로젝트·자격 증거를 검증한 뒤 완료됩니다.</p>
      </article>
    </section>

    <section class="landing-trust">
      <div id="privacy">
        <ShieldCheck :size="24" />
        <h2>내 데이터는 내가 결정합니다</h2>
        <p>커리어 자료와 공고는 계정별로 격리되며, 원본과 계정은 설정에서 내보내거나 삭제할 수 있습니다.</p>
      </div>
      <div id="terms">
        <MessageCircle :size="24" />
        <h2>AI 제안은 검토 후 반영됩니다</h2>
        <p>JOBIS는 AI의 분석을 자동 확정하지 않습니다. 저장할 조각과 지도 변경안을 사용자가 직접 승인합니다.</p>
      </div>
    </section>

    <footer class="landing-footer">
      <strong>JOBIS</strong>
      <span>개발자 취업 준비를 하나의 성장 경로로 연결합니다.</span>
      <RouterLink to="/terms">이용약관</RouterLink>
      <RouterLink to="/privacy">개인정보 처리 안내</RouterLink>
      <a href="mailto:support@jobis.local">문의</a>
    </footer>
  </main>
</template>

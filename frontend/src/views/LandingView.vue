<script setup lang="ts">
import { ArrowRight, GitBranch, MessageCircle, ShieldCheck } from "@lucide/vue";
</script>

<template>
  <main class="landing-page">
    <header class="landing-header">
      <RouterLink class="brand brand--large" to="/">
        <span class="brand-mark">J</span>
        <span>J.O.B.I.S</span>
      </RouterLink>
      <RouterLink class="press-button press-button--primary" to="/login">
        시작하기 <ArrowRight :size="18" />
      </RouterLink>
    </header>

    <section class="landing-hero">
      <p class="eyebrow">ONE CAREER GRAPH, MANY OPPORTUNITIES</p>
      <h1>공고마다 다시 시작하지 않는<br />나만의 커리어 지도</h1>
      <p>
        AI와 대화하며 목표를 찾고, 공고를 분석하고, 실제 증거로 단계를 완료하세요.
        이미 쌓은 역량은 다음 기회에서도 그대로 이어집니다.
      </p>
      <div class="landing-actions">
        <RouterLink class="press-button press-button--primary" to="/login">
          무료로 시작하기 <ArrowRight :size="18" />
        </RouterLink>
        <a class="press-button" href="#how">어떻게 작동하나요?</a>
      </div>
    </section>

    <section id="how" class="landing-features">
      <article>
        <MessageCircle :size="28" />
        <h2>대화로 시작</h2>
        <p>공고가 없어도 현재 상황과 목표부터 자유롭게 이야기합니다.</p>
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
  </main>
</template>

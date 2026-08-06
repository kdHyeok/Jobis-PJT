<script setup lang="ts">
import { ArrowLeft, ShieldCheck } from "@lucide/vue";
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const privacy = computed(() => route.name === "privacy");
</script>

<template>
  <main class="policy-page">
    <header>
      <RouterLink class="brand" to="/"><span class="brand-mark">J</span><span>JOBIS</span></RouterLink>
      <RouterLink class="back-link" to="/login"><ArrowLeft :size="16" /> 로그인으로 돌아가기</RouterLink>
    </header>

    <article v-if="privacy">
      <p class="eyebrow">PRIVACY NOTICE</p>
      <h1>개인정보 처리 안내</h1>
      <p class="policy-version">시행일 2026년 8월 4일 · 버전 2026-08-04</p>
      <section>
        <h2>수집하는 정보</h2>
        <p>계정 이메일과 이름, 사용자가 등록한 이력서·프로젝트 경험·채용 공고·대화·증빙 자료를 서비스 제공을 위해 처리합니다. GitHub·GitLab을 연결하면 계정 식별자, 허용 범위와 검증에 선택된 저장소 스냅샷을 처리합니다.</p>
      </section>
      <section>
        <h2>이용 목적과 AI 처리</h2>
        <p>공고 요건 구조화, 커리어 자료 정리, 역량 비교, 로드맵과 검증 문제 제공에 사용합니다. AI가 만든 제안은 자동 확정하지 않으며 사용자가 저장·반영 여부를 검토합니다.</p>
      </section>
      <section>
        <h2>보관과 삭제</h2>
        <p>계정이 유지되는 동안 데이터를 보관하며, 설정에서 원본 자료·공고·대화·계정을 직접 삭제할 수 있습니다. 계정 삭제 시 법령상 별도 보관 의무가 없는 계정별 데이터는 함께 삭제됩니다.</p>
      </section>
      <section>
        <h2>접근 권한과 보호</h2>
        <p>계정별 데이터는 PostgreSQL 행 수준 보안으로 격리합니다. 저장소 연결 토큰은 서버에서 암호화하고 AI에는 전달하지 않으며, 연결은 읽기 전용 권한을 사용합니다.</p>
      </section>
      <section>
        <h2>사용자의 권리와 문의</h2>
        <p>설정에서 데이터 내보내기, 계정 정보 변경, 연결 해제와 탈퇴를 할 수 있습니다. 개인정보 관련 요청은 <a href="mailto:support@jobis.local">support@jobis.local</a>로 접수할 수 있습니다.</p>
      </section>
    </article>

    <article v-else>
      <p class="eyebrow">TERMS OF SERVICE</p>
      <h1>이용약관</h1>
      <p class="policy-version">시행일 2026년 8월 4일 · 버전 2026-08-04</p>
      <section>
        <h2>서비스의 역할</h2>
        <p>JOBIS는 사용자의 자료와 채용 공고를 바탕으로 취업 준비 경로를 정리하는 보조 서비스입니다. 채용 합격, 정보의 완전성 또는 특정 학습 결과를 보장하지 않습니다.</p>
      </section>
      <section>
        <h2>계정과 자료</h2>
        <p>사용자는 정확한 계정 정보를 제공하고 계정 접근 정보를 안전하게 관리해야 합니다. 등록하는 공고와 커리어 자료에 대한 이용 권한을 보유해야 하며, 불필요한 타인의 개인정보나 비밀정보를 입력해서는 안 됩니다.</p>
      </section>
      <section>
        <h2>AI 결과와 사용자 확인</h2>
        <p>AI 분석은 오류나 누락을 포함할 수 있습니다. 공고 분석, 준비도 판정, 로드맵과 역량 검증 결과는 참고 자료이며 실제 지원 전 원문과 자신의 상황을 확인해야 합니다.</p>
      </section>
      <section>
        <h2>금지 행위</h2>
        <p>타인의 계정 사용, 서비스 방해, 접근 권한 우회, 악성 코드나 불법 자료 등록, 자동 수집 정책을 우회하는 행위를 금지합니다.</p>
      </section>
      <section>
        <h2>변경과 문의</h2>
        <p>중요한 정책 변경은 적용 전에 서비스 화면으로 알리고 새 버전을 표시합니다. 문의는 <a href="mailto:support@jobis.local">support@jobis.local</a>로 접수할 수 있습니다.</p>
      </section>
    </article>

    <aside>
      <ShieldCheck :size="20" />
      <p>이 문서는 현재 서비스 구현과 데이터 흐름을 설명하는 운영 초안입니다. 실제 외부 출시 전 관할 법률과 운영 주체 정보에 맞춘 법률 검토가 필요합니다.</p>
    </aside>
  </main>
</template>

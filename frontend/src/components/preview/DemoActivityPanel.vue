<script setup lang="ts">
import { Bell, CheckCircle2, FileCheck2, Map, MessageCircle, Sparkles, Trophy } from "@lucide/vue";
import ContributionHeatmap from "@/components/roadmap/ContributionHeatmap.vue";

const activities = [
  { time:"오늘 20:14", title:"SQL 과제 1개를 완료했어요", body:"JOIN 실전 문제 3개 · +12 XP", icon:CheckCircle2, tone:"green" },
  { time:"오늘 18:42", title:"AI가 새 로드맵 경로를 제안했어요", body:"금융 API 미니 프로젝트를 먼저 진행하면 적합도 +8점", icon:Sparkles, tone:"purple" },
  { time:"오늘 10:24", title:"광주은행 공고 분석이 완료됐어요", body:"현재 적합도 64점 · 보완 역량 3개", icon:FileCheck2, tone:"blue" },
  { time:"어제 21:05", title:"9일 연속 준비 기록을 달성했어요", body:"이번 주 활동 8개 · 누적 1,280 XP", icon:Trophy, tone:"yellow" },
  { time:"7월 29일", title:"커리어 로드맵이 업데이트됐어요", body:"새 경험 2개가 검증되어 프로젝트 단계가 열렸어요.", icon:Map, tone:"green" },
];
</script>

<template>
  <div class="activity-preview">
    <header class="activity-heading"><div><h1>활동 기록</h1><p>준비해온 과정과 AI의 변경 내역을 한곳에서 확인해요.</p></div><button type="button"><Bell :size="15" /> 모두 읽음</button></header>
    <div class="activity-grid">
      <section class="activity-main">
        <ContributionHeatmap :completed-today="2" />
        <section class="timeline">
          <header><div><h2>최근 활동</h2></div><button type="button">전체</button></header>
          <article v-for="item in activities" :key="item.title"><span :class="item.tone"><component :is="item.icon" :size="18" /></span><div><small>{{ item.time }}</small><strong>{{ item.title }}</strong><p>{{ item.body }}</p></div><i /></article>
        </section>
      </section>
      <aside>
        <section class="weekly"><h2>이번 주 요약</h2><div><p><small>완료한 활동</small><strong>8</strong></p><p><small>획득 XP</small><strong>+96</strong></p></div><ul><li><span>로드맵 과제</span><b>4/5</b><i style="width:80%"/></li><li><span>공고 분석</span><b>2/3</b><i style="width:67%"/></li><li><span>경험 정리</span><b>2/4</b><i style="width:50%"/></li></ul></section>
        <section class="achievement"><Trophy :size="32" /><h3>꾸준한 탐험가</h3><p>7일 이상 연속으로 취업 준비를 기록했어요.</p><strong>+50 XP</strong></section>
        <section class="ai-history"><MessageCircle :size="19" /><div><small>AI 변경 기록</small><strong>로드맵이 3번 조정됐어요</strong></div></section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.activity-preview{display:grid;gap:16px}.activity-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:15px}.activity-heading span,.timeline header span,.weekly>span{color:#328f69;font-size:9px;font-weight:900;letter-spacing:.12em}.activity-heading h1{margin:6px 0 4px;font-size:29px}.activity-heading p{margin:0;color:#7f8f88;font-size:10px}.activity-heading>button{display:flex;align-items:center;gap:6px;padding:9px 11px;border:1px solid #d9e3de;border-radius:11px;color:#64766e;background:#fff;font-size:8px;font-weight:900}.activity-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;align-items:start;gap:15px}.activity-main,.activity-grid aside{display:grid;gap:14px}.timeline,.weekly,.achievement,.ai-history{padding:20px;border:1px solid #dce6e1;border-radius:22px;background:#fff}.timeline header{display:flex;align-items:center;justify-content:space-between;margin-bottom:13px}.timeline h2,.weekly h2{margin:4px 0 0;font-size:16px}.timeline header button{padding:6px 9px;border:0;border-radius:9px;color:#318f69;background:#edf8f1;font-size:8px;font-weight:900}.timeline article{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:11px;padding:13px 0;border-top:1px solid #e7ece9}.timeline article>span{display:grid;width:39px;height:39px;place-items:center;border-radius:13px}.green{color:#2c9850;background:#e5f6e9}.purple{color:#7357ce;background:#f0ebff}.blue{color:#178ac1;background:#e4f5fd}.yellow{color:#a8790c;background:#fff2d0}.timeline small,.timeline strong,.timeline p{display:block}.timeline small{color:#98a39e;font-size:7px}.timeline strong{margin:3px 0;font-size:9px}.timeline p{margin:0;color:#82918a;font-size:8px}.timeline article>i{width:7px;height:7px;border-radius:50%;background:#58cc78}
.weekly h2{margin-bottom:14px}.weekly>div{display:grid;grid-template-columns:1fr 1fr;gap:7px}.weekly>div p{margin:0;padding:11px;border-radius:12px;background:#f4f8f6}.weekly small,.weekly strong{display:block}.weekly small{color:#87968f;font-size:7px}.weekly strong{margin-top:3px;font-size:17px}.weekly ul{display:grid;gap:10px;margin:14px 0 0;padding:0;list-style:none}.weekly li{position:relative;display:grid;grid-template-columns:1fr auto;gap:3px;padding-bottom:8px}.weekly li::after{content:"";position:absolute;right:0;bottom:0;left:0;height:5px;border-radius:99px;background:#edf2ef}.weekly li>i{position:absolute;z-index:1;bottom:0;left:0;height:5px;border-radius:99px;background:#58cc78}.weekly li span,.weekly li b{font-size:8px}.achievement{text-align:center;background:radial-gradient(circle at 50% 0,rgba(255,206,69,.22),transparent 38%),#fffdf8}.achievement>svg{color:#e4af18}.achievement small{display:block;margin-top:7px;color:#a97b10;font-size:7px;font-weight:900}.achievement h3{margin:5px 0;font-size:14px}.achievement p{margin:0;color:#837961;font-size:8px}.achievement>strong{display:inline-block;margin-top:9px;padding:6px 8px;border-radius:9px;color:#9b7010;background:#fff0be;font-size:8px}.ai-history{display:flex;align-items:center;gap:10px;color:#7357ce;background:#faf8ff}.ai-history div{display:grid;gap:3px}.ai-history small{font-size:7px}.ai-history strong{font-size:9px}
@media(max-width:900px){.activity-grid{grid-template-columns:1fr}.activity-grid aside{grid-template-columns:repeat(2,1fr)}.ai-history{grid-column:1/-1}}@media(max-width:560px){.activity-heading{align-items:flex-start;flex-direction:column}.activity-grid aside{grid-template-columns:1fr}.ai-history{grid-column:auto}}
</style>

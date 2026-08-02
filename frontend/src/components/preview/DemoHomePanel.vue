<script setup lang="ts">
import {
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  Clock3,
  MessageCircle,
  Sparkles,
  Target,
  TrendingUp,
} from "@lucide/vue";

defineEmits<{
  navigate: [page: "chat" | "postings" | "roadmap"];
}>();
</script>

<template>
  <div class="preview-page home-preview">
    <section class="home-welcome">
      <div>
        <span class="icon-label" aria-label="오늘의 홈"><Sparkles :size="22" /></span>
        <h1>박준영님,<br />오늘도 합격에 한 칸 가까워져요.</h1>
        <p>광주은행 디지털·IT 지원까지 42일 남았습니다.</p>
        <button type="button" @click="$emit('navigate', 'roadmap')">
          오늘 준비 이어가기 <ArrowRight :size="16" />
        </button>
      </div>
      <div class="readiness-orbit">
        <span class="mascot-glow" aria-hidden="true" />
        <img src="/img/jobi-mascot.png" alt="J.O.B.I.S 펭귄 커리어 도우미 자비" />
        <span class="readiness-score"><small>공고 적합도</small><strong>64</strong><em>이번 주 +2</em></span>
      </div>
    </section>

    <section class="home-summary">
      <article v-for="item in [
        { label: '진행 중 로드맵', value: '1개', note: '25% 완료', icon: Target, tone: 'mint' },
        { label: '분석한 공고', value: '6개', note: '이번 주 +2', icon: BriefcaseBusiness, tone: 'blue' },
        { label: '등록한 경험', value: '14개', note: '검증 완료 9개', icon: CheckCircle2, tone: 'yellow' },
        { label: '이번 주 활동', value: '8개', note: '9일 연속', icon: TrendingUp, tone: 'purple' },
      ]" :key="item.label">
        <span :class="item.tone"><component :is="item.icon" :size="19" /></span>
        <p><small>{{ item.label }}</small><strong>{{ item.value }}</strong></p>
        <em>{{ item.note }}</em>
      </article>
    </section>

    <div class="home-columns">
      <section class="home-card next-action">
        <header><div><span aria-hidden="true"><Target :size="20" /></span><h2>지금 하면 가장 효과적인 일</h2></div><small>약 35분</small></header>
        <article>
          <i>1</i>
          <div><strong>JOIN 실전 문제 3개 풀기</strong><p>SQL 실전 역량을 증명하기 위한 핵심 과제예요.</p><span><Clock3 :size="12" /> 35분 · +12 XP</span></div>
          <button type="button" @click="$emit('navigate', 'roadmap')">시작</button>
        </article>
        <article class="done">
          <i><CheckCircle2 :size="15" /></i>
          <div><strong>채용공고 핵심 요구사항 확인</strong><p>오늘 오전 10:24 완료</p></div>
          <em>+8 XP</em>
        </article>
      </section>

      <section class="home-card recent-postings">
        <header><div><span aria-hidden="true"><BriefcaseBusiness :size="20" /></span><h2>최근 분석한 공고</h2></div><button type="button" @click="$emit('navigate', 'postings')">전체 보기</button></header>
        <article v-for="item in [
          { mark:'광', company:'광주은행', role:'디지털·IT 직무', score:64, tone:'sky' },
          { mark:'신', company:'신한은행', role:'ICT 개발 직무', score:58, tone:'navy' },
          { mark:'N', company:'NH농협은행', role:'IT 일반 직무', score:51, tone:'green' },
        ]" :key="item.company">
          <i :class="item.tone">{{ item.mark }}</i><div><strong>{{ item.company }}</strong><p>{{ item.role }}</p></div><span class="score">{{ item.score }}점</span>
        </article>
      </section>
    </div>

    <section class="ai-callout">
      <span><MessageCircle :size="21" /></span>
      <div><strong>공고에 맞춘 준비 순서를 다시 확인해볼까요?</strong><p>새 경험을 반영하면 로드맵을 더 현실적으로 조정할 수 있어요.</p></div>
      <button type="button" @click="$emit('navigate', 'chat')">AI와 대화하기 <ArrowRight :size="15" /></button>
    </section>
  </div>
</template>

<style scoped>
.preview-page{display:grid;gap:18px}.home-welcome{display:grid;grid-template-columns:minmax(0,1fr) 250px;align-items:center;gap:20px;min-height:255px;padding:34px;border:1px solid #cee4da;border-radius:28px;background:radial-gradient(circle at 85% 10%,rgba(28,176,246,.2),transparent 30%),radial-gradient(circle at 10% 100%,rgba(88,204,120,.18),transparent 36%),#fff}.home-welcome>div>span,.home-card header span{color:#2b946b;font-size:9px;font-weight:900;letter-spacing:.12em}.home-welcome>div>span{display:inline-flex;align-items:center;gap:6px}.home-welcome h1{margin:12px 0 9px;font-size:clamp(30px,4vw,46px);line-height:1.1;letter-spacing:-.06em}.home-welcome p{margin:0;color:#788a82;font-size:11px}.home-welcome button,.ai-callout button{display:inline-flex;align-items:center;justify-content:center;gap:7px;margin-top:20px;padding:12px 15px;border:0;border-bottom:4px solid #17984f;border-radius:13px;color:#fff;background:#58cc78;cursor:pointer;font-size:10px;font-weight:900}
.readiness-orbit{position:relative;display:grid;width:185px;aspect-ratio:1;place-items:center;margin:auto;border:2px dashed #9fddc1;border-radius:50%}.readiness-orbit::before{content:"";position:absolute;inset:15px;border:1px solid #d1e9df;border-radius:50%}.readiness-orbit>i{position:absolute;top:7px;right:26px;width:14px;height:14px;border-radius:50%;background:#1cb0f6;box-shadow:0 0 0 7px rgba(28,176,246,.12)}.readiness-orbit>span{z-index:1;display:grid;width:124px;aspect-ratio:1;place-content:center;border-radius:50%;color:#fff;background:linear-gradient(145deg,#59cc79,#27a95a);text-align:center}.readiness-orbit small,.readiness-orbit strong,.readiness-orbit em{display:block}.readiness-orbit small{font-size:8px}.readiness-orbit strong{font-size:38px}.readiness-orbit em{font-size:8px;font-style:normal}
.home-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.home-summary article{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:11px;padding:16px;border:1px solid #dce6e1;border-radius:18px;background:#fff}.home-summary article>span{display:grid;width:40px;height:40px;place-items:center;border-radius:13px}.mint{color:#2b9850;background:#e6f7eb}.blue{color:#188bc1;background:#e5f5fd}.yellow{color:#a8790d;background:#fff3d4}.purple{color:#7458cf;background:#f0ebff}.home-summary p{margin:0}.home-summary small,.home-summary strong{display:block}.home-summary small{color:#88978f;font-size:8px}.home-summary strong{margin-top:3px;font-size:16px}.home-summary em{grid-column:2;color:#4b9d68;font-size:8px;font-style:normal;font-weight:850}
.home-columns{display:grid;grid-template-columns:1.15fr .85fr;gap:16px}.home-card{padding:21px;border:1px solid #dce6e1;border-radius:22px;background:#fff}.home-card header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:15px}.home-card h2{margin:5px 0 0;font-size:16px}.home-card header small{padding:6px 8px;border-radius:9px;color:#147ea9;background:#e6f7ff;font-size:8px;font-weight:900}.home-card header button{border:0;color:#278d61;background:transparent;cursor:pointer;font-size:8px;font-weight:900}.home-card article{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:11px;padding:13px;border:1px solid #e1e8e4;border-radius:15px}.home-card article+article{margin-top:8px}.home-card article>i{display:grid;width:36px;height:36px;place-items:center;border-radius:12px;color:#fff;background:#1cb0f6;font-style:normal;font-size:11px;font-weight:900}.home-card strong{display:block;font-size:10px}.home-card p{margin:3px 0;color:#84928d;font-size:8px}.next-action div span{display:flex;align-items:center;gap:4px;color:#9a702a;font-size:8px;font-weight:850}.next-action article>button{padding:7px 9px;border:0;border-radius:9px;color:#fff;background:#1cb0f6;cursor:pointer;font-size:8px;font-weight:900}.next-action article.done{background:#f6fbf7}.next-action article.done>i{background:#58cc78}.next-action article>em{color:#3e9d5c;font-size:8px;font-style:normal}.recent-postings article>i.navy{background:#44547d}.recent-postings article>i.green{background:#238a52}.score{padding:6px 8px;border-radius:9px;color:#248849;background:#e3f5e8;font-size:8px;font-weight:900}
.ai-callout{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:13px;padding:20px 23px;border:1px solid #d7cdf6;border-radius:22px;background:linear-gradient(135deg,#fbf9ff,#f5f1ff)}.ai-callout>span{display:grid;width:43px;height:43px;place-items:center;border-radius:14px;color:#fff;background:#8263e3}.ai-callout small,.ai-callout strong{display:block}.ai-callout small{color:#8066ca;font-size:8px;font-weight:900}.ai-callout strong{margin-top:4px;font-size:12px}.ai-callout p{margin:3px 0 0;color:#817692;font-size:8px}.ai-callout button{margin:0;border-bottom-color:#5d42b7;background:#8263e3}
@media(max-width:980px){.home-summary{grid-template-columns:repeat(2,1fr)}.home-columns{grid-template-columns:1fr}.ai-callout{grid-template-columns:auto 1fr}.ai-callout button{grid-column:1/-1}}@media(max-width:640px){.home-welcome{grid-template-columns:1fr;padding:24px}.readiness-orbit{display:none}.home-summary{grid-template-columns:1fr}.ai-callout{grid-template-columns:1fr}.ai-callout>span{display:none}}

/* JOBI character treatment */
.readiness-orbit{width:245px;border:0;border-radius:0}
.readiness-orbit::before{inset:30px 6px 12px;border:1px solid #bdd5ff;border-radius:44% 56% 50% 50%;background:radial-gradient(circle,#fff 0,#edf5ff 66%,transparent 67%)}
.readiness-orbit>img{position:relative;z-index:2;width:190px;filter:drop-shadow(0 16px 16px rgba(22,79,184,.2))}
.readiness-orbit>.mascot-glow{position:absolute;inset:25px 8px 2px;width:auto;aspect-ratio:auto;place-content:normal;border-radius:50%;background-image:linear-gradient(rgba(29,91,213,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(29,91,213,.08) 1px,transparent 1px);background-size:18px 18px}
.readiness-orbit>.readiness-score{position:absolute;z-index:3;right:-4px;bottom:16px;display:grid;width:90px;aspect-ratio:1;place-content:center;border:3px solid #fff;border-radius:25px;color:#0c2f79;background:linear-gradient(145deg,#fff8d8,#ffd335);box-shadow:0 10px 24px rgba(18,72,174,.2);text-align:center;transform:rotate(3deg)}
.readiness-orbit .readiness-score small{font-size:9px}.readiness-orbit .readiness-score strong{font-size:29px;line-height:1}.readiness-orbit .readiness-score em{margin-top:4px;font-size:8px}
</style>

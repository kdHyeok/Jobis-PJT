<script setup lang="ts">
import { Archive, Building2, CalendarDays, Plus, Search, SlidersHorizontal, Sparkles } from "@lucide/vue";
import { computed, ref } from "vue";

const query = ref("");
const selected = ref("gwangju");
const postings = [
  { id:"gwangju", company:"광주은행", role:"디지털·IT 직무", deadline:"D-42", score:64, status:"분석 완료", color:"#4c8fcb", requirements:["Java·Spring","SQL","금융 서비스 이해"] },
  { id:"shinhan", company:"신한은행", role:"ICT 개발 직무", deadline:"D-38", score:58, status:"분석 완료", color:"#44547d", requirements:["Java","클라우드","협업 경험"] },
  { id:"nh", company:"NH농협은행", role:"IT 일반 직무", deadline:"D-29", score:51, status:"보완 필요", color:"#268653", requirements:["정보처리기사","SQL","프로젝트"] },
  { id:"kakao", company:"카카오뱅크", role:"서버 개발자", deadline:"상시", score:46, status:"분석 중", color:"#e7b928", requirements:["Kotlin","MSA","대용량 트래픽"] },
];
const filtered = computed(()=>postings.filter(item=>`${item.company} ${item.role}`.includes(query.value)));
const current = computed(()=>postings.find(item=>item.id===selected.value) ?? postings[0]);
</script>

<template>
  <div class="postings-preview">
    <header class="page-heading"><div><h1>채용 공고</h1><p>공고를 모을수록 나에게 맞는 준비 경로가 더 정확해져요.</p></div><button type="button"><Plus :size="16" /> 새 공고 분석</button></header>
    <section class="posting-toolbar"><label><Search :size="16" /><input v-model="query" placeholder="기업명 또는 직무 검색" /></label><button type="button"><SlidersHorizontal :size="15" /> 필터</button><button type="button"><Archive :size="15" /> 보관함</button></section>
    <div class="posting-layout">
      <section class="posting-list">
        <button v-for="posting in filtered" :key="posting.id" type="button" :class="{active:selected===posting.id}" @click="selected=posting.id">
          <i :style="{background:posting.color}">{{ posting.company.slice(0,1) }}</i>
          <span><small>{{ posting.status }}</small><strong>{{ posting.company }}</strong><p>{{ posting.role }}</p><em><CalendarDays :size="11" /> {{ posting.deadline }}</em></span>
          <b :class="{high:posting.score>=60}">{{ posting.score }}점</b>
        </button>
      </section>
      <section class="posting-detail">
        <header><i :style="{background:current.color}"><Building2 :size="22" /></i><div><h2>{{ current.company }}</h2><p>{{ current.role }}</p></div><span>{{ current.deadline }}</span></header>
        <div class="fit-score"><span><Sparkles :size="17" /></span><div><small>현재 공고 적합도</small><strong>{{ current.score }}점</strong></div><p>프로젝트 경험은 강점이지만<br />SQL 실전 근거를 보완하면 좋아요.</p></div>
        <section><h3>공고 핵심 요구사항</h3><ul><li v-for="(item,index) in current.requirements" :key="item"><i :class="{done:index===0}">{{ index===0 ? "✓" : index+1 }}</i><span><strong>{{ item }}</strong><small>{{ index===0 ? "등록된 경험에서 근거를 찾았어요." : "보완 로드맵에 반영됐어요." }}</small></span></li></ul></section>
        <footer><button type="button">AI에게 물어보기</button><button class="primary" type="button">맞춤 로드맵 보기</button></footer>
      </section>
    </div>
  </div>
</template>

<style scoped>
.postings-preview{display:grid;gap:15px}.page-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:18px}.page-heading span{color:#318f69;font-size:9px;font-weight:900;letter-spacing:.12em}.page-heading h1{margin:6px 0 4px;font-size:29px}.page-heading p{margin:0;color:#7f8f88;font-size:10px}.page-heading>button{display:flex;align-items:center;gap:6px;padding:11px 13px;border:0;border-bottom:4px solid #19994f;border-radius:12px;color:#fff;background:#58cc78;font-size:9px;font-weight:900}.posting-toolbar{display:flex;gap:8px;padding:12px;border:1px solid #dce6e1;border-radius:17px;background:#fff}.posting-toolbar label{display:flex;min-width:0;flex:1;align-items:center;gap:8px;padding:0 10px;color:#8a9992;background:#f4f7f5;border-radius:11px}.posting-toolbar input{width:100%;padding:10px 0;border:0;outline:0;background:transparent;font:inherit;font-size:9px}.posting-toolbar button{display:flex;align-items:center;gap:5px;padding:9px 11px;border:1px solid #dce5e1;border-radius:11px;color:#64766e;background:#fff;font-size:8px;font-weight:850}
.posting-layout{display:grid;grid-template-columns:360px minmax(0,1fr);gap:14px}.posting-list{display:grid;align-content:start;gap:8px}.posting-list>button{display:grid;width:100%;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:11px;padding:14px;border:1px solid #dce6e1;border-radius:17px;color:#40534b;background:#fff;text-align:left}.posting-list>button.active{border-color:#77d398;outline:3px solid rgba(88,204,120,.1)}.posting-list>button>i{display:grid;width:42px;height:42px;place-items:center;border-radius:13px;color:#fff;font-style:normal;font-size:13px;font-weight:900}.posting-list small,.posting-list strong,.posting-list p,.posting-list em{display:block}.posting-list small{color:#3b9863;font-size:7px;font-weight:900}.posting-list strong{margin-top:3px;font-size:11px}.posting-list p{margin:2px 0;color:#819089;font-size:8px}.posting-list em{display:flex;align-items:center;gap:3px;color:#9a7630;font-size:7px;font-style:normal}.posting-list b{padding:7px;border-radius:9px;color:#916d22;background:#fff3d5;font-size:8px}.posting-list b.high{color:#248849;background:#e3f5e8}
.posting-detail{padding:23px;border:1px solid #dce6e1;border-radius:22px;background:#fff}.posting-detail>header{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:12px;padding-bottom:18px;border-bottom:1px solid #e5ebe8}.posting-detail>header>i{display:grid;width:51px;height:51px;place-items:center;border-radius:16px;color:#fff}.posting-detail header small{color:#399268;font-size:7px;font-weight:900}.posting-detail h2{margin:4px 0 2px;font-size:19px}.posting-detail header p{margin:0;color:#819089;font-size:9px}.posting-detail header>span{padding:7px 9px;border-radius:10px;color:#a05d26;background:#fff0df;font-size:8px;font-weight:900}.fit-score{display:grid;grid-template-columns:auto auto minmax(0,1fr);align-items:center;gap:10px;margin:17px 0;padding:16px;border-radius:16px;background:linear-gradient(135deg,#f0fbf4,#eef9ff)}.fit-score>span{display:grid;width:38px;height:38px;place-items:center;border-radius:12px;color:#fff;background:#58cc78}.fit-score small,.fit-score strong{display:block}.fit-score small{font-size:7px}.fit-score strong{font-size:20px;color:#268a4e}.fit-score p{margin-left:auto;color:#70847a;font-size:8px;text-align:right}.posting-detail>section{padding:16px;border:1px solid #e2e8e5;border-radius:16px}.posting-detail h3{margin:0 0 12px;font-size:12px}.posting-detail ul{display:grid;gap:9px;margin:0;padding:0;list-style:none}.posting-detail li{display:flex;align-items:center;gap:9px}.posting-detail li>i{display:grid;width:25px;height:25px;place-items:center;border-radius:9px;background:#edf1ef;font-style:normal;font-size:8px}.posting-detail li>i.done{color:#fff;background:#58cc78}.posting-detail li strong,.posting-detail li small{display:block}.posting-detail li strong{font-size:9px}.posting-detail li small{font-size:7px;color:#8b9792}.posting-detail footer{display:flex;justify-content:flex-end;gap:8px;margin-top:17px}.posting-detail footer button{padding:10px 12px;border:1px solid #d8e2dd;border-radius:11px;background:#fff;font-size:8px;font-weight:900}.posting-detail footer button.primary{border:0;border-bottom:4px solid #178f49;color:#fff;background:#58cc78}
@media(max-width:900px){.posting-layout{grid-template-columns:1fr}.posting-list{grid-template-columns:repeat(2,1fr)}}@media(max-width:600px){.page-heading{align-items:flex-start;flex-direction:column}.posting-toolbar button{font-size:0}.posting-list{grid-template-columns:1fr}.fit-score{grid-template-columns:auto 1fr}.fit-score p{grid-column:1/-1;margin:0;text-align:left}}
</style>

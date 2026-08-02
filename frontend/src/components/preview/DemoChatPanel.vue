<script setup lang="ts">
import { Check, FileText, Link2, Paperclip, Send, Sparkles, UserRound } from "@lucide/vue";
import { ref } from "vue";

type Message = { id: number; role: "user" | "assistant"; text: string };
const prompt = ref("");
const messages = ref<Message[]>([
  { id: 1, role: "assistant", text: "안녕하세요, 준영님. 오늘은 어떤 준비를 같이 해볼까요?" },
  { id: 2, role: "user", text: "광주은행 공고 기준으로 지금 가장 부족한 역량을 알려줘." },
  { id: 3, role: "assistant", text: "등록된 경험과 공고를 비교하면 SQL 실전 증거가 가장 부족해요. 작은 금융 API 프로젝트를 먼저 완성하면 적합도를 더 빠르게 높일 수 있습니다." },
]);
function sendMessage() {
  const text = prompt.value.trim();
  if (!text) return;
  messages.value.push({ id: Date.now(), role: "user", text });
  prompt.value = "";
  window.setTimeout(() => messages.value.push({
    id: Date.now() + 1,
    role: "assistant",
    text: "좋아요. 실제 서비스에서는 이 메시지가 백엔드 대화 API로 전달되고 분석 진행 상태도 함께 표시됩니다.",
  }), 300);
}
</script>

<template>
  <div class="chat-preview">
    <aside>
      <header><strong>대화</strong><button type="button">＋ 새 대화</button></header>
      <button class="active" type="button"><strong>광주은행 공고 분석</strong><small>방금 전</small><p>SQL 실전 증거가 가장 부족해요...</p></button>
      <button type="button"><strong>프로젝트 경험 정리</strong><small>어제</small><p>성과를 수치로 바꾸는 방법</p></button>
      <button type="button"><strong>자기소개서 방향</strong><small>7월 28일</small><p>지원동기 초안 검토</p></button>
    </aside>
    <section class="chat-room">
      <header><span class="jobi-avatar"><img src="/img/jobi-mascot.png" alt="" /></span><div><h1>광주은행 공고 분석</h1></div><em><i /> 연결됨</em></header>
      <div class="chat-context"><FileText :size="16" /><span><strong>광주은행 디지털·IT</strong><small>공고 분석 완료 · 적합도 64점</small></span><Check :size="15" /></div>
      <div class="message-stream">
        <article v-for="message in messages" :key="message.id" :class="message.role">
          <span><UserRound v-if="message.role === 'user'" :size="16" /><img v-else src="/img/jobi-mascot.png" alt="" /></span><p>{{ message.text }}</p>
        </article>
        <section class="analysis-card">
          <header><Sparkles :size="15" /><strong>AI 분석 요약</strong><small>공고와 경험 14개 비교</small></header>
          <div><span><small>강점</small><strong>프로젝트 실행력</strong></span><span><small>보완</small><strong>SQL 실전 증거</strong></span><span><small>추천</small><strong>금융 API 프로젝트</strong></span></div>
        </section>
      </div>
      <form class="chat-composer" @submit.prevent="sendMessage">
        <button type="button" aria-label="파일 첨부"><Paperclip :size="18" /></button>
        <textarea v-model="prompt" rows="1" placeholder="공고, 경험, 로드맵에 대해 물어보세요" @keydown.enter.exact.prevent="sendMessage" />
        <button class="send" type="submit" aria-label="보내기"><Send :size="17" /></button>
        <footer><span><Link2 :size="11" /> 공고 URL을 붙여넣어도 돼요</span><span>Enter로 전송</span></footer>
      </form>
    </section>
  </div>
</template>

<style scoped>
.chat-preview{display:grid;grid-template-columns:260px minmax(0,1fr);min-height:calc(100vh - 136px);overflow:hidden;border:1px solid #dbe5e0;border-radius:24px;background:#fff}.chat-preview>aside{padding:18px;border-right:1px solid #e1e8e4;background:#f7faf8}.chat-preview>aside header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.chat-preview>aside header span{color:#84948c;font-size:8px;font-weight:900}.chat-preview>aside header button{padding:7px 8px;border:0;border-radius:9px;color:#fff;background:#58cc78;font-size:8px;font-weight:900}.chat-preview>aside>button{display:block;width:100%;margin-bottom:7px;padding:12px;border:1px solid transparent;border-radius:13px;color:#54665f;background:transparent;text-align:left}.chat-preview>aside>button.active{border-color:#bfe4ca;background:#fff}.chat-preview>aside strong{font-size:9px}.chat-preview>aside small{float:right;color:#98a39f;font-size:7px}.chat-preview>aside p{margin:5px 0 0;overflow:hidden;color:#88968f;font-size:8px;text-overflow:ellipsis;white-space:nowrap}
.chat-room{display:grid;min-width:0;grid-template-rows:auto auto minmax(0,1fr) auto}.chat-room>header{display:flex;align-items:center;gap:10px;padding:16px 20px;border-bottom:1px solid #e4eae7}.chat-room>header>span{display:grid;width:38px;height:38px;place-items:center;border-radius:13px;color:#fff;background:#8062df}.chat-room>header div{flex:1}.chat-room>header small{color:#8066ca;font-size:7px;font-weight:900}.chat-room h1{margin:3px 0 0;font-size:13px}.chat-room>header em{display:flex;align-items:center;gap:5px;color:#368d56;font-size:8px;font-style:normal}.chat-room>header em i{width:7px;height:7px;border-radius:50%;background:#58cc78}.chat-context{display:flex;align-items:center;gap:9px;margin:12px 18px 0;padding:10px 12px;border:1px solid #dbe7e1;border-radius:13px;color:#31865e;background:#f5fbf7}.chat-context span{flex:1}.chat-context strong,.chat-context small{display:block}.chat-context strong{font-size:9px}.chat-context small{font-size:7px;color:#809087}
.message-stream{display:flex;overflow:auto;flex-direction:column;gap:13px;padding:22px}.message-stream article{display:flex;max-width:78%;align-items:flex-start;gap:9px}.message-stream article>span{display:grid;width:29px;height:29px;flex:0 0 auto;place-items:center;border-radius:10px;color:#fff;background:#8062df}.message-stream article p{margin:0;padding:12px 14px;border-radius:4px 15px 15px;color:#53665e;background:#f0f4f2;font-size:9px;line-height:1.65}.message-stream article.user{align-self:flex-end;flex-direction:row-reverse}.message-stream article.user>span,.message-stream article.user p{background:#6174d9}.message-stream article.user p{border-radius:15px 4px 15px 15px;color:#fff}
.analysis-card{width:min(100%,560px);margin-left:38px;padding:15px;border:1px solid #d8cdf6;border-radius:16px;background:#faf8ff}.analysis-card header{display:flex;align-items:center;gap:6px;color:#7354cb}.analysis-card header strong{font-size:9px}.analysis-card header small{margin-left:auto;font-size:7px}.analysis-card>div{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:11px}.analysis-card>div span{padding:10px;border-radius:11px;background:#fff}.analysis-card small,.analysis-card strong{display:block}.analysis-card small{font-size:7px}.analysis-card>div strong{margin-top:3px;font-size:8px}
.chat-composer{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:8px;margin:0 18px 17px;padding:9px;border:1px solid #cfdcd6;border-radius:16px;background:#fff;box-shadow:0 8px 28px rgba(42,73,61,.09)}.chat-composer button{display:grid;width:34px;height:34px;place-items:center;border:0;border-radius:11px;color:#71827a;background:#f0f4f2}.chat-composer button.send{color:#fff;background:#58cc78}.chat-composer textarea{resize:none;border:0;outline:0;font:inherit;font-size:10px}.chat-composer footer{display:flex;grid-column:1/-1;justify-content:space-between;padding:0 5px;color:#98a49e;font-size:7px}.chat-composer footer span{display:flex;align-items:center;gap:4px}
@media(max-width:760px){.chat-preview{grid-template-columns:1fr}.chat-preview>aside{display:none}.message-stream article{max-width:90%}.analysis-card{margin-left:0}.analysis-card>div{grid-template-columns:1fr}}

.chat-room>header>span.jobi-avatar{overflow:hidden;border:1px solid #bcd2ff;background:#eef5ff}
.jobi-avatar img{width:33px;height:33px;object-fit:contain}
.message-stream article.assistant>span{overflow:hidden;border:1px solid #c9dbff;background:#f1f6ff}
.message-stream article.assistant>span img{width:27px;height:27px;object-fit:contain}
</style>

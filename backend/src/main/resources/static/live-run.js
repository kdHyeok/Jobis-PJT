/*
   J.O.B.I.S — 진행 중인 분석 표시줄 (전역)

   분석은 시작해두고 커리어 저장소·로드맵 저장소 등을 돌아다닐 수 있다.
   그동안 어디까지 갔는지 하단에 계속 띄워두고, 누르면 그 대화창으로 돌아간다.

   상태는 /api/analyses 목록에서 가져온다(진행률은 이 API에 없다 —
   퍼센트는 채팅 화면이 WebSocket으로 받는 값이라, 여기서는 단계 이름만 보여준다).

   auth.js(JB) 다음에 로드해야 한다.
*/
(function () {
  'use strict';

  // 채팅 화면엔 자체 진행 표시(flow-nav)가 있으므로 중복해서 띄우지 않는다.
  if (/chat\.html$/.test(location.pathname)) return;
  if (!window.JB || !JB.token()) return;               // 로그인 전 페이지에선 동작하지 않는다

  var LIVE = {
    PENDING:          '대기 중',
    ANALYZING:        '분석 중',
    AWAITING_ANSWERS: '답변을 기다리는 중',
    FINALIZING:       '마무리 중'
  };
  var POLL_MS = 10000;

  /* 끊긴 세션 거르기 --------------------------------------------------
     서버가 내려가거나 분석이 중단되면 상태가 ANALYZING인 채로 영원히 남는다.
     그걸 계속 띄우면 표시줄이 사라지지 않고, 눌러도 이어지지 않는다.

     단, AWAITING_ANSWERS는 성격이 다르다 — 사람이 답할 때까지 기다리는
     정상 상태이므로 몇 시간이 지나도 유효하다. 이 기능이 존재하는 이유가
     "나중에 돌아와서 답하기"이므로 짧게 끊으면 안 된다. 아주 오래된 것만 뺀다. */
  var STALE_MS = {
    PENDING:          30 * 60 * 1000,
    ANALYZING:        30 * 60 * 1000,
    FINALIZING:       30 * 60 * 1000,
    AWAITING_ANSWERS: 7 * 24 * 60 * 60 * 1000
  };

  function isStale(a) {
    var limit = STALE_MS[a.status];
    if (limit == null || !a.createdAt) return false;
    // 서버가 타임존 없이 보내면(LocalDateTime) 브라우저 로컬 시각으로 해석된다.
    var t = Date.parse(a.createdAt);
    if (isNaN(t)) return false;                  // 못 읽으면 감추지 않는다 — 살아있는 걸 숨기는 쪽이 더 나쁘다
    var age = Date.now() - t;
    if (age < 0) return false;                   // 시계 차이로 미래면 방금 것으로 본다
    return age > limit;
  }
  var bar = null;
  var seenLive = {};        // 이 페이지에 머무는 동안 "진행 중"으로 본 분석 — 완료 안내를 띄울 대상
  var timer = null;

  function pickLive(list) {
    var live = (list || []).filter(function (a) { return LIVE[a.status] && !isStale(a); });
    // createdAt은 ISO 문자열이라 사전순 비교로 최신이 앞에 온다
    live.sort(function (a, b) { return String(b.createdAt || '').localeCompare(String(a.createdAt || '')); });
    return live[0] || null;
  }

  function pickJustDone(list) {
    var done = (list || []).filter(function (a) {
      return a.status === 'COMPLETED' && seenLive[a.analysisId];
    });
    return done[0] || null;
  }

  function ensureBar() {
    if (bar) return bar;
    bar = document.createElement('a');
    bar.className = 'live-run';
    bar.innerHTML = '<span class="lr-dot" aria-hidden="true"></span>' +
                    '<span class="lr-txt"></span>' +
                    '<span class="lr-go">이어보기 →</span>';
    document.body.appendChild(bar);
    return bar;
  }

  function show(a, done) {
    var b = ensureBar();
    var who = a.company || '분석';
    if (a.role) who += ' · ' + a.role;
    b.href = 'chat.html?id=' + encodeURIComponent(a.analysisId);
    b.querySelector('.lr-txt').textContent =
      done ? ('분석 완료 · ' + who) : (who + ' · ' + LIVE[a.status]);
    b.querySelector('.lr-go').textContent = done ? '결과 보기 →' : '이어보기 →';
    // 답변 대기는 사용자가 움직여야 진행되는 상태라 따로 표시한다
    b.classList.toggle('waiting', a.status === 'AWAITING_ANSWERS');
    b.classList.toggle('done', !!done);
    b.setAttribute('aria-label', b.querySelector('.lr-txt').textContent + ', 눌러서 이동');
    b.hidden = false;
  }

  function hide() { if (bar) bar.hidden = true; }

  function tick() {
    JB.api('/api/analyses').then(function (list) {
      var a = pickLive(list);
      if (a) { seenLive[a.analysisId] = true; show(a, false); return; }
      var d = pickJustDone(list);
      if (d) { show(d, true); return; }
      hide();
    }).catch(function () { /* 네트워크 일시 오류는 조용히 넘긴다 — 다음 폴링에서 회복 */ });
  }

  function start() {
    tick();
    timer = setInterval(tick, POLL_MS);
  }

  // 탭이 백그라운드면 폴링을 멈춘다(불필요한 요청 방지), 돌아오면 즉시 갱신
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { clearInterval(timer); timer = null; }
    else if (!timer) start();
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();

/* ============================================================
   J.O.B.I.S chat-app 공통 스크립트
   - JWT 토큰/사용자 저장 (localStorage)
   - 인증 fetch 헬퍼 (Authorization 자동 첨부, 401 → 로그인)
   - 로그인 게이트
   백엔드와 같은 오리진(/chat-app/)에서 서빙되므로 /api/** 로 바로 호출.
   ============================================================ */
(function () {
  'use strict';
  var TOKEN_KEY = 'jobis.token';
  var USER_KEY = 'jobis.user';

  var JB = {
    token: function () { return localStorage.getItem(TOKEN_KEY); },
    user: function () {
      try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); }
      catch (e) { return null; }
    },
    setAuth: function (token, user) {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(USER_KEY, JSON.stringify(user || null));
    },
    logout: function () {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    },

    /** 인증이 필요한 API 호출. 실패 시 Error(message) throw. */
    api: async function (path, opts) {
      opts = opts || {};
      // Accept 명시 — 정적 오류 페이지(error/*.html) 때문에 API 오류가 HTML로 협상되는 걸 막는다.
      var headers = Object.assign({ 'Content-Type': 'application/json', 'Accept': 'application/json' }, opts.headers || {});
      var t = JB.token();
      if (t) headers['Authorization'] = 'Bearer ' + t;
      var res = await fetch(path, Object.assign({}, opts, { headers: headers }));
      if (res.status === 401) { JB.logout(); location.href = 'login.html'; throw new Error('로그인이 필요합니다.'); }
      if (!res.ok) {
        var msg = 'HTTP ' + res.status;
        try { var j = await res.json(); msg = JB.errMsg(j, msg); } catch (e) {}
        throw new Error(msg);
      }
      if (res.status === 204) return null;
      var ct = res.headers.get('content-type') || '';
      return ct.indexOf('application/json') >= 0 ? res.json() : res.text();
    },

    /** 로그인 안 됐으면 login.html로 보내고 false 반환. */
    requireAuth: function () {
      if (!JB.token()) { location.href = 'login.html'; return false; }
      return true;
    },

    esc: function (s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    },

    /** 에러 응답 JSON에서 사람이 읽을 메시지 추출.
       표준 { error:{ code, message } } · 스프링 기본 { message, error:'문자열' } · { error:'문자열' } 모두 대응.
       (예전엔 j.error 를 문자열로 가정해 중첩 객체가 그대로 들어가 "[object Object]" 로 떴음) */
    errMsg: function (j, fallback) {
      if (!j || typeof j !== 'object') return fallback;
      if (j.error && typeof j.error === 'object') return j.error.message || j.error.code || fallback;
      if (typeof j.message === 'string' && j.message) return j.message;
      if (typeof j.error === 'string' && j.error) return j.error;
      return fallback;
    },

    /** 로드맵 상세 페이지 주소. 단계형(staged) 로드맵은 학습·검수·시험이 있는 페이지로 보낸다.
       staged 플래그는 AI가 로드맵과 함께 내려준다(없으면 기존 요건×증거 페이지). */
    roadmapHref: function (roadmap, analysisId, routeId) {
      var page = (roadmap && roadmap.staged === true) ? 'roadmap-stages.html' : 'roadmap.html';
      return page + '?id=' + encodeURIComponent(analysisId) + '&route=' + encodeURIComponent(routeId);
    },

    /**
     * 사이드바 "최근 대화" 목록 렌더.
     * 목록의 단위는 대화다 — 분석은 대화 안에서 일어난 사건이므로 그 상태를 점 색으로만 얹는다.
     * activeCid = 지금 열려 있는 대화(강조용).
     */
    loadConversations: async function (container, activeCid) {
      if (!container) return;
      try {
        var list = await JB.api('/api/conversations');
        if (!list || !list.length) {
          container.innerHTML = '<div class="side-empty">아직 대화가 없어요.<br>무엇이든 말을 걸어보세요.</div>';
          return;
        }
        container.innerHTML = list.map(function (c) {
          // 분석이 없는 대화는 회색 점 — "아직 분석 전"이라는 뜻
          var color = !c.analysisStatus ? 'var(--faint)'
            : (c.analysisStatus === 'COMPLETED' ? 'var(--ok)'
            : (c.analysisStatus === 'FAILED' ? 'var(--bad)' : 'var(--warn)'));
          var active = c.conversationId === activeCid ? ' active' : '';
          return '<a class="session' + active + '" href="chat.html?c=' + encodeURIComponent(c.conversationId) + '">' +
            '<span class="dot" style="background:' + color + '"></span>' +
            '<span class="tx">' + JB.esc(c.title || '새 대화') + '</span>' +
            '<button class="sess-menu" data-cmenu="' + JB.esc(c.conversationId) + '"' +
            (c.analysisId ? ' data-caid="' + JB.esc(c.analysisId) + '"' : '') +
            ' title="더 보기" aria-label="더 보기">⋮</button></a>';
        }).join('');
        container.querySelectorAll('[data-cmenu]').forEach(function (b) {
          b.addEventListener('click', function (e) {
            e.preventDefault(); e.stopPropagation();
            var cid = b.getAttribute('data-cmenu');
            JB.openConversationMenu(b, cid, b.getAttribute('data-caid'), function () {
              var cur = new URLSearchParams(location.search).get('c');
              if (cur && cur === cid && /chat\.html/.test(location.pathname)) location.href = 'chat.html';
              else JB.loadConversations(container, activeCid);
            });
          });
        });
      } catch (e) {
        container.innerHTML = '<div class="side-empty">목록을 불러오지 못했어요</div>';
      }
    },

    /**
     * 대화 케밥(⋮) → 삭제. 대화 안에 분석이 있으면 "분석까지" 지우는 선택지도 함께 준다
     * (대화만 지우면 분석은 남는다 — 목록에서 안 보이게 되므로 여기서 정리할 길이 있어야 한다).
     */
    openConversationMenu: function (btn, cid, aid, onDeleted) {
      JB.closeSessionMenu();
      JB._ensureModalCss();
      var trash = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>';
      var pop = document.createElement('div');
      pop.className = 'sess-menu-pop';
      pop.innerHTML = '<button class="smi danger" data-act="del">' + trash + '대화 삭제</button>' +
        (aid ? '<button class="smi danger" data-act="delall">' + trash + '분석까지 삭제</button>' : '');
      document.body.appendChild(pop);
      btn.classList.add('open');
      var r = btn.getBoundingClientRect();
      var w = pop.offsetWidth, h = pop.offsetHeight;
      var left = Math.min(r.right - w, window.innerWidth - w - 8); if (left < 8) left = 8;
      var top = r.bottom + 4; if (top + h > window.innerHeight - 8) top = r.top - h - 4;
      pop.style.left = left + 'px'; pop.style.top = top + 'px';
      pop.querySelector('[data-act=del]').addEventListener('click', function (e) {
        e.stopPropagation(); JB.closeSessionMenu(); JB.deleteConversationFlow(cid, onDeleted);
      });
      var all = pop.querySelector('[data-act=delall]');
      if (all) all.addEventListener('click', function (e) {
        e.stopPropagation(); JB.closeSessionMenu();
        // 분석을 지우면 그 분석만 담고 있던 대화는 서버가 함께 정리한다
        JB.deleteAnalysisFlow(aid, function () {
          JB.api('/api/conversations/' + encodeURIComponent(cid), { method: 'DELETE' })
            .catch(function () { /* 이미 함께 지워졌으면 정상 */ })
            .then(function () { if (onDeleted) onDeleted(); });
        });
      });
      JB._sessMenu = { pop: pop, btn: btn };
      setTimeout(function () {
        document.addEventListener('click', JB._sessMenuOutside);
        document.addEventListener('keydown', JB._sessMenuKey);
      }, 0);
    },

    /** 대화 삭제 흐름 — 대화만 지우고, 그 안에서 만든 분석·로드맵은 남긴다(자기 삭제 흐름이 따로 있다). */
    deleteConversationFlow: function (cid, onDeleted) {
      JB.confirmModal({
        title: '이 대화를 삭제할까요?', danger: true, confirmText: '삭제',
        message: '주고받은 내용이 사라져요. 되돌릴 수 없어요.',
        extraHtml: '<div class="jb-modal-note">이 대화에서 시작한 <b>분석과 저장한 로드맵은 남아요</b>. ' +
          '분석을 지우려면 로드맵 저장소에서 따로 지워주세요.</div>',
        onConfirm: async function (ov, close) {
          var ok = ov.querySelector('[data-ok]');
          ok.disabled = true; ok.textContent = '삭제 중…';
          try {
            await JB.api('/api/conversations/' + encodeURIComponent(cid), { method: 'DELETE' });
            close();
            if (onDeleted) onDeleted();
          } catch (e) {
            ok.disabled = false; ok.textContent = '삭제';
            ov.querySelector('.jb-modal-msg').textContent = '삭제하지 못했어요: ' + e.message;
          }
        }
      });
    },

    closeSessionMenu: function () {
      var m = JB._sessMenu; if (!m) return;
      if (m.pop && m.pop.parentNode) m.pop.remove();
      if (m.btn) m.btn.classList.remove('open');
      JB._sessMenu = null;
      document.removeEventListener('click', JB._sessMenuOutside);
      document.removeEventListener('keydown', JB._sessMenuKey);
    },
    _sessMenuOutside: function (e) {
      var m = JB._sessMenu;
      if (m && m.pop && m.pop.contains(e.target)) return;   // 메뉴 안 클릭은 유지
      JB.closeSessionMenu();
    },
    _sessMenuKey: function (e) { if (e.key === 'Escape') JB.closeSessionMenu(); },

    /** 위험 확인 모달. opts: {title, message, extraHtml, danger, confirmText, onConfirm(overlayEl, close)} */
    confirmModal: function (opts) {
      JB._ensureModalCss();
      var ov = document.createElement('div');
      ov.className = 'jb-modal';
      ov.innerHTML = '<div class="jb-modal-box"><h3>' + JB.esc(opts.title || '확인') + '</h3>' +
        '<p class="jb-modal-msg">' + (opts.message || '') + '</p>' + (opts.extraHtml || '') +
        '<div class="jb-modal-acts"><button class="jb-btn" data-x>취소</button>' +
        '<button class="jb-btn ' + (opts.danger ? 'danger' : 'pri') + '" data-ok>' + JB.esc(opts.confirmText || '확인') + '</button></div></div>';
      document.body.appendChild(ov);
      function close() { ov.remove(); }
      ov.addEventListener('click', function (e) { if (e.target === ov) close(); });
      ov.querySelector('[data-x]').addEventListener('click', close);
      ov.querySelector('[data-ok]').addEventListener('click', function () { if (opts.onConfirm) opts.onConfirm(ov, close); else close(); });
      return ov;
    },

    /** 분석 삭제 흐름: 미리보기(자식·로드맵 수) → 확인창(로드맵 체크박스) → DELETE. onDeleted() 콜백. */
    deleteAnalysisFlow: async function (analysisId, onDeleted) {
      var pv = { descendantCount: 0, roadmapCount: 0 };
      try { pv = await JB.api('/api/analyses/' + encodeURIComponent(analysisId) + '/deletion-preview'); } catch (e) {}
      var childLine = pv.descendantCount > 0 ? '<div class="jb-modal-note">↳ 딸린 <b>대체 재분석 ' + pv.descendantCount + '개</b>도 함께 삭제돼요.</div>' : '';
      var rmCheck = pv.roadmapCount > 0
        ? '<label class="jb-check"><input type="checkbox" id="jbDelRm" checked> 이 분석의 <b>저장 로드맵 ' + pv.roadmapCount + '개</b>도 함께 삭제 <span class="jb-check-sub">(끄면 로드맵은 남아요)</span></label>'
        : '';
      JB.confirmModal({
        title: '분석을 삭제할까요?', danger: true, confirmText: '삭제',
        message: '이 분석과 결과·진행 내역이 삭제돼요. 되돌릴 수 없어요.',
        extraHtml: childLine + rmCheck,
        onConfirm: async function (ov, close) {
          var cb = ov.querySelector('#jbDelRm'); var delRm = cb ? cb.checked : true;
          var ok = ov.querySelector('[data-ok]'); ok.disabled = true; ok.textContent = '삭제 중…';
          try {
            await JB.api('/api/analyses/' + encodeURIComponent(analysisId) + '?deleteRoadmaps=' + delRm, { method: 'DELETE' });
            close(); if (onDeleted) onDeleted();
          } catch (e) { ok.disabled = false; ok.textContent = '삭제'; alert('삭제 실패: ' + e.message); }
        }
      });
    },

    _ensureModalCss: function () {
      if (document.getElementById('jb-modal-css')) return;
      var st = document.createElement('style'); st.id = 'jb-modal-css';
      st.textContent =
        '.jb-modal{position:fixed;inset:0;background:rgba(0,0,0,.45);display:grid;place-items:center;z-index:200;padding:20px}' +
        '.jb-modal-box{background:var(--surface);border-radius:16px;max-width:410px;width:100%;padding:20px 22px;box-shadow:0 20px 60px rgba(0,0,0,.3)}' +
        '.jb-modal-box h3{margin:0 0 6px;font-size:16px;font-weight:800;color:var(--ink)}' +
        '.jb-modal-msg{margin:0 0 12px;font-size:13px;color:var(--muted);line-height:1.5}' +
        '.jb-modal-note{font-size:12.5px;color:var(--ink-2);background:var(--surface-2);border-radius:9px;padding:9px 11px;margin-bottom:10px;line-height:1.5}' +
        '.jb-check{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--ink-2);background:var(--warn-soft);border-radius:9px;padding:10px 12px;margin-bottom:4px;cursor:pointer;line-height:1.4}' +
        '.jb-check b{color:var(--warn)}.jb-check-sub{color:var(--muted);font-size:11.5px}' +
        '.jb-modal-acts{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}' +
        '.jb-btn{border:1px solid var(--line);background:var(--surface-2);color:var(--ink-2);border-radius:9px;padding:9px 15px;font-size:13px;font-weight:700;cursor:pointer}' +
        '.jb-btn.pri{background:var(--brand);color:#fff;border-color:var(--brand)}' +
        '.jb-btn.danger{background:var(--bad,#d64550);color:#fff;border-color:var(--bad,#d64550)}' +
        '.jb-btn:disabled{opacity:.6;cursor:default}';
      document.head.appendChild(st);
    }
  };

  /* ===== 사이드바 좌/우 접기 (모든 페이지 공용) =====
     좌: .sidebar(모든 페이지) · 우: .insight(chat만). 상태는 localStorage에 기억. */
  function initLayoutToggles() {
    var app = document.querySelector('.app');
    if (!app || app.dataset.toggleInit) return;
    app.dataset.toggleInit = '1';
    var sidebar = app.querySelector('.sidebar');
    var insight = app.querySelector('.insight');
    var LKEY = 'jobis.leftCollapsed', RKEY = 'jobis.rightCollapsed';

    function panelBtn(sym, title) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'panel-collapse'; b.innerHTML = sym; b.title = title;
      return b;
    }
    function edgeBtn(side, sym, title) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'edge-expand ' + side; b.innerHTML = sym; b.title = title;
      b.style.display = 'none'; document.body.appendChild(b); return b;
    }

    var leftEdge = null, rightEdge = null;
    function applyLeft(c) {
      app.classList.toggle('lcol', c);
      if (leftEdge) leftEdge.style.display = c ? 'grid' : 'none';
      try { localStorage.setItem(LKEY, c ? '1' : '0'); } catch (e) {}
    }
    function applyRight(c) {
      app.classList.toggle('rcol', c);
      if (rightEdge) rightEdge.style.display = c ? 'grid' : 'none';
      try { localStorage.setItem(RKEY, c ? '1' : '0'); } catch (e) {}
    }

    if (sidebar) {
      var lc = panelBtn('‹', '사이드바 접기'); lc.style.marginLeft = 'auto';
      var brand = sidebar.querySelector('.brand');
      if (brand) brand.appendChild(lc); else sidebar.insertBefore(lc, sidebar.firstChild);
      leftEdge = edgeBtn('left', '☰', '사이드바 펼치기');
      lc.addEventListener('click', function () { applyLeft(true); });
      leftEdge.addEventListener('click', function () { applyLeft(false); });
    }
    if (insight) {
      var rc = panelBtn('›', '인사이트 패널 접기'); rc.style.marginLeft = '6px';
      var ih = insight.querySelector('.insight-head .t') || insight.querySelector('.insight-head');
      if (ih) ih.appendChild(rc); else insight.appendChild(rc);
      rightEdge = edgeBtn('right', '‹', '인사이트 패널 펼치기');
      rc.addEventListener('click', function () { applyRight(true); });
      rightEdge.addEventListener('click', function () { applyRight(false); });
    }

    var lSaved = false, rSaved = false;
    try { lSaved = localStorage.getItem(LKEY) === '1'; rSaved = localStorage.getItem(RKEY) === '1'; } catch (e) {}
    if (sidebar) applyLeft(lSaved);
    if (insight) applyRight(rSaved);
    requestAnimationFrame(function () { app.classList.add('anim'); });   // 초기 적용엔 애니메이션 없이
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initLayoutToggles);
  else initLayoutToggles();

  window.JB = JB;
})();

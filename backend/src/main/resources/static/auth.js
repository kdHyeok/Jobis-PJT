/* ============================================================
   잡이스 chat-app 공통 스크립트
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
      var headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
      var t = JB.token();
      if (t) headers['Authorization'] = 'Bearer ' + t;
      var res = await fetch(path, Object.assign({}, opts, { headers: headers }));
      if (res.status === 401) { JB.logout(); location.href = 'login.html'; throw new Error('로그인이 필요합니다.'); }
      if (!res.ok) {
        var msg = 'HTTP ' + res.status;
        try { var j = await res.json(); msg = j.message || j.error || msg; } catch (e) {}
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

    /** 사이드바 "최근 분석" 목록 렌더. 대체 재분석 세션은 부모(원래 분석) 밑에 들여쓰기. */
    loadSessions: async function (container, activeId) {
      if (!container) return;
      try {
        var list = await JB.api('/api/analyses');
        if (!list || !list.length) {
          container.innerHTML = '<div class="side-empty">아직 분석이 없어요.<br>새 분석을 시작해보세요.</div>';
          return;
        }
        var exists = {};
        list.forEach(function (s) { exists[s.analysisId] = true; });
        var childrenOf = {}, roots = [];
        list.forEach(function (s) {
          if (s.parentAnalysisId && exists[s.parentAnalysisId]) {
            (childrenOf[s.parentAnalysisId] = childrenOf[s.parentAnalysisId] || []).push(s);
          } else {
            roots.push(s);   // 독립 분석, 또는 부모가 목록에 없으면 최상위로
          }
        });
        function item(s, isChild) {
          var title = (s.company || '분석') + (s.role ? ' · ' + s.role : '');
          var active = s.analysisId === activeId ? ' active' : '';
          var child = isChild ? ' child' : '';
          var color = s.status === 'COMPLETED' ? 'var(--ok)' : (s.status === 'FAILED' ? 'var(--bad)' : 'var(--warn)');
          return '<a class="session' + active + child + '" href="chat.html?id=' + encodeURIComponent(s.analysisId) + '">' +
            '<span class="dot" style="background:' + color + '"></span>' +
            '<span class="tx">' + JB.esc(title) + '</span></a>';
        }
        container.innerHTML = roots.map(function (r) {
          return item(r, false) + (childrenOf[r.analysisId] || []).map(function (c) { return item(c, true); }).join('');
        }).join('');
      } catch (e) {
        container.innerHTML = '<div class="side-empty">목록을 불러오지 못했어요</div>';
      }
    }
  };

  window.JB = JB;
})();

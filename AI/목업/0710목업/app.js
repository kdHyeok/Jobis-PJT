/* 잡퀘스트 공통 스크립트 — 탭 · 퀘스트 경로 확장 · 드로어 · 프로토타입 모드 · Agent UI */
document.addEventListener('DOMContentLoaded', function () {

  /* 탭 전환 (result 등) */
  document.querySelectorAll('.tabs [data-panel], .method [data-panel]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var group = btn.closest('.tabs, .method');
      group.querySelectorAll('[data-panel]').forEach(function (b) {
        b.classList.remove('on');
        b.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('on');
      btn.setAttribute('aria-selected', 'true');
      var scope = group.dataset.scope ? document.getElementById(group.dataset.scope) : document;
      scope.querySelectorAll('.tabpanel').forEach(function (p) { p.classList.remove('on'); });
      var panel = document.getElementById(btn.dataset.panel);
      if (panel) panel.classList.add('on');
    });
  });

  /* 퀘스트 노드 펼침 (잠긴 노드는 제외) */
  document.querySelectorAll('.qnode > .qhead').forEach(function (head) {
    head.addEventListener('click', function () {
      var node = head.closest('.qnode');
      if (node.classList.contains('locked')) return;
      node.classList.toggle('open');
      head.setAttribute('aria-expanded', node.classList.contains('open') ? 'true' : 'false');
    });
  });

  /* Tool Router — 도구 카드 입력/출력 펼침 */
  document.querySelectorAll('.tool > .tool-h').forEach(function (head) {
    head.addEventListener('click', function () {
      var tool = head.closest('.tool');
      tool.classList.toggle('open');
      head.setAttribute('aria-expanded', tool.classList.contains('open') ? 'true' : 'false');
    });
  });

  /* Decision Log — "다음 판단 보기" 순차 공개 */
  var revealBtn = document.querySelector('[data-reveal]');
  if (revealBtn) {
    revealBtn.addEventListener('click', function () {
      var next = document.querySelector('.dlog-row.hidden');
      if (next) next.classList.remove('hidden');
      if (!document.querySelector('.dlog-row.hidden')) {
        revealBtn.textContent = '모든 판단이 공개되었습니다';
        revealBtn.disabled = true;
        revealBtn.style.opacity = '.55';
        revealBtn.style.cursor = 'default';
      }
    });
  }

  /* 모바일 사이드바 드로어 */
  var drawerBtn = document.querySelector('.drawer-btn');
  var scrim = document.querySelector('.scrim');
  if (drawerBtn) drawerBtn.addEventListener('click', function () { document.body.classList.toggle('nav-open'); });
  if (scrim) scrim.addEventListener('click', function () { document.body.classList.remove('nav-open'); });

  /* 프로토타입(발표) 모드: URL에 proto 포함 시 흐름 내비 표시 */
  if (location.search.indexOf('proto') > -1 || location.hash.indexOf('proto') > -1) {
    document.body.classList.add('prototype-mode');
    document.querySelectorAll('.flow-nav a').forEach(function (a) {
      var href = a.getAttribute('href');
      if (href && href.indexOf('.html') > -1 && href.indexOf('proto') === -1) {
        a.setAttribute('href', href + '?proto');
      }
    });
  }
});

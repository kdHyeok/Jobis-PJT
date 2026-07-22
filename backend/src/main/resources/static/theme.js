/*
   J.O.B.I.S — 테마(라이트/다크) 전환

   <head>에서 동기로 불러야 한다. 아래 첫 줄이 body가 그려지기 전에 실행되면서
   html에 data-theme을 박아 넣기 때문에, 새로고침할 때 반대 테마가 번쩍이지 않는다.
   (defer/async를 붙이면 이 효과가 사라진다.)
*/
(function () {
  'use strict';

  var KEY = 'jbTheme';
  var DARK = 'dark', LIGHT = 'light';

  // 테마별 배경 영상. 포스터는 첫 프레임이라 영상과 정확히 이어진다.
  var MEDIA = {
    dark:  { vid: 'vid/vid1.mp4', poster: 'img/vid1-poster.jpg' },
    light: { vid: 'vid/vid2.mp4', poster: 'img/vid2-poster.jpg' }
  };

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }  // 시크릿 모드 등
  }

  function preferred() {
    var s = stored();
    if (s === DARK || s === LIGHT) return s;
    // 저장된 값이 없으면 OS 설정을 따른다
    try {
      if (window.matchMedia('(prefers-color-scheme: light)').matches) return LIGHT;
    } catch (e) {}
    return DARK;
  }

  // --- 1) 즉시 적용: body 파싱 전에 실행되어야 깜빡임이 없다 ---
  var current = preferred();
  document.documentElement.setAttribute('data-theme', current);

  // --- 2) 배경 영상 교체 ---
  // HTML의 <source>에는 src를 비워 두고 preload="none"으로 두었다.
  // 그래야 테마를 정하기 전에 엉뚱한 영상을 받아오지 않는다.
  function applyMedia(theme) {
    var v = document.querySelector('.page-bg, .home-bg');
    if (!v) return;
    var m = MEDIA[theme] || MEDIA.dark;
    if (v.getAttribute('data-loaded') === theme) return;
    v.setAttribute('data-loaded', theme);
    v.poster = m.poster;
    var src = v.querySelector('source');
    if (src) {
      src.src = m.vid;
      v.load();                       // src를 바꾼 뒤엔 load()를 불러야 반영된다
      var p = v.play();
      if (p && p.catch) p.catch(function () {});  // 자동재생 차단은 무시(배경 장식)
    }
  }

  function apply(theme, persist) {
    current = theme;
    document.documentElement.setAttribute('data-theme', theme);
    if (persist) { try { localStorage.setItem(KEY, theme); } catch (e) {} }
    applyMedia(theme);
    var btn = document.getElementById('themeTg');
    if (btn) {
      btn.setAttribute('aria-pressed', theme === LIGHT ? 'true' : 'false');
      btn.title = theme === LIGHT ? '다크모드로 전환' : '라이트모드로 전환';
    }
  }

  function init() {
    applyMedia(current);
    var btn = document.getElementById('themeTg');
    if (btn) {
      btn.setAttribute('aria-pressed', current === LIGHT ? 'true' : 'false');
      btn.title = current === LIGHT ? '다크모드로 전환' : '라이트모드로 전환';
      btn.addEventListener('click', function () {
        apply(current === LIGHT ? DARK : LIGHT, true);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 사용자가 직접 고른 적이 없다면 OS 테마 변경을 따라간다
  try {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function (e) {
      if (!stored()) apply(e.matches ? LIGHT : DARK, false);
    });
  } catch (e) {}

  window.JBTheme = { get: function () { return current; }, set: function (t) { apply(t, true); } };
})();

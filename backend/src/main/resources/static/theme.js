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

  // 영상 원본 프레임에서 오브(구체)가 차지하는 자리. 가로·세로 비율값이라
  // 해상도가 바뀌어도 그대로 쓸 수 있다. fr은 가로 대비 반지름.
  var ORB = { fx: 0.543, fy: 0.350, fr: 0.16 };

  // 호버 재생 상태. applyMedia가 "지금 재생해도 되는지" 판단할 때 함께 본다.
  var hover = { on: false, inside: false };

  function bgVideo() { return document.querySelector('.page-bg, .home-bg'); }

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
  function play(v) {
    var p = v.play();
    if (p && p.catch) p.catch(function () {});  // 자동재생 차단은 무시(배경 장식)
  }

  function applyMedia(theme) {
    var v = bgVideo();
    if (!v) return;
    var m = MEDIA[theme] || MEDIA.dark;
    if (v.getAttribute('data-loaded') === theme) return;
    v.setAttribute('data-loaded', theme);
    v.poster = m.poster;
    var src = v.querySelector('source');
    if (src) {
      src.src = m.vid;
      // preload="none"은 "테마를 정하기 전에 받지 마라"는 뜻이었다. src가 정해진 지금은 풀어 준다.
      // 호버 재생은 미리 받아 두지 않으면 처음 오브에 올렸을 때 버퍼링으로 끊긴다.
      if (hover.on) v.preload = 'auto';
      v.load();                       // src를 바꾼 뒤엔 load()를 불러야 반영된다
      // 호버 재생 페이지에서는 커서가 오브 위에 있을 때만 이어서 튼다.
      // (테마를 바꿔도 올려둔 커서를 내렸다 올릴 필요가 없도록)
      if (!hover.on || hover.inside) play(v);
    }
  }

  // --- 3) 오브 위에 커서가 있을 때만 재생 ---
  // 오브는 별도 요소가 아니라 영상 안에 그려진 그림이라, 화면 어디에 놓이는지를
  // 직접 계산해야 한다. object-fit:cover의 배율·여백을 재현한 뒤,
  // .home-bg에 걸린 transform은 getBoundingClientRect가 이미 반영한 값으로 보정한다.

  // object-position 한 축을 픽셀 오프셋으로. free는 (컨테이너 - 영상) 크기라 보통 음수다.
  var EDGE = { left: 0, top: 0, center: 50, right: 100, bottom: 100 };
  function axisOffset(raw, free) {
    if (raw in EDGE) return free * EDGE[raw] / 100;
    if (/%$/.test(raw)) return free * parseFloat(raw) / 100;
    if (/px$/.test(raw)) return parseFloat(raw);
    return free / 2;
  }

  function orbArea(v) {
    var vw = v.videoWidth || 1938, vh = v.videoHeight || 1080;  // 아직 메타데이터 전이면 원본 크기로
    var cw = v.offsetWidth, ch = v.offsetHeight;                // transform 적용 전 레이아웃 박스
    if (!cw || !ch) return null;

    // cover = 짧은 쪽을 채우는 배율. 남는 쪽은 잘려 나간다.
    var k = Math.max(cw / vw, ch / vh);
    var dw = vw * k, dh = vh * k;

    var pos = String(getComputedStyle(v).objectPosition || '50% 50%').split(/\s+/);
    var x = axisOffset(pos[0], cw - dw) + ORB.fx * dw;
    var y = axisOffset(pos[1] === undefined ? pos[0] : pos[1], ch - dh) + ORB.fy * dh;

    var r = v.getBoundingClientRect();
    var sx = r.width / cw, sy = r.height / ch;   // transform(scale)만큼의 추가 배율
    return { x: r.left + x * sx, y: r.top + y * sy, r: ORB.fr * dw * sx };
  }

  function setupHoverPlay() {
    var v = bgVideo();
    if (!v || !v.hasAttribute('data-hover-play')) return;
    // 호버가 없는 환경(터치)에선 판정할 방법이 없고, 움직임 최소화 설정에선 영상 자체가 숨는다.
    // 둘 다 기존처럼 그냥 재생한다.
    try {
      if (!matchMedia('(hover: hover)').matches) return;
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    } catch (e) { return; }

    hover.on = true;

    // 좌표는 창 크기가 바뀔 때만 다시 잰다(마우스 움직일 때마다 재면 레이아웃을 계속 건드린다)
    var area = null;
    function invalidate() { area = null; }
    window.addEventListener('resize', invalidate);
    window.addEventListener('orientationchange', invalidate);
    v.addEventListener('loadedmetadata', invalidate);

    window.addEventListener('pointermove', function (e) {
      if (!area) area = orbArea(v);
      if (!area) return;
      var dx = e.clientX - area.x, dy = e.clientY - area.y;
      var inside = dx * dx + dy * dy <= area.r * area.r;
      if (inside === hover.inside) return;        // 상태가 바뀔 때만 건드린다
      hover.inside = inside;
      if (inside) play(v); else v.pause();
    }, { passive: true });

    // 커서가 창 밖으로 나가면 pointermove가 더 안 오므로 여기서 멈춰 준다
    document.addEventListener('mouseleave', function () {
      if (!hover.inside) return;
      hover.inside = false;
      v.pause();
    });
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
    setupHoverPlay();   // applyMedia보다 먼저 — 호버 페이지에서 첫 로드부터 자동 재생되지 않도록
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

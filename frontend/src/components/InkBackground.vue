<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";

// Design-test/index.html 의 배경을 옮긴 것.
// (Ashima simplex noise 3D + 2단 도메인 워핑 + IQ 코사인 팔레트)
const VERT = `
attribute vec2 a;
void main(){ gl_Position = vec4(a, 0.0, 1.0); }`;

const FRAG = `
precision highp float;
uniform vec2  uRes;
uniform float uPhase;

vec3 mod289(vec3 x){ return x - floor(x * (1.0/289.0)) * 289.0; }
vec4 mod289(vec4 x){ return x - floor(x * (1.0/289.0)) * 289.0; }
vec4 permute(vec4 x){ return mod289(((x*34.0)+1.0)*x); }
vec4 taylorInvSqrt(vec4 r){ return 1.79284291400159 - 0.85373472095314 * r; }
float snoise(vec3 v){
  const vec2 C = vec2(1.0/6.0, 1.0/3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i  = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
             i.z + vec4(0.0, i1.z, i2.z, 1.0))
           + i.y + vec4(0.0, i1.y, i2.y, 1.0))
           + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
}

float fbm(vec3 p){
  float s = 0.0, a = 0.5;
  for (int i = 0; i < 3; i++){ s += a * snoise(p); p *= 2.03; a *= 0.5; }
  return s;
}

// 페리윙클 램프 — t=0 #7986e2, t=1 #f5f5ff.
// 참조 원본의 바닥은 #5c6bdb 였는데 그 위에서는 본문 대비가 AA(4.5:1) 에 못 미쳤다.
// 밝은 끝은 그대로 두고 어두운 끝만 끌어올렸다(가운데값·진폭 재계산).
vec3 palette(float t){
  return vec3(0.717, 0.7415, 0.9435) + vec3(0.243, 0.2185, 0.0565)
       * cos(6.28318 * (vec3(0.50) * t + vec3(0.50)));
}

void main(){
  vec2  uv = gl_FragCoord.xy / uRes;
  vec2  p  = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y * 0.42;
  float t = uPhase;

  vec2 q = vec2(fbm(vec3(p, t)),
                fbm(vec3(p + vec2(3.7, 1.3), t)));
  vec2 r = vec2(fbm(vec3(p + 0.96 * q + vec2(1.7, 9.2), t * 1.3)),
                fbm(vec3(p + 0.96 * q + vec2(8.3, 2.8), t * 1.3)));
  float f = fbm(vec3(p + 1.2 * r, t));

  float v = clamp(f * 0.75 + 0.5, 0.0, 1.0);
  v += (uv.y - 0.42) * 0.42;
  v += 0.08 * smoothstep(0.15, 0.95, length(r));

  vec3 col = palette(clamp(v, 0.0, 1.0));

  float g = fract(sin(dot(gl_FragCoord.xy + fract(uPhase * 7.0) * 91.7,
                         vec2(12.9898, 78.233))) * 43758.5453);
  col += (g - 0.5) * 0.024;

  gl_FragColor = vec4(col, 1.0);
}`;

const RING = ["$", ">", "_", "/", "{", "}", "#", "*", "0", "1", "+", "·", "~", "|"];

/** 커서를 따라 흐르는 점자 조각. U+2800 은 공백이라 제외한다. */
function braille(n: number) {
  let s = "";
  for (let i = 0; i < n; i++) s += String.fromCharCode(0x2800 + 1 + ((Math.random() * 255) | 0));
  return s;
}

type Part = {
  x: number; y: number; text: string; a: number; v: number;
  ttl: number; size: number; center: boolean; delay: number; life: number;
};

const bgCanvas = ref<HTMLCanvasElement | null>(null);
const fxCanvas = ref<HTMLCanvasElement | null>(null);

let cleanup: (() => void) | null = null;

onMounted(() => {
  const canvas = bgCanvas.value;
  const overlay = fxCanvas.value;
  if (!canvas || !overlay) return;

  const fx = overlay.getContext("2d");
  const gl = canvas.getContext("webgl", { antialias: false, alpha: false });
  if (!gl || !fx) return;    // 캔버스의 CSS 그라데이션이 그대로 보인다

  const compile = (type: number, src: string) => {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? "");
    return s;
  };

  const parts: Part[] = [];
  const MAX_PARTS = 240;

  const emit = (x: number, y: number, text: string, a: number, v: number,
                ttl: number, size: number, center: boolean, delay = 0) => {
    if (parts.length >= MAX_PARTS) parts.shift();
    parts.push({ x, y, text, a, v, ttl, size, center, delay, life: 0 });
  };

  const stepParts = (dt: number) => {
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      if (p.delay > 0) { p.delay -= dt; continue; }
      p.life += dt;
      if (p.life >= p.ttl) { parts.splice(i, 1); continue; }
      p.x += Math.cos(p.a) * p.v * dt;
      p.y += Math.sin(p.a) * p.v * dt;
      p.v *= Math.pow(0.12, dt);          // 감속 (프레임레이트 무관)
    }
  };

  // 캔버스가 화면 전체일 수도, 한 칸만 채울 수도 있다. 항상 자기 박스 기준으로 그린다.
  let boxW = 1, boxH = 1;

  const drawParts = (w: number, h: number) => {
    fx.clearRect(0, 0, w, h);
    fx.fillStyle = "#ffffff";
    fx.shadowColor = "rgba(16, 22, 66, .9)";
    fx.textBaseline = "middle";
    for (const p of parts) {
      if (p.delay > 0) continue;
      const k = p.life / p.ttl;
      fx.globalAlpha = Math.min(k / 0.1, 1) * Math.pow(1 - k, 1.6);
      fx.font = `${p.size}px ui-monospace, SFMono-Regular, Menlo, Consolas, "Segoe UI Symbol", monospace`;
      fx.textAlign = p.center ? "center" : "left";
      // 밝은 배경에서도 읽히도록 어두운 헤일로 위에 흰 글씨를 겹쳐 찍는다.
      fx.shadowBlur = 5;
      fx.fillText(p.text, p.x, p.y);
      fx.shadowBlur = 0;
      fx.fillText(p.text, p.x, p.y);
    }
    fx.globalAlpha = 1;
  };

  let raf = 0;
  let running = true;

  try {
    const prog = gl.createProgram()!;
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog) ?? "");
    gl.useProgram(prog);

    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const attr = gl.getAttribLocation(prog, "a");
    gl.enableVertexAttribArray(attr);
    gl.vertexAttribPointer(attr, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, "uRes");
    const uPhase = gl.getUniformLocation(prog, "uPhase");

    const resize = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      boxW = Math.max(1, Math.round(rect.width));
      boxH = Math.max(1, Math.round(rect.height));

      canvas.width = Math.round(boxW * dpr);
      canvas.height = Math.round(boxH * dpr);
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(uRes, canvas.width, canvas.height);

      overlay.width = Math.round(boxW * dpr);
      overlay.height = Math.round(boxH * dpr);
      fx.setTransform(dpr, 0, 0, dpr, 0, 0);   // 이후로는 CSS 픽셀로 그린다
    };
    resize();

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    const motion = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1;
    let px = -1e4, py = -1e4;

    /** 포인터 좌표를 캔버스 박스 기준으로 옮긴다. 박스 밖이면 null. */
    const local = (e: PointerEvent) => {
      const r = overlay.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      return x < 0 || y < 0 || x > r.width || y > r.height ? null : { x, y };
    };

    // 배경은 커서를 따라가지 않는다. 포인터는 글자 파티클을 뿌리는 데만 쓴다.
    const onMove = (e: PointerEvent) => {
      if (!motion) return;
      const p = local(e);
      if (!p) return;
      if (Math.hypot(p.x - px, p.y - py) < 58) return;
      px = p.x; py = p.y;
      const up = -Math.PI / 2 + (Math.random() - 0.5) * 0.9;
      emit(p.x + 16, p.y + 12 + Math.random() * 14,
           braille(5 + ((Math.random() * 6) | 0)), up, 26 + Math.random() * 22,
           1.5 + Math.random() * 0.5, 10, false);
    };

    const onDown = (e: PointerEvent) => {
      if (!motion) return;
      const p = local(e);
      if (!p) return;
      for (let ring = 0; ring < 3; ring++) {
        const n = 10 + ring * 5;
        for (let i = 0; i < n; i++) {
          const ang = (i / n) * Math.PI * 2 + ring * 0.35;
          emit(p.x, p.y, RING[(i + ring) % RING.length],
               ang, 330 + ring * 70, 0.85 + ring * 0.16,
               15 - ring * 1.6, true, ring * 0.11);
        }
      }
    };

    const onLost = (e: Event) => { e.preventDefault(); running = false; };

    addEventListener("pointermove", onMove, { passive: true });
    addEventListener("pointerdown", onDown);
    canvas.addEventListener("webglcontextlost", onLost);

    let phase = 0, last = 0;
    const frame = (ms: number) => {
      if (!running) return;
      const dt = Math.min((ms - last) / 1000, 0.1);   // 탭 복귀 시 점프 방지
      last = ms;

      phase += dt * 0.055 * motion;                   // 속도가 아니라 위상을 누적
      gl.uniform1f(uPhase, phase);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      stepParts(dt);
      drawParts(boxW, boxH);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    if (import.meta.env.DEV) {
      // 파티클이 수명 뒤 확실히 정리되는지 (누수·NaN 확인용)
      (window as unknown as Record<string, unknown>).__inkCheck = () => {
        const keep = parts.splice(0, parts.length);
        emit(10, 10, "x", 0, 300, 0.5, 12, false);
        emit(10, 10, "y", 1, 300, 0.5, 12, false, 0.3);
        for (let i = 0; i < 120; i++) stepParts(1 / 60);
        const leaked = parts.length;
        const finite = parts.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
        parts.push(...keep);
        return leaked === 0 && finite ? "OK — 파티클 정리됨" : `FAIL leaked=${leaked} finite=${finite}`;
      };
    }

    cleanup = () => {
      running = false;
      cancelAnimationFrame(raf);
      observer.disconnect();
      removeEventListener("pointermove", onMove);
      removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("webglcontextlost", onLost);
      // 브라우저가 유지하는 WebGL 컨텍스트 수는 제한돼 있다. 떠날 때 반납한다.
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  } catch (error) {
    console.warn("shader background off:", error);
  }
});

onBeforeUnmount(() => {
  cleanup?.();
  cleanup = null;
});
</script>

<template>
  <canvas ref="bgCanvas" class="ink-bg" aria-hidden="true"></canvas>
  <canvas ref="fxCanvas" class="ink-fx" aria-hidden="true"></canvas>
</template>

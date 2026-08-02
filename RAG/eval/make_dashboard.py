"""사람 검증 평가 결과 대시보드 생성 — 산출 JSON에서 수치를 주입한다.

수치를 손으로 적지 않는다. 리포트 JSON이 갱신되면 이 스크립트를 다시 돌려 대시보드를
재생성한다 — 대시보드와 산출물이 어긋나는 상태를 만들지 않기 위한 것이다.

입력: anchor/anchor_report_human.json, report_spec.json, ragas_report.json, contract_report.json
출력: eval/dashboard_human.html  (기존 report_dashboard.html은 자연어 트랙용이라 건드리지 않음)

실행: python -X utf8 -m eval.make_dashboard
"""
from __future__ import annotations

import json
from pathlib import Path

EVAL_DIR = Path(__file__).parent
OUT = EVAL_DIR / "dashboard_human.html"

ARMS = ["rrf_ce", "rrf", "bm25", "dense", "random"]
ARM_DESC = {
    "rrf_ce": "RRF 하이브리드 + 교차인코더 재순위",
    "rrf": "RRF 하이브리드 (BM25+dense 순위융합)",
    "bm25": "BM25 어휘 검색 단독",
    "dense": "임베딩 벡터 검색 단독",
    "random": "무작위 (바닥 기준선)",
}


def _load(name: str) -> dict:
    p = EVAL_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


# ── SVG 조각 ───────────────────────────────────────────

def kappa_chart(arms: list[dict], threshold: float, ceiling: float) -> str:
    """판정자별 κ 점추정 + 95% CI. 기준선과 사람 잡음 천장을 같은 축에 얹는다."""
    x0, x1 = 250, 660
    row_h, top = 46, 40
    h = top + row_h * len(arms) + 34
    sx = lambda v: x0 + (x1 - x0) * max(0.0, min(1.0, v))

    p = [f'<svg viewBox="0 0 700 {h}" role="img" class="chart" '
         f'aria-label="판정자별 Cohen 카파와 95% 신뢰구간">']
    # 축
    p.append(f'<line x1="{x0}" y1="{top - 14}" x2="{x1}" y2="{top - 14}" class="axis"/>')
    for t in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        p.append(f'<line x1="{sx(t):.1f}" y1="{top - 14}" x2="{sx(t):.1f}" y2="{h - 30}" class="grid"/>')
        p.append(f'<text x="{sx(t):.1f}" y="{h - 14}" class="tick mid">{t:.1f}</text>')
    # 기준선·천장
    p.append(f'<line x1="{sx(threshold):.1f}" y1="{top - 20}" x2="{sx(threshold):.1f}" '
             f'y2="{h - 30}" class="rule-crit"/>')
    p.append(f'<text x="{sx(threshold):.1f}" y="{top - 26}" class="rule-lbl crit mid">'
             f'기준 {threshold:.2f}</text>')
    p.append(f'<line x1="{sx(ceiling):.1f}" y1="{top - 20}" x2="{sx(ceiling):.1f}" '
             f'y2="{h - 30}" class="rule-mut"/>')
    p.append(f'<text x="{sx(ceiling):.1f}" y="{top - 26}" class="rule-lbl mut mid">'
             f'사람 천장 {ceiling:.3f}</text>')

    for i, a in enumerate(arms):
        y = top + row_h * i + row_h / 2
        k, ci = a["binary_kappa"], a["kappa_ci_95"]
        name, role = a["judge"].split(" (", 1)
        p.append(f'<text x="0" y="{y - 3}" class="rlabel">{esc(name)}</text>')
        p.append(f'<text x="0" y="{y + 12}" class="rsub">{esc(role.rstrip(")"))}</text>')
        p.append(f'<line x1="{sx(ci["lo"]):.1f}" y1="{y:.1f}" x2="{sx(ci["hi"]):.1f}" '
                 f'y2="{y:.1f}" class="ci"/>')
        for e in (ci["lo"], ci["hi"]):
            p.append(f'<line x1="{sx(e):.1f}" y1="{y - 5:.1f}" x2="{sx(e):.1f}" '
                     f'y2="{y + 5:.1f}" class="ci-cap"/>')
        p.append(f'<circle cx="{sx(k):.1f}" cy="{y:.1f}" r="5.5" class="dot s1">'
                 f'<title>{esc(a["judge"])}: κ={k:.4f}, 95% CI [{ci["lo"]:.4f}, {ci["hi"]:.4f}]</title></circle>')
        p.append(f'<text x="{x1 + 8}" y="{y + 4}" class="val">{k:.3f}</text>')
    p.append("</svg>")
    return "".join(p)


def arm_chart(macro_j: dict, macro_h: dict) -> str:
    """arm별 정규화 nDCG@3 — judge qrels vs 사람 반영 qrels 2계열."""
    x0, x1 = 92, 630
    grp, bar, gap, top = 44, 13, 2, 34
    h = top + grp * len(ARMS) + 30
    sx = lambda v: x0 + (x1 - x0) * max(0.0, min(1.0, v))

    p = [f'<svg viewBox="0 0 700 {h}" role="img" class="chart" '
         f'aria-label="검색 구성별 정규화 nDCG@3">']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        p.append(f'<line x1="{sx(t):.1f}" y1="{top - 12}" x2="{sx(t):.1f}" y2="{h - 28}" class="grid"/>')
        p.append(f'<text x="{sx(t):.1f}" y="{h - 12}" class="tick mid">{t:.2f}</text>')
    p.append(f'<line x1="{x0}" y1="{h - 28}" x2="{x1}" y2="{h - 28}" class="axis"/>')

    for i, arm in enumerate(ARMS):
        gy = top + grp * i
        p.append(f'<text x="0" y="{gy + 15}" class="rlabel mono">{esc(arm)}</text>')
        for j, (macro, cls, lab) in enumerate(
                ((macro_j, "s1", "judge qrels"), (macro_h, "s2", "사람 반영 qrels"))):
            v = macro[arm]["norm_ndcg3"]
            by = gy + 4 + j * (bar + gap)
            w = max(1.0, sx(v) - x0)
            p.append(f'<rect x="{x0}" y="{by}" width="{w:.1f}" height="{bar}" rx="4" '
                     f'class="bar {cls}"><title>{esc(arm)} / {esc(lab)}: {v:.4f}</title></rect>')
            p.append(f'<text x="{x0 + w + 7:.1f}" y="{by + bar - 2}" class="val">{v:.3f}</text>')
    p.append("</svg>")
    return "".join(p)


def forest_chart(comps: dict, comps_ref: dict) -> str:
    """쌍대 부트스트랩 CI — 0선을 걸치면 '구분 불가'다."""
    items = list(comps.items())
    lo = min(v["ci_95"][0] for _, v in items)
    hi = max(v["ci_95"][1] for _, v in items)
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    x0, x1 = 160, 600
    row_h, top = 30, 30
    h = top + row_h * len(items) + 30
    sx = lambda v: x0 + (x1 - x0) * (v - lo) / (hi - lo)

    p = [f'<svg viewBox="0 0 700 {h}" role="img" class="chart" '
         f'aria-label="구성 간 차이의 95% 신뢰구간">']
    for t in (-0.2, 0.0, 0.2, 0.4, 0.6, 0.8):
        if lo <= t <= hi:
            cls = "zero" if abs(t) < 1e-9 else "grid"
            p.append(f'<line x1="{sx(t):.1f}" y1="{top - 12}" x2="{sx(t):.1f}" y2="{h - 28}" class="{cls}"/>')
            p.append(f'<text x="{sx(t):.1f}" y="{h - 12}" class="tick mid">{t:+.1f}</text>')
    p.append(f'<text x="{sx(0):.1f}" y="{top - 18}" class="rule-lbl mut mid">차이 없음</text>')

    for i, (key, v) in enumerate(items):
        y = top + row_h * i + row_h / 2
        sig = v["significant"]
        flip = comps_ref.get(key, {}).get("significant") != sig
        cls = "s1" if sig else "nul"
        a, b = key.split("_vs_")
        p.append(f'<text x="0" y="{y + 4}" class="rlabel mono sm">{esc(a)} vs {esc(b)}</text>')
        p.append(f'<line x1="{sx(v["ci_95"][0]):.1f}" y1="{y:.1f}" x2="{sx(v["ci_95"][1]):.1f}" '
                 f'y2="{y:.1f}" class="ci {cls}"/>')
        p.append(f'<circle cx="{sx(v["mean_delta"]):.1f}" cy="{y:.1f}" r="4.5" class="dot {cls}">'
                 f'<title>{esc(key)}: Δ={v["mean_delta"]:+.4f}, '
                 f'CI [{v["ci_95"][0]:+.4f}, {v["ci_95"][1]:+.4f}]</title></circle>')
        tag = "유의" if sig else "구분 불가"
        p.append(f'<text x="{x1 + 10}" y="{y + 4}" class="tag {cls}">{tag}'
                 f'{" ※" if flip else ""}</text>')
    p.append("</svg>")
    return "".join(p)


def strip_chart(dists: dict, sat: dict) -> str:
    """질의별 nDCG@3을 점으로 흩뿌린다 — 오른쪽 끝(1.00)에 뭉치면 천장 포화다.
    같은 값이 겹치면 세로로 벌려 개수가 보이게 한다."""
    order = [a for a in ARMS if a in dists]
    x0, x1 = 92, 610
    row_h, top = 52, 26
    h = top + row_h * len(order) + 30
    sx = lambda v: x0 + (x1 - x0) * max(0.0, min(1.0, v))
    p = [f'<svg viewBox="0 0 700 {h}" role="img" class="chart" '
         f'aria-label="질의별 nDCG@3 분포와 천장 포화">']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        p.append(f'<line x1="{sx(t):.1f}" y1="{top - 10}" x2="{sx(t):.1f}" y2="{h - 28}" class="grid"/>')
        p.append(f'<text x="{sx(t):.1f}" y="{h - 12}" class="tick mid">{t:.2f}</text>')
    p.append(f'<line x1="{sx(1.0):.1f}" y1="{top - 16}" x2="{sx(1.0):.1f}" y2="{h - 28}" class="rule-crit"/>')
    p.append(f'<text x="{sx(1.0):.1f}" y="{top - 20}" class="rule-lbl crit mid">만점 = 측정 여지 없음</text>')
    for i, arm in enumerate(order):
        cy = top + row_h * i + row_h / 2
        s = sat[arm]
        p.append(f'<text x="0" y="{cy - 2}" class="rlabel mono sm">{esc(arm)}</text>')
        p.append(f'<text x="0" y="{cy + 12}" class="rsub">만점 {s["n_at_ceiling"]}/{s["n_queries"]}'
                 f' · 값 {s["n_distinct_values"]}종</text>')
        seen: dict[float, int] = {}
        for v in dists[arm]:
            key = round(v, 4)
            n = seen.get(key, 0)
            seen[key] = n + 1
            dy = (n % 5) * 6 - 12 if n else 0
            cls = "crit" if v >= 0.999 else "s1"
            p.append(f'<circle cx="{sx(v):.1f}" cy="{cy + dy:.1f}" r="4" class="pt {cls}">'
                     f'<title>{esc(arm)}: nDCG@3 = {v:.4f}</title></circle>')
    p.append("</svg>")
    return "".join(p)


def k_forest_chart(multi_k: dict, keys: list[str]) -> str:
    """같은 비교를 절단 k별로 늘어놓는다 — k를 깊게 해도 0선을 벗어나지 못하면
    그 차이는 절단 탓이 아니라 실제로 없는 것이다."""
    rows = [(key, kk, multi_k[kk]["comparisons"][key])
            for key in keys for kk in multi_k]
    lo = min(r[2]["ci_95"][0] for r in rows)
    hi = max(r[2]["ci_95"][1] for r in rows)
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    x0, x1 = 170, 590
    row_h, top, grp_gap = 26, 34, 16
    h = top + row_h * len(rows) + grp_gap * (len(keys) - 1) + 30
    sx = lambda v: x0 + (x1 - x0) * (v - lo) / (hi - lo)
    p = [f'<svg viewBox="0 0 700 {h}" role="img" class="chart" '
         f'aria-label="절단 k별 구성 간 차이의 신뢰구간">']
    for t in (-0.1, 0.0, 0.1, 0.2, 0.3):
        if lo <= t <= hi:
            p.append(f'<line x1="{sx(t):.1f}" y1="{top - 12}" x2="{sx(t):.1f}" '
                     f'y2="{h - 28}" class="{"zero" if abs(t) < 1e-9 else "grid"}"/>')
            p.append(f'<text x="{sx(t):.1f}" y="{h - 12}" class="tick mid">{t:+.1f}</text>')
    p.append(f'<text x="{sx(0):.1f}" y="{top - 18}" class="rule-lbl mut mid">차이 없음</text>')
    y = top
    for gi, key in enumerate(keys):
        a, b = key.split("_vs_")
        y += gi and grp_gap or 0
        p.append(f'<text x="0" y="{y + 12}" class="rlabel mono sm">{esc(b)} vs {esc(a)}</text>')
        for kk in multi_k:
            c = multi_k[kk]["comparisons"][key]
            cy = y + row_h / 2
            cls = "s1" if c["significant"] else "nul"
            p.append(f'<text x="112" y="{cy + 4}" class="tick">{esc(kk)}</text>')
            p.append(f'<line x1="{sx(c["ci_95"][0]):.1f}" y1="{cy:.1f}" '
                     f'x2="{sx(c["ci_95"][1]):.1f}" y2="{cy:.1f}" class="ci {cls}"/>')
            p.append(f'<circle cx="{sx(c["mean_delta"]):.1f}" cy="{cy:.1f}" r="4" class="dot {cls}">'
                     f'<title>{esc(key)} @{esc(kk)}: Δ={c["mean_delta"]:+.4f} '
                     f'CI [{c["ci_95"][0]:+.4f}, {c["ci_95"][1]:+.4f}]</title></circle>')
            p.append(f'<text x="{x1 + 10}" y="{cy + 4}" class="tag {cls}">'
                     f'{"유의" if c["significant"] else "구분 불가"}</text>')
            y += row_h
    p.append("</svg>")
    return "".join(p)


def ragas_chart(summary: dict, coverage: dict) -> str:
    order = [("context_precision_id", "context precision (ID기반)", "s1", "결정적"),
             ("context_recall_id", "context recall (ID기반)", "s1", "결정적"),
             ("faithfulness", "faithfulness", "s2", "LLM 판정"),
             ("answer_relevancy", "answer relevancy", "s2", "LLM 판정")]
    x0, x1 = 210, 600
    row_h, bar, top = 40, 14, 24
    h = top + row_h * len(order) + 30
    sx = lambda v: x0 + (x1 - x0) * max(0.0, min(1.0, v))
    p = [f'<svg viewBox="0 0 700 {h}" role="img" class="chart" aria-label="RAGAS 4축 점수">']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        p.append(f'<line x1="{sx(t):.1f}" y1="{top - 10}" x2="{sx(t):.1f}" y2="{h - 28}" class="grid"/>')
        p.append(f'<text x="{sx(t):.1f}" y="{h - 12}" class="tick mid">{t:.2f}</text>')
    p.append(f'<line x1="{x0}" y1="{h - 28}" x2="{x1}" y2="{h - 28}" class="axis"/>')
    for i, (key, label, cls, kind) in enumerate(order):
        if key not in summary:
            continue
        v, cov = summary[key], coverage.get(key, "")
        y = top + row_h * i
        p.append(f'<text x="0" y="{y + 11}" class="rlabel sm">{esc(label)}</text>')
        p.append(f'<text x="0" y="{y + 25}" class="rsub">{esc(kind)} · 표본 {esc(cov)}</text>')
        w = max(1.0, sx(v) - x0)
        p.append(f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="{bar}" rx="4" class="bar {cls}">'
                 f'<title>{esc(label)}: {v:.4f} (표본 {esc(cov)})</title></rect>')
        p.append(f'<text x="{x0 + w + 7:.1f}" y="{y + bar - 2}" class="val">{v:.3f}</text>')
    p.append("</svg>")
    return "".join(p)


# ── HTML ───────────────────────────────────────────────

CSS = """
:root{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --mut:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --bd:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834; --nul:#898781;
  --good:#0ca30c; --warn:#fab219; --crit:#d03b3b;
  --hm0:#cde2fb; --hm1:#9ec5f4; --hm2:#5598e7; --hm3:#256abf; --hm4:#104281;
  /* 셀 텍스트 색은 대비 실측으로 결정 (WCAG 4.5:1 이상). 밝은쪽 step2는 흰 글씨가
     2.99:1로 미달이라 잉크색으로 내린다 — 6.59:1. */
  --hm0t:#0b0b0b; --hm1t:#0b0b0b; --hm2t:#0b0b0b; --hm3t:#ffffff; --hm4t:#ffffff;
  --sans:system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --mut:#898781;
  --grid:#2c2c2a; --axis:#383835; --bd:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926;
  --hm0:#0d366b; --hm1:#184f95; --hm2:#256abf; --hm3:#5598e7; --hm4:#9ec5f4;
  --hm0t:#ffffff; --hm1t:#ffffff; --hm2t:#ffffff; --hm3t:#0b0b0b; --hm4t:#0b0b0b;
}}
:root[data-theme=dark]{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --mut:#898781;
  --grid:#2c2c2a; --axis:#383835; --bd:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926;
  --hm0:#0d366b; --hm1:#184f95; --hm2:#256abf; --hm3:#5598e7; --hm4:#9ec5f4;
  --hm0t:#ffffff; --hm1t:#ffffff; --hm2t:#ffffff; --hm3t:#0b0b0b; --hm4t:#0b0b0b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);font-family:var(--sans);
  line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:48px 24px 96px}
header.top{border-bottom:2px solid var(--ink);padding-bottom:20px;margin-bottom:8px}
.eyebrow{font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--mut);
  font-family:var(--mono);margin:0 0 10px}
h1{font-size:clamp(26px,4vw,40px);line-height:1.15;margin:0 0 12px;text-wrap:balance;
  letter-spacing:-.02em;font-weight:640}
.dek{font-size:17px;color:var(--ink2);margin:0;max-width:64ch}
.meta{display:flex;flex-wrap:wrap;gap:6px 20px;margin-top:16px;font-family:var(--mono);
  font-size:11.5px;color:var(--mut)}
section{margin-top:44px}
h2{font-size:20px;margin:0 0 6px;letter-spacing:-.01em;font-weight:640;
  display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h2 .n{font-family:var(--mono);font-size:11px;color:var(--mut);letter-spacing:.1em}
h3{font-size:15px;margin:26px 0 8px;font-weight:640}
.lede{color:var(--ink2);margin:0 0 18px;max-width:70ch;font-size:14.5px}
p{margin:0 0 12px}
.card{background:var(--surface);border:1px solid var(--bd);border-radius:10px;padding:20px 22px}
.grid2{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
/* 게이트 */
.gates{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.gate{background:var(--surface);border:1px solid var(--bd);border-radius:10px;
  padding:16px 18px;border-left:4px solid var(--mut)}
.gate.pass{border-left-color:var(--good)} .gate.fail{border-left-color:var(--crit)}
.gate.na{border-left-color:var(--warn)}
.gate .nm{font-size:12.5px;color:var(--ink2);margin:0 0 6px;font-weight:600}
.gate .st{display:flex;align-items:center;gap:8px;font-size:22px;font-weight:660;margin-bottom:6px}
.gate .st .ic{font-size:14px}
.gate.pass .st{color:var(--good)} .gate.fail .st{color:var(--crit)} .gate.na .st{color:var(--warn)}
.gate .why{font-size:12px;color:var(--mut);font-family:var(--mono);line-height:1.5}
/* 핵심수치 */
.tiles{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.tile{background:var(--surface);border:1px solid var(--bd);border-radius:10px;padding:16px 18px}
.tile .k{font-size:11.5px;color:var(--mut);margin:0 0 4px;font-family:var(--mono)}
.tile .v{font-size:29px;font-weight:660;letter-spacing:-.02em;line-height:1.1}
.tile .s{font-size:12px;color:var(--ink2);margin-top:4px}
/* 차트 */
.chart{width:100%;height:auto;display:block;overflow:visible}
.chart text{font-family:var(--sans);fill:var(--ink2)}
.chart .rlabel{font-size:12.5px;fill:var(--ink);font-weight:600}
.chart .rlabel.sm{font-size:11.5px}
.chart .rsub{font-size:10.5px;fill:var(--mut)}
.chart .mono,.chart .val,.chart .tick,.chart .tag{font-family:var(--mono)}
.chart .val{font-size:11.5px;fill:var(--ink);font-variant-numeric:tabular-nums}
.chart .tick{font-size:10px;fill:var(--mut)}
.chart .mid{text-anchor:middle}
.chart .tag{font-size:10.5px}
.chart .tag.s1{fill:var(--s1)} .chart .tag.nul{fill:var(--mut)}
.chart .grid{stroke:var(--grid);stroke-width:1}
.chart .axis{stroke:var(--axis);stroke-width:1}
.chart .zero{stroke:var(--ink2);stroke-width:1.5}
.chart .ci{stroke:var(--s1);stroke-width:2;opacity:.55}
.chart .ci.nul{stroke:var(--nul)}
.chart .ci-cap{stroke:var(--s1);stroke-width:2;opacity:.55}
.chart .dot.s1{fill:var(--s1)} .chart .dot.nul{fill:var(--nul)}
.chart .bar.s1{fill:var(--s1)} .chart .bar.s2{fill:var(--s2)}
.chart .pt{stroke:var(--surface);stroke-width:2}
.chart .pt.s1{fill:var(--s1)} .chart .pt.crit{fill:var(--crit)}
.chart .rule-crit{stroke:var(--crit);stroke-width:2}
.chart .rule-mut{stroke:var(--mut);stroke-width:2}
.chart .rule-lbl{font-size:10.5px;font-family:var(--mono)}
.chart .rule-lbl.crit{fill:var(--crit)} .chart .rule-lbl.mut{fill:var(--mut)}
.legend{display:flex;gap:18px;flex-wrap:wrap;margin:2px 0 14px;font-size:12.5px;color:var(--ink2)}
.legend span{display:flex;align-items:center;gap:7px}
.sw{width:13px;height:13px;border-radius:3px;flex:none}
.sw.s1{background:var(--s1)} .sw.s2{background:var(--s2)} .sw.nul{background:var(--nul)}
/* 표 */
.scroll{overflow-x:auto;border:1px solid var(--bd);border-radius:10px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:right;padding:9px 12px;border-bottom:1px solid var(--bd);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);
  font-weight:600;background:var(--plane);position:sticky;top:0}
tbody tr:last-child td{border-bottom:0}
td.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
td.best{font-weight:680;color:var(--s1)}
.hm td.c{text-align:center;font-family:var(--mono);font-variant-numeric:tabular-nums;
  font-weight:600;border:2px solid var(--surface);border-radius:0}
.hm td.c[data-step="0"]{background:var(--hm0);color:var(--hm0t)}
.hm td.c[data-step="1"]{background:var(--hm1);color:var(--hm1t)}
.hm td.c[data-step="2"]{background:var(--hm2);color:var(--hm2t)}
.hm td.c[data-step="3"]{background:var(--hm3);color:var(--hm3t)}
.hm td.c[data-step="4"]{background:var(--hm4);color:var(--hm4t)}
details{margin-top:14px;border:1px solid var(--bd);border-radius:10px;background:var(--surface)}
details>summary{cursor:pointer;padding:12px 16px;font-size:13px;font-weight:600;color:var(--ink2)}
details>summary:hover{color:var(--ink)}
details[open]>summary{border-bottom:1px solid var(--bd)}
details .in{padding:4px}
details .in .scroll{border:0;border-radius:0}
:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
/* 해설 */
.note{border-left:3px solid var(--s1);padding:12px 0 12px 16px;margin:16px 0;
  font-size:14px;color:var(--ink2);background:transparent}
.note strong{color:var(--ink)}
.warnbox{border-left:3px solid var(--crit);padding:12px 0 12px 16px;margin:16px 0;font-size:14px}
.warnbox strong{color:var(--crit)}
.gloss{display:grid;gap:0;grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.gi{padding:14px 18px;border-top:1px solid var(--bd)}
.gi dt{font-weight:660;font-size:13.5px;margin-bottom:3px}
.gi dt .en{font-family:var(--mono);font-size:11.5px;color:var(--mut);font-weight:400;margin-left:6px}
.gi dd{margin:0;font-size:13px;color:var(--ink2);line-height:1.6}
ul.tight{margin:0 0 12px;padding-left:20px;font-size:14px;color:var(--ink2)}
ul.tight li{margin-bottom:7px}
ul.tight strong{color:var(--ink)}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--bd);
  font-family:var(--mono);font-size:11.5px;color:var(--mut)}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def build() -> str:
    hum = _load("anchor/anchor_report_human.json")
    spec = _load("report_spec.json")
    rag = _load("ragas_report.json")
    con = _load("contract_report.json")

    arms_h = [a for a in hum["arms"] if a.get("n_compared")]
    g3, g3b, nc = hum["gate3"], hum["gate3b_human_self_consistency"], hum["noise_ceiling"]
    ci0 = arms_h[0]["kappa_ci_95"]
    inconclusive = ci0["lo"] <= g3["threshold"] <= ci0["hi"]

    mj = spec["qrels_judge_only"]["macro_average"]
    mh = spec["qrels_human_patched"]["macro_average"]
    cj = spec["qrels_judge_only"]["comparisons"]
    ch = spec["qrels_human_patched"]["comparisons"]
    sens, prov, ver = spec["label_sensitivity"], spec["label_provenance"], spec["version"]
    axes = spec["qrels_human_patched"]["by_role_axis"]
    pq = spec["qrels_human_patched"]["per_query"]

    best = sens["ranking_human_patched"][0]
    n_sig = sum(1 for v in ch.values() if v["significant"])

    h = ['<title>RAG 검색 성능 평가 — 사람 검증 결과</title>', f"<style>{CSS}</style>",
         '<div class="wrap">']

    # ── 헤더
    h.append(f"""<header class="top">
<p class="eyebrow">사람 채점 반영 · 정규화 질의 트랙</p>
<h1>RAG 검색 성능 평가 결과</h1>
<p class="dek">사람이 앵커 {hum['n_human_primary']}쌍을 손수 라벨링해, 이 프로젝트 최초로
<strong>사람 기준</strong> 측정이 됐다. 그전까지의 신뢰도 수치는 모두 LLM 대 LLM 비교였다.</p>
<div class="meta">
<span>판정 프롬프트 {esc(hum['judge_prompt_version'])}</span>
<span>질의 {ver['n_queries']}종</span>
<span>판정 {ver['n_judged_pairs']}쌍</span>
<span>사람 검증 {prov['human_verified_pairs']}쌍 ({prov['coverage']:.1%})</span>
<span>풀 depth {ver['pool_depth']}</span>
<span>{esc(ver['pool_generated_at'][:10])}</span>
</div></header>""")

    # ── 한눈에
    h.append(f"""<section><h2>한눈에 <span class="n">요약</span></h2>
<div class="tiles">
<div class="tile"><p class="k">최고 성능 구성</p><div class="v mono">{esc(best)}</div>
<p class="s">정규화 nDCG@3 {mh[best]['norm_ndcg3']:.3f}</p></div>
<div class="tile"><p class="k">판정 신뢰도 κ</p><div class="v">{g3['value']:.3f}</div>
<p class="s">기준 {g3['threshold']:.2f} · {'판정 불가' if inconclusive else g3['verdict']}</p></div>
<div class="tile"><p class="k">사람 자기일관성</p><div class="v">{g3b['binary_kappa']:.3f}</div>
<p class="s">측정 가능한 상한(천장)</p></div>
<div class="tile"><p class="k">순위 라벨 강건성</p>
<div class="v" style="color:var(--good)">{'동일' if sens['ranking_stable'] else '변동'}</div>
<p class="s">두 qrels에서 arm 순위 {'불변' if sens['ranking_stable'] else '변동'}</p></div>
<div class="tile"><p class="k">구분된 비교</p><div class="v">{n_sig}<span style="font-size:16px;color:var(--mut)">/{len(ch)}</span></div>
<p class="s">나머지는 표본 부족으로 구분 불가</p></div>
</div>""")

    h.append(f"""<div class="warnbox"><strong>먼저 읽을 것.</strong>
<code>{esc(best)}</code>가 점수상 1위지만, <strong>2·3위와 통계적으로 구분되지 않는다</strong>
(rrf 대비 CI [{ch['rrf_vs_rrf_ce']['ci_95'][0]:+.3f}, {ch['rrf_vs_rrf_ce']['ci_95'][1]:+.3f}],
bm25 대비 CI [{ch['bm25_vs_rrf_ce']['ci_95'][0]:+.3f}, {ch['bm25_vs_rrf_ce']['ci_95'][1]:+.3f}] —
둘 다 0을 포함). 질의 {ver['n_queries']}종은 상위 구성들을 가려낼 검정력이 없다.
<strong>"검색이 작동하며 무작위·단독 방식보다 낫다"까지가 이 데이터로 방어되는 결론이고,
"어떤 구성을 채택할지"는 아직 결론이 아니다.</strong></div></section>""")

    # ── 게이트
    tier0 = "PASS" if con.get("all_passed") else "FAIL"
    n_checks = len(con.get("checks", []))
    g3_cls = "na" if inconclusive else ("pass" if g3["verdict"] == "PASS" else "fail")
    g3_txt = "판정 불가" if inconclusive else g3["verdict"]
    g3_ic = "◐" if inconclusive else ("✓" if g3["verdict"] == "PASS" else "✕")
    g3b_pass = str(g3b["verdict"]).startswith("PASS")
    h.append(f"""<section><h2>게이트 현황 <span class="n">사전 등록 기준</span></h2>
<p class="lede">게이트는 측정 전에 정해둔 통과 조건이다. 실패한 게이트가 있으면 그 영향을 받는
수치는 헤드라인으로 인용하지 않는다 — 기준을 사후에 바꾸지 않기 위한 장치다.</p>
<div class="gates">
<div class="gate pass"><p class="nm">Tier 0 · 입출력 계약</p>
<div class="st"><span class="ic">✓</span>{tier0}</div>
<p class="why">{n_checks}/{n_checks} 검사 통과<br>결정적 검사 · LLM 무관</p></div>
<div class="gate {g3_cls}"><p class="nm">게이트 3 · 판정 신뢰도 (κ ≥ {g3['threshold']:.2f})</p>
<div class="st"><span class="ic">{g3_ic}</span>{g3_txt}</div>
<p class="why">κ = {g3['value']:.4f} (기준까지 {g3['threshold'] - g3['value']:+.4f})<br>
95% CI [{ci0['lo']:.3f}, {ci0['hi']:.3f}] → 기준선 포함</p></div>
<div class="gate {'pass' if g3b_pass else 'fail'}"><p class="nm">게이트 3b · 채점자 자기일관성</p>
<div class="st"><span class="ic">{'✓' if g3b_pass else '✕'}</span>{'PASS' if g3b_pass else 'FAIL'}</div>
<p class="why">κ = {g3b['binary_kappa']:.3f} · 3분류 {g3b['exact_3class_agreement']:.3f}<br>
재검사 {g3b['n_overlap']}쌍</p></div>
</div>
<div class="note"><strong>게이트 3은 "실패"가 아니라 "판정 불가"다.</strong>
점추정 {g3['value']:.4f}는 기준 {g3['threshold']:.2f}에 {g3['threshold'] - g3['value']:.4f} 미달이지만,
{hum['n_human_primary']}쌍 표본의 95% 신뢰구간이 기준선을 포함한다. 사전 등록 규칙대로
<strong>FAIL로 기록</strong>하되(기준을 사후에 낮추지 않는다), 이것은 통과 실패가 확정된 것이 아니라
표본이 판정을 낼 만큼 크지 않다는 뜻이다.</div>
<div class="note"><strong>게이트 3b가 처음으로 실제 작동했다.</strong>
이전 LLM 앵커는 temperature 0이라 같은 항목에 늘 같은 답을 내 κ가 구조적으로 1.0이었고
아무것도 검출하지 못했다. 사람 재검사 {g3b['n_overlap']}쌍에서 κ = {g3b['binary_kappa']:.3f},
<strong>이진 판정 원일치율 {g3b['binary_agreement_raw']:.1%}</strong>
(3분류 {g3b['exact_3class_agreement']:.1%}) — 즉 사람이 뒤집은 것은
<strong>{1 - g3b['binary_agreement_raw']:.1%}</strong>다.
<em>κ는 우연 일치를 보정한 값이므로 (1−κ)를 뒤집힘 비율로 읽으면 안 된다</em>
— 그렇게 읽으면 14.5%로 3배 과장된다.</div></section>""")

    # ── 판정자 신뢰도
    h.append(f"""<section><h2>누가 사람과 가장 비슷하게 판정하나 <span class="n">판정 신뢰도</span></h2>
<p class="lede">사람 라벨을 정답으로 두고 판정자 셋을 대조했다. 가로선은 95% 신뢰구간 —
길수록 표본이 부족해 값이 불확실하다는 뜻이다.</p>
{kappa_chart(arms_h, g3['threshold'], nc['human_self_kappa'])}
<div class="legend"><span><span class="sw s1"></span>κ 점추정 · 가로선 95% CI</span>
<span style="color:var(--crit)">│ 사전 등록 기준</span>
<span style="color:var(--mut)">│ 사람 자기일관성 = 도달 가능한 상한</span></div>""")

    h.append(f"""<div class="note"><strong>천장을 알고 나서야 기준의 의미가 보인다.</strong>
사람 자신의 일관성이 κ = {nc['human_self_kappa']:.3f}이므로, 어떤 판정기도 그 위로 갈 수 없다
— 정답 자체가 그만큼 흔들리기 때문이다. 본판정 judge는 천장의
<strong>{nc['attainment_vs_ceiling']:.1%}</strong>에 도달했고, 기준 {g3['threshold']:.2f}는
천장의 {nc['threshold_as_pct_of_ceiling']:.1%}를 요구한다. 애초에 여유가 거의 없는 기준이었다.</div>""")

    h.append("""<div class="scroll"><table><thead><tr>
<th>판정자</th><th>κ</th><th>95% CI</th><th>이진 일치</th><th>3분류 일치</th>
<th>정밀도</th><th>재현율</th><th>편향 방향</th></tr></thead><tbody>""")
    for a in arms_h:
        ci = a["kappa_ci_95"]
        mc = a["mcnemar"]
        dirs = {"judge inflates positives": "적합 과다 판정",
                "judge deflates positives": "적합 과소 판정", "balanced": "균형"}
        h.append(f"""<tr><td>{esc(a['judge'])}</td>
<td class="num best">{a['binary_kappa']:.4f}</td>
<td class="num">[{ci['lo']:.3f}, {ci['hi']:.3f}]</td>
<td class="num">{a['binary_agreement']:.4f}</td>
<td class="num">{a['exact_3class_agreement']:.4f}</td>
<td class="num">{a['precision_vs_human']:.4f}</td>
<td class="num">{a['recall_vs_human']:.4f}</td>
<td>{dirs.get(mc['direction'], mc['direction'])} (b={mc['b_human_pos_judge_neg']}, c={mc['c_human_neg_judge_pos']})</td></tr>""")
    h.append("</tbody></table></div>")

    h.append(f"""<div class="note"><strong>중요한 반전 둘.</strong>
① 더 큰 모델(gemini-2.5-flash)을 판정기로 올리려던 실험은 사전 등록 기준 미달로 기각했는데,
사람 기준으로 보니 실제로 <strong>더 나빴다</strong>(κ {arms_h[1]['binary_kappa']:.3f} &lt;
{arms_h[0]['binary_kappa']:.3f}). 기각이 옳았다.
② 그간 정답 대리로 써온 Claude 앵커도 사람에서 더 멀다(κ {arms_h[2]['binary_kappa']:.3f}).
<strong>즉 과거의 신뢰도 수치는 열등한 대리 기준에 맞춰 재고 있었다.</strong>
LLM끼리의 일치도는 사람과의 일치도를 대신하지 못한다.</div></section>""")

    # ── 검색 성능
    h.append(f"""<section><h2>검색 성능 <span class="n">정규화 nDCG@3</span></h2>
<p class="lede">0 = <strong>풀 안에서 무작위로 뽑은</strong> 수준(코퍼스 무작위보다 훨씬 높은 기준선),
1 = 완벽한 정렬. 같은 검색 결과를 두 가지 정답표로
채점했다 — 판정기 라벨만 쓴 것과, 사람이 라벨한 {prov['human_verified_pairs']}쌍을 사람 것으로 덮어쓴 것.</p>
{arm_chart(mj, mh)}
<div class="legend"><span><span class="sw s1"></span>judge qrels (판정기 라벨 439쌍)</span>
<span><span class="sw s2"></span>사람 반영 qrels (사람 {prov['human_verified_pairs']}쌍 덮어씀)</span></div>""")

    h.append(f"""<div class="note"><strong>순위가 정답표를 바꿔도 그대로다.</strong>
사람 라벨을 넣으면 이진 판정이 {prov['human_flip_rate']:.1%} 뒤집히고 절대 점수는 대체로 내려가지만
(bm25 {sens['delta_norm_ndcg3']['bm25']:+.3f}이 가장 크게 하락), 순위는
<code>{' &gt; '.join(esc(a) for a in sens['ranking_human_patched'])}</code>로 동일하다.
<strong>순위 결론은 라벨 오차에 강건하고, 절대 수치는 그렇지 않다.</strong>
가장 덜 흔들린 건 {esc(best)}({sens['delta_norm_ndcg3'][best]:+.3f})다.</div>""")

    h.append("""<div class="scroll"><table><thead><tr><th>구성</th><th>설명</th>
<th>nDCG@3</th><th>P@3</th><th>AP@3</th><th>정규화 nDCG@3</th><th>Δ vs judge qrels</th>
</tr></thead><tbody>""")
    for arm in ARMS:
        d = sens["delta_norm_ndcg3"][arm]
        h.append(f"""<tr><td class="num">{esc(arm)}</td><td>{esc(ARM_DESC[arm])}</td>
<td class="num">{mh[arm]['ndcg3']:.4f}</td><td class="num">{mh[arm]['p3']:.4f}</td>
<td class="num">{mh[arm]['ap3']:.4f}</td>
<td class="num{' best' if arm == best else ''}">{mh[arm]['norm_ndcg3']:.4f}</td>
<td class="num">{d:+.4f}</td></tr>""")
    h.append("</tbody></table></div>")
    h.append('<p class="lede" style="margin-top:8px;font-size:12.5px">표 수치는 '
             '사람 반영 qrels 기준. Δ는 판정기 라벨만 썼을 때와의 차이.</p>')

    # ── 유의성
    h.append(f"""<h3>무엇이 구분되고, 무엇이 구분되지 않는가</h3>
<p class="lede">두 구성의 차이를 질의 단위로 재표집해 95% 신뢰구간을 낸 것이다.
구간이 <strong>0을 걸치면</strong> 그 차이는 우연과 구별되지 않는다 — 즉 두 구성의 우열을 말할 수 없다.</p>
{forest_chart(ch, cj)}
<div class="legend"><span><span class="sw s1"></span>유의 — 차이 확인</span>
<span><span class="sw nul"></span>구분 불가 — 0을 포함</span>
<span style="color:var(--mut)">※ 판정기 라벨만 쓸 때와 결론이 달라진 비교</span></div>
<div class="warnbox"><strong>{esc(best)}의 우위는 확정되지 않았다.</strong>
무작위·dense 대비로는 확실히 낫지만, <code>rrf</code>·<code>bm25</code>와는 구간이 겹친다.
특히 <code>bm25_vs_rrf_ce</code>는 판정기 라벨에서는 유의했는데
사람 라벨을 넣으면 유의성이 사라진다 — <strong>사람 검증이 오히려 근거를 약화시켰다.</strong>
교차인코더는 질의당 0.836초로 다른 방식(0.006~0.04초)의 20배 이상 비싸다.
현재 데이터로는 그 비용을 정당화할 수 없다.</div></section>""")

    # ── k=3 해석 유효성
    ka = spec["k_analysis"]
    gc, ac, pa = ka["grade_composition"], ka["ambiguous_credit"], ka["p3_vs_attainable"]
    rb, sat = ka["random_baselines"], ka["saturation"]
    zr, tr = ka["zero_relevant_queries"], ka["thin_relevant_queries"]
    cr = sat[best]["ceiling_rate"]
    n_q = len(pq)
    avg_pool = sum(v["n_judged"] for v in pq.values()) / n_q
    avg_rel = sum(v["n_relevant"] for v in pq.values()) / n_q
    ratio = mh[best]["p3"] / max(mh["random"]["p3"], 1e-9)

    h.append(f"""<section><h2>절단 k=3에서 이 수치를 어디까지 믿을 수 있나
<span class="n">해석 유효성</span></h2>
<p class="lede">위 모든 점수는 <strong>상위 3건만</strong> 채점한 결과다. 이 절단이 타당한지,
타당하다면 수치를 어떻게 읽어야 하는지를 따로 진단했다.</p>
<div class="note"><strong>절단 자체는 옳게 골랐다.</strong> {esc(ka['product_cutoff'])}.
지표의 절단은 <strong>시스템이 실제로 내리는 결정의 크기와 같아야</strong> 하고, 그 점에서 k=3은
임의로 고른 숫자가 아니다. 문제는 타당성이 아니라 <strong>해상도</strong>다 — 아래 셋이
절대 수치를 낙관 쪽으로 민다.</div>

<h3>① 천장 포화 — 만점이 {sat[best]['n_at_ceiling']}/{sat[best]['n_queries']}질의</h3>
<p class="lede">점 하나가 질의 하나다. 오른쪽 끝(1.00)에 뭉친 만큼은 <strong>이미 만점이라
개선을 측정할 수 없는 구간</strong>이다.</p>
{strip_chart(ka['ndcg3_distribution'], sat)}
<div class="legend"><span><span class="sw s1"></span>측정 여지 있음</span>
<span><span class="sw" style="background:var(--crit)"></span>만점 — 개선을 잴 수 없음</span></div>
<div class="warnbox"><strong>"질의가 15종이라 검정력이 부족하다"는 진단은 절반만 맞았다.</strong>
<code>{esc(best)}</code>는 서로 다른 값이 {sat[best]['n_distinct_values']}종뿐이고
{cr:.0%}가 만점이다. 구성 간 우열이 안 갈리는 건 질의 수만의 문제가 아니라
<strong>지표가 포화됐기 때문</strong>이다. 질의당 후보 {avg_pool:.0f}건 중 적합이 평균
{avg_rel:.1f}건이니, 상위 3건에 적합을 넣는 건 애초에 어려운 과제가 아니었다.</div>

<h3>② nDCG@3은 애매 판정에 절반을 준다 — P@3는 주지 않는다</h3>
<p class="lede">사람 라벨 구성이 적합 {gc['Correct']} · 애매 {gc['Ambiguous']} ·
부적합 {gc['Incorrect']}건 — <strong>애매가 적합과 거의 맞먹는다.</strong>
애매를 0점으로 처리하면 점수가 이만큼 내려간다.</p>
<div class="scroll"><table><thead><tr><th>구성</th><th>nDCG@3 (애매=0.5)</th>
<th>nDCG@3 (애매=0)</th><th>차이</th><th>P@3</th><th>도달가능 대비 P@3</th>
</tr></thead><tbody>""")
    for arm in [a for a in ARMS if a in ac]:
        v = ac[arm]
        h.append(f"""<tr><td class="num">{esc(arm)}</td><td class="num">{v['base']:.4f}</td>
<td class="num{' best' if arm == best else ''}">{v['strict']:.4f}</td>
<td class="num">{v['delta']:+.4f}</td><td class="num">{mh[arm]['p3']:.4f}</td>
<td class="num">{pa[arm]['rate']:.1%}</td></tr>""")
    h.append(f"""</tbody></table></div>
<div class="warnbox"><strong>nDCG@3의 약 {abs(ac[best]['delta']):.2f}가 "애매한 공고"에서 나온
점수다.</strong> 극단적 사례 — <code>{esc(zr[0]['qid'])}</code>({esc(zr[0]['query'])})는
<strong>적합 공고가 0건</strong>인데 nDCG@3이 <strong>{zr[0]['ndcg3_of_best_arm']:.2f}</strong>다
(애매 {zr[0]['n_ambiguous']}건을 상위에 올려 얻은 점수 · P@3는 {zr[0]['p3_of_best_arm']:.2f}).
적합한 게 하나도 없는 질의의 0.70을 "70% 잘했다"로 읽으면 완전히 잘못 읽는 것이다.
<strong>운영 판단에는 P@3를, 순위 품질 비교에는 애매=0 열을 쓰는 게 안전하다.</strong></div>

<h3>③ 정규화의 "0"은 표에 보이는 random 구성이 아니다</h3>
<div class="note">무작위 기준선이 두 개다 — <strong>풀 내부 무작위
{rb['pool_internal_mean']:.4f}</strong>(정규화의 분모)와 <strong>코퍼스 무작위
{rb['corpus_random_arm_ndcg3']:.4f}</strong>(표의 random 구성). 정규화 점수의 0은 전자를 뜻하고,
random 구성은 그보다 낮아 0으로 절단된다. 결과적으로 <strong>정규화 점수는 보수적</strong>이다 —
이 지점은 수치를 부풀리지 않는다.</div>

<h3>적합 공고가 3건 미만인 질의 — P@3가 1.0에 도달 불가</h3>
<div class="scroll"><table><thead><tr><th>질의</th><th>적합 공고</th><th>P@3 상한</th><th>비고</th>
</tr></thead><tbody>""")
    for t in tr:
        note = ('적합 0건 — 옳은 동작은 "결과 없음"' if t["n_relevant"] == 0
                else "3건을 채울 적합 공고 부족")
        h.append(f"""<tr><td class="num">{esc(t['qid'])}</td><td class="num">{t['n_relevant']}</td>
<td class="num">{t['p3_ceiling']:.2f}</td><td>{note}</td></tr>""")
    h.append(f"""</tbody></table></div>
<div class="note">{n_q}질의 중 <strong>{len(tr)}건이 구조적으로 만점 불가</strong>이고 그중
{len(zr)}건은 적합 공고가 아예 없다. 이때 옳은 제품 동작은 3건을 내놓는 게 아니라
<strong>"조건에 맞는 공고가 없습니다"</strong>인데, 현재 지표는 그걸 상 주지도 벌 주지도 않는다.</div>

<h3>그래서 지금 수준은</h3>
<div class="tiles">
<div class="tile"><p class="k">운영 수치 · P@3</p><div class="v">{mh[best]['p3']:.3f}</div>
<p class="s">3건 보여주면 {mh[best]['p3'] * 3:.1f}건이 적합</p></div>
<div class="tile"><p class="k">도달가능 상한 대비</p><div class="v">{pa[best]['rate']:.1%}</div>
<p class="s">적합 {pa[best]['relevant_hits']:.0f}건 / 가능 {pa[best]['attainable']}건</p></div>
<div class="tile"><p class="k">nDCG@3 (애매=0)</p><div class="v">{ac[best]['strict']:.3f}</div>
<p class="s">기본 {ac[best]['base']:.3f}에서 하락</p></div>
<div class="tile"><p class="k">코퍼스 무작위 P@3</p><div class="v">{mh['random']['p3']:.3f}</div>
<p class="s">약 {ratio:.0f}배 차이</p></div>
</div>
<div class="warnbox"><strong>판정: "동작이 확인된 프로토타입" 수준이고, "성능 수치가 확정된
시스템"은 아니다.</strong> 무작위 대비 {ratio:.0f}배, BM25 단독(P@3 {mh['bm25']['p3']:.3f}) 대비
명확한 개선 — 방향은 맞다. 그러나 실서비스 기대치로 읽으면 <strong>낙관 편향이 세 겹</strong>이다:
① 코퍼스가 작아 풀 내 적합 밀도가 높다(실서비스는 훨씬 희박하고, 희박해지면 상위 3건 확보가
급격히 어려워진다) ② {cr:.0%} 질의가 이미 만점이라 개선 여지가 지표에 없다
③ 점수의 {abs(ac[best]['delta']):.2f}가 애매 판정 몫이다.</div>

<h3>지표 설계 보완 제안</h3>
<ul class="tight">
<li><strong>k=3은 운영 주장용으로 유지</strong>하되 P@3와 애매=0 nDCG@3를 헤드라인에 병기해
애매 인정분을 숨기지 않는다. <em>(이 대시보드에 반영됨)</em></li>
<li><strong>풀 depth를 늘려 nDCG@10 · Recall@10을 개발 감도용으로 추가</strong>한다. 천장 포화를
벗어나야 개선이 측정된다. 단 풀 재구성은 앵커 시트를 재생성시켜 사람 라벨을 무효화하므로
앵커·질의 확대와 <strong>한 번에</strong> 설계해야 한다.</li>
<li><strong>적합 0건 질의는 "결과 없음이 정답"인 별도 케이스로 분리</strong> 채점한다.
현재는 이 {len(zr)}건이 평균을 왜곡하기만 한다.</li>
</ul></section>""")

    # ── 절단 k를 늘려보기
    mk = spec["multi_k"]
    k10, k3 = mk["k=10"], mk["k=3"]
    h.append(f"""<section><h2>절단을 깊게 하면 달라지나 <span class="n">k = 1 · 3 · 5 · 10</span></h2>
<p class="lede">추가 라벨링 없이 절단만 바꿔 다시 측정했다. 풀이 5개 구성의 상위 10건
<strong>합집합</strong>으로 만들어져 각 구성의 상위 10건은 전부 판정돼 있다(750건 중 미판정 0건).
<strong>사람 라벨은 그대로 유지되며 앵커셋과 무관하다</strong> — 앵커는 라벨 신뢰도를 재는
별도 표본이고 절단 k와 상관이 없다.</p>

<div class="scroll"><table><thead><tr><th>절단</th><th>만점 질의</th><th>값 종류</th>
<th>구분된 비교</th><th>recall 천장</th><th>{esc(best)} nDCG</th><th>{esc(best)} recall</th>
</tr></thead><tbody>""")
    for kk, d in mk.items():
        v = d["arms"][best]
        mark = ' class="best"' if kk == "k=10" else ""
        h.append(f"""<tr><td class="num"{mark}>{esc(kk)}</td>
<td class="num">{v['n_at_ceiling']}/15</td><td class="num">{v['n_distinct']}/15</td>
<td class="num">{d['n_significant']}/{d['n_comparisons']}</td>
<td class="num">{d['recall_ceiling']:.3f}</td>
<td class="num">{v['ndcg']:.4f}</td><td class="num">{v['recall']:.4f}</td></tr>""")
    h.append(f"""</tbody></table></div>
<div class="note"><strong>절단을 깊게 하면 지표가 되살아난다.</strong>
만점 질의가 {mk['k=1']['arms'][best]['n_at_ceiling']}/15(k=1) →
{k3['arms'][best]['n_at_ceiling']}/15(k=3) → {k10['arms'][best]['n_at_ceiling']}/15(k=10)로 줄고,
질의별 값이 {k3['arms'][best]['n_distinct']}종 → <strong>{k10['arms'][best]['n_distinct']}종</strong>
(전 질의가 서로 다른 값)으로 늘어난다. 구분되는 비교도
{k3['n_significant']} → <strong>{k10['n_significant']}</strong>개로 증가한다.
<strong>진단·개발용으로는 k=10이 k=3보다 확실히 낫다.</strong>
recall도 천장이 {k3['recall_ceiling']:.3f} → {k10['recall_ceiling']:.3f}로 올라 비로소 의미를 갖는다.</div>

<h3>깊게 해도 안 갈리는 것 vs 갈리는 것</h3>
{k_forest_chart(mk, ['rrf_vs_rrf_ce', 'bm25_vs_rrf_ce'])}
<div class="legend"><span><span class="sw s1"></span>유의</span>
<span><span class="sw nul"></span>구분 불가</span></div>
<div class="warnbox"><strong>교차인코더의 기여는 어느 절단에서도 입증되지 않는다.</strong>
<code>rrf</code> 대비 차이가 k=1 · 3 · 5 · 10 <strong>전부</strong> 0선을 걸친다
(k=10에서도 CI [{k10['comparisons']['rrf_vs_rrf_ce']['ci_95'][0]:+.3f},
{k10['comparisons']['rrf_vs_rrf_ce']['ci_95'][1]:+.3f}]).
앞서 이 결론을 "k=3의 천장 포화 때문일 수 있다"고 유보했는데, <strong>포화가 해소된 k=10에서도
그대로다 → 절단 탓이 아니라 실제로 없는 차이</strong>로 봐야 한다. 질의당 0.836초를
추가로 쓸 근거가 사라진다.
<br><br><strong>반면 bm25 대비 우위는 깊게 하니 확인됐다</strong> — k=3에서는 구분 불가였으나
k=5·k=10에서 유의해진다(k=10 CI [{k10['comparisons']['bm25_vs_rrf_ce']['ci_95'][0]:+.3f},
{k10['comparisons']['bm25_vs_rrf_ce']['ci_95'][1]:+.3f}]). 즉 하이브리드의 가치는 실재하고,
<strong>재순위 단계의 가치만 미확인</strong>이다.</div>

<h3>구성별 성격 — recall이 드러내는 것</h3>
<div class="scroll"><table><thead><tr><th>구성</th>
<th>P@3</th><th>P@10</th><th>Recall@3</th><th>Recall@10</th><th>해석</th>
</tr></thead><tbody>""")
    interp = {
        "rrf_ce": "상위 정밀도 최고. 다만 rrf 대비 우위는 미확인",
        "rrf": "정밀도·재현율 모두 준수. 비용 대비 가장 합리적",
        "bm25": "상위권은 버티지만 <strong>깊은 재현율이 최하</strong> — 놓치는 공고가 많다",
        "dense": "<strong>재현율은 rrf급인데 상위 정밀도가 낮다</strong> — 찾아내지만 위로 못 올린다",
    }
    for arm in [a for a in ARMS if a != "random"]:
        h.append(f"""<tr><td class="num">{esc(arm)}</td>
<td class="num">{k3['arms'][arm]['precision']:.4f}</td>
<td class="num">{k10['arms'][arm]['precision']:.4f}</td>
<td class="num">{k3['arms'][arm]['recall']:.4f}</td>
<td class="num">{k10['arms'][arm]['recall']:.4f}</td>
<td>{interp[arm]}</td></tr>""")
    h.append(f"""</tbody></table></div>
<div class="note"><strong>dense의 성격이 진단적이다.</strong>
Recall@3은 {k3['arms']['dense']['recall']:.3f}로 최하위권이지만 Recall@10은
{k10['arms']['dense']['recall']:.3f}로 <code>rrf</code>({k10['arms']['rrf']['recall']:.3f})에
근접하고 <code>bm25</code>({k10['arms']['bm25']['recall']:.3f})를 앞선다.
<strong>적합 공고를 찾아내기는 하는데 상위로 올리지 못한다</strong>는 뜻이다 —
후보 생성기로는 좋고 최종 순위기로는 약하다. 하이브리드 구조가 실제로
이 성질을 활용하고 있다는 증거이기도 하다.</div></section>""")

    # ── 천장 100점 환산
    raw = g3b.get("binary_agreement_raw")
    # RAGAS는 judge 라벨 기반이므로 recall 천장도 그 트랙 값을 쓴다
    rc_ceil = spec["recall_at_3_ceiling"]["judge_only"]
    h.append(f"""<section><h2>천장을 100점으로 환산하면 <span class="n">도달률</span></h2>
<p class="lede">"측정 가능한 최선"을 100점으로 두고 각 지표가 몇 점인지 본다.
<strong>다만 천장이 지표마다 다르다</strong> — 이걸 섞으면 안 된다.</p>

<div class="warnbox"><strong>κ의 천장 0.855를 검색 지표에 그대로 쓰면 안 된다.</strong>
0.855는 <em>채점자끼리 얼마나 일치하는가</em>의 상한이고, nDCG·P@3의 상한이 아니다.
서로 다른 것을 재는 지표라 분모를 공유하지 않는다. 아래는 지표군을 나눠 환산한 것이다.</div>

<h3>A. 판정 신뢰도 — 천장 0.855 = 100점</h3>
<div class="scroll"><table><thead><tr><th>판정자</th><th>κ</th><th>천장 대비</th>
<th>95% CI (환산)</th></tr></thead><tbody>""")
    for a in arms_h:
        k, ci = a["binary_kappa"], a["kappa_ci_95"]
        c = nc["human_self_kappa"]
        h.append(f"""<tr><td>{esc(a['judge'])}</td><td class="num">{k:.4f}</td>
<td class="num{' best' if a is arms_h[0] else ''}">{k / c * 100:.1f}점</td>
<td class="num">[{ci['lo'] / c * 100:.1f}, {ci['hi'] / c * 100:.1f}]</td></tr>""")
    c = nc["human_self_kappa"]
    h.append(f"""<tr><td><strong>게이트 통과 기준</strong></td><td class="num">{g3['threshold']:.2f}</td>
<td class="num">{g3['threshold'] / c * 100:.1f}점</td><td class="num">—</td></tr>
</tbody></table></div>
<div class="note"><strong>본판정 judge는 69.3점, 통과선은 70.2점 — 0.9점 차이다.</strong>
게이트 3이 얼마나 아슬아슬한지가 환산하면 더 분명해진다. 신뢰구간으로는 50.8~86.1점이라
통과선을 걸친다.</div>

<h3>B. 검색 지표 — 각자의 천장 = 100점</h3>
<div class="scroll"><table><thead><tr><th>구성</th>
<th>정규화 nDCG@3<br><span style="font-weight:400;text-transform:none">천장=완벽정렬</span></th>
<th>P@3 / 도달가능<br><span style="font-weight:400;text-transform:none">천장=적합 수 한계 보정</span></th>
<th>라벨잡음 보정<br><span style="font-weight:400;text-transform:none">천장={raw:.1%}</span></th>
<th>엄격 nDCG@3<br><span style="font-weight:400;text-transform:none">애매=0점</span></th>
</tr></thead><tbody>""")
    for arm in [a for a in ARMS if a != "random"]:
        r = pa[arm]["rate"]
        h.append(f"""<tr><td class="num">{esc(arm)}</td>
<td class="num{' best' if arm == best else ''}">{mh[arm]['norm_ndcg3'] * 100:.1f}점</td>
<td class="num{' best' if arm == best else ''}">{r * 100:.1f}점</td>
<td class="num">{r / raw * 100:.1f}점</td>
<td class="num">{ac[arm]['strict'] * 100:.1f}점</td></tr>""")
    h.append(f"""</tbody></table></div>
<div class="note"><strong>어느 환산을 쓰든 {esc(best)}는 60~80점대다.</strong>
가장 관대한 읽기가 라벨잡음 보정 {pa[best]['rate'] / raw * 100:.1f}점,
가장 엄격한 읽기가 애매=0 기준 {ac[best]['strict'] * 100:.1f}점이다.
<strong>"측정 가능한 최선의 60~80%"</strong>가 현재 수준의 정직한 표현이고,
이 폭 자체가 지표 설계에 따른 불확실성이다.</div>
<div class="warnbox"><strong>세 번째 열(라벨잡음 보정)은 추정치다.</strong>
재검사 {g3b['n_overlap']}쌍의 이진 원일치율 {raw:.1%}를 "완벽한 시스템도 이 이상은 못 받는다"는
천장으로 가정했다. 표본 {g3b['n_overlap']}쌍으로 낸 값이라 정밀하지 않다 —
제대로 하려면 앵커 전량을 두 번 라벨링해야 한다. 방향만 참고할 것.</div>

<h3>C. RAGAS 축 — 둘은 환산 대상이 아니다</h3>
<div class="scroll"><table><thead><tr><th>축</th><th>실측</th><th>천장</th><th>환산</th>
<th>왜</th></tr></thead><tbody>
<tr><td>context precision (ID)</td><td class="num">{rag['summary']['context_precision_id']:.4f}</td>
<td class="num">—</td><td>중복</td>
<td>P@3와 <strong>산식이 같다</strong>(상위 3건 중 적합 비율). 독립 지표가 아님</td></tr>
<tr><td>context recall (ID)</td><td class="num">{rag['summary']['context_recall_id']:.4f}</td>
<td class="num">{rc_ceil:.4f}</td>
<td class="num best">{rag['summary']['context_recall_id'] / rc_ceil * 100:.1f}점</td>
<td>k=3이라 적합 n건 중 최대 3건만 회수 가능 → 천장이 1.0이 아님</td></tr>
<tr><td>faithfulness</td><td class="num">{rag['summary'].get('faithfulness', 0):.4f}</td>
<td class="num">—</td><td>환산 불가</td>
<td>템플릿 응답 기준 하네스 확인값. 성능이 아니라 환산 의미 없음</td></tr>
<tr><td>answer relevancy</td><td class="num">{rag['summary'].get('answer_relevancy', 0):.4f}</td>
<td class="num">—</td><td>환산 불가</td><td>위와 동일</td></tr>
</tbody></table></div>
<div class="note"><strong>context recall 0.41은 "낮다"가 아니다.</strong>
적합 공고가 19건인 질의에서 상위 3건으로 회수할 수 있는 최대치는 0.158이다. 질의별 상한을
평균하면 천장이 <strong>{rc_ceil:.3f}</strong>이고, 실측 {rag['summary']['context_recall_id']:.3f}은
그 <strong>{rag['summary']['context_recall_id'] / rc_ceil * 100:.1f}%</strong>다.
<strong>k=3에서 recall을 절대값으로 인용하면 반드시 오독된다</strong> — 이 지표는 절단이 작을수록
구조적으로 낮게 나온다. recall을 제대로 보려면 k를 늘려야 한다(Recall@10 등).</div></section>""")

    # ── 직군축
    h.append("""<section><h2>어디서 잘하고 어디서 못하나 <span class="n">직군축</span></h2>
<p class="lede">직군을 성격이 비슷한 축으로 묶은 정규화 nDCG@3. 축마다 질의가 2~4개뿐이라
개별 수치는 잡음이 크지만, 축 사이의 격차는 뚜렷하다.</p>
<div class="scroll"><table class="hm"><thead><tr><th>직군축</th><th>질의</th>""")
    for arm in ARMS:
        h.append(f'<th style="text-align:center">{esc(arm)}</th>')
    h.append("</tr></thead><tbody>")
    for axis, row in axes.items():
        h.append(f'<tr><td>{esc(axis)}</td><td class="num">{row["n"]}</td>')
        for arm in ARMS:
            v = row[arm]
            h.append(f'<td class="c" data-step="{min(4, int(v * 5))}" '
                     f'title="{esc(axis)} / {esc(arm)}: {v:.4f}">{v:.3f}</td>')
        h.append("</tr>")
    h.append("</tbody></table></div>")

    worst = min(axes.items(), key=lambda kv: kv[1][best])
    h.append(f"""<div class="warnbox"><strong>데이터·ML 직군이 명확한 약점이다.</strong>
{esc(worst[0])} 축에서 최고 구성도 {worst[1][best]:.3f}에 그치고,
임베딩 검색 단독(<code>dense</code>)은 {worst[1]['dense']:.3f}로 거의 작동하지 않는다.
직군명과 기술스택이 겹치는 인접 직군(데이터 엔지니어 / 사이언티스트 / ML 엔지니어 / 분석가)을
구분하지 못하는 것으로 보인다 — 실제 서비스에서 오배치가 가장 많이 날 지점이다.</div></section>""")

    # ── RAGAS
    cov = rag.get("scored_coverage", {})
    h.append(f"""<section><h2>RAGAS 4축 <span class="n">보조 지표</span></h2>
<p class="lede">업계 표준 RAG 평가 프레임워크의 4개 축. 위 두 축은 정답표만 있으면 계산이
결정적으로 정해지고, 아래 두 축은 LLM이 채점한다.</p>
{ragas_chart(rag.get('summary', {}), cov)}
<div class="legend"><span><span class="sw s1"></span>결정적 — 계산이 확정적</span>
<span><span class="sw s2"></span>LLM 판정 — 채점자 편차 있음</span></div>
<div class="warnbox"><strong>이 4축은 검색 성능의 독립적인 2차 검증이 아니다.</strong>
정답표가 위와 <em>같은</em> 판정기 라벨이라, 판정기의 편향을 그대로 물려받는다.
게다가 편향 방향이 축마다 반대다 — 적합 라벨이 과다하면 <strong>precision은 과대추정(상한),
recall은 과소추정(하한)</strong>이 된다. 두 수치를 같은 신뢰도로 나란히 읽으면 안 된다.
아래 두 축은 답변 생성부가 정식 연결되기 전 템플릿 응답 기준이라
<strong>하네스 동작 확인값</strong>이고 성능이 아니다. 실패 {rag.get('n_failed', 0)}건은
구조화 출력 파싱 실패로 해당 표본만 제외했다.</div></section>""")

    # ── 경계 기준
    bc = hum.get("boundary_criteria_applied", {}).get("by_query_type", {})
    if bc:
        h.append("""<section><h2>사람이 실제로 적용한 경계 기준 <span class="n">사후 역추출</span></h2>
<p class="lede">채점 전에 확정하려 했던 경계 사례 판단 기준을, 완료된 라벨에서 거꾸로 읽어낸 것이다.
불일치율이 높은 구간이 기준이 불명확했던 지점이다.</p>
<div class="scroll"><table><thead><tr><th>질의 유형</th><th>쌍</th>
<th>Correct</th><th>Ambiguous</th><th>Incorrect</th><th>판정기 불일치</th><th>불일치율</th>
</tr></thead><tbody>""")
        for k, v in bc.items():
            d = v["human_label_dist"]
            h.append(f"""<tr><td>{esc(k.replace('_', ' '))}</td><td class="num">{v['n']}</td>
<td class="num">{d.get('Correct', 0)}</td><td class="num">{d.get('Ambiguous', 0)}</td>
<td class="num">{d.get('Incorrect', 0)}</td><td class="num">{v['judge_disagreements']}</td>
<td class="num">{v['disagree_rate']:.1%}</td></tr>""")
        h.append("</tbody></table></div>")
        wk = max(bc.items(), key=lambda kv: kv[1]["disagree_rate"] or 0)
        h.append(f"""<div class="note"><strong>경력 질의가 가장 불안정하다</strong>
({esc(wk[0].replace('_', ' '))} 불일치율 {wk[1]['disagree_rate']:.1%}).
연차 요건이 질의보다 높은 공고를 어디까지 허용하는지가 여전히 미정의 상태다.
다음 라운드 전에 이 기준을 문서로 확정해야 사람 라벨끼리도 일관성이 올라간다.</div></section>""")

    # ── 질의별
    h.append("""<section><h2>질의별 상세 <span class="n">15종</span></h2>
<details><summary>질의별 점수·정답 분포 펼치기</summary><div class="in">
<div class="scroll"><table><thead><tr><th>ID</th><th>질의</th><th>판정</th><th>적합</th>""")
    for arm in ARMS:
        h.append(f'<th>{esc(arm)}</th>')
    h.append("</tr></thead><tbody>")
    for qid, d in pq.items():
        vals = {a: d["arms"][a]["norm_ndcg3"] for a in ARMS}
        top = max(vals, key=lambda a: vals[a])
        h.append(f"""<tr><td class="num">{esc(qid)}</td><td>{esc(d['query'])}</td>
<td class="num">{d['n_judged']}</td><td class="num">{d['n_relevant']}</td>""")
        for arm in ARMS:
            h.append(f'<td class="num{" best" if arm == top else ""}">{vals[arm]:.3f}</td>')
        h.append("</tr>")
    h.append("</tbody></table></div></div></details></section>")

    # ── 용어
    gloss = [
        ("정규화 nDCG@3", "normalized nDCG@3",
         "상위 3건이 얼마나 잘 정렬됐는지를 0~1로 환산한 값. 0 = 무작위로 뽑은 수준, "
         "1 = 이 후보 풀에서 이론상 가능한 최선. 질의마다 난이도가 달라 원점수를 그대로 "
         "평균하면 왜곡되므로, 무작위 바닥과 오라클 천장 사이에서 어디쯤인지로 바꾼 것이다."),
        ("nDCG@3", "normalized discounted cumulative gain",
         "상위 3건의 적합도를 순위가 낮을수록 깎아서 더한 뒤, 이상적 정렬로 나눈 값. "
         "1등에 적합한 게 오면 3등에 오는 것보다 높은 점수를 준다."),
        ("P@3", "precision at 3",
         "상위 3건 중 적합한 것의 비율. 순서는 안 본다."),
        ("AP@3", "average precision at 3",
         "상위 3건 안에서 적합한 항목이 나타난 위치까지의 정밀도를 평균한 값. 순서를 본다."),
        ("qrels", "query relevance judgments",
         "정답표. 질의–문서 쌍마다 적합/애매/부적합 라벨을 붙여둔 것. 검색 점수는 전부 "
         "이 표에 상대적이라, 표가 틀리면 점수도 틀린다."),
        ("풀링", "pooling",
         "여러 검색 방식의 상위 결과를 모아 그 합집합만 채점하는 방식. 전체 코퍼스를 다 "
         "채점할 수 없어 쓰는 표준 기법이지만, 어떤 방식도 못 찾은 적합 문서는 "
         "영원히 누락된다 — 그래서 recall의 절대값은 신뢰할 수 없다."),
        ("Cohen's κ", "Cohen's kappa",
         "두 채점자가 얼마나 일치하는지를, 우연히 맞을 확률을 뺀 뒤 재는 값. 0 = 우연 수준, "
         "1 = 완전 일치. 단순 일치율보다 엄격하다 — 라벨이 한쪽으로 치우쳐 있으면 "
         "찍어도 일치율은 높게 나오기 때문이다."),
        ("이진화", "binarization",
         "3분류(적합/애매/부적합)를 '적합 대 나머지'로 접는 것. 본평가의 P@3가 적합만 "
         "적합으로 세므로, 신뢰도 게이트도 같은 기준으로 재야 앞뒤가 맞는다."),
        ("McNemar b, c", "McNemar's test",
         "불일치가 한쪽으로 쏠렸는지 본다. b = 사람은 적합인데 판정기가 아니라 한 건, "
         "c = 그 반대. c가 b보다 크게 많으면 판정기가 적합을 남발하는 편향이 있다는 뜻이다."),
        ("쌍대 부트스트랩", "paired bootstrap",
         "질의 집합을 복원추출로 수천 번 다시 뽑아 두 구성의 차이 분포를 만드는 방법. "
         "'이 15개 질의가 우연히 유리했을 가능성'을 수치로 바꿔준다."),
        ("95% 신뢰구간", "95% CI",
         "참값이 있을 만한 범위. 차이의 구간이 0을 포함하면 '차이가 있다'고 말할 수 없다. "
         "구간이 길다 = 표본이 적어 불확실하다."),
        ("유의 / 구분 불가", "significance",
         "여기서 '구분 불가'는 '차이가 없다'가 아니라 '있는지 없는지 이 표본으로는 알 수 없다'는 뜻이다. "
         "둘을 섞으면 결론이 과장된다."),
        ("자기일관성", "self-consistency",
         "같은 채점자에게 같은 항목을 다시 보여줬을 때 같은 답을 내는 정도. 사람은 완벽하지 않고, "
         "이 값이 정답표 품질의 실질적 상한이 된다."),
        ("잡음 천장", "noise ceiling",
         "정답 자체가 흔들리는 만큼 어떤 모델도 그 위로 못 올라가는 한계선. 사람 자기일관성이 "
         "그 값이다. 이걸 모르면 '기준 0.60'이 쉬운지 어려운지 판단할 수 없다."),
        ("context precision / recall", "RAGAS",
         "검색이 가져온 근거 중 실제 정답 문서의 비율(precision)과, 정답 문서 중 가져온 "
         "비율(recall). 여기서는 문서 ID 대조로 계산해 LLM이 개입하지 않는다 — 단 "
         "정답표 자체는 LLM이 만든 것이다."),
        ("faithfulness", "RAGAS",
         "생성된 답변의 주장들이 검색된 근거에 실제로 있는지. 낮으면 없는 내용을 지어낸 것이다."),
        ("answer relevancy", "RAGAS",
         "답변이 질문에 실제로 답하고 있는지. 근거에 충실하지만 질문과 상관없는 답변을 걸러낸다."),
        ("bm25", "arm",
         "단어가 얼마나 겹치는지로 찾는 고전 어휘 검색. 표기가 정확히 일치할 때 강하다."),
        ("dense", "arm",
         "문장을 벡터로 바꿔 의미가 가까운 것을 찾는 검색. 표현이 달라도 뜻이 비슷하면 찾아낸다."),
        ("rrf", "reciprocal rank fusion",
         "bm25와 dense의 순위를 합치는 방법. 점수 척도가 달라도 순위만으로 섞을 수 있다."),
        ("rrf_ce", "cross-encoder rerank",
         "rrf 결과 상위권을 질의와 함께 다시 읽어 정밀 재정렬하는 방식. 가장 정확할 수 있지만 "
         "가장 느리다(질의당 0.836초)."),
        ("오라클 / 랜덤 바닥", "oracle / random floor",
         "오라클 = 정답표를 다 알고 완벽히 정렬했을 때의 점수(천장). 랜덤 바닥 = 후보를 "
         "무작위로 뽑았을 때의 기대 점수. 정규화는 이 둘 사이 위치로 환산하는 것이다. "
         "주의: 여기서 랜덤 바닥은 '풀 안에서' 무작위로 뽑은 값이라, 코퍼스 전체에서 "
         "무작위로 뽑는 random 구성보다 훨씬 높은(엄격한) 기준선이다."),
        ("절단 k", "metric cutoff",
         "상위 몇 건까지 채점할지. 여기서는 3 — 생성부가 상위 3건을 근거로 쓰기 때문이다. "
         "지표의 절단은 시스템이 실제로 내리는 결정의 크기와 같아야 한다."),
        ("천장 포화", "ceiling saturation",
         "지표가 만점에 붙어버려 더 나아진 것을 표현할 수 없는 상태. 만점 질의가 많으면 "
         "구성 간 우열도 갈리지 않는다 — 검정력 부족의 원인이 표본 수가 아니라 지표일 수 있다."),
        ("도달가능 상한 대비 P@3", "attainable-adjusted P@3",
         "적합 공고가 3건 미만인 질의는 P@3가 애초에 1.0에 도달할 수 없다. 질의별로 "
         "min(3, 적합 수)를 분모로 삼아 '맞출 수 있었던 것 중 얼마를 맞췄나'로 환산한 값."),
        ("등급 배점", "graded relevance",
         "적합 2점 · 애매 1점 · 부적합 0점. nDCG는 이 배점을 쓰므로 애매 판정에서도 "
         "절반의 점수가 나온다. 반면 P@3·AP@3는 적합만 센다 — 그래서 같은 결과에서 "
         "nDCG가 P@3보다 후하게 나온다."),
    ]
    h.append("""<section><h2>용어 해설 <span class="n">읽는 법</span></h2>
<p class="lede">위 수치를 해석하는 데 필요한 용어만 모았다.</p>
<div class="card" style="padding:0"><dl class="gloss">""")
    for ko, en, desc in gloss:
        h.append(f'<div class="gi"><dt>{esc(ko)}<span class="en">{esc(en)}</span></dt>'
                 f'<dd>{esc(desc)}</dd></div>')
    h.append("</dl></div></section>")

    # ── 한계
    h.append(f"""<section><h2>이 결과가 말할 수 없는 것 <span class="n">한계</span></h2>
<ul class="tight">
<li><strong>어떤 검색 구성을 채택할지</strong> — 상위 3개 구성이 통계적으로 구분되지 않는다.
질의 {ver['n_queries']}종으로는 검정력이 부족하다. 대략 60~120종이 필요하다.</li>
<li><strong>절대 성능 수치</strong> — 게이트 3이 판정 불가 상태다. 정답표의
{100 - prov['coverage'] * 100:.0f}%는 아직 사람 검증을 받지 않은 판정기 라벨이다.</li>
<li><strong>recall의 절대값</strong> — 풀링 방식이라 어떤 검색 방식도 찾지 못한 적합 공고는
집계에서 빠진다. 측정된 recall은 하한이다.</li>
<li><strong>답변 생성 품질</strong> — faithfulness·answer relevancy는 템플릿 응답 기준
하네스 확인값이다. 생성부를 정식 연결한 뒤가 본측정이다.</li>
<li><strong>실서비스 대표성</strong> — 코퍼스가 작고, 질의도 직접 만든 정규화 고정형이다.
실제 사용자 입력 분포와 같다는 보장이 없다.</li>
<li><strong>자연어 질의 트랙과의 직접 비교</strong> — 사람 검증은 정규화 질의 트랙에서만
이뤄졌다. 두 트랙의 신뢰도 수치를 서로 대입할 수 없다.</li>
</ul>
<div class="note"><strong>다음에 할 일 하나만 고르라면:</strong> 앵커 표본을 250~300쌍으로
늘려 게이트 3의 판정 불가를 해소하는 것이다. 지금 CI 반폭이 ±0.15라 기준선을 배제하지 못한다.
질의 수 확대(15 → 60+)는 구성 선택을 위해 별도로 필요하며, 두 작업은 함께 설계하는 게 낫다.</div>
</section>""")

    h.append(f"""<footer>생성 {esc(spec['generated_at'][:19])}Z ·
정답표 {esc(prov['base'])} · 사람 검증 {prov['human_verified_pairs']}쌍 ·
판정 프롬프트 {esc(hum['judge_prompt_version'])} ·
수치는 report_spec.json / anchor_report_human.json / ragas_report.json에서 자동 주입</footer>
</div>""")
    return "\n".join(h)


STANDALONE = EVAL_DIR / "dashboard_human_standalone.html"

# Artifact는 <head>·<body>를 붙여 감싸므로 OUT에는 골격을 넣지 않는다. 반면 브라우저에서
# 파일을 직접 열려면 골격이 필요하다 — 같은 본문을 감싸 별도 파일로 한 번 더 내보낸다.
SHELL = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  *,*::before,*::after{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0}
  img,svg{max-width:100%}
  table{border-collapse:collapse}
</style>
</head>
<body>
{body}
</body>
</html>
"""


if __name__ == "__main__":
    body = build()
    OUT.write_text(body, encoding="utf-8")
    STANDALONE.write_text(SHELL.replace("{body}", body), encoding="utf-8")
    print(f"Artifact용 : {OUT}  ({OUT.stat().st_size:,} bytes)")
    print(f"브라우저용 : {STANDALONE}  ({STANDALONE.stat().st_size:,} bytes)")
    print("   -> 더블클릭하거나 브라우저로 끌어다 놓으면 열립니다. 외부 의존 없음(단일 파일).")

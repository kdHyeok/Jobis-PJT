# -*- coding: utf-8 -*-
"""120건 규모 생성 환각 테스트 — 실검색 컨텍스트 + Haiku 생성 + 결정적 채점."""
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
SYSTEM_PROMPT = """당신은 채용공고 검색 어시스턴트입니다.
아래 [검색결과]만 근거로 사용자 질문에 답하세요.
- 검색결과에 없는 공고를 지어내지 마세요.
- 각 추천에는 회사명과 핵심 조건(경력/지역/기술)을 포함하세요.
- 조건에 정확히 맞는 게 없으면 그렇다고 말하고 가장 가까운 대안을 제시하세요.
- 한국어로, 간결하게 답하세요."""


def norm_company(name: str) -> str:
    s = unicodedata.normalize("NFKC", name)
    s = re.sub(r"[㈜(（]\s*주\s*[)）]|㈜|\(주\)|주식회사|유한회사|유한책임회사", "", s)
    s = re.sub(r"[\s·.\-_/\[\]()（）]", "", s)
    return s.lower()


def _company_in(cnorm, tnorm):
    if not cnorm:
        return False
    if cnorm in tnorm:
        return True
    for cut in range(len(cnorm) - 1, 3, -1):
        if cnorm[:cut] in tnorm:
            return True
    return False


def parse_context(ctx: str) -> dict:
    company = ""
    m = re.search(r"\[회사\]\s*(.+)", ctx)
    if m:
        company = m.group(1).strip()
    return {"company": company, "company_norm": norm_company(company)}


def extract_recommendations(answer: str, known: list[dict]) -> list[dict]:
    """번호목록/볼드 항목을 추천으로 취급. 회사명이 헤더 문장에만 등장하고
    그 아래 번호목록이 같은 회사의 하위 공고를 나열하는 패턴('단일회사, 다중공고
    헤더')을 지원 — 그 경우 번호 항목에 회사명이 없어도 헤더에서 상속받는다.
    """
    recs = []
    active_company = None  # 직전에 등장한(비-번호) 문장에서 확정된 회사
    for raw in answer.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_numbered = bool(re.match(r"^\d+[.)]\s+", line))
        is_bold = "**" in line and not line.rstrip("*").rstrip().endswith(":")
        is_attr = bool(re.match(r"^[-*•]\s*\S[^:]{0,20}:", line))
        tn = norm_company(line)

        if not is_numbered and not is_attr:
            # 일반 문장/헤더 — 회사가 언급되면 이후 번호목록의 상속 대상으로 기억
            for k in known:
                if _company_in(k["company_norm"], tn):
                    active_company = k
                    break

        if is_numbered or (is_bold and not is_attr):
            has_sep = bool(re.search(r"\s[-–]\s|—", line)) or is_numbered
            matched = None
            for k in known:
                if _company_in(k["company_norm"], tn):
                    matched = k
                    break
            if matched is None and is_numbered and active_company is not None:
                # 헤더에서 회사를 이미 밝혔고, 번호 항목은 그 회사의 세부 공고인 패턴
                matched = active_company
            if matched is None and not has_sep:
                continue
            recs.append({"line": line, "matched": matched})
    return recs


def check_answer(answer: str, contexts: list[str]) -> dict:
    known = [parse_context(c) for c in contexts]
    recs = extract_recommendations(answer, known)
    fabrications = [r["line"] for r in recs if r["matched"] is None]
    return {"n_recs": len(recs), "n_grounded": len(recs) - len(fabrications),
            "fabrications": fabrications}


def build_inputs():
    samples = json.loads((HERE / "gen_samples.json").read_text(encoding="utf-8"))
    indir = HERE / "gen_inputs"
    outdir = HERE / "gen_outputs"
    indir.mkdir(exist_ok=True)
    outdir.mkdir(exist_ok=True)
    for s in samples:
        ctx_lines = [f"{i}. {c}" for i, c in enumerate(s["contexts"], 1)]
        prompt = (f"{SYSTEM_PROMPT}\n\n[검색결과]\n" + "\n\n".join(ctx_lines)
                  + f"\n\n[사용자 질문]\n{s['text']}\n")
        (indir / f"{s['qid']}.txt").write_text(prompt, encoding="utf-8")
    print(f"{len(samples)}건 입력 파일 생성 -> {indir}")
    return samples


def evaluate():
    samples = json.loads((HERE / "gen_samples.json").read_text(encoding="utf-8"))
    outdir = HERE / "gen_outputs"
    rows = []
    missing = []
    for s in samples:
        f = outdir / f"{s['qid']}.txt"
        if not f.exists():
            missing.append(s["qid"])
            continue
        answer = f.read_text(encoding="utf-8")
        g = check_answer(answer, s["contexts"])
        rows.append({"qid": s["qid"], "text": s["text"], **g})

    n = len(rows)
    fab_rows = [r for r in rows if r["fabrications"]]
    tot_recs = sum(r["n_recs"] for r in rows)
    tot_ground = sum(r["n_grounded"] for r in rows)
    print(f"\n===== 대규모 생성 환각 테스트 결과 (n={n}, 누락={len(missing)}) =====")
    print(f"허위 공고 포함 답변: {len(fab_rows)}/{n} ({len(fab_rows)/n*100:.1f}%)" if n else "n=0")
    print(f"전체 추천 항목: {tot_recs}, grounded: {tot_ground}, 환각 항목: {tot_recs-tot_ground} ({(tot_recs-tot_ground)/tot_recs*100:.2f}% of items)" if tot_recs else "")
    if fab_rows:
        print("\n허위 공고 상세:")
        for r in fab_rows:
            print(f"  {r['qid']} ({r['text'][:40]}): {r['fabrications']}")
    if missing:
        print(f"\n미생성(누락) qid: {missing[:20]}{'...' if len(missing)>20 else ''}")
    (HERE / "gen_eval_rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "eval"
    if cmd == "build":
        build_inputs()
    else:
        evaluate()

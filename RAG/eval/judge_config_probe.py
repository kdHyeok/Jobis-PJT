"""판정 '설정'이 병목인지 검증하는 소량 실험.

프롬프트 v1->v2 수정으로 κ가 0.26->0.33까지만 올랐다. 남은 원인 후보는
프롬프트가 아니라 판정 설정이다: 배치 20개 + thinkingBudget 0.
한 호출에 20건을 사고 없이 훑으면 직군 판단이 표면 유사도로 흐를 수 있다.

앵커 112건에만 배치 크기·thinking을 바꿔 재판정하고 κ를 비교한다.
전량(3361건)에 적용할지 결정하기 위한 저비용 사전 실험이다.
"""
from __future__ import annotations

import csv
import json
import os
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

EVAL_DIR = Path(__file__).parent
ANCHOR_DIR = EVAL_DIR / "anchor"
LABELS = ("Correct", "Ambiguous", "Incorrect")


def _url() -> str:
    base = os.environ.get("GMS_BASE_URL",
                          "https://generativelanguage.googleapis.com")
    model = os.environ.get("GMS_MODEL", "gemini-2.5-flash-lite")
    return f"{base}/v1beta/models/{model}:generateContent?key={os.environ['GMS_KEY']}"


def _call(prompt: str, thinking_budget: int) -> str:
    cfg = {"temperature": 0.0, "maxOutputTokens": 8192}
    # thinkingBudget 0 = 사고 비활성. -1 = 모델 자율. 양수 = 상한 지정.
    cfg["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": cfg}
    for attempt in range(4):
        r = requests.post(_url(), json=body, timeout=120)
        if r.status_code == 200:
            parts = r.json()["candidates"][0]["content"].get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        if r.status_code in (429,) or r.status_code >= 500:
            time.sleep(2 ** attempt + 1)
            continue
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    raise RuntimeError("재시도 초과")


def _anchor_pairs() -> dict[str, dict]:
    out = {}
    for name in ("session_easy_claude.csv", "session_ambiguous_claude.csv"):
        p = ANCHOR_DIR / name
        if not p.exists():
            continue
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            if r.get("label", "").strip() in LABELS:
                out[f"{r['qid']}:{r['uid']}"] = r
    return out


def _kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    av = [1 if x == "Correct" else 0 for x in a]
    bv = [1 if x == "Correct" else 0 for x in b]
    p_o = sum(1 for x, y in zip(av, bv) if x == y) / n
    p1, p2 = sum(av) / n, sum(bv) / n
    p_e = p1 * p2 + (1 - p1) * (1 - p2)
    return 1.0 if p_e >= 1.0 else (p_o - p_e) / (1 - p_e)


def run(batch_size: int, thinking_budget: int, label: str) -> dict[str, str]:
    from .judge import ACTIVE_PROMPT, _format_posting, _parse_response, _fetch_posting_details
    from jobrag.store import connect

    pairs = _anchor_pairs()
    by_q: dict[str, list[str]] = {}
    meta: dict[str, str] = {}
    for key, row in pairs.items():
        qid, uid = key.split(":", 1)
        by_q.setdefault(qid, []).append(uid)
        meta[qid] = row["query"]

    conn = connect()
    result: dict[str, str] = {}
    n_calls = 0
    t0 = time.time()
    try:
        for qid, uids in by_q.items():
            details = _fetch_posting_details(conn, uids)
            batches = [uids[i:i + batch_size] for i in range(0, len(uids), batch_size)]
            for batch in batches:
                bd = {u: details[u] for u in batch if u in details}
                if not bd:
                    continue
                id_map, parts = {}, []
                for i, (uid, d) in enumerate(bd.items(), 1):
                    sid = f"P{i}"
                    id_map[sid] = uid
                    parts.append(_format_posting(sid, d["title"], d["company"],
                                                 d["tech"], d["snippet"]))
                prompt = ACTIVE_PROMPT.format(query=meta[qid],
                                              postings="\n\n".join(parts), n=len(bd))
                try:
                    resp = _call(prompt, thinking_budget)
                    n_calls += 1
                except Exception as e:
                    print(f"    호출 실패 {qid}: {e}")
                    continue
                for uid, lab in _parse_response(resp, id_map).items():
                    result[f"{qid}:{uid}"] = lab
                time.sleep(0.4)
    finally:
        conn.close()

    elapsed = time.time() - t0
    anchor = {k: v["label"].strip() for k, v in pairs.items()}
    common = [k for k in anchor if k in result]
    kappa = _kappa([anchor[k] for k in common], [result[k] for k in common])
    agree = sum(1 for k in common
                if (anchor[k] == "Correct") == (result[k] == "Correct"))
    jc = [k for k in common if result[k] == "Correct"]
    prec = (sum(1 for k in jc if anchor[k] == "Correct") / len(jc)) if jc else 0.0
    ji = [k for k in common if result[k] == "Incorrect"]
    rec = (sum(1 for k in ji if anchor[k] != "Correct") / len(ji)) if ji else 0.0

    print(f"\n[{label}] batch={batch_size} thinking={thinking_budget}")
    print(f"  판정 {len(result)}/{len(anchor)}건, API {n_calls}콜, {elapsed:.0f}초")
    print(f"  κ = {kappa:.4f}   일치 = {agree/len(common)*100:.1f}%")
    print(f"  judge Correct {len(jc)}건 -> 앵커 동의 {prec*100:.0f}%")
    print(f"  judge Incorrect {len(ji)}건 -> 앵커 동의 {rec*100:.0f}%")
    print(f"  분포: {dict(Counter(result.values()))}")
    return {"label": label, "batch": batch_size, "thinking": thinking_budget,
            "kappa": round(kappa, 4), "n": len(common),
            "correct_precision": round(prec, 4), "incorrect_precision": round(rec, 4),
            "n_calls": n_calls, "seconds": round(elapsed, 1)}


def main() -> None:
    configs = [
        (5, -1, "소량배치+사고"),
        (1, -1, "단건+사고"),
    ]
    out = []
    for bs, tb, name in configs:
        try:
            out.append(run(bs, tb, name))
        except Exception as e:
            print(f"[{name}] 실패: {e}")
    path = EVAL_DIR / "judge_config_probe.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과: {path}")


if __name__ == "__main__":
    main()

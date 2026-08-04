# -*- coding: utf-8 -*-
"""claude.exe CLI 세션 한도(7:40pm 리셋)로 judge_v2가 막혔을 때, 이 대화(Claude Desktop)가
직접 PROMPT_V4로 판정한 결과를 judgments_v2.json에 병합하는 보조 도구.

  python -m eval.manual_batch --peek [--n 40]      # 다음 미판정 배치의 프롬프트를 파일로 출력
  python -m eval.manual_batch --apply <응답파일>    # 그 응답(JSON lines)을 파싱해 병합

peek/apply는 한 쌍으로 쓴다 — peek이 저장한 id_map(_manual_batch_state.json)을 apply가 그대로 사용.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jobrag.store import connect

from . import judge

EVAL_DIR = Path(__file__).parent
POOL_PATH = EVAL_DIR / "pool_v2.json"
STATE_PATH = EVAL_DIR / "_manual_batch_state.json"
PROMPT_OUT = EVAL_DIR / "_manual_batch_prompt.txt"

judge.JUDGMENTS_PATH = EVAL_DIR / "judgments_v2.json"


def _next_pending(pool: dict, n: int, only_qid: str | None = None):
    data = judge._load_judgments()
    for qid, q in pool["queries"].items():
        if only_qid and qid != only_qid:
            continue
        existing = data.get("queries", {}).get(qid, {}).get("labels", {})
        pending = [u for u in q["uids"] if u not in existing]
        if pending:
            return qid, q["query"], pending[:n], len(q["uids"]), len(existing)
    return None, None, [], 0, 0


def peek(n: int, only_qid: str | None = None):
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    qid, query_text, batch_uids, n_pool, n_existing = _next_pending(pool, n, only_qid)
    if qid is None:
        print("모든 질의 판정 완료")
        return

    conn = connect()
    try:
        details = judge._fetch_posting_details(conn, batch_uids)
    finally:
        conn.close()

    id_map, parts = {}, []
    for i, uid in enumerate(batch_uids, 1):
        sid = f"P{i}"
        id_map[sid] = uid
        d = details.get(uid, {"title": "?", "company": "?", "tech": [], "snippet": ""})
        parts.append(judge._format_posting(sid, d["title"], d["company"], d["tech"], d["snippet"]))

    prompt = judge.PROMPT.format(query=query_text, postings="\n\n".join(parts), n=len(batch_uids))
    PROMPT_OUT.write_text(prompt, encoding="utf-8")
    STATE_PATH.write_text(json.dumps({"qid": qid, "query": query_text, "id_map": id_map,
                                       "n_pool": n_pool}, ensure_ascii=False), encoding="utf-8")
    print(f"질의 {qid} ({n_existing}/{n_pool} 완료) — 이번 배치 {len(batch_uids)}건")
    print(f"프롬프트: {PROMPT_OUT}")


def apply(response_path: str):
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    qid, query_text, id_map, n_pool = (
        state["qid"], state["query"], state["id_map"], state["n_pool"])
    response = Path(response_path).read_text(encoding="utf-8")
    labels = judge._parse_response(response, id_map)

    unparsed = set(id_map.values()) - set(labels)
    if unparsed:
        print(f"[경고] 파싱 안 된 uid {len(unparsed)}건: {sorted(unparsed)[:5]}...")

    data = judge._load_judgments()
    existing = data.get("queries", {}).get(qid, {}).get("labels", {})
    existing.update(labels)
    data.setdefault("queries", {})[qid] = {
        "query": query_text, "n_judged": len(existing), "n_pool": n_pool,
        "labels": existing,
    }
    judge._save_judgments(data)
    print(f"병합 완료: {qid} {len(existing)}/{n_pool} ({len(existing)/n_pool*100:.0f}%)")


def main():
    if "--peek" in sys.argv:
        n = 40
        if "--n" in sys.argv:
            n = int(sys.argv[sys.argv.index("--n") + 1])
        qid = sys.argv[sys.argv.index("--qid") + 1] if "--qid" in sys.argv else None
        peek(n, qid)
    elif "--apply" in sys.argv:
        apply(sys.argv[sys.argv.index("--apply") + 1])
    else:
        print("사용: --peek [--n N] | --apply <응답파일>")


if __name__ == "__main__":
    main()

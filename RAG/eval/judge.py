"""LLM 판정 엔진 -배치 50, 워커 3, 지수 백오프, 재개 루프."""
from __future__ import annotations

import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

JUDGMENTS_PATH = Path(__file__).parent / "judgments.json"
BATCH_SIZE = 20
MAX_WORKERS = 3
GLOBAL_THROTTLE = 0.5
MAX_RETRIES = 3

PROMPT_V1 = """You are an IR relevance judge for Korean job postings.

Query: "{query}"

For each posting below, output one JSON per line:
{{"id": "<ID>", "label": "Correct|Ambiguous|Incorrect"}}

Correct = clearly relevant. Ambiguous = borderline. Incorrect = not relevant.

Postings:
{postings}

Output {n} JSON lines. No other text."""


def _api_url() -> str:
    base = os.environ.get("GMS_BASE_URL",
                          "https://gms.ssafy.io/gmsapi/generativelanguage.googleapis.com")
    model = os.environ.get("GMS_MODEL", "gemini-2.5-flash-lite")
    key = os.environ["GMS_KEY"]
    return f"{base}/v1beta/models/{model}:generateContent?key={key}"


def _call_llm(prompt: str) -> str:
    url = _api_url()
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    for attempt in range(MAX_RETRIES):
        r = requests.post(url, json=body, timeout=60)
        if r.status_code == 200:
            data = r.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            if retry_after:
                wait = float(retry_after)
            else:
                wait = (2 ** attempt) + random.random()
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            time.sleep((2 ** attempt) + random.random())
            continue
        raise RuntimeError(f"LLM 호출 실패 {r.status_code}: {r.text[:300]}")
    raise RuntimeError(f"LLM 호출 {MAX_RETRIES}회 실패")


def _format_posting(short_id: str, title: str, company: str, tech: list[str],
                    detail_snippet: str) -> str:
    tech_str = ", ".join(tech[:10]) if tech else "N/A"
    return f"{short_id} | {company} - {title} | tech: {tech_str}\n{detail_snippet[:300]}"


def _parse_response(text: str, id_map: dict[str, str]) -> dict[str, str]:
    """Parse LLM response. id_map: {short_id -> real_uid}."""
    labels = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            short_id = obj.get("id", "").strip()
            label = obj.get("label", "")
            real_uid = id_map.get(short_id)
            if real_uid and label in ("Correct", "Ambiguous", "Incorrect"):
                labels[real_uid] = label
        except json.JSONDecodeError:
            continue
    return labels


def _fetch_posting_details(conn, uids: list[str]) -> dict[str, dict]:
    if not uids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT p.uid, p.title, p.company, p.tech,
                      COALESCE(
                          (SELECT text FROM chunks WHERE posting_uid = p.uid
                           ORDER BY (part = 'full') DESC, chunk_id LIMIT 1),
                          ''
                      ) AS snippet
               FROM postings p WHERE p.uid = ANY(%s)""",
            (uids,),
        )
        return {r[0]: {"title": r[1], "company": r[2], "tech": r[3] or [], "snippet": r[4]}
                for r in cur.fetchall()}


_throttle_lock = None
_last_call = 0.0


def _throttled_call(prompt: str) -> str:
    global _last_call
    import threading
    global _throttle_lock
    if _throttle_lock is None:
        _throttle_lock = threading.Lock()
    with _throttle_lock:
        now = time.time()
        wait = GLOBAL_THROTTLE - (now - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
    return _call_llm(prompt)


def judge_batch(conn, query_text: str, uids: list[str]) -> dict[str, str]:
    details = _fetch_posting_details(conn, uids)
    postings_text = "\n\n".join(
        _format_posting(uid, d["title"], d["company"], d["tech"], d["snippet"])
        for uid, d in details.items()
    )
    prompt = PROMPT_V1.format(
        query=query_text,
        postings=postings_text,
        n=len(details),
    )
    response = _throttled_call(prompt)
    return _parse_response(response, set(details.keys()))


def _load_judgments() -> dict:
    if JUDGMENTS_PATH.exists():
        return json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
    return {"queries": {}}


def _save_judgments(data: dict) -> None:
    JUDGMENTS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


_save_lock = None


def _get_save_lock():
    import threading
    global _save_lock
    if _save_lock is None:
        _save_lock = threading.Lock()
    return _save_lock


def judge_query(conn, qid: str, query_text: str, pool_uids: list[str]) -> dict[str, str]:
    """질의 1건의 풀 전체를 배치 단위로 판정. 재개형, 3-worker 병렬 API 호출."""
    data = _load_judgments()
    existing = data.get("queries", {}).get(qid, {}).get("labels", {})
    pending = [u for u in pool_uids if u not in existing]

    if not pending:
        return existing

    all_details = _fetch_posting_details(conn, pending)

    all_labels = dict(existing)
    batches = [pending[i:i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]

    def _process_batch(batch):
        batch_details = {uid: all_details[uid] for uid in batch if uid in all_details}
        if not batch_details:
            return {}, batch
        id_map = {}
        postings_parts = []
        for i, (uid, d) in enumerate(batch_details.items(), 1):
            short_id = f"P{i}"
            id_map[short_id] = uid
            postings_parts.append(
                _format_posting(short_id, d["title"], d["company"], d["tech"], d["snippet"])
            )
        postings_text = "\n\n".join(postings_parts)
        prompt = PROMPT_V1.format(query=query_text, postings=postings_text, n=len(batch_details))
        response = _throttled_call(prompt)
        return _parse_response(response, id_map), batch

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool_ex:
        futures = [pool_ex.submit(_process_batch, b) for b in batches]
        for fut in as_completed(futures):
            try:
                result, batch = fut.result()
                with _get_save_lock():
                    all_labels.update(result)
                    data.setdefault("queries", {})[qid] = {
                        "query": query_text,
                        "n_judged": len(all_labels),
                        "n_pool": len(pool_uids),
                        "labels": all_labels,
                    }
                    _save_judgments(data)
            except Exception as e:
                print(f"  batch failed: {e}")

    return all_labels


def judge_all(conn, pool: dict[str, dict]) -> dict[str, dict[str, str]]:
    """풀 전체를 판정. pool: {qid: {"query": str, "uids": [str]}}"""
    results = {}
    total_q = len(pool)
    for i, (qid, info) in enumerate(pool.items(), 1):
        print(f"[{i}/{total_q}] Judging {qid}: {info['query']} ({len(info['uids'])} items)")
        labels = judge_query(conn, qid, info["query"], info["uids"])
        results[qid] = labels
        judged = len(labels)
        total = len(info["uids"])
        print(f"  -> {judged}/{total} judged ({judged/total*100:.0f}%)")
    return results


def coverage(pool: dict[str, dict]) -> dict[str, float]:
    data = _load_judgments()
    result = {}
    for qid, info in pool.items():
        existing = data.get("queries", {}).get(qid, {}).get("labels", {})
        result[qid] = len(existing) / len(info["uids"]) if info["uids"] else 1.0
    return result

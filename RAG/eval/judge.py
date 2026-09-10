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

# v2: v1 판정이 기술 스택 겹침만 보고 직군을 무시하는 실패가 앵커 대조에서 확인됐다
# ("Python QA 테스트 자동화" -> "AI 서비스 개발자"를 Correct로 판정). 직군 일치를
# Correct의 필요조건으로 명시한다. 앵커에 맞춘 튜닝이 아니라 확인된 결함 1건만 수정.
PROMPT_V2 = """You are an IR relevance judge for Korean job postings.

Query: "{query}"

The query states a desired JOB ROLE, plus optional tech / region / experience.

Judge each posting:
- Correct: the posting's job role matches what the query asks for, AND the
  stated tech/region/experience conditions are broadly satisfied.
- Ambiguous: the role matches but some stated condition clearly does not,
  OR the role is adjacent but not the same (e.g. backend vs full-stack).
- Incorrect: the job role is different from what the query asks for.

Sharing a technology is NOT enough. A posting is Incorrect if its role differs,
even when the tech stack overlaps heavily. Examples:
- query "Python QA engineer test automation" vs posting "AI service developer
  (Python)" -> Incorrect. Python matches but the role is not QA.
- query "Python data analyst" vs posting "MLOps engineer (Python)" -> Incorrect.
Decide the role first; only then check tech, region, and experience.

Postings:
{postings}

Now output exactly {n} lines, one per posting, in this exact format:
{{"id": "P1", "label": "Correct"}}

Use the key names "id" and "label" verbatim. No code fences, no other text."""

# v3: v2 A/B(앵커 112쌍)에서 직군 결함은 잡혔으나(binary 70.5%->79.5%) 잔여 불일치
# 20건이 전부 경력 요건·지역 무시였다 ("부산 신입" -> "경력 4년^" Correct,
# "3년차" -> "경력 10년^" Correct, "서울" -> 원주 근무지 Correct).
# 경력·지역 양립을 Correct의 필요조건으로 명시한다. 역시 확인된 결함 단위 수정.
PROMPT_V3 = """You are an IR relevance judge for Korean job postings.

Query: "{query}"

The query states a desired JOB ROLE, plus optional tech / region / experience.
Judge in this order: role first, then region, then experience.

1. ROLE: if the posting's job role differs from the query's role, label Incorrect.
   Sharing a technology is NOT enough. Examples:
   - query "Python QA engineer test automation" vs posting "AI service developer
     (Python)" -> Incorrect. Python matches but the role is not QA.
   - query "Python data analyst" vs posting "MLOps engineer (Python)" -> Incorrect.

2. REGION: if the query names a region and the posting's workplace is in a
   different city/province, label Incorrect. (e.g. query "서울" vs workplace
   원주/부산/대구 -> Incorrect. 강남/판교 etc. count as their containing city.)

3. EXPERIENCE: compare the query's experience level with the posting's requirement.
   - Query "신입" but posting requires 3+ years -> Incorrect.
   - Query "N년차" but posting requires far more (e.g. 3년차 vs 7년/10년 이상)
     -> Incorrect.
   - Requirement slightly above the query (within ~2 years, e.g. 3년차 vs
     5년 이상) or the query says 경력무관 but the posting requires seniority
     -> Ambiguous.
   - Requirement at or below the query's level, or 무관/unstated -> compatible.

Labels:
- Correct: role matches AND region compatible AND experience compatible.
- Ambiguous: role matches but one condition is borderline as defined above,
  OR the role is adjacent but not the same (e.g. backend vs full-stack).
- Incorrect: any rule above says Incorrect.

Postings:
{postings}

Now output exactly {n} lines, one per posting, in this exact format:
{{"id": "P1", "label": "Correct"}}

Use the key names "id" and "label" verbatim. No code fences, no other text."""

# 실제 판정에 쓰이는 프롬프트. 바꾸면 기존 judgments.json은 무효 -전량 재판정해야 한다.
ACTIVE_PROMPT = PROMPT_V3
PROMPT_VERSION = "v3"


def _api_url() -> str:
    base = os.environ.get("GMS_BASE_URL",
                          "https://generativelanguage.googleapis.com")
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


_ID_KEYS = ("id", "posting_id", "uid", "postingId")
_LABEL_KEYS = ("label", "result", "relevance", "judgment", "verdict")


def _parse_response(text: str, id_map: dict[str, str]) -> dict[str, str]:
    """Parse LLM response. id_map: {short_id -> real_uid}.

    프롬프트가 길어지면 모델이 키 이름을 바꾸거나(id -> posting_id) 코드펜스로
    감싸는 드리프트가 관찰됐다. 형식 변주를 흡수해 판정 자체를 잃지 않는다.
    """
    labels = {}
    for line in text.strip().split("\n"):
        line = line.strip().strip("`")
        if not line or line in ("json", "JSON"):
            continue
        if line.startswith("```"):
            continue
        line = line.rstrip(",")
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        short_id = next((str(obj[k]).strip() for k in _ID_KEYS if k in obj), None)
        label = next((str(obj[k]).strip() for k in _LABEL_KEYS if k in obj), None)
        if short_id is None or label is None:
            continue
        real_uid = id_map.get(short_id)
        if real_uid and label in ("Correct", "Ambiguous", "Incorrect"):
            labels[real_uid] = label
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
    prompt = ACTIVE_PROMPT.format(
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
        prompt = ACTIVE_PROMPT.format(query=query_text, postings=postings_text, n=len(batch_details))
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

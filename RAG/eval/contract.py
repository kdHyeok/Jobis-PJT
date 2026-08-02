"""Tier 0 -결정적 검증. LLM·사람 판정 없이 계약 위반을 잡는다."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from jobrag.store import connect
from jobrag.query_parser import parse_query, load_region_vocab
from jobrag.search import hybrid_search

REPORT_PATH = Path(__file__).parent / "contract_report.json"

SAMPLE_QUERIES_A = [
    "데이터 엔지니어",
    "백엔드 개발자",
    "React 프론트엔드",
    "서울 개발자 채용",
    "AWS 클라우드 엔지니어",
]

SAMPLE_PROFILE_B = {
    "education": [{"id": "edu-1", "school": "OO대학교", "major": "컴퓨터공학",
                   "degree": "학사", "status": "졸업", "period": "2018.03 ~ 2022.02"}],
    "experiences": [{"id": "exp-1", "company": "OO스타트업", "role": "프론트엔드 개발자",
                     "employmentType": "정규직", "period": "2022.03 ~ 2024.06",
                     "summary": "React 기반 웹 서비스 프론트엔드 개발 및 유지보수"}],
    "projects": [{"id": "prj-1", "title": "커머스 웹 리뉴얼", "projectType": "실무",
                  "period": "2023.01 ~ 2023.08", "teamSize": 5, "role": "프론트엔드 리드",
                  "summary": "React + TypeScript 기반 커머스 프론트엔드 전면 개편",
                  "techStack": ["React", "TypeScript", "Next.js", "Redux"],
                  "achievements": ["초기 로딩 속도 40% 개선"]}],
    "skills": [{"name": "React", "level": "상"}, {"name": "TypeScript", "level": "상"},
               {"name": "JavaScript", "level": "상"}, {"name": "Next.js", "level": "중"}],
    "certifications": [],
    "languages": [],
    "bootcamp": [],
    "awards": [],
    "evidenceMap": [],
    "uncertainties": [],
}


def _posting_hash(row: dict, fields: list[str]) -> str:
    parts = [str(row.get(f, "")) for f in fields]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


ORIGINAL_FIELDS = [
    "source", "posting_id", "company", "title", "url", "employment_type",
    "experience", "education", "location", "posted_date", "deadline",
    "detail_text", "image_urls", "need_ocr", "collected_at",
]


def _fetch_db_hashes(conn, uids: list[str]) -> dict[str, str]:
    """DB의 raw JSONB에서 원본 필드 해시를 뽑는다."""
    if not uids:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT uid, raw FROM postings WHERE uid = ANY(%s)", (uids,))
        rows = cur.fetchall()
    hashes = {}
    for uid, raw in rows:
        if raw:
            hashes[uid] = _posting_hash(raw, ORIGINAL_FIELDS)
    return hashes


def check_fields_intact(output_postings: list[dict], conn) -> dict:
    uids = [p.get("posting_id", "") for p in output_postings]
    source_uids = []
    for p in output_postings:
        src = p.get("source", "")
        pid = p.get("posting_id", "")
        source_uids.append(f"{src}:{pid}")
    db_hashes = _fetch_db_hashes(conn, source_uids)

    results = []
    for p, suid in zip(output_postings, source_uids):
        out_hash = _posting_hash(p, ORIGINAL_FIELDS)
        db_hash = db_hashes.get(suid)
        results.append({
            "uid": suid,
            "match": out_hash == db_hash if db_hash else None,
            "note": "uid not in DB" if db_hash is None else "",
        })
    passed = all(r["match"] is True for r in results)
    return {"name": "fields_intact", "passed": passed, "details": results}


def check_sorted(output_postings: list[dict]) -> dict:
    scores = [p.get("score", 0) for p in output_postings]
    monotone = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
    return {"name": "sorted", "passed": monotone, "scores": scores}


def check_topk(output_postings: list[dict], top_k: int = 3) -> dict:
    return {"name": "topk", "passed": len(output_postings) <= top_k,
            "actual": len(output_postings), "limit": top_k}


def check_empty_ok(search_fn, conn) -> dict:
    """존재할 수 없는 질의로 검색해 빈 결과가 예외 없이 나오는지 확인."""
    try:
        result = search_fn(conn, "zzzzz_없는직업_99999")
        passed = isinstance(result, dict) and "postings" in result and result["postings"] == []
        return {"name": "empty_ok", "passed": passed}
    except Exception as e:
        return {"name": "empty_ok", "passed": False, "error": str(e)}


def check_accepts_string(search_fn, conn) -> dict:
    try:
        result = search_fn(conn, "백엔드 개발자")
        passed = isinstance(result, dict) and "postings" in result
        return {"name": "accepts_string", "passed": passed}
    except Exception as e:
        return {"name": "accepts_string", "passed": False, "error": str(e)}


def check_accepts_profile(search_fn, conn) -> dict:
    try:
        result = search_fn(conn, SAMPLE_PROFILE_B)
        passed = isinstance(result, dict) and "postings" in result
        return {"name": "accepts_profile", "passed": passed}
    except Exception as e:
        return {"name": "accepts_profile", "passed": False, "error": str(e)}


def check_skills_grounded(output_postings: list[dict]) -> dict:
    violations = []
    for p in output_postings:
        reason = p.get("match_reason", {})
        skills = reason.get("matched_skills", [])
        text = (p.get("detail_text") or "").lower()
        for s in skills:
            if s.lower() not in text:
                violations.append({"uid": f"{p.get('source')}:{p.get('posting_id')}",
                                   "skill": s})
    return {"name": "skills_grounded", "passed": len(violations) == 0,
            "violations": violations}


def check_fields_grounded(output_postings: list[dict], input_data) -> dict:
    if isinstance(input_data, str):
        return {"name": "fields_grounded", "passed": True, "note": "input is string"}
    nonempty_fields = set()
    for field in ("skills", "projects", "experiences", "education",
                  "certifications", "languages", "bootcamp", "awards"):
        val = input_data.get(field, [])
        if val:
            nonempty_fields.add(field)
            if field == "projects":
                for proj in val:
                    if proj.get("techStack"):
                        nonempty_fields.add("projects.techStack")
    violations = []
    for p in output_postings:
        reason = p.get("match_reason", {})
        for mf in reason.get("matched_fields", []):
            base = mf.split(".")[0] if "." not in mf else mf
            if base not in nonempty_fields and mf not in nonempty_fields:
                violations.append({"uid": f"{p.get('source')}:{p.get('posting_id')}",
                                   "field": mf})
    return {"name": "fields_grounded", "passed": len(violations) == 0,
            "violations": violations}


def check_latency(conn, region_vocab, queries: list[str] | None = None,
                  n_runs: int = 3) -> dict:
    if queries is None:
        queries = SAMPLE_QUERIES_A
    timings = []
    for q in queries:
        for _ in range(n_runs):
            spec = parse_query(q, region_vocab)
            t0 = time.perf_counter()
            hybrid_search(conn, spec, top_k=3)
            timings.append(time.perf_counter() - t0)
    timings.sort()
    n = len(timings)
    return {
        "name": "latency",
        "p50": round(timings[n // 2], 3),
        "p95": round(timings[int(n * 0.95)], 3),
        "max": round(timings[-1], 3),
        "n_measurements": n,
    }


def run_all(conn, search_fn=None) -> dict:
    """Tier 0 전체 실행. search_fn은 명세서 계약 어댑터(없으면 계약 검증 일부 skip)."""
    region_vocab = load_region_vocab(conn)
    results = []

    results.append(check_latency(conn, region_vocab))

    if search_fn is not None:
        results.append(check_accepts_string(search_fn, conn))
        results.append(check_accepts_profile(search_fn, conn))
        results.append(check_empty_ok(search_fn, conn))

        for q in SAMPLE_QUERIES_A:
            out = search_fn(conn, q)
            postings = out.get("postings", [])
            if postings:
                results.append(check_sorted(postings))
                results.append(check_topk(postings))
                results.append(check_skills_grounded(postings))
                results.append(check_fields_grounded(postings, q))
                results.append(check_fields_intact(postings, conn))

        out = search_fn(conn, SAMPLE_PROFILE_B)
        postings = out.get("postings", [])
        if postings:
            results.append(check_sorted(postings))
            results.append(check_topk(postings))
            results.append(check_fields_grounded(postings, SAMPLE_PROFILE_B))
    else:
        results.append({"name": "contract_adapter", "passed": None,
                        "note": "no search_fn provided -skipping contract checks. "
                                "명세서 계약 어댑터(입력A/B -> postings+score+match_reason) 미구현"})

    report = {
        "tier": 0,
        "all_passed": all(r.get("passed", True) is not False for r in results),
        "checks": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    from jobrag import spec_adapter

    conn = connect()
    try:
        report = run_all(conn, search_fn=spec_adapter.search)
        n_pass = sum(1 for c in report["checks"] if c.get("passed") is True)
        n_fail = sum(1 for c in report["checks"] if c.get("passed") is False)
        n_skip = sum(1 for c in report["checks"] if c.get("passed") is None)
        print(f"\nTier 0 결과: {n_pass} passed, {n_fail} failed, {n_skip} skipped")
        if report["all_passed"]:
            print("[OK] all passed")
        else:
            for c in report["checks"]:
                if c.get("passed") is False:
                    print(f"  [FAIL] {c['name']}")
        print(f"리포트: {REPORT_PATH}")
    finally:
        conn.close()

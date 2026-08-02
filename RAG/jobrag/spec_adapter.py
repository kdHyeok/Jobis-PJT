"""RAG 입출력 명세서 계약 어댑터.

입출력 계약: RAG_입출력_명세서.md (AI Agent -> RAG 공고 검색)
- 입력 A: 직업명 문자열 (예: "백엔드 개발자")
- 입력 B: 이력서 profile JSON (_UserProfileRead)
- 출력: {"postings": [원본 공고 JSON + score + match_reason, ...]}
  · 원본 공고 필드는 postings.raw(JSONB)를 그대로 사용 — 변경 금지 계약
  · score 내림차순, 기본 top_k=3, 0건이면 {"postings": []}

입력 정규화 방침:
- 입력 A(자유 문자열)만 parse_query 텍스트 정규화를 탄다.
- 입력 B는 필드가 이미 구조화돼 있으므로 파싱 없이 **필드 -> QuerySpec 직접 매핑**:
  · skills[].name + projects[].techStack  -> spec.tech (화이트리스트 표준명으로 정규화)
  · experiences[].role (+projects[].role) -> spec.role_category (룰 분류) + 임베딩 질의 텍스트
  · experiences[].period 합산            -> spec.exp_years (지원자 연차)
  · 명세서 입력에는 지역 선호가 없으므로 regions는 항상 빈 값
  · evidenceMap / uncertainties 는 명세서상 메타데이터 — 검색 신호로 쓰지 않는다
"""
from __future__ import annotations

import re
import sys

from .query_parser import QuerySpec, parse_query, load_region_vocab
from . import query_text
from .role_taxonomy import classify
from .search import hybrid_search
from .whitelist import extract_tech

TOP_K_DEFAULT = 3

# ── 입력 B: profile -> QuerySpec ──────────────────────────

_PERIOD_RE = re.compile(r"(\d{4})\.(\d{1,2})\s*~\s*(\d{4})\.(\d{1,2})")


def _total_exp_years(experiences: list[dict]) -> int | None:
    """재직 기간 합산(개월) -> 연차. 파싱 불가 항목은 건너뛴다."""
    months = 0
    for exp in experiences or []:
        m = _PERIOD_RE.search(exp.get("period") or "")
        if not m:
            continue
        y1, m1, y2, m2 = map(int, m.groups())
        months += max(0, (y2 - y1) * 12 + (m2 - m1))
    return months // 12 if months > 0 else None


def _profile_tech(profile: dict) -> tuple[list[str], dict[str, set[str]]]:
    """skills + projects.techStack -> 표준 기술명. 기술별 출처 필드도 기록한다."""
    provenance: dict[str, set[str]] = {}
    for s in profile.get("skills") or []:
        for std in extract_tech(str(s.get("name") or "")):
            provenance.setdefault(std, set()).add("skills")
    for prj in profile.get("projects") or []:
        for raw in prj.get("techStack") or []:
            for std in extract_tech(str(raw)):
                provenance.setdefault(std, set()).add("projects.techStack")
    return list(provenance.keys()), provenance


def _profile_roles(profile: dict) -> list[str]:
    roles = [e.get("role") or "" for e in profile.get("experiences") or []]
    roles += [p.get("role") or "" for p in profile.get("projects") or []]
    return [r for r in roles if r.strip()]


def _spec_from_profile(profile: dict) -> tuple[QuerySpec, dict[str, set[str]]]:
    tech, provenance = _profile_tech(profile)
    roles = _profile_roles(profile)

    role_category = None
    if roles:
        role_category = classify(roles[0], " ".join(roles), tech) or None

    # 질의 텍스트는 축별로 나뉜다 (jobrag/query_text.py 참고):
    #   text        — 어휘 축(BM25). 직군 + 기술. 파서를 거치지 않는다(고정형 입력)
    #   dense_text  — 의미 축(dense + 재순위). 범용 기술로 임베딩이 희석되는 결함 대응
    role0 = roles[0] if roles else ""
    text = query_text.lexical_text(role0, tech) if (role0 or tech) else "개발자"
    exp_years = _total_exp_years(profile.get("experiences") or [])

    spec = QuerySpec(
        text=text,
        dense_text=(query_text.semantic_text(role0, tech, exp_years) if role0 else None),
        tech=tech,
        regions=[],                      # 명세서 입력에 지역 선호 없음
        exp_years=exp_years,
        role_category=role_category,
    )
    return spec, provenance


# ── 출력 조립 ─────────────────────────────────────────────

def _fetch_raw(conn, uids: list[str]) -> dict[str, dict]:
    if not uids:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT uid, raw FROM postings WHERE uid = ANY(%s)", (uids,))
        return {uid: raw for uid, raw in cur.fetchall() if raw}


_TOKEN_RE = re.compile(r"[가-힣A-Za-z]{2,}")


def _match_reason(spec: QuerySpec, provenance: dict[str, set[str]] | None,
                  raw: dict) -> dict:
    detail = (raw.get("detail_text") or "").lower()
    title = (raw.get("title") or "").lower()

    # matched_skills: 입력 기술 중 공고 본문에 실제로 등장하는 것만 (환각 0 계약)
    matched_skills = [t for t in spec.tech if t.lower() in detail]

    # matched_keywords: 질의 텍스트 토큰 중 제목/본문에 등장하는 것 (기술 제외)
    skill_lower = {t.lower() for t in matched_skills}
    matched_keywords = []
    for tok in _TOKEN_RE.findall(spec.text):
        low = tok.lower()
        if low in skill_lower or tok in matched_keywords:
            continue
        if low in title or low in detail:
            matched_keywords.append(tok)

    # matched_fields: 매칭에 기여한 '입력' 필드 — 비어있지 않은 필드만 (계약)
    matched_fields: list[str] = []
    if provenance is not None:
        for skill in matched_skills:
            for field in provenance.get(skill, ()):
                if field not in matched_fields:
                    matched_fields.append(field)
        if matched_keywords and "experiences" not in matched_fields:
            matched_fields.append("experiences")

    return {
        "matched_skills": matched_skills,
        "matched_keywords": matched_keywords[:8],
        "matched_fields": matched_fields,
    }


def _hit_score(h, prev: float | None) -> float:
    """최종 순위와 정합인 단조 score. 재순위 점수 > RRF > dense 순으로 사용하고,
    계층(exact/relaxed) 경계에서 원점수가 역전하면 직전 값으로 클립한다."""
    raw = getattr(h, "rerank_score", None)
    if raw is None:
        raw = h.rrf if h.rrf else (h.dense_score or 0.0)
    score = round(float(raw), 4)
    if prev is not None and score > prev:
        score = prev
    return score


# ── 진입점 ────────────────────────────────────────────────

def search(conn, input_data, top_k: int = TOP_K_DEFAULT,
           use_rerank: bool = True) -> dict:
    """명세서 계약 진입점. 입력 A(str) / 입력 B(dict) 모두 수용.

    계약상 이 함수는 예외를 밖으로 내보내지 않고, 매칭 없음은 {"postings": []}다.
    """
    try:
        provenance = None
        if isinstance(input_data, dict):
            spec, provenance = _spec_from_profile(input_data)
        else:
            region_vocab = load_region_vocab(conn)
            spec = parse_query(str(input_data or ""), region_vocab)
            if not spec.text.strip():
                return {"postings": []}

        result = hybrid_search(conn, spec, top_k=top_k,
                               allow_relax=True, use_rerank=use_rerank)
        hits = result.hits

        # 무의미 질의 가드: 기술·직군 신호가 전혀 없고 어휘 매치(BM25)도 전무하면
        # dense 최근접만으로 채우지 않고 0건을 반환한다 (empty_ok 계약).
        if not spec.tech and not spec.role_category and not spec.regions:
            if not any(h.bm25_rank is not None for h in hits):
                return {"postings": []}

        raw_map = _fetch_raw(conn, [h.posting_uid for h in hits])
        postings = []
        prev_score = None
        for h in hits:
            raw = raw_map.get(h.posting_uid)
            if not raw:
                continue                     # 원본 없는 공고는 계약상 반환 불가
            item = dict(raw)                 # 원본 필드 그대로 (변경 금지)
            score = _hit_score(h, prev_score)
            prev_score = score
            item["score"] = score
            item["match_reason"] = _match_reason(spec, provenance, raw)
            postings.append(item)

        return {"postings": postings}
    except Exception:                        # noqa: BLE001 — 계약: 예외 금지
        return {"postings": []}


if __name__ == "__main__":
    import json
    from .store import connect

    query = sys.argv[1] if len(sys.argv) > 1 else "백엔드 개발자"
    conn = connect()
    try:
        out = search(conn, query)
        slim = [{k: p.get(k) for k in ("source", "posting_id", "title", "company",
                                        "score", "match_reason")}
                for p in out["postings"]]
        print(json.dumps(slim, ensure_ascii=False, indent=2))
    finally:
        conn.close()

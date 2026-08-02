"""RAG 입출력 명세서 계약 어댑터.

입출력 계약: RAG_입출력_명세서.md (AI Agent -> RAG 공고 검색)
- 입력 A  : 직업명 문자열 (예: "백엔드 개발자")
- 입력 B  : 이력서 profile JSON (_UserProfileRead)
- 입력 A+B: 직업명 + profile을 함께 (예: {"title": "백엔드 개발자", "profile": {...}})
  · 판별은 classify_input() 한 곳에서 한다. A+B에서는 직업명이 직군을 **명시**하므로
    이력에서 직군을 추론하지 않는다 — 실제 이력서 직함의 classify() 오분류 위험을 피한다.
- 출력: {"postings": [원본 공고 JSON + score + match_reason, ...]}
  · 원본 공고 필드는 postings.raw(JSONB)를 그대로 사용 — 변경 금지 계약
  · score 내림차순, 기본 top_k=3, 0건이면 {"postings": []}

입력 정규화 방침:
- 입력 A(자유 문자열)만 parse_query 텍스트 정규화를 탄다.
- 입력 A+B는 두 경로를 모두 태우고 필드별 우선순위로 합친다 (_spec_from_combined 참고).
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


# ── 입력 경우의 수 판별 (명세서 §2) ──────────────────────
#
# 입력은 A · B · A+B 세 가지로 온다.
#   A   직업명 문자열              "백엔드 개발자"
#   B   profile JSON               {_UserProfileRead ...}
#   A+B 직업명 + profile           {"title": "...", "profile": {...}}
#
# 2026-07-30까지 어댑터는 `isinstance(input_data, dict)` 하나로만 갈라져서 A+B가 오면
# **profile만 보고 직업명을 버렸다.** 직업명은 "지금 무엇을 원하는가"(의도)이고 profile은
# "무엇을 해왔는가"(이력)이므로, 직업명을 버리면 이력에서 직군을 **추론**해야 한다 —
# 실제 이력서 직함("주임연구원", "Software Engineer")에서 classify()가 오분류할 위험이
# 그대로 남는다. A+B에서는 추론이 불필요하므로 직업명을 반드시 써야 한다.

_PROFILE_KEYS = ("education", "experiences", "projects", "skills",
                 "certifications", "languages", "bootcamp", "awards")


def classify_input(input_data) -> tuple[str, str, dict | None]:
    """입력을 (형태, 직업명, profile)로 판별한다. 형태는 "A" | "B" | "AB"."""
    if input_data is None or isinstance(input_data, str):
        return "A", str(input_data or ""), None
    if isinstance(input_data, dict):
        prof = input_data.get("profile")
        title = str(input_data.get("title") or input_data.get("job_title") or "")
        if isinstance(prof, dict):
            return ("AB" if title.strip() else "B"), title, prof
        # 래퍼 없이 profile 자체가 온 경우 (명세서 입력 B 예시 형태)
        if any(k in input_data for k in _PROFILE_KEYS):
            return "B", "", input_data
    return "A", "", None          # 알 수 없는 형태 — 빈 질의로 흘려보낸다


def _merge_tech(primary: list[str], extra: list[str]) -> list[str]:
    """profile 기술을 우선하고 직업명에서 뽑힌 기술을 뒤에 덧붙인다(중복 제거)."""
    out = list(primary)
    for t in extra:
        if t not in out:
            out.append(t)
    return out


def _spec_from_combined(conn, title: str, profile: dict):
    """A+B 결합 -> QuerySpec.

    필드 우선순위 (근거를 함께 적는다):
      role_category  A의 직업명 (명시 의도가 이력 추론을 이긴다)
      tech           B 우선 + A에서 추출된 기술 추가 (2×2 분해: 기술 효과 +0.0497)
      exp_years      A에 연차가 명시되면 A, 없으면 B의 재직기간 합산
                     — A의 "신입 백엔드"처럼 명시된 조건은 이력보다 강한 신호다
      regions        A만 가질 수 있다 (명세서 입력 B에는 지역 선호가 없다)
    """
    spec_b, provenance = _spec_from_profile(profile)
    spec_a = parse_query(title, load_region_vocab(conn))

    tech = _merge_tech(spec_b.tech, spec_a.tech)
    role = title.strip()
    exp_years = spec_a.exp_years if spec_a.exp_years is not None else spec_b.exp_years
    role_category = classify(role, "", tech) or spec_b.role_category

    spec = QuerySpec(
        text=query_text.lexical_text(role, tech),
        dense_text=query_text.semantic_text(role, tech, exp_years),
        tech=tech,
        regions=spec_a.regions,
        exp_years=exp_years,
        role_category=role_category,
    )
    return spec, provenance


def spec_from_input(conn, input_data) -> tuple[str, "QuerySpec", dict | None]:
    """명세서 세 입력 형태를 모두 받아 (형태, QuerySpec, provenance)를 돌려준다."""
    kind, title, profile = classify_input(input_data)
    if kind == "AB":
        spec, prov = _spec_from_combined(conn, title, profile)
    elif kind == "B":
        spec, prov = _spec_from_profile(profile)
    else:
        spec, prov = parse_query(title, load_region_vocab(conn)), None
    return kind, spec, prov


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
           use_rerank: bool = True, evaluate: bool | None = None) -> dict:
    """명세서 계약 진입점. 입력 A(str) / 입력 B(dict) 모두 수용.

    계약상 이 함수는 예외를 밖으로 내보내지 않고, 매칭 없음은 {"postings": []}다.

    `evaluate` — CRAG 평가자(grader.py) 통과 여부. None이면 `JOBRAG_EVALUATOR`
    환경변수(기본 켜짐)를 따른다. 평가자는 INCORRECT 판정 공고를 **반환에서 제외**하므로
    반환 건수가 top_k보다 적을 수 있고, 전부 탈락하면 0건이 된다 — 이게 의도한 동작이다
    (무관한 공고를 자신 있게 추천하지 않는 것이 평가자의 존재 이유).
    끄면 채점도 하지 않는다: 결정적 재현이 필요한 평가 하네스는 반드시 False로 부른다.
    """
    try:
        # 명세서 §2 세 형태(A · B · A+B)를 한 곳에서 판별한다 — classify_input 참고
        kind, spec, provenance = spec_from_input(conn, input_data)
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

        # ── CRAG 평가자 ────────────────────────────────────
        # 검색 결과를 그대로 반환하지 않고, 질의 대비 관련성을 문서별로 판정한 뒤
        # INCORRECT를 제외한다. 순위는 바꾸지 않는다(평가자는 필터, 재순위기가 아님).
        from . import grader
        run_eval = grader.enabled() if evaluate is None else evaluate
        correction = (grader.evaluate_and_correct(conn, spec, hits)
                      if run_eval else None)
        if correction is not None:
            hits = correction.kept

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
            if correction is not None:
                v = correction.verdicts.get(h.posting_uid)
                # 신뢰성 검증 흔적 — 왜 이 공고가 통과했는지 사후 감사가 가능해야 한다
                item["evaluation"] = {"confidence": grader.confidence_of(v),
                                      **(v.to_dict() if v else {})}
            postings.append(item)

        out: dict = {"postings": postings}
        if correction is not None:
            out["evaluation_summary"] = correction.summary()
            if correction.dropped:
                out["rejected"] = correction.dropped
            if not postings and correction.all_rejected:
                # 0건이 '검색 실패'인지 '평가자가 전부 반려'인지 구분되어야 한다
                out["no_direct_match_reason"] = correction.no_direct_match_reason()
        return out
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

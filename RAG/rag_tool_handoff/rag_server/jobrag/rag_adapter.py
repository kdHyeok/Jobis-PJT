"""find_alternatives 훅 — 대체 경로 공고 검색.

입출력 계약: rag-alternative-search-io.md (오케스트레이터 -> RAG).
판단 계층 훅이므로 LLM을 쓰지 않는다 — subRole별 hybrid_search(rerank 없이) +
role_category 하드필터 + 결과 조립뿐이다. 계약이 "결과 없으면 빈 리스트
(예외 금지)"를 명시하므로 이 모듈 밖으로는 어떤 예외도 내보내지 않는다.
"""
from __future__ import annotations

from .query_parser import QuerySpec
from .role_taxonomy import ROLE_CATEGORIES
from .search import hybrid_search
from .seniority import to_seniority
from .tracing import new_trace_id, node_span
from .whitelist import extract_tech

_ROLE_SET = set(ROLE_CATEGORIES)


def _fetch_snippets(conn, uids: list[str]) -> dict[str, str]:
    """tech가 비어 requiredSkills를 못 채우는 공고를 위한 text 폴백."""
    if not uids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (posting_uid) posting_uid, text FROM chunks
               WHERE posting_uid = ANY(%s)
               ORDER BY posting_uid, (part = 'full') DESC, chunk_id""",
            (uids,),
        )
        return dict(cur.fetchall())


def _search_one_role(conn, sub_role: dict, top_k: int,
                     use_rerank: bool = True) -> tuple[list, str | None]:
    """서브 직군 1건 검색. 실패해도 예외를 올리지 않고 (hits, error) 로 알린다."""
    query = (sub_role.get("query") or "").strip()
    role_category = sub_role.get("roleCategory") or ""
    if not query or role_category not in _ROLE_SET:
        return [], f"invalid sub_role: {sub_role!r}"
    try:
        spec = QuerySpec(text=query, tech=extract_tech(query), role_category=role_category)
        result = hybrid_search(conn, spec, top_k=top_k, allow_relax=False,
                               use_rerank=use_rerank)
        return result.hits, None
    except Exception as e:  # noqa: BLE001 — 계약상 이 훅은 절대 예외를 전파하지 않음
        return [], f"{type(e).__name__}: {e}"


def _build_item(h, text: str | None, with_reason: bool) -> dict:
    item = {
        "title": h.title,
        "companyName": h.company,
        "jobPostingId": h.posting_uid,
        "roleCategory": h.role_category,
        "seniority": to_seniority(h.exp_min, h.employment_type),
        "url": h.url,
    }
    if h.tech:
        item["requiredSkills"] = h.tech
    else:
        item["text"] = text
    if with_reason:
        # 계약 밖 디버그 필드 — 오케스트레이터용 search()에는 안 붙인다(스키마 오염 방지).
        item["similarity"] = h.dense_score
        parts = []
        if h.dense_rank:
            parts.append(f"의미 유사도 {h.dense_score} (dense #{h.dense_rank})")
        if h.bm25_rank:
            parts.append(f"어휘 매치 {h.bm25_score} (BM25 #{h.bm25_rank})")
        parts.append("역할필터 정확매치" if h.exact else "조건 일부 완화")
        item["reason"] = " · ".join(parts)
    return item


def _run(conn, sub_roles: list[dict], top_k: int, with_reason: bool,
         use_rerank: bool = True) -> list[dict]:
    trace = new_trace_id()
    out: list[dict] = []
    seen: set[str] = set()
    failed_roles: list[str] = []

    with node_span(trace, "rag_adapter_search", "query",
                    f"{len(sub_roles)} sub_roles, top_k={top_k}") as span:
        try:
            need_snippet_hits = []
            per_role_hits = []
            for sub_role in sub_roles[:6]:
                hits, error = _search_one_role(conn, sub_role, top_k, use_rerank)
                if error:
                    failed_roles.append(error)
                    continue
                per_role_hits.append(hits)
                need_snippet_hits += [h for h in hits if not h.tech]

            snippets = _fetch_snippets(conn, [h.posting_uid for h in need_snippet_hits])

            for hits in per_role_hits:
                for h in hits:
                    if h.posting_uid in seen:
                        continue
                    text = None if h.tech else snippets.get(h.posting_uid)
                    if not h.tech and not text:
                        continue  # text도 requiredSkills도 없음 — 계약대로 버림
                    seen.add(h.posting_uid)
                    out.append(_build_item(h, text, with_reason))
        except Exception as e:  # noqa: BLE001 — 최후 방어선, 예외 대신 빈 리스트
            span.metrics = {"error": f"{type(e).__name__}: {e}"}
            return []

        span.output_summary = f"{len(out)}건 반환"
        span.metrics = {"sub_roles": len(sub_roles), "returned": len(out),
                        "failed_roles": failed_roles}
    return out


def search(conn, sub_roles: list[dict], top_k: int,
           use_rerank: bool = True) -> list[dict]:
    """subRoles(1~6개) 각각 top_k건 검색 -> 중복 제거된 평평한 공고 리스트.

    출력은 rag-alternative-search-io.md 계약을 정확히 따른다(디버그 필드 없음).

    use_rerank: 한동안 False로 고정돼 있었다(CI에서 끈 것이 남은 것). CE 재순위는
    recall을 바꾸지 않고 순서만 바꾸므로, 켜고 끄는 효과는 eval/adapter_rerank_ab.py
    에서 순위 지표로 비교한다.
    """
    return _run(conn, sub_roles, top_k, with_reason=False, use_rerank=use_rerank)


def search_with_reasons(conn, sub_roles: list[dict], top_k: int,
                        use_rerank: bool = True) -> list[dict]:
    """search()와 동일하되 각 항목에 similarity/reason을 덧붙인다.

    테스트 웹앱 전용 — 오케스트레이터가 소비하는 계약 스키마가 아니다.
    """
    return _run(conn, sub_roles, top_k, with_reason=True, use_rerank=use_rerank)


class RagAdapter:
    """오케스트레이터가 커넥션 하나로 여러 번 호출할 때 쓰는 얇은 래퍼."""

    def __init__(self, conn):
        self._conn = conn

    def search(self, sub_roles: list[dict], top_k: int) -> list[dict]:
        return search(self._conn, sub_roles, top_k)

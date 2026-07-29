"""청킹 — 실측 분포(211건, bge-m3: p50 552 / p90 1067 / max 2028) 근거 전략.

1. 공고 경계 절대 고립: posting_id 단위로만 청킹
2. 모든 청크에 컨텍스트 프리픽스(회사/직무/핵심조건, 기술 별칭 병기)
3. 통짜 상한 WHOLE_MAX=1024 tok — 88.6%가 분할 없이 1청크
4. 초과 시 SPLIT_TARGET=600 tok 목표로 항목(-,•,숫자,줄) 경계 분할 + 1항목 오버랩
5. 하드컷(HARD_MAX)은 방어 코드로만 — 발생 시 forced_split + needs_review
"""
from __future__ import annotations

import re

from .schema import Posting, Chunk
from .tokenizer import count_tokens
from .whitelist import with_aliases

WHOLE_MAX = 1024    # 통짜 허용 상한 (본문 기준, 프리픽스 별도)
SPLIT_TARGET = 600  # 분할 시 청크 목표 크기
HARD_MAX = 1400     # 단일 항목이 이를 넘으면 강제 절단 (실데이터 발생 0 예상)

_ITEM_RE = re.compile(r"\n[-•·*]\s*|\n\d+[.)]\s*|\n")


def context_prefix(p: Posting) -> str:
    exp = "경력 무관/미상" if p.exp_min is None else (
        "신입 가능" if p.exp_min == 0 else f"경력 {p.exp_min}년 이상")
    tech = ", ".join(with_aliases(t) for t in p.tech[:8]) or "명시 없음"
    return (f"[회사] {p.company}\n"
            f"[직무] {p.title}\n"
            f"[핵심조건] {exp} · {p.region_display} · {p.employment_type} · 기술: {tech}\n")


def _split_items(text: str) -> list[str]:
    return [it.strip() for it in _ITEM_RE.split(text) if it.strip()]


def chunk_posting(p: Posting) -> list[Chunk]:
    prefix = context_prefix(p)
    body = p.detail_text.strip()
    chunks: list[Chunk] = []

    def add(part: str, text_body: str, forced=False, review=False):
        text = prefix + text_body
        chunks.append(Chunk(
            chunk_id=f"{p.uid}-c{len(chunks)}",
            posting_uid=p.uid, part=part,
            text=text, tokens=count_tokens(text),
            forced_split=forced, needs_review=review or p.needs_review,
        ))

    if count_tokens(body) <= WHOLE_MAX:
        add("full", body)
        return chunks

    # 항목 경계 분할, 목표 SPLIT_TARGET, 오버랩 1항목
    items = _split_items(body)
    cur: list[str] = []
    cur_tok = 0
    for it in items:
        it_tok = count_tokens(it)
        if it_tok > HARD_MAX:
            # 방어: 개별 항목이 비정상적으로 김 → 문자 기준 강제 절단
            if cur:
                add("split", "\n".join(cur))
                cur, cur_tok = [], 0
            step = HARD_MAX * 2  # tok≈0.5/char → 문자수 환산
            for i in range(0, len(it), step):
                add("split", it[i:i + step], forced=True, review=True)
            continue
        if cur and cur_tok + it_tok > SPLIT_TARGET:
            add("split", "\n".join(cur))
            cur = [cur[-1]]  # 오버랩 1항목
            cur_tok = count_tokens(cur[0])
        cur.append(it)
        cur_tok += it_tok
    if cur:
        add("split", "\n".join(cur))
    return chunks


def chunk_stats(chunks: list[Chunk]) -> dict:
    """청킹 노드 지표 (실측 재캘리브레이션 목표값):
    full_ratio 0.85~0.90 / p95 ≤ 1024+프리픽스 / forced_split 0 / prefix 누락 0."""
    if not chunks:
        return {"count": 0}
    toks = sorted(c.tokens for c in chunks)
    n = len(toks)
    full = sum(1 for c in chunks if c.part == "full")
    postings = {c.posting_uid for c in chunks}
    return {
        # 공고 기준 통짜율 — 실측 예상치(88.6%)와 비교하는 핵심 지표
        "posting_whole_ratio": round(full / len(postings), 3),
        "count": n,
        "tok_min": toks[0], "tok_max": toks[-1],
        "tok_avg": round(sum(toks) / n, 1),
        "tok_p50": toks[n // 2], "tok_p95": toks[min(n - 1, int(n * 0.95))],
        "full_ratio": round(full / n, 3),
        "forced_split_ratio": round(sum(1 for c in chunks if c.forced_split) / n, 3),
        "needs_review_ratio": round(sum(1 for c in chunks if c.needs_review) / n, 3),
        "prefix_missing": sum(1 for c in chunks if not c.text.startswith("[회사]")),
    }

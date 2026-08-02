"""응답 생성 — SSAFY GMS 게이트웨이 경유 Gemini 2.5 Flash Lite.

네이티브 Gemini REST(OpenAI 호환 아님). 등급 평가는 grader.py — GmsClient를
공유해 재순위 결과를 채점만 하고(교정 동작은 아직 없음), 여기서는 그대로
컨텍스트로 넘겨 1회 생성한다.
"""
from __future__ import annotations

import os

from .search import SearchHit

SYSTEM_PROMPT = """당신은 채용공고 검색 어시스턴트입니다.
아래 [검색결과]만 근거로 사용자 질문에 답하세요.
- 검색결과에 없는 공고를 지어내지 마세요.
- 각 추천에는 회사명과 핵심 조건(경력/지역/기술)을 포함하세요.
- 조건에 정확히 맞는 게 없으면 그렇다고 말하고 가장 가까운 대안을 제시하세요.
- 한국어로, 간결하게 답하세요."""


def fetch_bodies(conn, uids: list[str]) -> dict[str, str]:
    """공고 원문(raw->>'detail_text')을 uid별로 가져온다.

    후보 단계(`search._fetch_postings`)에서는 본문을 가져오지 않는다 — 후보가 30건이라
    낭비다. **최종 반환분에 대해서만** 여기서 붙인다.
    `detail_text`는 별도 컬럼이 아니라 `raw` JSONB 안에만 있다.
    """
    if not uids:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT uid, COALESCE(raw->>'detail_text','') "
                    "FROM postings WHERE uid = ANY(%s)", (uids,))
        return dict(cur.fetchall())


def _format_context(hits: list[SearchHit], bodies: dict[str, str] | None = None) -> str:
    """생성부에 넘길 컨텍스트.

    2026-07-30 수정 — **공고 원문 전체를 넘긴다.**
    이전에는 회사·제목·연차·지역·기술·URL만 넘겼다. 즉 생성부가 **공고 본문을 한 글자도
    보지 못한 상태로** 답변을 썼다. 그래서 (a) 본문에만 있는 조건(우대사항·업무내용·
    복리후생)을 근거로 쓸 수 없었고, (b) RAGAS `faithfulness` 측정은 `chunks.text`
    (본문 포함)를 컨텍스트로 줬으므로 **운영이 실제로 쓰지 않는 컨텍스트를 재고 있었다.**
    이 수정으로 둘이 일치한다.

    본문은 자르지 않는다. top_k=3(계약 기본)에서는 문제가 없으나, top_k를 크게 키우면
    컨텍스트가 선형으로 늘어난다 — 실측: 3건 약 3.6천자 / 10건 약 12.2천자.
    """
    bodies = bodies or {}
    lines = []
    for i, h in enumerate(hits, 1):
        exp = "경력무관" if h.exp_min is None else f"{h.exp_min}년+"
        loc = ", ".join(h.regions[:2]) or "지역 미상"
        tech = ", ".join(h.tech[:8]) or "명시 없음"
        tag = "" if h.exact else " [조건 일부 완화된 결과]"
        body = (bodies.get(h.posting_uid) or "").strip()
        block = (f"{i}. {h.company} — {h.title}{tag}\n"
                 f"   조건: {exp} · {loc} · 기술: {tech}\n"
                 f"   URL: {h.url}")
        if body:
            block += f"\n   [공고 원문]\n{body}"
        lines.append(block)
    return "\n\n".join(lines) if lines else "(검색 결과 없음)"


class GmsClient:
    def __init__(self):
        import requests
        from dotenv import load_dotenv
        load_dotenv()
        self._rq = requests
        self._key = os.environ["GMS_KEY"]
        base = os.environ.get("GMS_BASE_URL",
                              "https://gms.ssafy.io/gmsapi/generativelanguage.googleapis.com")
        model = os.environ.get("GMS_MODEL", "gemini-2.5-flash-lite")
        self._url = f"{base}/v1beta/models/{model}:generateContent?key={self._key}"

    def _call(self, system_prompt: str, user_text: str, max_tokens: int = 800,
              temperature: float = 0.2) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {"temperature": temperature,
                                 "maxOutputTokens": max_tokens},
        }
        r = self._rq.post(self._url, json=body, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"GMS 호출 실패 {r.status_code}: {r.text[:300]}")
        data = r.json()
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)

    def generate(self, query: str, hits: list[SearchHit],
                 bodies: dict[str, str] | None = None) -> str:
        context = _format_context(hits, bodies)
        return self._call(SYSTEM_PROMPT, f"[검색결과]\n{context}\n\n[질문]\n{query}")

    def classify(self, system_prompt: str, user_text: str) -> str:
        """등급 채점 등 분류 용도 — grader.py가 사용. 짧은 출력이면 충분해 토큰을 줄인다."""
        return self._call(system_prompt, user_text, max_tokens=20)

    def judge(self, system_prompt: str, user_text: str, max_tokens: int = 300) -> str:
        """CRAG 평가자용 — 등급 + 근거 한 문장을 JSON으로 받으므로 20토큰으로는 잘린다.

        `temperature=0`: 같은 입력에 같은 등급이 나와야 감사(audit)가 성립한다.
        생성부(0.2)와 다른 값을 쓰는 이유가 이것이며, 섞으면 안 된다.
        """
        return self._call(system_prompt, user_text,
                          max_tokens=max_tokens, temperature=0.0)


_client: GmsClient | None = None


def generate_answer(query: str, hits: list[SearchHit], conn=None) -> str:
    """답변 생성. conn을 주면 **공고 원문 전체**를 컨텍스트에 넣는다.

    conn 없이 부르면 원문 없이(메타데이터만) 생성한다 — 이전 동작이며 하위 호환용이다.
    본문 없이 생성하면 본문에만 있는 조건을 근거로 쓸 수 없으므로 **conn을 넘기는 쪽이
    정상 경로**다. 호출측에서 이미 원문을 갖고 있으면 bodies로 직접 넘겨도 된다.
    """
    global _client
    if _client is None:
        _client = GmsClient()
    bodies = fetch_bodies(conn, [h.posting_uid for h in hits]) if conn is not None else None
    return _client.generate(query, hits, bodies)

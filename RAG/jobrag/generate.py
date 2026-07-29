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


def _format_context(hits: list[SearchHit]) -> str:
    lines = []
    for i, h in enumerate(hits, 1):
        exp = "경력무관" if h.exp_min is None else f"{h.exp_min}년+"
        loc = ", ".join(h.regions[:2]) or "지역 미상"
        tech = ", ".join(h.tech[:8]) or "명시 없음"
        tag = "" if h.exact else " [조건 일부 완화된 결과]"
        lines.append(
            f"{i}. {h.company} — {h.title}{tag}\n"
            f"   조건: {exp} · {loc} · 기술: {tech}\n"
            f"   URL: {h.url}"
        )
    return "\n".join(lines) if lines else "(검색 결과 없음)"


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

    def _call(self, system_prompt: str, user_text: str, max_tokens: int = 800) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
        }
        r = self._rq.post(self._url, json=body, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"GMS 호출 실패 {r.status_code}: {r.text[:300]}")
        data = r.json()
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)

    def generate(self, query: str, hits: list[SearchHit]) -> str:
        context = _format_context(hits)
        return self._call(SYSTEM_PROMPT, f"[검색결과]\n{context}\n\n[질문]\n{query}")

    def classify(self, system_prompt: str, user_text: str) -> str:
        """등급 채점 등 분류 용도 — grader.py가 사용. 짧은 출력이면 충분해 토큰을 줄인다."""
        return self._call(system_prompt, user_text, max_tokens=20)


_client: GmsClient | None = None


def generate_answer(query: str, hits: list[SearchHit]) -> str:
    global _client
    if _client is None:
        _client = GmsClient()
    return _client.generate(query, hits)

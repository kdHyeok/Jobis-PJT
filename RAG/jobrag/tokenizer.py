"""토큰 카운터.

청킹 임계(1024/600)는 bge-m3 실측 분포에서 도출했으므로
가능하면 실제 bge-m3 토크나이저를 쓴다. 미설치 환경은 근사치 폴백
(실측: 평균 622tok/1255자 ≈ 0.5 tok/char).
"""
from __future__ import annotations

_tokenizer = None
_backend = "approx"


def _try_load():
    global _tokenizer, _backend
    try:
        from transformers import AutoTokenizer
        _tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")
        _backend = "bge-m3"
    except Exception:
        _tokenizer = None
        _backend = "approx"


_try_load()


def backend() -> str:
    return _backend


def count_tokens(text: str) -> int:
    if _tokenizer is not None:
        return len(_tokenizer.encode(text))
    return max(1, round(len(text) * 0.5))

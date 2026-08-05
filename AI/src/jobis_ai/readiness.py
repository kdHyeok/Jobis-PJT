"""Explicit production dependency probe used by the CD rollback gate."""
from __future__ import annotations

import argparse
import json
import urllib.request

from jobis_ai.config import get_settings


def _rag_probe(base_url: str) -> None:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/health", timeout=15) as response:
        health = json.load(response)
    if health.get("status") != "ok" or health.get("warm") is not True:
        raise RuntimeError("RAG health is not warm")

    body = json.dumps(
        {"input": "백엔드 개발자", "top_k": 1, "evaluate": False, "use_rerank": False},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/search",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    if not isinstance(result.get("postings"), list):
        raise RuntimeError("RAG search response is missing postings[]")


def _llm_probe() -> None:
    from jobis_ai.llm import get_llm

    response = get_llm("light").invoke(
        [
            ("system", "This is a deployment health probe. Reply with one short word."),
            ("human", "Reply OK."),
        ]
    )
    if not str(getattr(response, "content", "")).strip():
        raise RuntimeError("LLM provider returned an empty response")


def probe(*, live: bool) -> None:
    settings = get_settings()
    if settings.rag_provider != "http":
        raise RuntimeError("Production readiness requires RAG_PROVIDER=http")
    if not live:
        return
    _rag_probe(settings.rag_search_url)
    _llm_probe()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="perform real RAG and LLM requests")
    args = parser.parse_args()
    probe(live=args.live)
    print("runtime-probe: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

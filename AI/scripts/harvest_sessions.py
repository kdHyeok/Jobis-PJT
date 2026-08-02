"""세션 저장소에서 **예상 못한 상황의 신호**를 센다 — 읽기 전용, 실 LLM 없음.

평가 하네스(`eval/`)는 전부 **사전 정의 케이스**를 잰다. 그건 우리가 예상한 것만 재는
것이고, 출시 뒤에 오는 것은 정의상 예상 밖이다. 이 스크립트가 그 반대편이다:
실제 대화에서 **무엇이 어긋났는지를 사후에** 센다.

    uv run --extra prototype python scripts/harvest_sessions.py [sessions.sqlite3]

읽는 곳이 `sessions.sqlite3` 인 이유: 로그는 stdout 전용이라 휘발하고 trace 는 턴 끝에
사라진다. **발화와 답변이 함께 영속하는 곳은 세션 `history` 하나뿐이다.**

그래서 신호는 답변 **문구**로 잡을 수밖에 없다(warnings 는 응답과 함께 사라진다). 문구
지문의 위험은 문구가 바뀌면 조용히 0을 보고하는 것이라, `_assert_fingerprints_alive()`
가 매 실행마다 소스에 그 문구가 남아 있는지 확인하고 없으면 **죽는다.** 0 을 "괜찮다"로
읽는 사고를 막는 것이 이 스크립트의 존재 이유이므로, 침묵보다 실패가 낫다.

첫 실측(2026-08-02, 133세션·275턴): `career_chat` 고정 안내문 7건(2.5%) — 전부 정상
요청("적합도 분석해 주세요"·"응, 진단해줘"·위로 요청)이 기능 목록을 받았다. 그 발견이
`career_chat_fallback` 경고(§2-6)를 넣게 했다.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from jobis_ai.agents.career_chat import _FALLBACK                      # noqa: E402
from jobis_ai.orchestrator.chat import (                               # noqa: E402
    _SCHEMELESS_URL_RE,
    _URL_RE,
    JOB_SITE_HOSTS,
)

# 답변 문구 → 무엇이 일어났나. **소스에 실재하는 조각만** 쓴다(아래 자기검사가 강제).
# f-string 안의 고정 부분이라 상수로 임포트할 수 없는 것들이다.
SIGNALS: dict[str, tuple[str, str]] = {
    # 이름              (지문,                  설명)
    "oos_refusal":     ("취업 관련 외",         "범위 밖 질의로 보고 거절"),
    "fetch_failed":    ("가져오지 못",          "공고 수집 실패"),
    "dropped_step":    ("진행하지 못했어요",     "관찰 규칙이 단계를 제외(전제 붕괴·수집 실패)"),
    "lacking_asset":   ("아직 없어서",          "검증기가 전제 생산자를 앞에 끼움"),
    "consent_gate":    ("바로 진행할까요",       "동의 게이트 — 무거운 작업 전 질의"),
    "weak_grade":      ("잠시 미뤘어요",         "약한 판정으로 생성 단계 교체"),
    "not_implemented": ("아직 준비 중",          "미구현 에이전트 dispatch"),
    "recover_posting": ("다시 보내주면",         "라이브러리에 없는 공고 — 복구 경로 안내"),
}
# 고정 상수라 임포트로 추적한다 — 문구가 바뀌어도 지문이 따라간다.
FALLBACK_FP = _FALLBACK[:20]


def _assert_fingerprints_alive() -> None:
    """지문이 소스에서 사라졌으면 죽는다 — 조용한 0 보고가 이 스크립트 최대의 실패다."""

    src = "\n".join(p.read_text(encoding="utf-8")
                    for p in (REPO / "src" / "jobis_ai").rglob("*.py"))
    dead = [f"{name}({needle!r})" for name, (needle, _) in SIGNALS.items()
            if needle not in src]
    if dead:
        raise SystemExit(
            "지문이 소스에 없다 — 문구가 바뀌었다. 고치기 전에는 집계를 믿지 말 것:\n  "
            + "\n  ".join(dead))


def _pairs(history: list[dict]) -> list[tuple[str, str]]:
    """user → assistant 쌍. `chat._finish` 가 이 순서로 기록한다."""

    return [(history[i].get("content") or "", history[i + 1].get("content") or "")
            for i in range(len(history) - 1)
            if history[i].get("role") == "user"
            and history[i + 1].get("role") == "assistant"]


def _urls(message: str) -> list[str]:
    """프로덕션 인테이크와 **같은 정규식**으로 발화의 주소를 찾는다(기준이 갈리면 무의미)."""

    found = list(_URL_RE.findall(message))
    if not found and _SCHEMELESS_URL_RE.match(message.strip()):
        found = [message.strip()]
    return found


def main(db: str) -> None:
    _assert_fingerprints_alive()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    turns = 0

    def note(key: str, text: str) -> None:
        counts[key] += 1
        examples.setdefault(key, [])
        if len(examples[key]) < 5:
            examples[key].append(" ".join(text.split())[:80])

    for (raw,) in conn.execute("SELECT assets FROM sessions"):
        try:
            data = json.loads(raw)
        except ValueError:
            continue                      # 깨진 세션은 세지 않는다(store 도 빈 세션으로 본다)
        # 플래너가 "로스터로 못 한다"고 신고한 요청(D117). 답변 문구가 아니라 **구조화된
        # 기록**이라 유일하게 지문이 필요 없는 신호다 — 출시 뒤 로스터 후보의 1순위 원료.
        for request in data.get("unsupported_requests") or []:
            note("unsupported_request", str(request))

        had_posting = False
        for message, reply in _pairs(data.get("history") or []):
            turns += 1
            for name, (needle, _) in SIGNALS.items():
                if needle in reply:
                    note(name, message)
            if reply.strip().startswith(FALLBACK_FP):
                note("career_chat_fallback", message)
            # 채용사이트가 아닌 주소 — 이미 공고를 받은 뒤라면 그 링크가 활성 공고와
            # 분석 결과를 **말없이 교체**한다(`chat._stage({"analysis": None, …})`).
            for url in _urls(message):
                if not any(host in url for host in JOB_SITE_HOSTS):
                    note("posting_url_replaced" if had_posting else "nonjob_url", url)
                had_posting = True

    print(f"{db}: 발화 턴 {turns}건\n")
    descriptions = {name: desc for name, (_, desc) in SIGNALS.items()}
    descriptions["career_chat_fallback"] = "대화 에이전트가 고정 안내문으로 강등"
    descriptions["unsupported_request"] = "**로스터 밖 요청** — 새 에이전트 후보의 원료"
    descriptions["nonjob_url"] = "채용사이트 아닌 주소를 공고로 등록"
    descriptions["posting_url_replaced"] = "그 등록이 **기존 공고·분석을 교체**"
    for name, n in counts.most_common():
        print(f"{name:22s} {n:4d} ({n / turns:5.1%})  {descriptions.get(name, '')}")
        for ex in examples[name]:
            print(f"                            · {ex}")
    if not counts:
        print("신호 없음.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(REPO / "sessions.sqlite3"))

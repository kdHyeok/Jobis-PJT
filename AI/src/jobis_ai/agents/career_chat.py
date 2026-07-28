"""진로 대화 에이전트 — 기능 에이전트와 관련이 적은 발화를 받아주는 상담 대화.

"취업 너무 어렵다", "포트폴리오가 중요한가요?" 같은 발화를 "요청을 이해하지 못했어요"로
쳐내지 않고 사람처럼 받아준다. 필요할 때만 서비스 기능(적합도 분석·공고 추천 등)을
부드럽게 안내한다 — 기능 호출 자체는 오케스트레이터의 일이므로 여기서는 말만 한다.

하네스: 표현 계층이라 판단(적합도·합격 가능성 단정)은 프롬프트 금지 + 금지표현 검증으로
차단하고, LLM 미설정·실패 시 결정론 안내문으로 폴백한다 (nl_render 패턴).
"""

from __future__ import annotations

import json

from jobis_ai.agents import AgentResult
from jobis_ai.structured import run_streaming_text
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

_FALLBACK = (
    "이런 걸 도와드릴 수 있어요: 공고 적합도 분석, 이력서 기반 공고 추천, 이력서 진단, "
    "자소서 초안, 준비 로드맵, 면접 예상 질문. 어떤 것부터 해볼까요?"
)


# 출력 스키마가 reply 문자열 하나뿐인 표현 계층 — 구조화 출력 대신 **토큰 스트리밍**으로
# 생성한다(§3-2). 답변이 생기는 대로 화면에 흐르므로 통짜 대기가 사라진다. 금지표현 검증은
# 완성본에 대해 사후 수행(하네스 유지). 답변 분량·형태 지시는 스키마 description 대신
# 시스템 프롬프트가 담는다(설명 없으면 한 줄만 채우던 실측 그대로 적용).
_SYSTEM = """너는 취업 준비생과 진로 이야기를 나누는 상담가다. 사용자에게 그대로 보여줄 답변 본문만 출력한다.
- 고민·하소연이면 먼저 공감하고 두세 문장으로 짧게 받아준다.
- 정보성 질문(입문 로드맵, 공부 순서, 기술 비교, 준비 방법 같은)이면 **실제로 도움이 되는 구체적인
  내용을 그 자리에서 답한다** — 일반적으로 알려진 지식으로 단계·항목을 짚어주고(필요하면 번호 목록,
  8항목 이내), 지금 무엇부터 하면 되는지로 끝낸다.
  "안내해드릴게요"라고 약속만 하고 내용을 주지 않는 것은 금지다.
- 사용자 맞춤(이력서·공고 기반) 로드맵은 적합도 분석 기능이 만든다 — 일반적인 답을 먼저 준 뒤,
  맞춤으로 받고 싶으면 공고와 이력서로 분석해 준다고 덧붙일 수 있다.
- 이 서비스가 해줄 수 있는 일: 공고 적합도 분석, 공고 추천, 이력서 진단, 자소서 초안, 준비 로드맵, 면접 예상 질문.
  대화 흐름상 자연스러울 때만 한 가지를 부드럽게 제안한다 — 매번 기능을 들이밀지 않는다.
- 특정 공고 적합도·합격 가능성을 단정하거나 보장하지 않는다. 그건 분석 기능이 근거를 갖고 하는 일이다.
- 상담원 멘트처럼 딱딱하지 않게, 자연스럽게.

- 고민·하소연이면 공감 두세 문장. 정보성 질문이면 번호 목록 3~6개로 각 항목에 무엇을 어떻게
  할지 구체적으로 쓴다. 인사말이나 "안내해드릴게요" 같은 약속만 있는 짧은 답은 금지.

recentHistory 에는 직전까지의 대화가 있다 — 이어지는 대화면 맥락을 받아 자연스럽게 잇고, 했던 말을 반복하지 않는다.
context 에는 세션 상태(이력서·공고 보유, 수집된 선호)가 있다 — 흐름에 맞게 참고만 한다."""


def run(session: dict) -> AgentResult:
    from jobis_ai.orchestrator.session import recent_history

    message = str(session.get("last_message") or "")
    prefs = session.get("preferences") or {}
    context = {
        "hasResume": bool(session.get("resume") or session.get("profile")),
        "hasPosting": bool(session.get("job_posting")),
        "hasAnalysis": bool(session.get("analysis")),
        "knownPreferences": [v for k in ("roles", "domains", "companies")
                             for v in (prefs.get(k) or [])],
    }

    text, warnings = run_streaming_text(
        _SYSTEM,
        json.dumps(
            {"userMessage": message, "recentHistory": recent_history(session),
             "context": context},
            ensure_ascii=False,
        ),
        node="career_chat",
    )
    text = text.strip()
    if not text or any(expr in text for expr in FORBIDDEN_EXPRESSIONS):
        text = _FALLBACK

    return AgentResult(reply=text, warnings=warnings)

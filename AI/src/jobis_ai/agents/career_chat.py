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
from jobis_ai.verify_rules import drop_forbidden_sentences

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
- **취업·커리어와 무관한 요청**(날씨, 일반 상식, 코딩 문제 풀이, 잡담을 가장한 정보 요청 등)에는
  내용을 답하지 않는다 — "취업 관련 외 질의는 받지 않아요"라고 정중히 밝히고 서비스 범위
  (공고 분석·추천·이력서 진단 등)를 한 줄로 안내한다. 취업 준비 고민·하소연은 무관 질의가 아니다.
- 상담원 멘트처럼 딱딱하지 않게, 자연스럽게.

- 고민·하소연이면 공감 두세 문장. 정보성 질문이면 번호 목록 3~6개로 각 항목에 무엇을 어떻게
  할지 구체적으로 쓴다. 인사말이나 "안내해드릴게요" 같은 약속만 있는 짧은 답은 금지.

recentHistory 에는 직전까지의 대화가 있다 — 이어지는 대화면 맥락을 받아 자연스럽게 잇고, 했던 말을 반복하지 않는다.
context 에는 세션 상태(이력서·공고 보유, 수집된 선호)가 있다 — 흐름에 맞게 참고만 한다.
- context 의 postingFacts/analysisFacts 는 **도구가 이미 만들어 둔 사실**이다. 공고 요건·분석 결과를
  묻는 질문에는 거기 있는 내용만으로 바로 답한다 — "다시 분석하겠다"고 하지 않고, 거기 없는
  항목·수치를 만들지 않는다. 물은 것만 답하고 전체 목록을 다시 낭독하지 않는다.
- postingLibrary 는 이 대화에서 정리했던 **모든 공고**의 사실이다. 이전 공고(회사명으로 지칭)에
  대한 질문도 여기서 찾아 답한다 — "그 공고는 없다"고 하기 전에 반드시 postingLibrary 를 본다.
- postingLibrary 에도 없는 공고를 물으면, 없다고만 끝내지 말고 **그 공고 링크(또는 본문)를 다시
  보내주면 바로 정리해 답하겠다**고 복구 경로를 안내한다."""


# 대화 입력 상한(M6/D75) — 자산으로 승격되지 못한 긴 원문(문서 붙여넣기)이 **통째로**
# 대화 근거가 되는 것을 구조로 막는다(§2-5 근거는 도구만: 프롬프트 금지는 실측에서 안
# 지켜졌다 — 2026-07-31 이력서 원문 위 즉흥 코칭 유출). 일반 상담 발화는 이 밑이다.
_MAX_INPUT_CHARS = 1000


def _clip_message(message: str) -> str:
    if len(message) <= _MAX_INPUT_CHARS:
        return message
    return (message[:_MAX_INPUT_CHARS]
            + f"\n…(총 {len(message)}자 중 앞부분만 제공됨 — 긴 원문은 분석 대상이 아니라"
              " 자료 등록 안내 대상이다)")


def run(session: dict) -> AgentResult:
    from jobis_ai.orchestrator.session import recent_history

    message = _clip_message(str(session.get("last_message") or ""))
    prefs = session.get("preferences") or {}
    context = {
        "hasResume": bool(session.get("resume") or session.get("profile")),
        "hasPosting": bool(session.get("job_posting")),
        "hasAnalysis": bool(session.get("analysis")),
        "knownPreferences": [v for k in ("roles", "domains", "companies")
                             for v in (prefs.get(k) or [])],
        # 발화에서 누적된 지속 사실(D82) — "지난번에 말한 조건" 류 질문의 근거.
        "userFacts": [str(f) for f in (session.get("user_facts") or [])],
    }
    # 이미 도구가 만들어 둔 정형 사실 — 조회 질문("공고 필수 항목이 뭐였지?")은 재분석 없이
    # 이 데이터로 답한다(D79, §1: 판단은 데이터가 하고 LLM 은 말만 한다).
    def _texts(items: list) -> list[str]:
        return [str((i or {}).get("text") if isinstance(i, dict) else i)
                for i in (items or [])][:12]

    def _posting_facts(summary: dict) -> dict:
        return {
            "companyName": summary.get("companyName"),
            "jobTitle": summary.get("jobTitle"),
            "requiredRequirements": _texts(summary.get("requiredRequirements")),
            "preferredRequirements": _texts(summary.get("preferredRequirements")),
            "techStack": summary.get("techStack"),
            # 이 공고로 돌렸던 판정 요약(이력서별) — 활성 판정 슬롯이 무효화된 뒤에도
            # "아까 A 공고는 뭐였지?" 에 저장된 사실로 답한다.
            "pastAnalyses": summary.get("_analyses") or [],
        }

    posting_summary = session.get("posting_summary") or {}
    if posting_summary:
        context["postingFacts"] = _posting_facts(posting_summary)
    # 이 대화에서 정리했던 **모든** 공고(D86) — 활성 공고가 바뀌어도 이전 공고 질문에 답한다.
    library = session.get("posting_library") or []
    if library:
        context["postingLibrary"] = [_posting_facts(p) for p in library]
    analysis = session.get("analysis") or {}
    if analysis:
        context["analysisFacts"] = {
            "fitGrade": analysis.get("fitGrade"),
            "strengths": [str((s or {}).get("text") or "") for s in (analysis.get("strengths") or [])][:5],
            "gaps": [str((g or {}).get("reason") or (g or {}).get("text") or "")
                     for g in (analysis.get("gaps") or [])][:5],
        }
    if context.get("postingFacts") or context.get("analysisFacts") or context.get("userFacts"):
        from jobis_ai import trace

        # 진행 로그에 "이전 대화 검토"로 구분 표시된다(D83) — 새 분석이 아니라 저장 정보 참조.
        trace.emit("recall", "저장된 사실(공고 정리·분석·사용자 메모)을 대화 근거로 제공", {
            "keys": [k for k in ("postingFacts", "analysisFacts", "userFacts") if context.get(k)],
        })

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
    # 폴백은 이유를 삼키지 않는다(§2-6). LLM 미설정·실패는 run_streaming_text 가 이미
    # warnings 에 담지만, **금지표현 강등과 빈 응답은 여기가 유일한 관측 지점인데 무음이었다** —
    # 실측(sessions.sqlite3 275턴): 이 고정 문구가 7건(2.5%) 나갔고 전부 정상 요청이었는데
    # (적합도 요청·"응, 진단해줘"·위로 요청) 원인 셋 중 어느 것이었는지 사후에 알 수 없었다.
    # 처방이 원인마다 다르므로(재작성 루프 vs 인프라) 세는 것이 먼저다.
    #
    # 금지표현은 **문장 단위로만** 버린다(D123) — '반드시' 하나로 답변 전체를 메뉴 문구로
    # 바꾸던 것이 위 7건의 주범이었다. 걸린 문장은 여전히 나가지 않는다(판정 원칙 유지).
    text, hits = drop_forbidden_sentences(text)
    if hits:
        warnings.append({"code": "career_chat_softened", "message": (
            f"career_chat: 금지표현 {hits} 이 든 문장을 답변에서 제거.")})
    if not text:
        warnings.append({"code": "career_chat_fallback", "message": (
            f"career_chat: 금지표현 {hits} 제거 후 남은 문장이 없어 고정 안내문으로 강등." if hits
            else "career_chat: 답변이 비어 고정 안내문으로 강등.")})
        text = _FALLBACK

    return AgentResult(reply=text, warnings=warnings)

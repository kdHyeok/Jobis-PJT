"""공고 분석 에이전트 — 이력서 없이 공고만으로 핵심 요구사항을 정리한다.

부분 자산의 우아한 대응(graceful degradation): 적합도 분석에는 이력서가 필요하지만,
공고만 있어도 "이 공고가 무엇을 요구하는가"는 알려줄 수 있다. 되묻기만 하고 끝나는 대신
**정리 결과를 먼저 주고** 이력서를 자연스럽게 요청한다 — 오케스트레이터가 존재하는 이유.

판정하지 않는다 — 공고를 읽어 정리할 뿐, 적합/불충분은 말하지 않는다(그건 판정 엔진의 일).

**도구다 — 말하지 않는다**(0729 표현 분리). 요약 줄·마무리 문장은 `tool_render` 로 옮겼다.
"""

from __future__ import annotations

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import ensure_posting_text
from jobis_ai.graph.nodes import parse_job_posting

def run(session: dict) -> AgentResult:
    """세션의 공고 원문 → 파싱 결과(데이터). **도구다 — 말하지 않는다.**

    요약 줄·마무리 문장은 전부 표현이므로 `tool_render.render_posting_analysis` 로 옮겼다.
    여기 남은 것은 "무엇을 읽어냈나"뿐이고, 문구를 고칠 때 이 파일을 건드릴 일은 없다.
    """

    # URL 자산이면 먼저 수집해 원문으로 승격한다(D62) — 이후 소비자는 재수집하지 않는다.
    posting_input, fetch_warnings = ensure_posting_text(session)
    state = {
        "jobPostingInput": posting_input,
        "sources": [], "toolLog": [], "warnings": [], "retryCount": {},
    }
    update = parse_job_posting(state)
    posting = update.get("normalizedJobPosting") or {}
    warnings = fetch_warnings + update.get("warnings", [])

    readable = any(
        posting.get(k)
        for k in ("requiredRequirements", "preferredRequirements", "techStack", "jobTitle")
    )
    return AgentResult(
        reply="",                       # 도구는 말하지 않는다 — 문장은 render 가 만든다
        data={"postingAnalysis": posting, "readable": readable},
        warnings=warnings,
        # 카드에 실리는 질문은 **결정론**이다. 맥락을 살린 마무리 문장은 표현 계층이 쓰고
        # 대화 답변으로 나간다 — 데이터 계약(질문 카드)과 표현을 같은 문자열로 묶지 않는다.
        followUpQuestions=([] if not readable else [{
            "field": "resume",
            "question": "이 요건들과 대조해 적합도를 분석해 드릴게요. 이력서(또는 경력·기술 소개)를 주시겠어요?",
        }]),
    )

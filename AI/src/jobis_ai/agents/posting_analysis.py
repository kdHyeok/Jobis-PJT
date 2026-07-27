"""공고 분석 에이전트 — 이력서 없이 공고만으로 핵심 요구사항을 정리한다.

부분 자산의 우아한 대응(graceful degradation): 적합도 분석에는 이력서가 필요하지만,
공고만 있어도 "이 공고가 무엇을 요구하는가"는 알려줄 수 있다. 되묻기만 하고 끝나는 대신
**정리 결과를 먼저 주고** 이력서를 자연스럽게 요청한다 — 오케스트레이터가 존재하는 이유.

판정하지 않는다 — 공고를 읽어 정리할 뿐, 적합/불충분은 말하지 않는다(그건 판정 엔진의 일).
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from jobis_ai.agents import AgentResult
from jobis_ai.graph.nodes import parse_job_posting
from jobis_ai.role_taxonomy import SENIORITY_KO
from jobis_ai.structured import run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

# LLM 이 못 쓸 때만 쓰는 결정론 폴백 문장. 평소 마무리 문장은 맥락을 보고 LLM 이 쓴다 —
# 같은 문장이 매번 나오면 사용자가 방금 한 말과 어긋난다.
_CLOSING_FALLBACK = (
    "여기까지 정리해 봤어요 — 충분한가요? 관련 이력서가 있으시면 주실래요? "
    "주시면 이 요건들과 하나씩 대조해 적합도까지 분석해 드릴 수 있어요."
)


class _ClosingWrite(BaseModel):
    """공고 정리 결과를 건네고 턴을 되돌려주는 마무리 문장."""

    reply: str = Field(default="", description=(
        "공고 정리를 마친 뒤 사용자에게 보낼 한두 문장. **사용자가 방금 한 말에 이어지게** 쓴다. "
        "정리 결과가 충분한지 확인하고, 더 해볼 수 있는 일(이력서를 주면 요건과 하나씩 대조해 "
        "적합도까지 분석)을 제안하는 질문으로 끝낸다. 이력서를 이미 받은 상태면 이력서를 다시 "
        "요구하지 않고 다음으로 무엇을 해볼지 묻는다. 요건을 다시 나열하지 않는다."))


_CLOSING_SYSTEM = """너는 취업 서비스의 대화 상담원이다. 방금 공고 하나를 읽어 요건을 정리해 사용자에게 보여줬다.
그 아래에 붙일 마무리 문장을 쓴다.

입력:
- userMessage: 사용자의 직전 발화. 여기에 이어지게 쓴다(무엇을 물었는지 놓치지 않는다).
- recentHistory: 직전까지의 대화. 이미 한 말을 반복하지 않는다.
- posting: 방금 정리한 공고의 요점(회사·직무·요건 수). 숫자를 다시 나열하지는 않는다.
- hasResume: 세션에 이력서가 이미 있는지.

규칙:
- 응답은 **질문으로 끝난다** — 사용자가 다음에 무엇을 할지 고를 수 있게 한다.
- 적합도·합격 가능성·연차 충족 여부를 단정하지 않는다. 그건 분석 기능이 근거를 갖고 하는 일이다.
- 짧고 자연스럽게, 두 문장 이내."""


def _closing(facts: dict) -> tuple[str, list[dict]]:
    """마무리 문장 — LLM 표현 + 검증, 실패 시 결정론 폴백 (nl_render 와 같은 패턴).

    검증 2종: 금지표현, 그리고 **질문으로 끝나는지**(턴을 되돌려주지 않는 문장은 버린다).
    """

    read, warnings = run_structured(
        _ClosingWrite, _CLOSING_SYSTEM, json.dumps(facts, ensure_ascii=False),
        node="posting_analysis_closing",
    )
    text = (read.reply or "").strip() if read is not None else ""
    if not text or "?" not in text or any(expr in text for expr in FORBIDDEN_EXPRESSIONS):
        return _CLOSING_FALLBACK, warnings
    return text, warnings


# 공고 원문의 연차 표기 — 사다리 키(junior 등) 대신 사용자에게 보여줄 근거.
_YEARS_MENTION = re.compile(r"(신입|경력\s*무관|(?:경력\s*)?\d+\s*년(?:\s*이상|\s*이하)?)")


def _seniority_line(posting: dict) -> str:
    """사다리 키를 한글 라벨로, 가능하면 공고 원문 표기를 근거로 붙인다."""

    key = posting.get("seniority") or ""
    if not key:
        return ""
    label = SENIORITY_KO.get(key, key)

    texts = (
        [r.get("text", "") for r in posting.get("requiredRequirements", [])]
        + [r.get("text", "") for r in posting.get("preferredRequirements", [])]
        + [posting.get("jobTitle", "")]
        + [str(c) for c in posting.get("rawChunks", [])]
    )
    evidence = ""
    for text in texts:
        m = _YEARS_MENTION.search(str(text))
        if m:
            evidence = m.group(1)
            break

    if evidence:
        return f"요구 연차는 {label} 수준이에요(공고 표기: {evidence})."
    return f"요구 연차는 {label} 수준이에요."


def _fmt_reqs(reqs: list[dict], limit: int = 6) -> str:
    texts = [str(r.get("text", "")).strip() for r in reqs if r.get("text")]
    shown = " / ".join(texts[:limit])
    more = f" 외 {len(texts) - limit}건" if len(texts) > limit else ""
    return shown + more


# 대화 한 줄에 나열할 요건 수. 나머지는 "외 N건"으로 접고, 전체 항목은 data 로 넘어간다
# (웹 UI 는 그걸 오른쪽 패널에 표로 그린다). 한 문단에 다 붓으면 읽히지 않는다.
_INLINE_REQS = 3


def _summary_reply(posting: dict, closing: str) -> str:
    """파싱 결과를 **줄로 나눠** 요약 — 순수 조립, LLM 없음.

    한 덩어리 문단이 아니라 항목별 줄로 낸다. 전체 목록은 AgentResult.data 에 그대로 실려
    가므로, 화면이 있는 쪽(웹 패널)은 거기서 표로 그리고 대화에는 요점만 남는다.
    """

    title = posting.get("jobTitle") or ""
    company = posting.get("companyName") or ""
    head = " · ".join(p for p in (company, title) if p)

    lines = [f"{head} 공고를 정리했어요." if head else "공고를 정리했어요."]

    seniority_line = _seniority_line(posting)
    if seniority_line:
        lines.append(f"· {seniority_line}")
    if posting.get("requiredRequirements"):
        lines.append(f"· 필수 요건 {len(posting['requiredRequirements'])}건 — "
                     f"{_fmt_reqs(posting['requiredRequirements'], _INLINE_REQS)}")
    if posting.get("preferredRequirements"):
        lines.append(f"· 우대 사항 {len(posting['preferredRequirements'])}건 — "
                     f"{_fmt_reqs(posting['preferredRequirements'], _INLINE_REQS)}")
    if posting.get("techStack"):
        lines.append(f"· 요구 기술 {len(posting['techStack'])}개 — "
                     f"{', '.join(posting['techStack'][:6])}"
                     + (" 외" if len(posting["techStack"]) > 6 else ""))
    if posting.get("domainKeywords"):
        lines.append(f"· 도메인 — {', '.join(posting['domainKeywords'][:4])}")

    lines.append("")
    lines.append(closing)
    return "\n".join(lines)


def run(session: dict) -> AgentResult:
    """세션의 공고 원문 → 파싱 → 요구사항 요약 + 이력서 자연 요청."""

    state = {
        "jobPostingInput": session.get("job_posting"),
        "sources": [], "toolLog": [], "warnings": [], "retryCount": {},
    }
    update = parse_job_posting(state)
    posting = update.get("normalizedJobPosting") or {}
    warnings = update.get("warnings", [])

    has_content = any(
        posting.get(k)
        for k in ("requiredRequirements", "preferredRequirements", "techStack", "jobTitle")
    )
    if not has_content:
        return AgentResult(
            reply="공고를 읽어내지 못했어요. 공고 텍스트나 URL을 다시 확인해 주시겠어요?",
            warnings=warnings,
        )

    from jobis_ai.orchestrator.session import recent_history

    closing, closing_warnings = _closing({
        "userMessage": str(session.get("last_message") or ""),
        "recentHistory": recent_history(session, max_items=4),
        "posting": {
            "company": posting.get("companyName") or "",
            "role": posting.get("jobTitle") or "",
            "requiredCount": len(posting.get("requiredRequirements") or []),
            "preferredCount": len(posting.get("preferredRequirements") or []),
            "techStack": list(posting.get("techStack") or [])[:6],
        },
        "hasResume": bool(session.get("resume") or session.get("profile")),
    })

    return AgentResult(
        reply=_summary_reply(posting, closing),
        data={"postingAnalysis": posting},
        warnings=warnings + closing_warnings,
        followUpQuestions=[{
            "field": "resume",
            # 이 턴에 실제로 사용자에게 한 말을 그대로 — UI 가 요청 카드에 다시 쓴다.
            "question": closing,
        }],
    )

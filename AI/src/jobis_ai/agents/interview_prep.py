"""interview_prep — **첫 자기 루프 에이전트.** 면접관처럼 묻고, 답을 듣고, 파고든다.

전에는 판정 결과에서 질문 문장을 템플릿으로 찍어 한 번에 내보내는 결정론 함수였다.
면접 준비의 본질은 그게 아니다 — 질문 → 사용자 답변 → 평가 → **꼬리 질문**이 여러 턴
이어지고, 무엇을 더 파고들지는 방금 들은 답변에 달려 있다. 한 번 호출로 끝나는 순수
함수로는 표현할 수 없는 일이다.

그래서 이 에이전트는 자기 루프(agent_loop)를 돈다. 역할 분담:

  · **도구(이 파일의 파이썬 함수들)** — 정확해야 하는 것. 어떤 소재가 남았는지, 이력서에
    실제로 어떤 근거가 있는지, 답변이 그 근거를 실제로 말했는지. 전부 LLM 없이 계산한다.
  · **에이전트(LLM)** — 자유도가 필요한 것. 어떤 소재를 고를지, 무엇을 어떻게 물을지,
    답변의 어디를 파고들지. 다만 **근거는 도구가 준 것만** 쓸 수 있다.

여러 턴 상태는 세션 자산 `interview` 에 보존된다(asked/answers/usedTopics). 그래서 다음
턴의 이 에이전트는 "무엇을 이미 물었고 사용자가 어떻게 답했는지"를 알고 시작한다.

LLM 미설정·실패면 기존 결정론 템플릿으로 폴백한다 — 면접 준비가 통째로 죽지 않는다.
"""

from __future__ import annotations

from typing import Any

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import agent_arg, posting_identity
from jobis_ai.agents.agent_loop import ToolSpec, run_agent_loop
from jobis_ai.skill_taxonomy import get_skill_taxonomy

_MAX_QUESTIONS_PER_KIND = 5
# 답변에 근거가 담겼다고 보는 최소 신호 수(스킬 언급·수치·역할 서술 중).
_ANSWER_EVIDENCE_MIN = 1


# ---------------------------------------------------------------------------
# 상태 — 여러 턴에 걸쳐 세션에 보존된다
# ---------------------------------------------------------------------------
def _interview_state(session: dict[str, Any]) -> dict[str, Any]:
    state = dict(session.get("interview") or {})
    state.setdefault("asked", [])        # [{question, topic, type, basis}]
    state.setdefault("answers", [])      # [{question, answer, evidence}]
    state.setdefault("usedTopics", [])
    # 도구가 읽어야 하는 재료를 상태에 실어 둔다(도구는 session 을 모른다).
    state["_analysis"] = session.get("analysis") or {}
    state["_profile"] = session.get("profile") or {}
    state["_lastMessage"] = str(session.get("last_message") or "")
    # 하네스가 대화 이력을 루프 입력에 싣는 통로(agent_loop 규약). 위임 도구도 같은 키를 읽는다.
    state["_session"] = session
    return state


def _persisted(state: dict[str, Any]) -> dict[str, Any]:
    """세션에 저장할 부분만 — 밑줄 키(턴 내부 재료)는 저장하지 않는다."""

    return {k: v for k, v in state.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# 도구 — 전부 결정론. 판단·권유를 담지 않고 사실만 돌려준다.
# ---------------------------------------------------------------------------
def _materials(analysis: dict) -> list[dict]:
    """판정 결과에서 질문 소재를 뽑는다. 분석에 없는 것은 소재가 되지 않는다(근거 제한)."""

    out: list[dict] = []
    for gap in list(analysis.get("gaps") or [])[:_MAX_QUESTIONS_PER_KIND]:
        skills = gap.get("missingSkills") or []
        topic = ", ".join(skills) if skills else str(gap.get("requirementId", ""))
        if topic:
            out.append({"type": "gap", "topic": topic,
                        "requirementId": str(gap.get("requirementId") or ""),
                        "basis": str(gap.get("reason") or ""),
                        "severity": str(gap.get("severity") or "")})
    for strength in list(analysis.get("strengths") or [])[:_MAX_QUESTIONS_PER_KIND]:
        skills = strength.get("matchedSkills") or []
        if skills:
            out.append({"type": "strength", "topic": ", ".join(skills[:3]),
                        "requirementId": str(strength.get("requirementId") or ""),
                        "basis": str(strength.get("text") or ""), "severity": ""})
    return out


def _terms(topic: str) -> list[str]:
    return [t.strip() for t in str(topic).split(",") if t.strip()]


def _project_entries(profile: dict) -> list[tuple[str, str]]:
    """(이름표, 서술) — 사용자가 실제로 한 프로젝트·경력. 질문의 착지점이 된다."""

    out: list[tuple[str, str]] = []
    for key in ("projects", "experiences"):
        for entry in profile.get(key) or []:
            text = " ".join(str(entry.get(f) or "")
                            for f in ("role", "name", "description", "period")).strip()
            if text:
                label = str(entry.get("name") or entry.get("role") or "")[:40]
                out.append((label, text))
    return out


def _requirement_types(analysis: dict) -> dict[str, str]:
    """requirementId → required | preferred (공고가 필수로 요구한 것인지)."""

    return {str(r.get("requirementId") or ""): str(r.get("type") or "")
            for r in analysis.get("requirements") or []}


# 소재를 고르는 합리적 조건들. 값이 클수록 먼저 묻는다 — **결정론 계산**이고, LLM 은
# 이 순위를 바꿀 수 없다(무엇을 물을지 문장만 자유롭게 쓴다).
_W_IN_PROJECT = 3       # 사용자가 실제로 한 프로젝트에 그 스택이 등장 → 답할 소재가 있다
_W_REQUIRED = 2         # 공고의 **필수** 요건 → 면접에서 확실히 다뤄진다
_W_PREFERRED = 1        # 우대 사항
_W_SEVERITY = {"high": 2, "medium": 1, "low": 0}
_W_CLAIMED_NO_EVIDENCE = 2   # 이력서에 기재만 되고 경험 근거가 없음 → 면접에서 찔리는 지점


def _score_material(material: dict, profile: dict, req_types: dict[str, str]) -> tuple[int, list[str], str]:
    """(점수, 고른 이유들, 착지할 프로젝트 이름). LLM 없이 계산한다."""

    terms = _terms(material["topic"])
    score, reasons, landing = 0, [], ""

    for label, text in _project_entries(profile):
        if any(t.lower() in text.lower() for t in terms):
            score += _W_IN_PROJECT
            landing = label or text[:40]
            reasons.append(f"사용자 프로젝트('{landing}')에 실제로 등장 — 경험으로 답할 수 있다")
            break

    req_type = req_types.get(material.get("requirementId", ""), "")
    if req_type == "required":
        score += _W_REQUIRED
        reasons.append("공고의 필수 요건")
    elif req_type == "preferred":
        score += _W_PREFERRED
        reasons.append("공고의 우대 사항")

    severity = str(material.get("severity") or "")
    if severity in _W_SEVERITY and _W_SEVERITY[severity]:
        score += _W_SEVERITY[severity]
        reasons.append(f"격차 심각도 {severity}")

    # 스킬로는 적어 놨는데 프로젝트 서술에는 없는 경우 — 면접관이 반드시 파고드는 지점.
    listed = [s.get("name", "") for s in profile.get("skills") or []]
    if not landing and any(t.lower() in " ".join(listed).lower() for t in terms):
        score += _W_CLAIMED_NO_EVIDENCE
        reasons.append("이력서에 기재만 되고 경험 근거가 없다 — 면접에서 확인될 지점")

    return score, reasons, landing


def _tool_pick_material(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """다음에 물을 소재를 **합리적 조건으로 골라** 근거와 함께 준다.

    조건(점수 순): 사용자 프로젝트에 실제로 등장 > 공고 필수 요건 > 격차 심각도 >
    기재만 되고 근거 없음. 아직 안 다룬 것만. arg: strength | gap | 빈 문자열.
    """

    want = (arg or "").strip().lower()
    used = {t.lower() for t in state.get("usedTopics", [])}
    analysis = state.get("_analysis") or {}
    profile = state.get("_profile") or {}
    req_types = _requirement_types(analysis)

    candidates = []
    for material in _materials(analysis):
        if material["topic"].lower() in used:
            continue
        if want in ("strength", "gap") and material["type"] != want:
            continue
        score, reasons, landing = _score_material(material, profile, req_types)
        candidates.append((score, material, reasons, landing))

    if not candidates:
        remaining = "요청한 종류의" if want else "남은"
        return (f"{remaining} 소재가 없습니다. 이미 다룬 주제: "
                f"{', '.join(state.get('usedTopics') or []) or '없음'}"), {}

    # 동점이면 등장 순서(판정 엔진이 중요도 순으로 낸 순서)를 지킨다 — 안정적 선택.
    score, material, reasons, landing = max(candidates, key=lambda c: c[0])
    state.setdefault("usedTopics", []).append(material["topic"])
    state["_pending"] = {**material, "landing": landing}
    kind = "강점" if material["type"] == "strength" else "부족 역량"
    return (f"소재({kind}): {material['topic']} / 판정 근거: "
            f"{material['basis'] or '(근거 문장 없음)'} / 이 소재를 고른 이유: "
            f"{'; '.join(reasons) if reasons else '남은 소재 중 첫 항목'}"
            + (f" / 질문을 걸 프로젝트: {landing}" if landing else "")), {}


def _tool_find_evidence(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """이력서(프로필)에서 그 주제의 실제 근거를 찾는다. 없으면 없다고 말한다."""

    topic = (arg or "").strip()
    if not topic:
        return "주제를 지정해야 근거를 찾을 수 있습니다.", {}
    profile = state.get("_profile") or {}
    hits: list[str] = []
    for key in ("experiences", "projects"):
        for entry in profile.get(key) or []:
            text = " ".join(str(entry.get(f) or "") for f in ("role", "name", "description", "period"))
            if any(term.strip().lower() in text.lower()
                   for term in topic.split(",") if term.strip()):
                hits.append(text.strip()[:120])
    skills = [s.get("name", "") for s in profile.get("skills") or []]
    mentioned = [s for s in skills
                 if any(term.strip().lower() in s.lower()
                        for term in topic.split(",") if term.strip())]
    if not hits and not mentioned:
        return f"'{topic}' 관련 근거가 이력서에서 확인되지 않습니다.", {}
    parts = []
    if mentioned:
        parts.append("기재된 스킬: " + ", ".join(mentioned[:5]))
    if hits:
        parts.append("경험·프로젝트 서술: " + " / ".join(hits[:2]))
    else:
        parts.append("경험·프로젝트 서술에는 이 주제가 없습니다(스킬 기재만)")
    return " | ".join(parts), {}


def _tool_check_answer(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """사용자의 마지막 답변이 근거를 실제로 담았는지 결정론 점검.

    LLM 의 인상이 아니라 세는 것으로 판정한다: 이력서/공고에 있는 기술 용어를 몇 개
    말했나, 숫자(기간·규모·기여도)를 댔나, 본인 역할을 서술했나.
    """

    answer = (arg or "").strip() or state.get("_lastMessage", "")
    if not answer:
        return "점검할 답변이 없습니다(사용자 발화 없음).", {}
    taxonomy = get_skill_taxonomy()
    named_skills = taxonomy.find_in_text(answer)
    has_number = any(ch.isdigit() for ch in answer)
    role_words = [w for w in ("담당", "맡아", "구현", "설계", "개선", "주도", "기여") if w in answer]
    signals = len(named_skills) + (1 if has_number else 0) + (1 if role_words else 0)
    verdict = "근거 있음" if signals >= _ANSWER_EVIDENCE_MIN else "근거 부족"
    pending = state.get("_pending") or {}
    state.setdefault("answers", []).append({
        "question": str(pending.get("topic") or ""),
        "answer": answer[:500],
        "evidence": {"skills": named_skills, "hasNumber": has_number,
                     "roleWords": role_words, "verdict": verdict},
    })
    return (f"답변 점검({verdict}): 언급한 기술 {named_skills or '없음'}, "
            f"수치 {'있음' if has_number else '없음'}, 역할 서술 {role_words or '없음'}"), {}


def _tool_record_question(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """이번 턴에 사용자에게 낼 질문을 기록한다(다음 턴이 무엇을 물었는지 안다)."""

    question = (arg or "").strip()
    if not question:
        return "질문 문장이 비어 기록하지 않았습니다.", {}
    pending = state.get("_pending") or {}
    state.setdefault("asked", []).append({
        "question": question,
        "topic": str(pending.get("topic") or ""),
        "type": str(pending.get("type") or ""),
        "basis": str(pending.get("basis") or ""),
    })
    return f"질문을 기록했습니다(총 {len(state['asked'])}개).", {}


_TOOLS = {
    t.name: t for t in (
        ToolSpec("pick_material",
                 "아직 다루지 않은 질문 소재(강점/부족 역량)를 판정 결과에서 하나 가져온다.",
                 _tool_pick_material, "strength 또는 gap, 아무거나면 빈 문자열."),
        ToolSpec("find_evidence",
                 "그 주제에 대해 이력서에 실제로 어떤 근거가 있는지 확인한다(없으면 없다고 답한다).",
                 _tool_find_evidence, "확인할 주제·기술 이름."),
        ToolSpec("check_answer",
                 "사용자가 방금 한 답변이 근거(기술 언급·수치·역할 서술)를 담았는지 점검한다.",
                 _tool_check_answer, "점검할 답변. 비우면 사용자의 마지막 발화를 쓴다."),
        ToolSpec("record_question",
                 "이번 턴에 사용자에게 낼 질문을 기록한다. 질문을 확정했으면 반드시 부른다.",
                 _tool_record_question, "사용자에게 낼 질문 문장."),
    )
}

_GOAL_SYSTEM = """너는 취업 지원 서비스의 면접 준비 담당이다. 사용자가 실제 면접에서 답할 수 있게
연습시킨다.

이번 턴에 할 일은 상황에 따라 다르다 — 네가 판단한다:
- 아직 아무것도 묻지 않았다면: 소재를 골라 첫 질문을 한다.
- 사용자가 방금 답을 했다면: 그 답을 점검해 무엇이 근거로 부족한지 짧게 짚고, **그 답에서
  파고들 지점으로 꼬리 질문**을 한다. 새 소재로 넘어가는 것보다 파고드는 게 낫다.
- 다룰 소재가 더 없다면 지금까지 연습을 정리하고 마무리한다.

말하기 규칙:
- 한 번에 **질문 하나만** 한다. 여러 개를 나열하면 연습이 안 된다.
- 답변 평가는 사실만 짧게(무엇을 말했고 무엇이 빠졌는지). 합격 가능성·실력 단정 금지.
- 질문을 확정하면 record_question 으로 기록한다."""


def _fallback(session: dict[str, Any], extra_warnings: list[dict] | None = None) -> AgentResult:
    """LLM 불가 시 결정론 템플릿 — 기존 동작을 그대로 보존한다.

    루프가 실패한 이유(extra_warnings)를 반드시 함께 싣는다. 폴백이 이유를 삼키면
    "왜 템플릿 답변이 나왔는지" 로그에 아무것도 남지 않는다(실측으로 겪은 문제다).
    """

    analysis = session.get("analysis") or {}
    materials = _materials(analysis)
    if not materials:
        return AgentResult(
            reply=("적합도 분석 결과에 질문을 만들 만한 강점·부족 역량 정보가 없습니다. "
                   "먼저 공고 적합도 분석을 다시 실행해 주세요."),
            warnings=[{"code": "no_interview_basis",
                       "message": "interview_prep: analysis 에 gaps/strengths 가 비어 질문을 생성하지 않았습니다."}]
                     + list(extra_warnings or []),
        )
    questions = []
    for material in materials:
        topic = material["topic"]
        if material["type"] == "gap":
            question = f"{topic} 경험이 부족한 것으로 보이는데, 이 부분을 어떻게 보완할 계획인지 설명해 주시겠어요?"
        else:
            question = (f"{topic}을(를) 실제 프로젝트나 업무에서 어떻게 활용했는지, "
                        "본인이 기여한 부분을 중심으로 구체적으로 설명해 주시겠어요?")
        questions.append({"type": material["type"], "topic": topic,
                          "question": question, "basis": material["basis"],
                          "severity": material.get("severity", "")})
    gap_count = sum(1 for q in questions if q["type"] == "gap")
    reply = (f"분석 결과를 바탕으로 면접 예상 질문 {len(questions)}개를 준비했습니다 — "
             f"보완이 필요한 역량 관련 {gap_count}개, 강점 검증 관련 {len(questions) - gap_count}개입니다. "
             "각 질문은 적합도 분석에서 확인된 항목만 근거로 삼았습니다.")
    return AgentResult(reply=reply, data={"questions": questions},
                       warnings=list(extra_warnings or []))


def run(session: dict[str, Any]) -> AgentResult:
    """자기 루프를 돌려 이번 턴의 면접 진행을 만든다. LLM 불가면 결정론 폴백."""

    state = _interview_state(session)
    analysis = state["_analysis"]
    if not _materials(analysis):
        return _fallback(session)

    asked = state["asked"]
    company, role = posting_identity(session)
    facts = {
        "userMessage": state["_lastMessage"],
        # 어느 회사·직무 면접인가 — 질문 소재는 analysis 에서 나오지만, 면접 맥락을 모르면
        # 문장이 회사와 무관한 일반 질문처럼 읽힌다(화이트보드에 있는 것을 안 읽었을 뿐).
        "company": company,
        "role": role,
        "askedCount": len(asked),
        "lastQuestion": asked[-1]["question"] if asked else "",
        "answeredCount": len(state["answers"]),
        "userJustAnswered": bool(state["_lastMessage"]) and bool(asked),
        # 사용자가 다룰 주제를 지목했으면(플래너가 읽어 넘긴다) 그것부터 다룬다.
        "focusRequested": agent_arg(session, "interview_prep", "focus"),
    }
    outcome = run_agent_loop(
        goal_system=_GOAL_SYSTEM, facts=facts, tools=_TOOLS, state=state,
        node="interview_prep", session_id=str(session.get("_sessionId") or ""),
    )
    if not outcome.reply:
        # 루프가 검증 통과 문장을 못 만들었다 — 템플릿으로 답하되 **이유는 남기고**,
        # 이번 턴에 도구가 이미 쌓아 둔 진행분(점검한 답변·다룬 주제)은 보존한다.
        # 그러지 않으면 LLM 이 한 번 실패했다는 이유로 사용자의 답변 기록이 사라진다.
        fallback = _fallback(session, outcome.warnings)
        return AgentResult(
            reply=fallback.reply, data=fallback.data, warnings=fallback.warnings,
            followUpQuestions=fallback.followUpQuestions,
            sessionUpdates={"interview": _persisted(state)},
        )

    return AgentResult(
        reply=outcome.reply,
        data={"interview": _persisted(state), "loopSteps": outcome.steps},
        warnings=outcome.warnings,
        # 여러 턴에 걸친 진행 상태를 자산으로 승격 — 다음 턴의 이 에이전트가 이어받는다.
        sessionUpdates={"interview": _persisted(state)},
    )

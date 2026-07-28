"""공고 선호 파악 에이전트 — 이력서 없이도 대화로 원하는 직군·회사·도메인을 수집한다.

"이력서 없는데 공고 추천받고 싶어" → "이력서 주세요"로 닫아버리는 대신, 사람과
주고받듯 선호를 묻고 세션에 누적한다. **분기점(충분한 선호 확보)은 결정론 룰**이
정하고, 넘으면 "○○에 관심이 있으시군요. 준비해두신 이력서가 있으신가요?"로
자연스럽게 전환한다.

역할 분담 (판단은 데이터, LLM은 읽기):
- 직군 탐지 1차: role_taxonomy 별칭 매칭 (룰, LLM 없이도 동작)
- 회사·도메인 등 자유 표현: LLM 읽기 전용 스키마 (경량 티어 — 짧은 발화의 추출)
- 분기점·응답 선택: 순수 파이썬 (아래 _sufficient)
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from jobis_ai.agents import AgentResult
from jobis_ai.role_taxonomy import get_role_taxonomy
from jobis_ai.structured import run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

# 분기점 룰: 선호 차원(직군/회사/도메인) 2개 이상 확보, 또는 1개 이상 + 대화 2턴 경과.
# 무한 되묻기 방지 — 사용자를 질문 루프에 가두지 않는다.
_MIN_DIMENSIONS = 2
_MAX_PROBE_TURNS = 2

_ASK_OPEN = (
    "좋아요, 이력서 없이 시작해도 됩니다. 어떤 공고를 찾으시는지부터 알려주세요 — "
    "관심 있는 직군(백엔드·데이터·모바일 같은)이나 가고 싶은 회사, 해보고 싶은 일이면 충분해요."
)


# 선호 차원 — 이 키들의 확보 개수로 분기점(_sufficient)을 계산한다.
_DIM_KEYS = ("roles", "companies", "domains", "regions", "techStack")


def _detect_roles_by_rule(text: str) -> list[str]:
    """role_taxonomy 별칭 분류 — LLM 없이도 직군을 잡는다."""

    taxonomy = get_role_taxonomy()
    key = taxonomy.classify_role(text or "")
    return [taxonomy.label_of(key)] if key else []


def _merge(prefs: dict, key: str, values: list[str]) -> None:
    seen = {v.strip().lower() for v in prefs[key]}
    for v in values:
        v = (v or "").strip()
        if v and v.lower() not in seen:
            prefs[key].append(v)
            seen.add(v.lower())


def _dimensions(prefs: dict) -> int:
    return sum(1 for k in _DIM_KEYS if prefs.get(k))


def _summary(prefs: dict) -> str:
    parts = []
    if prefs.get("roles"):
        parts.append(f"{'·'.join(prefs['roles'][:3])} 직군")
    if prefs.get("domains"):
        parts.append(f"{'·'.join(prefs['domains'][:3])} 도메인")
    if prefs.get("companies"):
        parts.append(f"{'·'.join(prefs['companies'][:3])} 같은 회사")
    if prefs.get("regions"):
        parts.append(f"{'·'.join(prefs['regions'][:3])} 지역")
    if prefs.get("techStack"):
        parts.append(f"{'·'.join(prefs['techStack'][:3])} 환경")
    return ", ".join(parts)


def _sufficient(prefs: dict) -> bool:
    """분기점 — 순수 결정론. 차원 2개 이상, 또는 1개 이상 + 되묻기 2턴 소진."""

    dims = _dimensions(prefs)
    return dims >= _MIN_DIMENSIONS or (dims >= 1 and prefs.get("turns", 0) >= _MAX_PROBE_TURNS)


def _next_probe(prefs: dict) -> tuple[str, str]:
    """다음에 물을 차원 → (결정론 질문 문장, 렌더 LLM 용 askFor 서술).

    우선순위: 직군 → 도메인/회사 → 지역 → 기술스택·개발환경.
    질문 순서는 룰이 정하고(판단), 문장은 LLM 이 다듬는다(표현).
    """

    if not prefs.get("roles"):
        return ("어떤 직군·역할로 지원하고 싶으신가요? (예: 백엔드, 데이터, 모바일)",
                "어느 직군·역할을 원하는지 (백엔드·데이터·모바일 같은)")
    if not (prefs.get("domains") or prefs.get("companies")):
        return ("특별히 관심 있는 도메인(커머스·핀테크 같은)이나 가고 싶은 회사가 있나요?",
                "관심 도메인이나 가고 싶은 회사 — 직군이 백엔드처럼 넓으면 세부 분야(Spring·Node 같은)를 함께 물어도 좋다")
    if not prefs.get("regions"):
        return ("선호하는 근무 지역이 있나요? (예: 서울, 판교, 원격)",
                "선호하는 근무 지역")
    return ("선호하는 기술 스택이나 개발환경이 있나요? (예: Java/Spring, Node, AWS)",
            "선호하는 기술 스택·개발환경")


def _probe_reply(prefs: dict) -> str:
    """아직 분기점 전 — 아는 것을 받아주고, 모르는 차원을 이어 묻는다 (대화의 주고받기)."""

    if not _dimensions(prefs):
        return _ASK_OPEN
    question, _ = _next_probe(prefs)
    return f"{_summary(prefs)} 쪽이시군요. {question} 없으면 지금 기준으로 바로 넘어가도 돼요."


# --- 말하기 계층: 무엇을 물을지는 룰이 정하고, 어떻게 말할지는 LLM 이 쓴다 --------
class _ReplyWrite(BaseModel):
    """표현 전용 — 한두 문장의 대화 응답. 판단 필드 없음.

    필드 설명을 비워 두면 구조화 출력에서 모델이 이 칸을 '제목'처럼 취급해 한 줄로 끝낸다
    (career_chat 에서 실측된 문제). 여기는 짧은 게 맞지만, 끝을 질문으로 맺어야 하므로 명시한다.
    """

    reply: str = Field(default="", description=(
        "사용자에게 보낼 두세 문장. 먼저 발화를 짧게 받아주고, **반드시 askFor 를 묻는 "
        "구체적인 질문으로 끝낸다**(보기 예시 한두 개 포함). 확인·안내만 하고 끝내지 않는다."))


_RENDER_SYSTEM = """너는 취업 서비스 상담 대화의 문장을 쓰는 작가다. facts 를 바탕으로 사용자에게 보낼 자연스러운 두세 문장을 쓴다.
- userMessage: 사용자의 직전 발화 — 먼저 한 말을 짧게 받아준다.
- recentHistory: 직전까지의 대화 — 이미 물었던 것을 똑같이 되묻지 않고 흐름을 잇는다.
- known: 지금까지 파악한 선호(직군·도메인·회사·지역·기술스택). 있으면 자연스럽게 언급한다.
- askFor: 이번에 물어야 할 것. **응답은 반드시 askFor 를 묻는 구체적 질문으로 끝난다** —
  확인·안내만 하고 끝내지 않는다. 보기 예시를 한두 개 곁들인다
  (직군이면 백엔드·데이터, 백엔드 세부 분야면 Spring·Node, 지역이면 서울·판교·원격 같은).
  "resume"면 준비된 이력서가 있는지 묻고, 주시면 그 기준으로 공고를 추천한다고 안내한다.
- facts 에 없는 판단·예측·조언(적합도, 합격 가능성 등)은 절대 쓰지 않는다. 과장 금지.
- 상담원처럼 딱딱하지 않게, 짧고 자연스럽게."""


# --- 행동 선택 계층: 다음에 무엇을 할지 **에이전트가 고른다** -------------------
# 규칙으로 "이 말엔 이 답" 을 열거하는 방식은 문장 하나 바뀌면 무너진다(사용자가 "공고 보내면 돼?"
# 라고 물었는데 선호를 또 캐묻는 문제). 그래서 선택지(행동)만 규칙이 정의하고, 무엇을 할지는
# 에이전트가 발화·맥락을 보고 정한다. 각 행동의 **효과**는 여전히 코드가 통제한다.
_ACTIONS = ("ask_preference", "request_posting", "request_resume", "proceed")


class _IntakeAct(BaseModel):
    """이번 턴의 행동 + 사용자에게 할 말 + 발화에서 읽어낸 선호.

    별도 추출 호출(_PreferenceRead)을 두지 않고 한 번에 받는다 — CLI 경유 공급자에서는
    호출 수가 곧 응답 시간이다(호출당 수 초). 추출 규칙은 필드 description 이 강제한다.
    """

    roles: list[str] = Field(default_factory=list, description=(
        "발화에 실제로 언급된 직군·직무 표현만(예: 백엔드, 데이터 엔지니어). 추측·확장 금지."))
    companies: list[str] = Field(default_factory=list, description=(
        "발화에 언급된 회사 이름 또는 회사 선호 특성(\"규모가 큰 회사\" 등)만. 없으면 빈 배열."))
    domains: list[str] = Field(default_factory=list, description=(
        "발화에 언급된 산업/서비스 도메인(커머스·핀테크·게임 등)만. 없으면 빈 배열."))
    regions: list[str] = Field(default_factory=list, description=(
        "발화에 언급된 근무 지역·형태(서울·판교·원격 등)만. 없으면 빈 배열."))
    techStack: list[str] = Field(default_factory=list, description=(
        "발화에 언급된 기술 스택·개발환경(Java/Spring, AWS 등)만. 없으면 빈 배열."))
    action: str = Field(default="ask_preference", description=(
        "이번 턴에 할 일. 하나만 고른다.\n"
        "- request_posting: 사용자가 특정 공고를 갖고 있다/보내겠다고 하거나, 그 공고 기준으로 "
        "보고 싶어할 때. 이 대화창에 공고 원문이나 URL 을 붙여넣으라고 안내한다.\n"
        "- request_resume: 사용자가 이력서·경력을 주겠다고 하거나, 맞춤 추천을 원해 이력이 필요할 때.\n"
        "- ask_preference: 아직 무엇을 원하는지 모를 때만. suggestedAsk 를 참고해 한 가지를 묻는다.\n"
        "- proceed: 이미 충분히 파악돼 다음 단계로 넘어가도 될 때."))
    reply: str = Field(default="", description=(
        "사용자에게 보낼 두세 문장. **사용자가 방금 한 말에 먼저 답한다** — 질문을 받았으면 그 질문에 "
        "답하고, 무언가를 주겠다고 하면 어떻게 주면 되는지 알려준다. 같은 질문을 반복하지 않는다."))


_ACT_SYSTEM = """너는 취업 서비스의 대화 상담원이다. 사용자가 원하는 공고를 찾도록 돕는다.

발화에 실제로 언급된 선호(직군·회사·도메인·지역·기술스택)는 해당 필드에 그대로 옮겨 적는다 —
추측·확장 금지, 없으면 빈 배열.

이번 턴에 무엇을 할지 네가 고른다(action). 판단 기준:
- 사용자가 특정 공고를 언급하거나 "보내면 되냐/있다"고 하면 → request_posting.
  이 대화창에 공고 원문이나 URL 을 그대로 붙여넣으면 된다고 알려준다. 다른 화면으로 보내지 않는다.
- 사용자가 이력서·경력을 주겠다고 하거나 맞춤 추천에 이력이 필요하면 → request_resume.
- 아직 무엇을 원하는지 전혀 모를 때만 → ask_preference (suggestedAsk 참고).
- known 에 이미 충분히 모였고 사용자가 진행을 원하면 → proceed.

입력:
- userMessage: 사용자의 직전 발화. **여기에 먼저 답한다.**
- recentHistory: 직전 대화. 이미 물어본 것을 똑같이 되묻지 않는다.
- known: 지금까지 파악한 선호.
- hasResume / hasPosting: 세션에 이력서·공고가 이미 있는지.
- suggestedAsk: 규칙이 제안하는 다음 질문(참고용 — 맥락에 안 맞으면 무시해도 된다).

- 적합도·합격 가능성을 단정하지 않는다. 그건 분석 기능이 근거를 갖고 하는 일이다.
- 상담원처럼 딱딱하지 않게, 짧고 자연스럽게."""


def _decide(facts: dict) -> tuple[str, str, "_IntakeAct | None", list[dict]]:
    """(action, reply, 추출된 선호, warnings). LLM 미설정·실패면 ("", "", None, warnings)."""

    read, warnings = run_structured(
        _IntakeAct, _ACT_SYSTEM, json.dumps(facts, ensure_ascii=False),
        node="preference_intake_act",
    )
    if read is None:
        return "", "", None, warnings
    action = read.action if read.action in _ACTIONS else "ask_preference"
    reply = (read.reply or "").strip()
    if not reply or any(expr in reply for expr in FORBIDDEN_EXPRESSIONS):
        return "", "", read, warnings
    return action, reply, read, warnings


def _render_reply(facts: dict, fallback: str) -> tuple[str, list[dict]]:
    """LLM 표현 + 검증, 실패 시 결정론 템플릿 폴백 (nl_render 와 같은 패턴).

    검증 2종: 금지표현, 그리고 **질문으로 끝나는지** — 이 에이전트의 응답은 항상
    다음 정보를 물어야 하므로, 확인만 하고 끝난 문장은 버리고 폴백(항상 질문형)을 쓴다.
    """

    read, warnings = run_structured(
        _ReplyWrite, _RENDER_SYSTEM, json.dumps(facts, ensure_ascii=False),
        node="preference_intake_render",
    )
    text = (read.reply or "").strip() if read is not None else ""
    if not text or "?" not in text or any(expr in text for expr in FORBIDDEN_EXPRESSIONS):
        return fallback, warnings
    return text, warnings


def run(session: dict) -> AgentResult:
    from jobis_ai.orchestrator.session import recent_history

    prefs = {
        **{k: [] for k in _DIM_KEYS}, "turns": 0,
        **(session.get("preferences") or {}),
    }
    message = str(session.get("last_message") or "")
    history = recent_history(session, max_items=4)

    # 1차 룰: 직군은 taxonomy 별칭으로 결정론 탐지
    _merge(prefs, "roles", _detect_roles_by_rule(message))

    warnings: list[dict] = []
    known = {k: prefs[k] for k in _DIM_KEYS if prefs.get(k)}

    # 행동 선택 + 선호 추출을 **한 호출로** 받는다 (읽기 호출 분리는 CLI 공급자에서 턴을
    # 배로 느리게 한다). 규칙(_next_probe)은 제안만 넘긴다.
    _, suggested_ask = _next_probe(prefs)
    action, reply, extracted, act_warnings = _decide({
        "userMessage": message,
        "recentHistory": history,
        "known": known,
        "hasResume": bool(session.get("resume") or session.get("profile")),
        "hasPosting": bool(session.get("job_posting")),
        "suggestedAsk": suggested_ask,
    })
    if extracted is not None:
        for key in _DIM_KEYS:
            _merge(prefs, key, getattr(extracted, key))

    # LLM 이 직군 표현을 도메인·회사로도 중복 분류하는 것 정리 — 직군은 직군 한 곳에만.
    taxonomy = get_role_taxonomy()
    role_lower = {r.lower() for r in prefs["roles"]}
    for key in ("domains", "companies"):
        prefs[key] = [
            v for v in prefs[key]
            if v.lower() not in role_lower and not taxonomy.classify_role(v)
        ]
    known = {k: prefs[k] for k in _DIM_KEYS if prefs.get(k)}
    if action:
        warnings.extend(act_warnings)
        # 행동의 효과는 코드가 정한다 — 무엇을 받아야 하는지를 followUpQuestions 로 알린다.
        follow_up: list[dict] = []
        if action == "request_posting":
            follow_up = [{"field": "job_posting",
                          "question": "분석할 공고 원문이나 URL 을 이 대화에 붙여넣어 주세요."}]
        elif action == "request_resume":
            follow_up = [{"field": "resume", "question": "이력서(또는 경력·기술 소개)를 올려 주세요."}]
        elif action == "ask_preference":
            prefs["turns"] = int(prefs.get("turns", 0)) + 1
            follow_up = [{"field": "preferences", "question": reply}]
        return AgentResult(
            reply=reply,
            data={"preferences": known, "sufficient": _sufficient(prefs), "action": action},
            warnings=warnings,
            followUpQuestions=follow_up,
            sessionUpdates={"preferences": prefs},
        )

    warnings.extend(act_warnings)
    # 여기부터는 LLM 미설정·실패 시의 결정론 경로(기존 동작 유지).
    if _sufficient(prefs):
        fallback = (
            f"{_summary(prefs)}에 관심이 있으시군요. 준비해두신 이력서가 있으신가요? "
            f"주시면 그 기준으로 맞는 공고를 바로 추천해 드릴게요. "
            f"아직 없다면 간단한 경력·기술 소개만 주셔도 시작할 수 있어요."
        )
        reply, render_warnings = _render_reply(
            {"userMessage": message, "recentHistory": history, "known": known,
             "askFor": "resume"}, fallback
        )
        follow_up = [{"field": "resume", "question": "이력서(또는 경력·기술 소개)를 올려 주세요."}]
    else:
        prefs["turns"] = int(prefs.get("turns", 0)) + 1
        _, ask_for = _next_probe(prefs)
        reply, render_warnings = _render_reply(
            {"userMessage": message, "recentHistory": history, "known": known,
             "askFor": ask_for}, _probe_reply(prefs)
        )
        follow_up = [{"field": "preferences", "question": reply}]
    warnings.extend(render_warnings)

    return AgentResult(
        reply=reply,
        data={"preferences": {k: v for k, v in prefs.items() if k != "turns"}},
        warnings=warnings,
        followUpQuestions=follow_up,
        sessionUpdates={"preferences": prefs},
    )

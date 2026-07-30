"""공고 선호 파악 에이전트 — 이력서 없이도 대화로 원하는 직군·회사·도메인을 수집한다.

"이력서 없는데 공고 추천받고 싶어" → "이력서 주세요"로 닫아버리는 대신, 사람과
주고받듯 선호를 묻고 세션에 누적한다. **분기점(충분한 선호 확보)은 결정론 룰**이
정하고, 넘으면 "○○에 관심이 있으시군요. 준비해두신 이력서가 있으신가요?"로
자연스럽게 전환한다.

**자기 루프 에이전트다**(2026-07-29 전환, agent_loop 세 번째 적용). 전에는 LLM 을 한 번 불러
행동·추출·문장을 동시에 받고 끝냈다. 선호 수집의 본질은 그게 아니다 — 듣고 기록하고, *지금
조건으로 실제 공고가 나오는지 확인하고*, 좁으면 넓히자고 다시 묻는 일이 이어진다. 한 번
호출로 끝나는 구조에는 그 반복이 일어날 자리가 없었다.

역할 분담 (판단은 데이터, LLM은 읽기·말하기):
- 직군 탐지 1차: role_taxonomy 별칭 매칭 (룰, LLM 없이도 동작)
- 도구(결정론): 선호 기록·충분성 판정 · **실공고 미리보기(job_recommend 위임)** · 자료 요청 표시
- 에이전트(LLM): 어떤 도구를 쓸지, 무엇을 물을지, 어떻게 말할지
- 분기점: 순수 파이썬 (아래 _sufficient) — LLM 이 바꿀 수 없다
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from jobis_ai.agents import AgentResult
from jobis_ai.agents.agent_loop import ToolSpec, delegate_tool, run_agent_loop
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


# --- 도구 (전부 결정론. LLM 없음 — 값을 단정하는 일은 여기서만 한다) --------------
# 도구 인자는 문자열 하나뿐이라, 여러 차원을 한 번에 받을 때는 **라벨 줄 미니포맷**을 쓰고
# 도구가 결정론으로 파싱한다(coverletter_draft 의 '동기:/강점:/보완:' 과 같은 선례).
_LABEL_TO_KEY = {
    "직군": "roles", "역할": "roles",
    "회사": "companies",
    "도메인": "domains", "분야": "domains",
    "지역": "regions",
    "기술": "techStack", "스택": "techStack",
}
_EXPERIENCE_LABELS = ("경력", "연차")


def _parse_labeled(arg: str) -> tuple[dict[str, list[str]], str]:
    """'직군: 백엔드' 형태의 줄들 → ({차원: 값들}, 경력수준). 알 수 없는 라벨은 버린다."""

    found: dict[str, list[str]] = {}
    experience = ""
    for line in str(arg or "").splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label, value = label.strip(), value.strip()
        if not value:
            continue
        if label in _EXPERIENCE_LABELS:
            experience = value
            continue
        key = _LABEL_TO_KEY.get(label)
        if key:
            found.setdefault(key, []).extend(
                v.strip() for v in value.split(",") if v.strip())
    return found, experience


def _known(prefs: dict) -> dict:
    return {k: prefs[k] for k in _DIM_KEYS if prefs.get(k)}


def _sync_session(state: dict) -> None:
    """작업 중인 선호를 세션 **사본**에 반영한다 — 위임(preview_postings)이 그것으로 검색한다.

    사본이어야 한다. 진짜 세션을 여기서 고치면 턴의 상태 전이가 오케스트레이터 독점이라는
    규약이 깨진다(저장은 sessionUpdates 로만).
    """

    state["_session"] = {**state["_sessionBase"], "preferences": state["prefs"]}


def _tool_record_preference(state: dict, arg: str) -> tuple[str, dict]:
    """발화에서 읽은 선호를 기록한다. **충분한지 판정(룰)까지 관찰로 돌려준다.**"""

    prefs = state["prefs"]
    found, experience = _parse_labeled(arg)
    if not found and not experience:
        return ("라벨을 찾지 못해 아무것도 기록하지 않았습니다. "
                "'직군:', '도메인:', '회사:', '지역:', '기술:', '경력:' 으로 시작하는 줄에 적어 다시 부르세요."), {}

    for key, values in found.items():
        _merge(prefs, key, values)
    if experience:
        # 단일 값 — 새로 말했을 때만 갱신한다(빈 값으로 지우지 않는다).
        prefs["experienceLevel"] = experience

    # 직군 표현이 도메인·회사로도 중복 분류되는 것 정리 — 직군은 직군 한 곳에만.
    taxonomy = get_role_taxonomy()
    role_lower = {r.lower() for r in prefs["roles"]}
    for key in ("domains", "companies"):
        prefs[key] = [v for v in prefs[key]
                      if v.lower() not in role_lower and not taxonomy.classify_role(v)]
    _sync_session(state)

    enough = _sufficient(prefs)
    _, next_ask = _next_probe(prefs)
    return (f"기록했습니다. 지금 아는 것: {_summary(prefs) or '(없음)'} "
            f"(선호 차원 {_dimensions(prefs)}개, 충분한가: {'예' if enough else '아니오'}). "
            + (f"아직 모르는 것: {next_ask}" if not enough
               else "선호만으로 추천할 수 있는 상태입니다.")), {}


def _tool_request_material(state: dict, arg: str) -> tuple[str, dict]:
    """사용자에게 받아야 할 자료를 표시한다. 실제 요청 문구·질문 카드는 코드가 만든다."""

    wanted = str(arg or "").strip()
    kind = ("job_posting" if "공고" in wanted or "posting" in wanted.lower()
            else "resume" if "이력" in wanted or "resume" in wanted.lower() else "")
    if not kind:
        return "'공고' 또는 '이력서' 중 하나를 인자로 주세요.", {}
    state["_requested"] = kind
    label = "공고" if kind == "job_posting" else "이력서"
    # 관찰은 **사실만** 담는다(ToolSpec 규약). 무엇을 어떻게 안내할지는 goal_system 이 정한다 —
    # 관찰에 "안내하세요" 같은 지시를 넣었더니 답변이 도구 동작을 서술했다("이력서를 요청드렸어요").
    return f"받을 자료를 {label}(으)로 표시했습니다. 이 서비스는 대화창 붙여넣기로 자료를 받습니다.", {}


_TOOLS = {
    t.name: t for t in (
        ToolSpec("record_preference",
                 "발화에서 읽어낸 선호를 기록한다. 기록 후 지금 아는 것과 충분한지를 알려준다.",
                 _tool_record_preference,
                 ("줄마다 '직군:', '도메인:', '회사:', '지역:', '기술:', '경력:' 으로 시작해 값을 적는다"
                  "(한 줄에 쉼표로 여러 개 가능). **발화에 실제로 있는 것만** — 추측 금지. "
                  "예) 직군: 백엔드\n도메인: 커머스")),
        # 에이전트 간 통신 — "지금 조건으로 실제 공고가 있나"는 공고 추천이 이미 계산한다.
        # 같은 계산을 여기 다시 구현하는 대신 물어본다(읽기 전용). 이 관찰이 다음 질문을 바꾼다:
        # 0건이면 조건을 넓히자고 묻고, 여러 건이면 이력서를 받아 정교화하자고 넘어간다.
        delegate_tool(("job_recommend",), name="preview_postings"),
        ToolSpec("request_material",
                 "사용자에게 받아야 할 자료(공고·이력서)를 표시한다.",
                 _tool_request_material, "'공고' 또는 '이력서'."),
    )
}

_GOAL_SYSTEM = """너는 취업 서비스의 대화 상담원이다. 사용자가 원하는 공고를 찾도록 돕는다.

하는 일: 사용자의 말에서 선호를 읽어 record_preference 로 기록하고, 필요하면 preview_postings
로 지금 조건에 실제 공고가 있는지 확인한 뒤, 부족한 것을 하나 물어본다.

판단 기준:
- 발화에 선호(직군·회사·도메인·지역·기술스택·본인 연차)가 있으면 **먼저 record_preference**.
  없는 것을 추측해 넣지 않는다.
- 기록 결과가 "충분한가: 예" 면 이력서를 받는 쪽으로 넘어간다(request_material 로 '이력서').
- 선호가 어느 정도 모였는데 정말 공고가 있는지 궁금하면 preview_postings 로 확인한다.
  **0건이면** 조건이 좁다는 뜻이니 넓힐 방향을 제안하며 다시 묻는다. 여러 건이면 그 사실을
  알려주고 이력서를 받아 더 맞게 골라주겠다고 안내한다.
- 사용자가 특정 공고를 갖고 있다/보내겠다고 하면 request_material 로 '공고'.
- 아직 무엇을 원하는지 전혀 모르면 도구 없이 바로 물어도 된다.
- 자료를 청할 때는 **이 대화창에 원문이나 URL 을 붙여넣으면 된다**고 알려준다. 다른 화면으로
  보내지 않는다. 도구를 불렀다는 사실을 서술하지 말고(예: "요청드렸어요") 사용자에게 직접 청한다.

답변(action=reply)은 두세 문장이다. **사용자가 방금 한 말에 먼저 답하고**, 아직 부족하면
구체적인 질문(보기 예시 한두 개 포함)으로 끝낸다. 같은 질문을 반복하지 않는다.
관찰로 확인되지 않은 공고 건수·회사명을 지어내지 않는다."""


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

    # 1차 룰: 직군은 taxonomy 별칭으로 결정론 탐지 (LLM 없이도 잡힌다)
    _merge(prefs, "roles", _detect_roles_by_rule(message))

    warnings: list[dict] = []
    _, suggested_ask = _next_probe(prefs)

    # 자기 루프 — 어떤 도구를 쓸지·무엇을 물을지는 에이전트가 정하고, 값과 분기점은 도구가 낸다.
    state: dict = {
        "prefs": prefs,
        "_requested": "",
        # 위임·대화 이력의 출처. `_sessionBase` 는 원본, `_session` 은 작업 선호를 얹은 사본이다
        # (진짜 세션을 고치지 않는다 — 상태 전이는 오케스트레이터 독점).
        "_sessionBase": session,
    }
    _sync_session(state)
    outcome = run_agent_loop(
        goal_system=_GOAL_SYSTEM,
        facts={
            "userMessage": message,
            "known": _known(prefs),
            "hasResume": bool(session.get("resume") or session.get("profile")),
            "hasPosting": bool(session.get("job_posting")),
            "suggestedAsk": suggested_ask,
        },
        tools=_TOOLS, state=state, node="preference_intake",
        session_id=str(session.get("_sessionId") or ""),
    )
    warnings.extend(outcome.warnings)

    if outcome.reply:
        requested = state["_requested"]
        # 행동의 효과는 코드가 정한다 — 무엇을 받아야 하는지를 followUpQuestions 로 알린다.
        if requested == "job_posting":
            follow_up = [{"field": "job_posting",
                          "question": "분석할 공고 원문이나 URL 을 이 대화에 붙여넣어 주세요."}]
        elif requested == "resume":
            follow_up = [{"field": "resume", "question": "이력서(또는 경력·기술 소개)를 올려 주세요."}]
        else:
            # 자료를 청하지 않았으면 이번 턴은 선호를 더 물은 것이다 — 되묻기 횟수를 센다
            # (무한 되묻기 방지 — _sufficient 가 이 값을 읽는다).
            prefs["turns"] = int(prefs.get("turns", 0)) + 1
            follow_up = [{"field": "preferences", "question": outcome.reply}]
        return AgentResult(
            reply=outcome.reply,
            data={"preferences": _known(prefs), "sufficient": _sufficient(prefs),
                  "action": requested or "ask_preference", "loopSteps": outcome.steps},
            warnings=warnings,
            followUpQuestions=follow_up,
            sessionUpdates={"preferences": prefs},
        )

    # 루프가 검증 통과 문장을 못 만들었다(LLM 미설정·실패) — 결정론 경로로 답한다.
    # 도구가 이미 기록한 선호는 보존한다(한 번 실패했다고 사용자가 말한 것을 버리지 않는다).
    known = _known(prefs)
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

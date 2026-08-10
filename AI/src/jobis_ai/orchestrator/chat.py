"""대화 진입점 — handle_chat (llm-planner-design.md).

**추론은 자율, 행동과 상태 전이는 하네스로 좁힌다.**

- 그라운딩: 첨부·세션 자산·최근 대화·에이전트 실행 가능 여부를 플래너의 입력으로 강제한다.
- 액션 스페이스 제한: 플래너가 낼 수 있는 것은 레지스트리에 등록된 에이전트 이름뿐이다
  (스키마 Literal). 실행은 그 에이전트만 하고, 상태 전이는 outcome.sessionUpdates 로만 일어난다.
- 검증: 고른 시퀀스의 실행 가능성은 validate_plan(순수 코드)이, 사용자에게 나가는 문장은
  금지표현 검증(safe_ack)이 사후에 확인한다.
- 재계획: 에이전트가 끝날 때마다 남은 계획을 다시 정한다 — 판단자는 **규칙**(observe_rules)이다.
  전에는 경량 LLM 이 결과 요약을 보고 continue/finish/call 을 냈는데, 실측에서 실행을 바꾼
  사례가 없고 자기 자리의 위험(전제 붕괴)조차 못 막아 규칙으로 내렸다. LLM 이 도구를 골라
  스스로 도는 ReAct 는 한 층 아래(agents/agent_loop.py)가 담당한다.

이 모듈은 판단하지 않고, 흐름 순서도 정해 두지 않는다. 무엇을 할지는 플래너가 매 턴 새로
정한다. LLM 이 없거나 확신이 낮으면 대화형 에이전트가 턴을 받는다 — 고정 문구로 대화를
끝내지 않는다.

세션 I/O 는 **write-back** 이다: 턴 시작에 한 번 읽고(작업 사본), 턴 중의 모든 변경은
사본+pending 에만 쌓고, 턴 끝에 한 번 저장한다. 에이전트가 중간에 남기는 캐시
(_common.ensure_profile)도 사본의 _stagedUpdates(=pending) 로 들어온다.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from jobis_ai import llm_usage, trace
from jobis_ai.agents import AgentResult, get_agent_registry
from jobis_ai.contracts.api import ChatRequest, ChatResponse
from jobis_ai.orchestrator import observe_rules
from jobis_ai.orchestrator.attachment_kind import MIN_ASSET_CHARS, resolve_kind
from jobis_ai.orchestrator.planner import (
    CONFIDENCE_THRESHOLD,
    plan_agents,
    replacement_for,
    safe_ack,
)
from jobis_ai.orchestrator.router import (
    FALLBACK_AGENT,
    Dispatch,
    agent_feasibility,
    agent_label,
    asset_label,
    runnable_now,
    session_assets,
    validate_agent_args,
    validate_plan,
)
from jobis_ai.orchestrator.session import (
    HISTORY_MAX_ITEMS,
    UNSUPPORTED_MAX_ITEMS,
    get_session_store,
)
from jobis_ai.orchestrator.user_facts import extract_user_facts

# 판단 궤적은 trace(창문) 외에 **로그로도** 남긴다. trace 이벤트는 턴이 끝나면 사라지므로
# (SSE 중계·패널 조립용으로만 쓰인다) 사후에 "무엇을 왜 골랐나"를 볼 수단이 없었다.
# 한 줄에 한 결정 — 세션 단위로 grep 하면 궤적 전체가 순서대로 읽힌다.
log = logging.getLogger(__name__)

_ATTACHMENT_ACK = {
    "resume": "이력서를 받았어요.",
    "job_posting": "공고를 받았어요.",
    "resume_extra": "추가 정보를 이력서에 반영했어요.",
}

# 프론트의 kind 를 내용으로 바로잡았을 때 — 무엇이 왜 바뀌었는지 사용자에게 말한다.
_ATTACHMENT_ACK_CORRECTED = {
    "resume": "붙여주신 내용이 공고가 아니라 이력서로 보여서, 이력서로 등록했어요.",
    "job_posting": "붙여주신 내용이 이력서가 아니라 채용 공고로 보여서, 공고로 등록했어요.",
}

# URL 은 공고 전용이다(D62) — 이력서·포트폴리오 링크는 받지 않는다. 주소는 내용 판정이
# 성립하지 않으므로(resolve_kind 불가) 종류를 규약으로 고정할 수 있어야 결정론이 된다.
_ATTACHMENT_ACK_URL_POSTING = "공고 링크를 받았어요."
_ATTACHMENT_ACK_URL_COERCED = (
    "링크는 채용 공고로만 받고 있어서 공고 링크로 등록했어요. "
    "이력서는 내용을 직접 붙여넣어 주세요."
)

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
# 스킴 없이 붙여넣는 주소("saramin.co.kr/zf_user/…") — **발화 전체가 도메인/경로 한
# 토큰**일 때만 주소로 본다. 경로(/)를 요구해 문장 속 도메인("github.com에 올렸어요")
# 오탐을 막고, 경로 뒤는 \S 로 열어 한글 검색어가 인코딩 없이 섞인 실제 붙여넣기
# 주소(searchword=ai엔지니어)도 받는다. 실측(2026-07-30): 사람인 주소가 스킴이 없어
# 감지되지 않았고 일반 대화로 흘러 "열람할 수 없어요"가 나갔다.
_SCHEMELESS_URL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}/\S*$")
# 문장 **속에** 섞인 스킴 없는 주소("saramin.co.kr/… 공고분석해줘")는 **채용 사이트
# 도메인일 때만** 공고로 본다(D80) — 일반 도메인까지 받으면 언급만 한 링크("react.dev/learn
# 참고했어요")가 공고 자산을 덮고 분석을 무효화한다. 발화 전체가 주소 한 토큰이면 위
# 규칙(도메인 제한 없음)이 그대로 적용된다. 실측(2026-07-31): 사람인 주소 + "공고분석해줘"
# 가 한 문장이라 감지되지 않았고, 대화 에이전트가 "URL 을 못 연다"는 즉흥 답을 냈다.
JOB_SITE_HOSTS = ("saramin.co.kr", "jobkorea.co.kr", "wanted.co.kr", "programmers.co.kr",
                  "jumpit.co.kr", "incruit.com", "rocketpunch.com", "catch.co.kr")
_JOB_SITE_TOKEN_RE = re.compile(
    r"(?:^|\s)((?:www\.)?(?:" + "|".join(h.replace(".", r"\.") for h in JOB_SITE_HOSTS)
    + r")/\S+)")


# 한 발화에서 받아 주는 공고 URL 상한 — 라이브러리 상한(5)보다 작게, 한 턴의 수집·파싱 폭주 방지.
_MAX_URLS_PER_TURN = 3


def detect_posting_urls(message: str, session: dict) -> list[str]:
    """발화에 붙여넣은 공고 URL **전부**를 찾는다 — **결정론(LLM 없음).** (D94)

    URL 은 공고 전용(D62)이므로 주소만으로 공고 제출로 확정할 수 있다. 실측(2026-07-31
    16:01): 한 메시지에 URL 두 개("이 두개 공고 관심있어")를 보냈는데 첫 번째만 잡히고
    두 번째는 조용히 버려졌다 — 사용자가 준 자료는 전부 접수한다. 이미 세션의 공고와
    같은 주소는 뺀다(재등록으로 분석 자산을 무효화하지 않는다).
    """

    text = (message or "").strip()
    found = list(_URL_RE.findall(text))
    if not found and _SCHEMELESS_URL_RE.match(text):
        found = [f"https://{text}"]   # 수집기가 열 수 있게 스킴을 붙여 정규화한다
    found += [f"https://{m}" for m in _JOB_SITE_TOKEN_RE.findall(text)]   # 문장 속 채용 사이트(D80)

    posting = session.get("job_posting") or {}
    known = {posting.get("sourceUrl"), posting.get("value")}
    urls: list[str] = []
    for url in found:
        url = url.rstrip(".,;)]}>'\"")   # 문장 부호 꼬리 제거 ("…?Gno=123." 등)
        if url and url not in known and url not in urls:
            urls.append(url)
    return urls[:_MAX_URLS_PER_TURN]


def detect_posting_url(message: str, session: dict) -> str:
    """단수 규약 유지용 — 첫 공고 URL (없으면 빈 문자열)."""

    urls = detect_posting_urls(message, session)
    return urls[0] if urls else ""

# 이보다 짧은 글은 이력서 본문이라 보기 어렵다.
_RESUME_MIN_CHARS = 180


def detect_pasted_resume(message: str, session: dict) -> str:
    """발화에 섞여 붙여넣어진 이력서 원문을 찾는다 — **결정론(LLM 없음).**

    detect_posting_url(공고 URL)과 대칭인 인테이크다. 실측(2026-07-31): 한 메시지에
    공고 URL + 이력서 원문 + "적합도 분석해줘"가 함께 오면 URL 만 자산이 되고 이력서는
    "긴 대화"로 흘러 적합도 분석까지 못 갔다. URL 은 판정에서 빼고(공고 전용, D62) 남은
    본문을 신호 어휘 스코어(detect_kind)로 판정한다 — 확신 있을 때만 이력서로 승격한다.

    **메시지는 호출부가 비우지 않는다** — 요청 문장("적합도 분석해줘")은 플래너가 읽어야
    한다. 같은 원문이 이미 이력서 자산이면 빈 문자열(재등록으로 파생 자산을 무효화하지
    않는다 — detect_posting_url 과 같은 규약).
    """

    body = _URL_RE.sub(" ", (message or "")).strip()
    if len(body) < _RESUME_MIN_CHARS:
        return ""
    from jobis_ai.orchestrator.attachment_kind import detect_kind

    if detect_kind(body) != "resume":
        return ""
    if body == ((session.get("resume") or {}).get("value") or ""):
        return ""
    return body


# 턴당 에이전트 실행 상한 — 관찰(call)이 실행을 무한히 잇는 폭주 방지
# (Agent_Test 의 MAX_STEPS 가드와 같은 역할).
_MAX_AGENT_STEPS = 5


def _apply_attachments(request: ChatRequest, session: dict,
                       stage) -> tuple[list[str], list[str], list[dict], list[str]]:
    """첨부를 세션 사본에 반영하고 (확인 문구, 저장된 kind, 경고, 발화로 되돌린 텍스트) 를 돌려준다.

    프론트는 "직전에 요청한 자료"의 슬롯으로 다음 붙여넣기를 그대로 보내므로,
    공고를 기다리는 중에 이력서를 붙여넣으면 job_posting 으로 온다. 저장 전에
    내용을 보고(resolve_kind) 명백히 반대 종류면 바로잡는다.

    **짧은 텍스트는 저장된 이력서를 교체하지 못한다(D98).** 자료 요청 슬롯이 열려 있는 동안
    사용자가 "네" 같은 대답을 하면 그것이 `kind="resume"` 첨부로 도착한다 —
    `resolve_kind` 는 `MIN_ASSET_CHARS` 미만이면 판정을 포기하고 claimed 를 그대로 돌려주므로,
    저장 단계가 그걸 믿으면 한 줄이 이력서와 파생 자산(profile·analysis)을 통째로 지운다.
    그래서 여기서 되돌린다 — 첨부가 아니라 **발화로** 취급해 호출부가 메시지에 되돌려 놓는다
    (버리면 사용자가 방금 한 말이 사라져 플래너가 동의를 못 읽는다).

    가드를 입구가 아니라 **여기**에 두는 이유: 모든 입구(v2bridge 승격·첨부 저장·
    store_attachments)가 이 함수로 합류한다. 입구마다 길이 검사를 두면 다음 입구를 만드는
    사람이 그것을 다시 지켜야 하고, 실제로 그렇게 흩어져 있던 동안 틈이 열려 있었다.

    `resume_extra` 는 면제다 — 짧은 조각이 정상이고, 교체가 아니라 **덧붙이기**라 파괴가 없다.
    """

    acks: list[str] = []
    kinds: list[str] = []
    warnings: list[dict] = []
    demoted: list[str] = []
    for att in request.attachments:
        kind = att.kind
        url_coerced = False
        # URL 은 내용이 아니라 주소라 판정이 성립하지 않는다 — 종류는 규약으로 고정한다:
        # **URL 첨부는 공고 전용(D62).** 텍스트만 내용으로 검증한다.
        if att.sourceType.value == "url" and kind != "job_posting":
            url_coerced, kind = True, "job_posting"
            warnings.append({"code": "url_posting_only",
                             "message": f"URL 첨부는 공고 전용 — {att.kind} → job_posting 으로 저장"})
            trace.emit("attachment_kind", "URL 첨부를 공고로 고정(공고 전용 규약)", {
                "claimed": att.kind, "resolved": kind,
            })
        if kind in ("resume", "job_posting") and att.sourceType.value == "text":
            kind, kind_warnings = resolve_kind(kind, att.value)
            warnings.extend(kind_warnings)
            if kind != att.kind:
                trace.emit("attachment_kind", "첨부 종류를 내용으로 바로잡음", {
                    "claimed": att.kind, "resolved": kind, "chars": len(att.value),
                })
        payload = {"sourceType": att.sourceType.value, "value": att.value}
        if (kind == "resume" and att.sourceType.value == "text"
                and (session.get("resume") or {}).get("value")
                and len((att.value or "").strip()) < MIN_ASSET_CHARS):
            # 저장된 이력서가 있는데 종류를 판정할 수 없을 만큼 짧다 — 교체하지 않는다(D98).
            demoted.append((att.value or "").strip())
            warnings.append({
                "code": "short_resume_demoted",
                "message": (f"{len((att.value or '').strip())}자 텍스트는 이력서로 저장하지 않고 "
                            "발화로 처리했어요 — 저장된 이력서를 유지합니다."),
            })
            trace.emit("attachment_kind", "짧은 이력서 첨부를 발화로 되돌림(저장 이력서 보호)", {
                "claimed": att.kind, "chars": len((att.value or "").strip()),
                "threshold": MIN_ASSET_CHARS,
            })
            continue
        if kind == "resume":
            # 이력서가 갱신되면 이전 이력서로 만든 파생 자산은 무효다. 다만 **이전 이력서
            # 자체는 라이브러리로 회수한다**(D119) — 등록은 ensure_profile 이 하지만 그건
            # 소비자가 돈 턴에만 돌아서, 붙여넣고 대화만 한 뒤 다음 이력서가 오면 사라졌다.
            from jobis_ai.agents._common import preserve_active_resume

            stage({"resume": payload, "profile": None, "analysis": None,
                   "resume_library": preserve_active_resume(session)})
        elif kind == "resume_extra":
            # 추가 정보는 기존 이력서에 **덧붙인다** — 교체하면 몇 줄이 전체를 지운다.
            # 정보가 늘었으니 프로필·분석 파생 자산은 다시 만든다.
            existing = (session.get("resume") or {}).get("value", "")
            merged = (existing + "\n\n[추가 입력]\n" + att.value).strip()
            stage({
                "resume": {"sourceType": "text", "value": merged},
                "profile": None, "analysis": None,
            })
        else:
            # 새 공고가 오면 이전 공고의 파생 자산(분석·파싱 캐시)은 무효다 — 캐시를 남기면
            # 다음 분석 전까지 조회 질문이 **이전 공고의 사실**로 답한다(D79 캐시의 짝).
            stage({"job_posting": payload, "analysis": None, "posting_summary": None})
        acks.append(_ATTACHMENT_ACK_URL_COERCED if url_coerced
                    else _ATTACHMENT_ACK[kind] if kind == att.kind
                    else _ATTACHMENT_ACK_CORRECTED[kind])
        kinds.append(kind)
    return acks, kinds, warnings, demoted


def store_attachments(request: ChatRequest, session_id: str) -> list[str]:
    """write-back 루프 밖(관찰 UI 스텝퍼 등)에서 첨부만 즉시 저장할 때 쓰는 헬퍼.

    handle_chat 은 이걸 쓰지 않는다 — 턴 전체를 pending 으로 모아 한 번에 저장한다.
    """

    store = get_session_store()
    session = store.get(session_id)
    pending: dict[str, Any] = {}

    def _stage(updates: dict[str, Any]) -> None:
        pending.update(updates)
        session.update(updates)

    acks, _, _, _ = _apply_attachments(request, session, _stage)
    if pending:
        store.update(session_id, pending)
    return acks


def _visible_assets(session: dict) -> list[str]:
    """트레이스용 자산 목록 — _sessionId 같은 턴 내부 표식은 자산이 아니므로 뺀다."""

    return sorted(k for k in session if session.get(k) and not k.startswith("_"))


# 한 번에 동시 실행할 에이전트 상한. LLM 호출은 I/O 대기라 스레드로 충분하지만, 동시
# 호출은 곧 동시 과금·레이트리밋이므로 무한정 넓히지 않는다.
_MAX_PARALLEL = 3


def parallel_group(queue: list[str], dispatched: list[str], session: dict) -> list[str]:
    """큐 앞에서 **서로 독립이고 지금 실행 가능한** 연속 구간을 고른다(2개 이상일 때만 의미).

    독립의 기준은 capability manifest 가 이미 갖고 있다 — 앞 멤버가 만드는 자산(`produces`)을
    뒤 멤버가 전제로 쓰면 순서가 있는 것이므로 거기서 끊는다. 같은 자산을 둘이 만들어도
    끊는다(누가 이겼는지가 실행 순서에 좌우되면 결과가 흔들린다).

    실측 예: `posting_analysis`(공고) ∥ `resume_diagnosis`(이력서) ∥ `fit_analysis`(둘 다 이미
    보유) — 셋 다 지금 실행 가능하고 서로의 산출을 기다리지 않는다.
    """

    registry = get_agent_registry()
    assets = session_assets(session)
    group: list[str] = []
    produced: set[str] = set()
    for name in queue[:_MAX_PARALLEL]:
        spec = registry.get(name)
        if spec is None or name in dispatched or name in group:
            break
        if spec.internal:
            # 오케스트레이터가 끼운 단계(공고 수집 등)는 **단독으로** 돈다 — 세션 자산을
            # 그 자리에서 바꾸는 단계라(URL→원문 승격), 병렬 사본과 섞이면 뒤 멤버가
            # 승격 전 자산으로 따로 수집한다(이중 fetch).
            break
        if not runnable_now(spec, assets):
            break                                   # 앞 단계가 만들어 줘야 도는 것
        deps = set(spec.preconditions) | set(spec.preconditions_any)
        if deps & produced or set(spec.produces) & produced:
            break                                   # 의존하거나 같은 자산을 쓴다 → 순서가 있다
        group.append(name)
        produced |= set(spec.produces)
    return group


# 첨부 kind → 그 첨부가 채우는 세션 자산 (resume_extra 는 기존 이력서에 덧붙는다).
_KIND_TO_ASSET = {"resume": "resume", "resume_extra": "resume", "job_posting": "job_posting"}

# 이번 턴 제출 kind → 그 자료를 정리해 보여주는 에이전트 (D71).
_KIND_TO_REVIEWER = {"job_posting": "posting_analysis",
                     "resume": "resume_diagnosis", "resume_extra": "resume_diagnosis"}


def submission_review_inserts(queue: list[str] | tuple[str, ...],
                              stored_kinds: list[str]) -> list[str]:
    """판정(fit_analysis)이 예정된 큐에 끼울 정리 단계(D71) — 순수 함수.

    평가 하네스(planner_harness)도 이 함수를 그대로 쓴다 — 프로덕션과 하네스의 삽입
    기준이 갈리면 하네스가 프로덕션이 아닌 흐름을 재게 된다(dispatch_case docstring).
    """

    if "fit_analysis" not in queue:
        return []
    submitted_reviewers = {_KIND_TO_REVIEWER.get(k) for k in stored_kinds} - {None}
    return [name for name in ("posting_analysis", "resume_diagnosis")
            if name in submitted_reviewers and name not in queue]


# 이력서 확인 질문(D159)의 필드와 선택지 — **`resume` 를 쓰면 안 된다.** `/analyze` 는
# `field="resume"` 를 "자료가 없다"로 읽어 분석을 CAREER_DATA_REQUIRED 로 끝낸다
# (`v2bridge.service._ASSET_REQUEST_CODE`). 여기서는 자료가 **있는데** 어느 것을 쓸지 묻는
# 것이라 그 코드는 거짓말이 된다. 선택지를 함께 내는 이유는 `mapping.build_question` 이
# 선택지 없는 질문을 만들지 않아서다 — 없으면 왼쪽 패널 경로에서 질문이 사라진다.
# 아래 두 문자열은 **계약**이다: v2bridge 가 "다른 이력서" 선택을 알아보고 업로드를 청한다.
RESUME_CONFIRM_FIELD = "confirm_resume"
RESUME_CONFIRM_KEEP = "커리어 저장소 이력서로 분석해 주세요"
RESUME_CONFIRM_OTHER = "다른 이력서를 올릴게요"


def _ask_card(field: str, question: str, options: list[str]) -> dict:
    """게이트 질문 카드. 선택지가 없으면 `options` 칸을 만들지 않는다 — 빈 목록을 실으면
    소비자가 "선택지가 있는데 비었다"로 읽는다."""

    card = {"field": field, "question": question}
    return {**card, "options": list(options)} if options else card


def posting_fingerprint(session: dict) -> str:
    """활성 공고 원천의 지문. 원문이 아니라 **자산 값**으로 센다 — 파싱 전에도 값이 있어야
    하고(URL 이면 주소), 이력서 확인 게이트가 공고 도착 턴에 바로 물어야 하기 때문이다."""

    value = str((session.get("job_posting") or {}).get("value") or "")
    return hashlib.md5(value.encode("utf-8")).hexdigest() if value else ""


def resume_confirm_ask(dispatch: Dispatch, session: dict) -> str:
    """판정 전에 **어느 이력서로 볼지** 공고당 한 번 묻는 문구. 안 물으면 "" (D159).

    이 서비스의 이력서는 **대화 중에** 들어온다 — 커리어 저장소에 있는 것이 이 공고를 위해
    낸 것이라는 보장이 없다. 강행하면 사용자는 그 판정이 자기가 의도한 이력서의 것인 줄
    안다(`switch_active_resume` 가 지목 실패에서 이미 고른 방향, D126).

    **커리어 저장소 이력서일 때만 묻는다.** 판단 기준은 `resume_identity` 의 origin 이고
    새 표식을 심지 않는다: `career_summary`(저장소에서 실려 온 것)만 확인 대상이다.
    `pasted`·`uploaded` 는 사용자가 **이 대화에서 직접 준** 것이므로 되물으면 소음이다 —
    이번 턴 제출만 보는 것으로는 부족했다(직전 턴에 붙여넣은 이력서에도 물었다).

    그 밖에 묻지 않는 경우:
      · 판정이 예정되지 않았다(`agents` 도 `pending` 도 아니다).
      · 이력서가 아예 없다 — 그건 확인이 아니라 자료 요청이고, 담당이 자기 문구로 청한다.
      · 이 공고로 이미 물었다(`resumeAskedFor`) — 같은 질문을 매 턴 되풀이하지 않는다.
    """

    from jobis_ai.agents._common import resume_identity

    if "fit_analysis" not in dispatch.agents and "fit_analysis" not in dispatch.pending:
        return ""
    resume = session.get("resume")
    if not resume:
        return ""
    if resume_identity(resume)[0] != "career_summary":
        return ""
    key = posting_fingerprint(session)
    if not key or session.get("resumeAskedFor") == key:
        return ""

    labels = [str(r.get("_label") or "").strip()
              for r in (session.get("resume_library") or []) if r.get("_label")]
    # 문구는 **무엇을 쓸지 밝히고** 바꿀 길을 준다. 저장된 것이 여럿이면 이름을 보여준다 —
    # 어느 것으로 볼지는 사용자만 안다.
    if len(labels) > 1:
        return ("이 공고에 맞춰 분석할 이력서가 따로 있으신가요? 파일(md·docx)이나 내용을 "
                f"보내주시면 그걸로 볼게요. 없으면 커리어 저장소의 '{labels[0]}'(으)로 "
                f"분석할게요. 저장된 것 중에서 고르시려면 이름을 말씀해 주세요 — {', '.join(labels)}.")
    stored = f"커리어 저장소의 '{labels[0]}'" if labels else "커리어 저장소에 저장된 이력서"
    return ("이 공고에 맞춰 분석할 이력서가 따로 있으신가요? 파일(md·docx)이나 내용을 "
            f"보내주시면 그걸로 볼게요. 없으면 {stored}(으)로 분석할게요.")


def _submission_grounds_plan(agents: tuple[str, ...] | list[str],
                             submitted_kinds: list[str]) -> bool:
    """이번 턴 제출물이 계획 첫 에이전트의 전제를 채우는가 — 확신 문턱 면제의 근거.

    확신도는 **발화(언어)의 모호함**을 잰다. 그런데 첨부 제출은 말이 아니라 행동이라,
    말없이 공고만 붙여넣은 턴은 합성 발화 탓에 확신이 낮게 나온다(실측 2026-07-30:
    posting_analysis 원안 확신 0.55 → career_chat 강등, 사용자는 항목화를 기대했다).
    방금 낸 첨부를 소비하는 계획이라면 의도는 첨부가 이미 증명하므로 문턱을 면제한다.

    첫 에이전트만 본다 — 문턱이 막는 실패는 "턴을 통째로 엉뚱한 일에 쓰는 것"이고
    그 방향은 첫 에이전트가 정한다. 판단은 manifest(전제 선언)에서 파생한다(§2-2).
    """

    from jobis_ai.agents import get_agent_registry

    if not agents or not submitted_kinds:
        return False
    spec = get_agent_registry().get(agents[0])
    if spec is None:
        return False
    submitted = {_KIND_TO_ASSET.get(kind) for kind in submitted_kinds} - {None}
    return bool((set(spec.preconditions) | set(spec.preconditions_any)) & submitted)


def lead_text(changed_by: str, ack: str, note: str, steps: int, said: list[str]) -> str:
    """계획 설명(lead) 문장 선택 — compose_reply 의 규칙 그대로. 출처 기록(replySources)이
    같은 판단을 써야 해서 함수로 뽑았다(둘이 갈리면 출처가 거짓말을 한다)."""

    return {"rule": "", "validator": note}.get(
        changed_by, (ack or note) if (steps > 1 or not said) else "")


def compose_reply(acks: list[str], said: list[str], *, ack: str = "", note: str = "",
                  steps: int = 1, changed_by: str = "") -> str:
    """턴의 사용자향 문장을 조립하는 **유일한 자리.** 순서: 첨부 확인 → 계획 설명 → 한 말.

    전에는 이 결정이 호출부의 4중 불리언(`show_lead`)이었고, 같은 자리에서 실측 결함이 세 번
    났다. 원인은 조건이 부족해서가 아니라 화자가 넷(첨부·계획·에이전트·규칙)인데 문장을 하나만
    낸다는 사실이 어디에도 적혀 있지 않아서였다. 규칙은 하나다 — **계획 설명(lead)은 다른
    화자가 대신할 수 없을 때만 실린다.**

      · changed_by="rule"      실행 중 규칙이 계획을 바꿨다. 이유는 규칙이 이미 `said` 에
        말했으므로 계획 설명은 **침묵한다** — 그러지 않으면 하지 않은 일을 하겠다고 말한다
        (실측: 등급 하로 자소서를 미뤄 놓고 첫 문장이 "자기소개서 초안을 작성하겠습니다").
      · changed_by="validator" 검증기가 계획을 바꿨다 → 바뀐 이유(`note`)를 말한다. 플래너의
        `ack` 는 원안 설명이라 여기서 쓰면 사실과 어긋난다.
      · changed_by=""          계획대로 돌았다 → 알려 줄 순서가 있거나(`steps`>1) 아무도 말하지
        않았을 때만 `ack`. 하나가 스스로 말했으면 같은 말을 두 번 하는 셈이다.
    """

    lead = lead_text(changed_by, ack, note, steps, said)
    return " ".join(part for part in [*acks, lead, *said] if part).strip()


def _src(agent: str, channel: str, text: str) -> dict:
    """replySources 항목 하나 — 누가(agent) 어떤 경로(channel)로 이 문장을 말했나."""

    return {"agent": agent, "channel": channel, "text": text}


def handle_chat(request: ChatRequest) -> ChatResponse:
    """대화 한 턴을 처리한다. 턴 전체의 LLM 사용량(콜·토큰)을 집계해 한 줄로 남긴다.

    집계를 이 바깥 껍질에서 여는 이유: "이 턴이 몇 콜로 결론에 도달했고 토큰을 얼마나
    태웠나"가 지금까지 어디에도 없었다(평가 리포트 §1-2 "집계기가 없다"·§2-1 "토큰 실측 0").
    trace 는 턴 끝에 소멸하므로 요약을 **로그**에 남기고, 관찰 UI 용으로 trace 에도 사본을
    흘린다. 동의 게이트로 일찍 끝나는 턴도 플래너 콜은 썼으므로 finally 로 잡는다.
    """

    with llm_usage.collecting() as usage, trace.audit_session(request.sessionId):
        try:
            return _handle_chat_turn(request)
        finally:
            s = usage.summary()
            if s["calls"]:
                trace.emit("llm_usage", "턴 LLM 사용량", s)
                tokens = (f"{s['inputTokens']}→{s['outputTokens']}"
                          if s["inputTokens"] is not None else "미계측")
                if s["unmeteredCalls"] and s["inputTokens"] is not None:
                    tokens += f"(+미계측 {s['unmeteredCalls']}콜)"
                # 비용은 **잰 콜만** 더한 값이다 — 단가를 모르는 모델은 0 으로 지어내지 않고
                # `uncostedCalls` 로 따로 센다(토큰 미계측과 같은 규약).
                cost = (f" 비용 ${s['costUsd']:.4f}" if s["costUsd"] is not None else "")
                if cost and s["uncostedCalls"]:
                    cost += f"(+단가미상 {s['uncostedCalls']}콜)"
                log.info("[%s] llm: 콜 %d건(재시도 %d·실패 %d) 토큰 %s%s 노드=%s",
                         request.sessionId, s["calls"], s["retries"], s["failed"], tokens, cost,
                         ",".join(f"{n}×{c}" for n, c in s["byNode"].items()))


# 지속 사실 추출을 시작하지 않는 발화 — 합성 발화는 자료 제출이지 사용자의 말이 아니다.
_SYNTHETIC_UTTERANCE = "방금 드린 자료로 이어서 진행해 주세요."


def _start_user_facts(message: str, session: dict[str, Any]):
    """지속 사실 추출(D82)을 **별 스레드로 띄운다.** 안 돌릴 턴이면 None.

    입력이 발화 하나뿐이라 플래너·에이전트와 독립이므로 동시에 돌 수 있다. 스킵 조건은
    종전 그대로다(빈 발화 / 합성 발화) — **그 이상 좁히지 않는다**: 한국어는 주어를 생략해서
    "9월까지 취업하고 싶어" 처럼 1인칭 표지가 없는 진짜 사실이 흔하고, 어휘 화이트리스트로
    거르면 목록 밖 표현이 조용히 버려진다(§3-1 이 경고하는 규칙 추가 쪽이다).
    느린 이유가 '필요 없는 일'이 아니라 '줄을 잘못 선 일'이었으므로 순서만 바꾼다.

    **컨텍스트를 복사해 넘긴다**(`copy_context`). 새 스레드는 contextvars 를 물려받지 않으므로
    그대로 두면 `trace` 기록 싱크를 못 찾아 이 콜이 진행 스트림에서 사라지고,
    `llm_usage` 수집기도 못 찾아 턴 요약의 콜 수가 줄어든다(관측 손실).
    """

    import contextvars
    import threading

    text = (message or "").strip()
    if not text or text == _SYNTHETIC_UTTERANCE:
        return None

    existing = list(session.get("user_facts") or [])
    box: dict[str, Any] = {}
    ctx = contextvars.copy_context()

    def _run() -> None:
        try:
            box["result"] = ctx.run(extract_user_facts, text, existing)
        except Exception as exc:      # noqa: BLE001 — 사실 축적은 강화지 기능이 아니다
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True, name="user-facts")
    thread.start()
    return thread, box


def _collect_user_facts(job, session: dict[str, Any]):
    """띄워 둔 사실 추출을 거둔다 → (facts, warnings). 안 돌렸거나 실패면 (None, [])."""

    if job is None:
        return None, []
    thread, box = job
    thread.join(_USER_FACTS_TIMEOUT_SEC)
    if thread.is_alive():
        log.warning("[%s] user_facts: %.0f초 안에 끝나지 않아 이번 턴은 건너뜁니다",
                    session.get("_sessionId") or "", _USER_FACTS_TIMEOUT_SEC)
        return None, [{"code": "user_facts_timeout",
                       "message": "발화의 지속 사실 추출이 제한 시간을 넘겨 이번 턴은 건너뜁니다."}]
    if "error" in box:
        log.warning("[%s] user_facts 실패: %r", session.get("_sessionId") or "", box["error"])
        return None, []
    return box.get("result") or (None, [])


# 사실 추출을 기다리는 상한 — 답변이 끝났는데 이것 때문에 턴이 늘어지면 안 된다.
# 강화(enrichment)라 못 거두면 다음 턴에 같은 발화가 다시 오지 않을 뿐, 기능은 멀쩡하다.
_USER_FACTS_TIMEOUT_SEC = 20.0


def _handle_chat_turn(request: ChatRequest) -> ChatResponse:
    """턴 본체 — 플래너 → 검증기 → 실행 큐 → 관찰 규칙."""

    session_id = request.sessionId
    store = get_session_store()

    # 세션은 턴에 한 번 읽는다(작업 사본). 변경은 pending 에 쌓고 턴 끝에 한 번 저장한다.
    session = store.get(session_id)
    session["_sessionId"] = session_id
    pending: dict[str, Any] = {}
    # 에이전트 내부 캐시(ensure_profile)도 같은 pending 으로 들어오게 하는 통로.
    session["_stagedUpdates"] = pending

    def _stage(updates: dict[str, Any]) -> None:
        pending.update(updates)
        session.update(updates)

    def _finish(reply_text: str) -> None:
        """턴 종료 규약: user → assistant 순으로 이력 기록 후 **한 번에** 저장."""

        history = list(session.get("history") or [])
        for role, content in (("user", request.message), ("assistant", reply_text)):
            content = (content or "").strip()
            if content:
                history.append({"role": role, "content": content})
        pending["history"] = history[-HISTORY_MAX_ITEMS:]
        store.update(session_id, pending)

    acks, stored_kinds, attach_warnings, demoted_texts = _apply_attachments(
        request, session, _stage)

    # 발화에 붙여넣은 링크 — URL 은 공고 전용(D62)이므로 내용 판정 없이 결정론으로 공고
    # 자산에 올린다. 첨부와 같은 규약: 새 공고가 오면 이전 공고의 분석은 무효다.
    # 원문 수집(feat_url)은 여기서 하지 않는다 — 첫 소비자 도구(posting_analysis·
    # fit_analysis)가 ensure_posting_text 로 수집해 원문을 자산으로 승격한다. 플래너 전에
    # 수십 초 fetch 를 하면 계획도 없이 사용자를 기다리게 한다.
    learning_session = (request.message or "").lstrip().startswith("[JOBIS_LEARNING_SESSION]")

    if "job_posting" not in stored_kinds and not learning_session:
        posting_urls = detect_posting_urls(request.message, session)
        # **저장된 분석이 있을 때만** 채용사이트로 알아볼 수 있는 주소로 제한한다. 등록하면
        # 바로 아래 `_stage` 가 활성 공고를 바꾸고 `analysis` 를 무효화하는데, 대화 중에 붙인
        # 깃허브·포트폴리오·블로그 링크가 수십 초짜리 판정을 **말없이** 지우는 것은 D98(짧은
        # 텍스트가 저장 이력서를 못 지운다)이 이력서 쪽에서 막은 것과 같은 종류의 파괴다.
        #
        # 조건을 "공고 보유"가 아니라 **"분석 보유"** 로 좁힌 이유가 둘이다: ① 분석이 없으면
        # 교체는 되돌릴 수 있어(다음 링크가 다시 덮는다) 막을 것이 없고, ② 회사 자체 채용
        # 페이지(careers.*·*.im/career)는 화이트리스트에 없어서 넓게 걸면 **정상 공고를
        # 놓친다.** 화이트리스트는 판별 수단이지 공고의 정의가 아니다.
        #
        # 버리지 않고 발화에 남긴다 — URL 은 메시지 원문에 그대로 있으므로 플래너가 읽는다
        # (D98 이 되돌린 텍스트를 발화로 합친 것과 같은 규약).
        if session.get("analysis"):
            unknown = [u for u in posting_urls
                       if not any(host in u for host in JOB_SITE_HOSTS)]
            if unknown:
                posting_urls = [u for u in posting_urls if u not in unknown]
                attach_warnings.append({"code": "unknown_host_url_kept", "message": (
                    f"채용 사이트로 알아볼 수 없는 주소 {len(unknown)}개는 공고로 등록하지 "
                    "않았어요 — 저장된 적합도 분석을 유지합니다.")})
                acks.append(
                    "보내주신 링크는 채용 사이트로 알아보지 못해 공고로 등록하지 않았어요"
                    " (기존 분석 결과를 지우지 않으려고요). 공고가 맞다면 본문을 붙여넣어 주세요.")
                trace.emit("url_intake", "미확인 호스트 URL 을 공고 등록에서 제외(분석 보호)",
                           {"kept": posting_urls, "skipped": unknown})
                log.info("[%s] url_intake: 미확인 호스트 %s 제외(분석 보호)", session_id, unknown)
        if posting_urls:
            # 첫 URL 이 활성 공고(판정 대상), 나머지는 posting_analysis 가 같은 턴에 병렬
            # 수집·파싱해 라이브러리로 승격한다(D94) — 턴 마커라 세션에 저장되지 않는다.
            _stage({"job_posting": {"sourceType": "url", "value": posting_urls[0]},
                    "analysis": None, "posting_summary": None})
            if len(posting_urls) > 1:
                session["_extraPostingUrls"] = posting_urls[1:]
                acks.append(f"공고 링크 {len(posting_urls)}개를 받았어요.")
            else:
                acks.append(_ATTACHMENT_ACK_URL_POSTING)
            stored_kinds.append("job_posting")
            trace.emit("url_intake", "발화의 URL 을 공고 자산으로 등록",
                       {"urls": posting_urls})
            log.info("[%s] url_intake: 발화 URL %d개 → job_posting 등록 %s",
                     session_id, len(posting_urls), posting_urls)

    # 발화에 섞여 붙여넣어진 이력서 원문 — URL 인테이크와 대칭(결정론). 메시지는 그대로 둔다
    # (요청 문장은 플래너의 입력이다). 같은 규약: 새 이력서가 오면 이전 파생 자산은 무효다.
    if "resume" not in stored_kinds and not learning_session:
        resume_text = detect_pasted_resume(request.message, session)
        if resume_text:
            from jobis_ai.agents._common import preserve_active_resume

            _stage({"resume": {"sourceType": "text", "value": resume_text},
                    "profile": None, "analysis": None,
                    "resume_library": preserve_active_resume(session)})
            acks.append(_ATTACHMENT_ACK["resume"])
            stored_kinds.append("resume")
            trace.emit("resume_intake", "발화의 이력서 원문을 자산으로 등록",
                       {"chars": len(resume_text)})
            log.info("[%s] resume_intake: 발화 본문 → resume 등록 (%d자)",
                     session_id, len(resume_text))

    # 메시지 없이 첨부만 온 턴 — **멈추지 않는다.** 자료를 준 것 자체가 "이걸로 이어가 달라"는
    # 요청이므로, 발화를 합성해 플래너가 다음 단계를 고르게 한다. 첨부도 발화도 없으면
    # 플래너가 None 을 주고 대화형 에이전트가 턴을 받는다.
    # 자산으로 저장하지 않고 되돌린 첨부(D98)는 사용자가 방금 한 말이다 — 발화에 되돌려
    # 놓아야 플래너가 그 대답("네")을 읽는다. 버리면 동의가 사라진다.
    message = " ".join(t for t in [(request.message or "").strip(), *demoted_texts] if t).strip()
    if not message and acks:
        message = "방금 드린 자료로 이어서 진행해 주세요."

    request = request.model_copy(update={"message": message})

    # 발화 원문을 세션에 실어 대화형 에이전트(preference_intake 등)가 읽게 한다.
    _stage({"last_message": request.message})
    # 이번 턴에 무엇이 제출됐는지 — 플래너의 그라운딩 입력(자산이 아니라 사본에만 붙는 표식).
    # 이게 없으면 첨부만 온 턴의 합성 발화("자료로 이어서…")만 보고 플래너가 이력서 제출과
    # 공고 제출을 구분하지 못한다. 프론트의 kind 가 아니라 **바로잡힌 kind** 를 준다.
    session["_submittedThisTurn"] = stored_kinds

    # 지난 턴까지의 미완수 요청(D72) — 이번 턴에 새로 기억되는 것과 구분하기 위해 먼저 읽는다.
    prior_pending = dict(session.get("pendingRequest") or {})
    new_pending_staged = False
    # 저확신으로 실행하지 않은 플래너 추측(D124) — 턴 끝에 확인 버튼으로 복구 경로를 만든다.
    low_conf_guess: list[str] = []

    # 0) 지속 사실 추출을 **먼저 띄운다**(D144) — 입력이 발화 하나뿐이라 플래너·에이전트와
    #    독립이다. 전에는 턴 맨 끝에 순차로 돌아 6~9초가 답변 뒤에 그대로 붙었다(실측 08-03:
    #    28초 턴에서 6.6초). 결과를 거두고 세션에 반영하는 자리는 그대로 턴 끝이다 —
    #    **상태 전이는 오케스트레이터 독점**(§2-4)이고, 이 스레드는 값만 계산한다.
    facts_job = _start_user_facts(request.message, session)

    # 1) 플래너 — LLM 이 발화·상태를 보고 에이전트를 직접 고른다(자율 추론).
    plan, warnings = plan_agents(request.message, session)
    warnings = attach_warnings + warnings

    # requestedAgents 는 스키마상 agents 의 부분집합이지만 공급자가 이 불변식을 어기면,
    # 사용자가 직접 청한 작업이 턴 끝의 request_not_fulfilled 경고로만 남고 실행되지 않는다.
    # 요청 이름은 이미 AgentName 으로 검증된 닫힌 집합이므로 실행 계획에 복구한 뒤 기존
    # validate_plan 에 다시 맡긴다. 자산이 없으면 검증기가 제거하고 pendingRequest/M3가
    # 원래대로 처리하므로, 실행 가능성 검증을 우회하지 않는다.
    if plan is not None:
        missing_requested = [
            name for name in plan.requestedAgents if name not in plan.agents
        ]
        if missing_requested:
            plan = plan.model_copy(update={
                "agents": list(dict.fromkeys([*plan.agents, *missing_requested])),
            })
            warnings.append({
                "code": "planner_requested_agents_reconciled",
                "message": "직접 요청된 작업을 실행 계획에 복구함: "
                + ", ".join(missing_requested),
            })
            log.warning(
                "[%s] planner 불변식 복구 — requestedAgents 누락 %s → agents=%s",
                session_id,
                missing_requested,
                list(plan.agents),
            )

        # 서비스 채팅의 적합도 요청은 레거시 세션 판정을 실행하지 않는다. 공고 정리 뒤
        # v2bridge가 ANALYZE_POSTING 확인 계약을 만들고, 백엔드가 UNIFIED 분석을 시작한다.
        # V3 분석 자체가 이 오케스트레이터를 계산 엔진으로 재사용하는 경로는 LEGACY
        # 기본값이라 영향을 받지 않는다.
        if request.analysisOwner == "UNIFIED" and any(
            "fit_analysis" in names
            for names in (plan.agents, plan.requestedAgents, plan.blockedRequests)
        ):
            plan = plan.model_copy(update={
                "agents": list(dict.fromkeys(
                    "posting_analysis" if name == "fit_analysis" else name
                    for name in plan.agents
                )),
                "requestedAgents": list(dict.fromkeys(
                    "posting_analysis" if name == "fit_analysis" else name
                    for name in plan.requestedAgents
                )),
                "blockedRequests": list(dict.fromkeys(
                    "posting_analysis" if name == "fit_analysis" else name
                    for name in plan.blockedRequests
                )),
                "agentArgs": [
                    arg for arg in plan.agentArgs if arg.agent != "fit_analysis"
                ],
                "ack": "적합도 분석을 시작하기 전에 사용할 공고 기준을 확인할게요.",
            })
            warnings.append({
                "code": "unified_analysis_handoff",
                "message": "레거시 세션 판정 대신 UNIFIED 공고 분석 확인 단계로 연결했습니다.",
            })
            trace.emit("unified_analysis_handoff", "적합도 요청을 UNIFIED 분석으로 이관", {
                "agents": list(plan.agents),
            })
            log.info("[%s] unified_analysis_handoff: agents=%s", session_id, list(plan.agents))

    ack = safe_ack(plan)   # 플래너의 이해 확인 문장 — 검증 통과 시 결정론 note 대신 쓴다
    # LLM 이 정한 인자 — 선언된 이름만 통과시킨다(미선언 인자 환각 차단). 에이전트는
    # 세션의 `_agentArgs` 에서 자기 것만 꺼내 쓴다(없으면 기존대로 세션만 보고 동작).
    agent_args = validate_agent_args(plan.agentArgs) if plan is not None else {}
    if agent_args:
        session["_agentArgs"] = agent_args
    if plan is not None:
        trace.emit("planner", "플래너(LLM)가 에이전트를 선택", {
            "selectedAgents": list(plan.agents), "confidence": plan.confidence,
            "target": plan.target, "ack": plan.ack, "agentArgs": agent_args,
            "sessionAssets": _visible_assets(session),
        })
        log.info("[%s] planner: 원안=%s 확신=%.2f 인자=%s 자산=%s", session_id,
                 list(plan.agents), plan.confidence, agent_args or "-",
                 _visible_assets(session))
        # 청했지만 지금 못 하는 요청은 **기억한다**(D72) — 폐기하면 다음 턴 완수가 플래너
        # 재량이 된다. 사람이 채울 수 있는 자산(이력서·공고) 결측일 때만: 그 자료가 오는
        # 턴에 아래 재큐 블록이 결정론으로 이어서 완수한다.
        for name in plan.blockedRequests:
            missing = agent_feasibility(session).get(name)
            if missing in ("resume", "job_posting"):
                _stage({"pendingRequest": {"agent": name, "missing": missing, "turnsLeft": 3}})
                new_pending_staged = True
                trace.emit("pending_request", "실행 불가 요청을 기억", {
                    "agent": name, "missing": missing})
                log.info("[%s] pending_request: %s 기억(결측 %s)", session_id, name, missing)
                break
        # 로스터 밖 요청을 **세기만 한다**(D117) — 라우팅은 바꾸지 않는다. 여기서 흐름을
        # 갈래로 나누면 아직 근거가 없는 판단을 코드로 못 박게 된다. 무엇이 실제로 오는지
        # 첫 주 데이터를 보고 로스터 후보를 정하는 것이 순서다.
        unsupported = (plan.unsupportedRequest or "").strip()
        if unsupported:
            kept = [*(session.get("unsupported_requests") or []), unsupported]
            _stage({"unsupported_requests": kept[-UNSUPPORTED_MAX_ITEMS:]})
            warnings.append({"code": "unsupported_request",
                             "message": f"로스터로 처리할 수 없는 요청: {unsupported}"})
            trace.emit("unsupported_request", "로스터 밖 요청을 기록", {"request": unsupported})
            log.info("[%s] unsupported_request: %r", session_id, unsupported[:120])

        label = plan.agents[0] if plan.agents else "unclear"
        confidence = plan.confidence
        grounded = _submission_grounds_plan(plan.agents, stored_kinds)
        if grounded and plan.agents and plan.confidence < CONFIDENCE_THRESHOLD:
            log.info("[%s] 확신 %.2f < %.2f 이지만 이번 턴 제출물(%s)이 계획을 뒷받침 — 면제",
                     session_id, plan.confidence, CONFIDENCE_THRESHOLD, stored_kinds)
        if not plan.agents or (plan.confidence < CONFIDENCE_THRESHOLD and not grounded):
            # 무엇을 원하는지 확신이 낮으면 대화로 받는다 — 기능 목록만 읽어주고 끝내지 않는다.
            # 단 **버리되 잃지 않는다**(D124): 전에는 저확신 계획이 조용히 폐기돼 사용자가
            # 다시 말해야 했고 흔적도 0이었다. 추측한 계획을 확인 버튼 + pendingConsent 로
            # 남긴다 — 다음 턴의 동의 한마디("응")면 플래너 규칙 2(동의 잇기)와 동의 게이트
            # 통과 조건 ②가 그대로 이어받는다. 문턱 숫자는 안 내렸다: 현 baseline(08-01,
            # 52케이스×3회) 케이스별 최저 확신이 0.793 이라 0.6 은 평가셋에서 아무것도 자르지
            # 않는다 — 내릴 근거가 없고, 실사용의 저확신 구간은 여기서 세는 것이 먼저다.
            dispatch = Dispatch((FALLBACK_AGENT,))
            low_conf_guess = [n for n in plan.agents if n != FALLBACK_AGENT]
        else:
            # 2) 검증기(순수 코드) — 전제 자산 확인·생산자 삽입·실행 불가 제거.
            dispatch = validate_plan(plan.agents, session, plan.requestedAgents)
    else:
        # 플래너 불가(LLM 미설정·실패) — 대응표로 흐름을 대신 정하지 않는다. 대화형 에이전트가
        # 턴을 받아 사용자의 말에 답하고 필요한 자료를 요청한다.
        trace.emit("fallback", "플래너 불가 → 대화형 에이전트가 턴을 받음", {"agent": FALLBACK_AGENT})
        label, confidence = FALLBACK_AGENT, 0.0
        dispatch = Dispatch((FALLBACK_AGENT,))

    # 이력서 확인 게이트(D159) — 판정 전에 **어느 이력서로 볼지** 공고당 한 번 묻는다.
    # 동의 게이트보다 **먼저** 본다: 둘 다 걸릴 상황이면 이 질문이 더 구체적이고, 답이
    # 동의까지 겸한다("따로 없어요" = 진행해도 좋다). 두 질문을 겹쳐 묻지 않는다.
    #
    # 아래 동의 게이트와 **같은 배관**을 탄다(D158): 물어본 이름을 `pending` 에 실어 두면
    # 방금 낸 자료의 정리는 실행되고, 질문은 그 뒤에 붙고, `pendingConsent` 로 다음 턴에
    # 통과권이 생긴다. 새 흐름을 만들지 않고 있는 것을 쓴다.
    # 질문 카드 — 단순 동의는 버튼(`confirm_pipeline`), 이력서 확인은 선택지가 붙은
    # `confirm_resume` 다(위 상수 주석: `resume` 를 쓰면 /analyze 가 자료 결측으로 끝낸다).
    ask_field, ask_options = "confirm_pipeline", []
    confirm_resume = resume_confirm_ask(dispatch, session)
    if confirm_resume:
        ask_field = RESUME_CONFIRM_FIELD
        ask_options = [RESUME_CONFIRM_KEEP, RESUME_CONFIRM_OTHER]
        deferred = tuple(dict.fromkeys((*dispatch.pending, "fit_analysis")))
        dispatch = Dispatch((), ask=confirm_resume, pending=deferred)
        _stage({"resumeAskedFor": posting_fingerprint(session)})
        trace.emit("resume_confirm_gate", "판정 전 이력서 확인 — 공고당 1회", {
            "ask": confirm_resume, "deferred": list(deferred),
        })
        log.info("[%s] resume_confirm_gate: 판정 보류하고 이력서 확인 (대기=%s)",
                 session_id, list(deferred))

    # 동의 게이트 — 사용자가 청하지 않은 무거운 작업은 실행하지 않고 먼저 묻는다.
    # 물어본 이름을 세션에 적어 둔다 — 다음 턴 계획에 다시 들어오면 그것이 동의다(router).
    # **묻는 동안에도 방금 낸 자료의 정리는 보여준다(D158).** 전에는 게이트가 걸리면 턴이
    # 통째로 질문 하나로 끝났다 — 공고를 붙였는데 판정이 게이트에 걸리면 **공고 정리까지
    # 삼켜져서** 사용자는 자료를 냈는데 아무 정리 없이 질문만 받았다. 게이트의 목적은 무거운
    # 것을 말없이 시작하지 않는 것이지(§2-7), 가벼운 담당의 입을 막는 것이 아니다.
    #
    # 무엇을 실행할지는 **이번 턴 제출물**이 정한다 — D71 의 정리 단계(공고 분석·이력서 진단)
    # 그대로다. 계획의 나머지(자소서 등)는 미루는 것의 산출을 기대하므로 함께 미룬다.
    # `dispatch.pending` 을 넘긴다: `submission_review_inserts` 는 판정이 예정된 큐에서만
    # 삽입하고, 그 판정은 지금 pending 에 들어 있다.
    if dispatch.ask:
        review = submission_review_inserts(dispatch.pending, stored_kinds)
        if review:
            dispatch = Dispatch(tuple(review), ask=dispatch.ask, pending=dispatch.pending)
    if dispatch.ask and not dispatch.agents:
        trace.emit("consent_gate", "청하지 않은 무거운 작업 — 실행 전 동의 요청", {
            "ask": dispatch.ask, "plannedAgents": list(plan.agents) if plan else [],
            "pendingConsent": list(dispatch.pending),
        })
        _stage({"pendingConsent": list(dispatch.pending)})
        final_reply = compose_reply(acks, [dispatch.ask])
        _finish(final_reply)
        return ChatResponse(
            sessionId=session_id, reply=final_reply, intent=label,
            confidence=confidence, dispatched=[], results={},
            followUpQuestions=[_ask_card(ask_field, dispatch.ask, ask_options)],
            warnings=warnings,
            replySources=[_src("orchestrator", "attachment_ack", a) for a in acks]
                         + [_src("orchestrator", "consent_gate", dispatch.ask)],
        )

    # 가시화 라벨은 **실제 실행 시퀀스**의 첫 에이전트 — 검증기가 생산자를 삽입/강등하면
    # 플래너 원안과 달라지므로, 프론트에 나가는 intent 는 dispatched 와 맞춘다 (§4 결함 수정).
    if dispatch.agents:
        label = dispatch.agents[0]

    # 게이트를 통과했으므로 대기 중인 동의는 소진됐다 — 남겨 두면 다음 턴에도 통과권이 된다.
    # **아직 묻고 있는 중이면 비우지 않는다**(D158: 부분 실행 턴) — 이 턴에 가벼운 담당만
    # 돌았고 무거운 것은 여전히 대기다. 여기서 비우면 아래에서 다시 심어야 한다.
    if session.get("pendingConsent") and not dispatch.ask:
        # **동의한 에이전트가 실제로 실행될 때만 소진한다.** 플래너가 동의 응답 턴에 빈
        # 플랜을 내면 폴백(대화)이 도는데, 그때도 소진하면 동의가 증발해 사용자가 같은
        # 질문을 다시 받는다(실측 2026-08-07 12:13: granted=[fit_analysis],
        # agents=[career_chat] — 분석은 안 돌고 통과권만 사라졌다).
        granted = [n for n in (session.get("pendingConsent") or [])
                   if n in dispatch.agents]
        if granted:
            # 승인은 감사 대상이다 — 물은 것만 남기고 **승인을 안 남기면** "몇 번 물어 몇 번
            # 진행됐나"의 분모만 있고 분자가 없다(위임 거부에서 겪은 것과 같은 실수).
            trace.emit("consent_granted", "동의 소진 — 무거운 작업 실행", {
                "granted": granted,
                "agents": list(dispatch.agents),
            })
            _stage({"pendingConsent": []})

    # 검증기가 계획을 바꿨는지 — 아래 로그와 계획 설명 문장이 함께 쓴다.
    plan_changed = plan is not None and tuple(plan.agents) != tuple(dispatch.agents)

    trace.emit("dispatch", "검증기 확정 실행 시퀀스", {
        "agents": list(dispatch.agents), "note": dispatch.note,
        "planChanged": plan_changed,
    })
    # 플래너 원안과 다르면 그 사실을 남긴다 — 다중 에이전트 순서가 LLM 판단인지
    # 검증기의 생산자 자동 삽입인지 로그만 보고 구분할 수 있게(둘은 성격이 다르다).
    log.info("[%s] dispatch: 확정=%s%s%s", session_id, list(dispatch.agents),
             " (플래너 원안과 다름 — 생산자 삽입/제외)" if plan_changed else "",
             f" ask={dispatch.ask[:40]!r}" if dispatch.ask else "")

    # 4) 에이전트 실행 — 레지스트리에 있는 것만, 순서대로. 결과는 그대로 전달.
    # 대화형 에이전트 단독 실행이면 ack 를 생략한다 — 에이전트의 말이 이미 대화라
    # "이해했다" 문장이 겹치면 상담원 멘트 두 번 듣는 느낌이 된다.
    registry = get_agent_registry()
    # 계획 설명을 누가 하는지는 compose_reply 가 정한다 — 여기서는 "무엇이 계획을 바꿨나"만
    # 넘긴다("" 없음 / "validator" 검증기 / "rule" 실행 중 규칙).
    changed_by = "validator" if plan_changed else ""
    replies: list[str] = []
    # replies 와 나란히 쌓는 화자 기록 — reply 문장 하나에 출처 하나(오라우팅 디버깅용).
    said_sources: list[dict] = []
    dispatched: list[str] = []
    results: dict[str, dict] = {}
    follow_up: list[dict] = []

    # 실행 큐 — 관찰(call)이 다음 실행을 끼워 넣을 수 있어 튜플 대신 큐로 돈다.
    queue: list[str] = list(dispatch.agents)

    # **이번 턴의 계획을 에이전트에게 알린다**(자산이 아니라 사본에만 붙는 표식 —
    # `_submittedThisTurn` 과 같은 규약). 자기 루프 에이전트는 자기가 턴을 독점한다고
    # 가정하고 답하는데, 계획에 여러 담당이 있으면 그 가정이 사용자 눈에 모순으로 나온다:
    # 실측(2026-08-01) — 사용자가 적합도를 청한 턴에 `resume_diagnosis`(정리 단계, D71)가
    # "적합도는 제가 못 해요"라고 선언한 **직후** `fit_analysis` 가 등급을 냈다.
    # 계획을 모르면 프롬프트로는 못 고친다 — 없는 사실을 지시로 메울 수 없기 때문이다.
    session["_planThisTurn"] = list(queue)

    # URL 공고가 미수집 상태면 수집 도구를 **결정론으로** 맨 앞에 끼운다(D64). 플래너의
    # 판단이 아니다 — 자산 상태에서 따라 나오는 필연적 단계라서, manifest 에 없는
    # internal 도구를 오케스트레이터가 직접 배치한다(플래너 어휘 불변 → 재측정 불필요).
    # 성공하면 원문이 자산으로 굳고, 실패하면 관찰 규칙이 공고 소비 단계를 걷어낸다.
    if (not learning_session
            and (session.get("job_posting") or {}).get("sourceType") == "url"
            and "posting_fetch" not in queue):
        queue.insert(0, "posting_fetch")
        trace.emit("dispatch", "URL 공고 미수집 — 수집 도구를 큐 맨 앞에 삽입", {
            "inserted": "posting_fetch", "queue": list(queue),
        })
        log.info("[%s] dispatch: posting_fetch 삽입(URL 공고 미수집) 큐=%s",
                 session_id, list(queue))

    # 지난 턴의 미완수 요청(D72) — 자산이 채워졌으면 결정론으로 이어서 완수한다. 이미 청한
    # 일이므로 동의 게이트 대상이 아니다. 아직 못 채웠으면 수명(turnsLeft)을 줄이고 다 되면
    # 잊는다 — 오래된 요청이 엉뚱한 턴에 무거운 작업을 말없이 되살리지 않게.
    if prior_pending.get("agent"):
        pending_name = str(prior_pending["agent"])
        pending_spec = registry.get(pending_name)
        if pending_name in queue or pending_spec is None:
            if not new_pending_staged:
                _stage({"pendingRequest": None})    # 플래너가 스스로 흐름을 이었다
        elif runnable_now(pending_spec, session_assets(session)):
            queue.append(pending_name)
            notice = f"지난번에 요청하신 {agent_label(pending_name)}도 이어서 진행할게요."
            replies.append(notice)
            said_sources.append(_src("orchestrator", "notice", notice))
            if not new_pending_staged:
                _stage({"pendingRequest": None})
            trace.emit("dispatch", "미완수 요청 재큐(자료 충족)", {
                "inserted": pending_name, "queue": list(queue)})
            log.info("[%s] dispatch: 미완수 요청 %s 재큐 큐=%s",
                     session_id, pending_name, list(queue))
        elif not new_pending_staged:
            turns = int(prior_pending.get("turnsLeft") or 1) - 1
            _stage({"pendingRequest":
                    {**prior_pending, "turnsLeft": turns} if turns > 0 else None})

    # 판정이 예정된 턴에 자료가 **방금 제출**됐으면 그 자료의 정리 단계를 판정 앞에 끼운다
    # (D71) — 사용자는 판정만이 아니라 "무엇을 읽고 판정했는지"를 본다(접수 → 공고 분석 →
    # 이력서 진단 → 적합도). 플래너 판단이 아니라 제출 사실에서 따라 나오는 표시 단계라
    # 결정론으로 끼운다(D64 posting_fetch 와 같은 원리 — manifest 불변, 재측정 불필요).
    # 셋은 서로 독립이라 parallel_group 이 같은 배치로 돌려 지연이 거의 늘지 않는다.
    # 이미 세션에 있던 자산(지난 턴에 정리를 보여준 것)은 다시 정리하지 않는다.
    inserts = submission_review_inserts(queue, stored_kinds)
    if inserts:
        fit_at = queue.index("fit_analysis")
        queue[fit_at:fit_at] = inserts
        trace.emit("dispatch", "제출 자료 정리 단계를 판정 앞에 삽입", {
            "inserted": inserts, "queue": list(queue),
        })
        log.info("[%s] dispatch: 정리 단계 삽입 %s (이번 턴 제출 %s) 큐=%s",
                 session_id, inserts, stored_kinds, list(queue))

    steps = 0
    # 실패 대체 예산 — 턴당 1회. `_MAX_AGENT_STEPS` 와 별개로 두는 이유는 막는 것이 다르기
    # 때문이다: 스텝 상한은 계획이 긴 턴을, 이 예산은 **실패가 실패를 부르는 연쇄**를 막는다.
    replacement_used = False

    def _execute(name: str, spec, sess: dict):
        """에이전트 하나 실행 + 도구면 표현 계층까지. 병렬 워커도 이걸 부른다."""

        trace.emit("agent_start", f"{name} 실행 시작", {
            "agent": name, "description": spec.description,
            "preconditions": list(spec.preconditions),
            "sessionAssets": _visible_assets(sess),
        })
        try:
            outcome = spec.entry(sess)
            # 도구는 말하지 않는다 — 데이터만 내고, 사용자향 문장은 표현 계층(spec.render)이 만든다.
            # 그래서 문구를 고칠 때 계산 코드를 건드리지 않는다(AgentSpec docstring 의 tool/agent 구분).
            # 표현 계층도 LLM 을 쓸 수 있으므로 경고를 함께 받는다(폴백 이유를 삼키지 않는다).
            if spec.kind == "tool" and spec.render is not None:
                outcome.reply, render_warnings = spec.render(outcome.data, sess)
                outcome.warnings.extend(render_warnings)
        except Exception as exc:  # noqa: BLE001 — 멤버 하나의 결함이 턴 전체를 죽이면 안 된다 (D122)
            # 격리하되 삼키지 않는다(§2-6): 경고 코드 + ERROR 스택 + 사용자향 한 문장.
            # 크래시한 멤버의 산출 자산은 안 생기므로 그것에 기대는 후속 단계는 관찰 규칙
            # (observe_rules.drop_unrunnable)이 정리하고, 청한 기능이 안 돌았으면
            # request_not_fulfilled 가 턴 끝에 한 번 더 센다 — 격리가 은폐가 되지 않는다.
            log.exception("[%s] agent: %s 실행 중 예외 — 이 단계만 건너뛴다", session_id, name)
            trace.emit("agent_crashed", f"{name} 실행 중 예외 — 단계 건너뜀", {
                "agent": name, "error": f"{type(exc).__name__}: {exc}",
            })
            return AgentResult(
                reply=f"{agent_label(name)} 실행 중 문제가 생겨 이 단계는 건너뛰었어요.",
                warnings=[{"code": "agent_crashed",
                           "message": f"{name}: {type(exc).__name__}: {exc}"}],
            )
        return outcome

    def _absorb(name: str, outcome) -> None:
        """실행 결과를 턴에 반영한다. **큐 순서대로** 부른다 — 병렬로 돌아도 결과 순서는 계획 순서다."""

        dispatched.append(name)
        results[name] = outcome.data
        warnings.extend(outcome.warnings)
        follow_up.extend(outcome.followUpQuestions)
        trace.emit("agent_end", f"{name} 실행 종료", {
            "agent": name, "reply": outcome.reply, "data": outcome.data,
            "warnings": outcome.warnings,
            "followUpQuestions": outcome.followUpQuestions,
            "sessionUpdates": sorted(outcome.sessionUpdates.keys()),
        })
        log.info("[%s] agent: %s 완료 질문=%s 갱신=%s", session_id, name,
                 [q.get("field") for q in outcome.followUpQuestions],
                 sorted(outcome.sessionUpdates.keys()))
        if outcome.sessionUpdates:
            _stage(outcome.sessionUpdates)
        if outcome.reply:
            replies.append(outcome.reply)
            # 도구는 말하지 않으므로(§2-3) 도구의 reply 는 표현 계층(render)이 만든 문장이다.
            kind = registry[name].kind if registry.get(name) else "agent"
            said_sources.append(_src(
                name, "tool_render" if kind == "tool" else "agent_llm", outcome.reply))

    def _run_parallel(group: list[str]) -> dict[str, Any]:
        """서로 독립인 에이전트들을 동시에 돌린다.

        **이득 실측 (2026-07-29 재측정, claude_code/sonnet, 독립 3개 = posting_analysis ∥
        resume_diagnosis ∥ fit_analysis)**: 순차 47.8 · 48.0초 vs 병렬 13.3 · 37.6초.
        순차는 안정적이고 병렬은 캐시 상태에 따라 갈리므로 **최소 10초, 최대 35초** 단축이다.
        세션 사본·contextvars 복사·토큰 뮤트·큐순서 병합이라는 복잡도를 지고 가는 근거가
        이 수치다 — 숫자가 없으면 지우는 것이 맞다(그래서 여기 박아 둔다).
        재현: `_MAX_PARALLEL` 을 1 과 3 으로 바꿔 같은 턴을 번갈아 두 번씩 돌린다.

        규율 둘:
        - 각 에이전트는 **세션 사본**을 받는다. 상태 변경(sessionUpdates·내부 캐시)은 끝난 뒤
          큐 순서대로 합친다 — 병렬이 결과나 상태 순서를 흔들면 안 된다.
        - 토큰 델타는 끈다. 프론트는 델타를 한 버퍼에 이어 붙이므로(ask.html `streamed +=`)
          두 에이전트의 토큰이 동시에 흐르면 섞인 글이 보인다. 진행 이벤트는 그대로 흘린다.

        프로필을 미리 만들어 두는 최적화는 **넣었다가 뺐다.** 여러 멤버가 각자 프로필을 지으면
        같은 LLM 추출을 두 번 하니 미리 한 번 만들자는 것이었는데, 실측(2026-07-29)에서 그
        선빌드가 임계 경로에 **8.3초**를 얹었다. 전제에 resume 이 있다고 프로필을 쓰는 것이
        아니기 때문이다 — fit_analysis 는 그래프 안에서 따로 짓는다. 실제 중복은 프로필을 쓰는
        에이전트 둘이 같은 구간에 들어올 때만 생기고, 그때도 두 호출이 **동시에** 나가므로
        늘어나는 것은 비용이지 시간이 아니다. 확실한 손해로 드문 손해를 막지 않는다.
        """

        trace.emit("parallel", f"{len(group)}개 에이전트 동시 실행", {
            "agents": list(group), "labels": [agent_label(n) for n in group],
            "reason": "서로의 산출을 기다리지 않는 구간",
        })
        log.info("[%s] parallel: %s 동시 실행", session_id, list(group))

        copies: dict[str, dict] = {}
        futures = {}
        started_at = time.perf_counter()
        with trace.muted_tokens(), ThreadPoolExecutor(max_workers=len(group)) as pool:
            for name in group:
                sess = dict(session)
                sess["_stagedUpdates"] = {}      # 사본의 캐시는 사본에만 쌓인다
                copies[name] = sess
                # 워커 스레드는 부모 컨텍스트를 물려받지 않는다 — 복사해서 넘기지 않으면
                # trace 레코더가 안 보여 진행 이벤트가 통째로 사라진다.
                ctx = contextvars.copy_context()
                futures[name] = pool.submit(ctx.run, _execute, name, registry[name], sess)
            outcomes = {name: future.result() for name, future in futures.items()}
        # 병렬의 이득을 수치로 남긴다(확장 계획 P3-4) — "몇 초 벽시계 vs 멤버 합산 몇 초"가
        # 이 복잡도를 지고 가는 근거다. 합산은 로그로 추정 불가하므로 벽시계만 정확값이다.
        log.info("[%s] parallel: %s 완료 — 벽시계 %.1f초 (동시 %d개)",
                 session_id, list(group), time.perf_counter() - started_at, len(group))

        for name in group:      # 사본에 쌓인 캐시(ensure_profile 등)를 큐 순서대로 반영
            staged = copies[name].get("_stagedUpdates") or {}
            if staged:
                _stage(staged)
        return outcomes

    while queue and steps < _MAX_AGENT_STEPS:
        if queue[0] in dispatched:      # 같은 턴에 같은 에이전트 재실행 금지 (루프 방어)
            queue.pop(0)
            continue
        if registry.get(queue[0]) is None:
            name = queue.pop(0)
            replies.append(
                f"'{name}' 기능은 아직 준비 중이에요. 다른 기능(적합도 분석·공고 추천·이력서 진단·면접 준비)을 이용해 주세요."
            )
            said_sources.append(_src("orchestrator", "notice", replies[-1]))
            warnings.append({"code": "agent_not_implemented",
                             "message": f"orchestrator: 미구현 에이전트 dispatch — {name}"})
            break

        # 서로 독립인 구간은 동시에 돈다. 순차로 돌 이유가 "코드가 그렇게 생겨서"뿐이면
        # 사용자는 이유 없이 기다린다.
        group = parallel_group(queue, dispatched, session)
        if len(group) > 1 and steps + len(group) <= _MAX_AGENT_STEPS:
            outcomes = _run_parallel(group)
            for name in group:
                _absorb(name, outcomes[name])
            del queue[:len(group)]
            steps += len(group)
            batch, batch_outcomes = list(group), [outcomes[n] for n in group]
        else:
            name = queue.pop(0)
            steps += 1
            outcome = _execute(name, registry[name], session)
            _absorb(name, outcome)
            batch, batch_outcomes = [name], [outcome]

        last = batch[-1]

        # 5) 관찰 → 재선택 — 방금 결과를 보고 남은 계획을 다시 정한다. **결정론(LLM 없음).**
        #
        # 전에는 여기서 경량 LLM(planner.observe_after)이 실행 결과 **요약**을 보고
        # continue/finish/call 을 냈다. 그 층을 걷어낸 이유는 observe_rules 모듈 docstring 에
        # 있다 — 요약해서 말하면: 관찰 LLM 은 플래너보다 정보가 적고(발화·자산·이력은 플래너가
        # 이미 봤다), 추가로 가진 실행 결과에서 제어에 쓸 신호는 전부 열거 가능한 구조화 값이며,
        # 실측에서 call 0건·finish 는 전부 규칙 커버 범위였고, **자기 자리의 위험조차 못 막았다**
        # (판정이 실패해 analysis 가 없는데 자소서가 그대로 돌던 결함 — drop_unrunnable 참고).
        #
        # 프로토타입도 같은 분할을 했다: 툴 선택은 LLM, level 분기는 조건엣지(decisions D11).
        # 이 자리는 그 조건엣지에 해당한다. LLM 이 도구를 골라 스스로 도는 ReAct 는 한 층 아래
        # (agents/agent_loop.py)에 있고, 그쪽이 본체의 에이전트다움을 지는 곳이다.
        obs = observe_rules.observe(batch, dict(zip(batch, batch_outcomes)),
                                    queue, dispatched, session)
        queue = list(obs.queue)
        trace.emit("observe", f"관찰 후 재선택: {obs.action}", {
            "afterAgent": last, "action": obs.action, "rule": obs.rule,
            "reason": obs.reason, "remainingPlanned": list(queue),
        })
        log.info("[%s] observe: %s after=%s 규칙=%s 남은예정=%s 이유=%s", session_id,
                 obs.action, last, obs.rule, list(queue), obs.reason[:80])
        if obs.note:
            # 규칙이 계획을 바꿨으면 이유를 말한다. 이유를 말한 화자가 있으므로 계획 설명은
            # compose_reply 에서 침묵한다 — 하지 않은 일을 하겠다고 말하게 되므로.
            replies.append(obs.note)
            said_sources.append(_src("orchestrator", "rule_note", obs.note))
            changed_by = "rule"

        # 5-b) 빠진 자리에 **대체 단계**를 한 번 물어본다 (턴당 1회).
        #
        # 규칙은 "뺐다"까지만 한다. "대신 무엇을 할까"는 빠진 단계 × 남은 자산의 조합이라
        # 규칙표로 열거할 수 없다 — 위 5)가 LLM 을 걷어낸 근거("신호가 전부 열거 가능한
        # 구조화 값")가 **여기에는 성립하지 않는** 유일한 자리다. 그래서 이 한 자리만 연다.
        #
        # 자율은 고르기까지다: 후보는 코드가 만들고(등록·실행가능·heavy 아님), 고른 뒤에도
        # 다시 검증한다(`planner.replacement_for`). 예산 1회는 실패가 실패를 부르는 폭주 방어다.
        if obs.dropped and not replacement_used:
            replacement_used = True
            picked, why, replace_warnings = replacement_for(
                obs.dropped, session, exclude=set(dispatched) | set(queue),
            )
            warnings.extend(replace_warnings)
            if picked:
                queue.append(picked)
                trace.emit("replan", f"실패 대체: {' · '.join(obs.dropped)} → {picked}", {
                    "trigger": "failure", "dropped": list(obs.dropped),
                    "replacement": picked, "reason": why,
                })
                log.info("[%s] replan(failure): %s → %s (%s)", session_id,
                         list(obs.dropped), picked, why[:80])

        # 대체를 끼웠으면 큐가 다시 찼다 — obs.action 이 아니라 **큐**를 보고 끝낸다.
        if obs.action == "finish" and not queue:
            break

    # 요청 완수 검증(M3) — 사용자가 직접 청한 에이전트가 실행되지도(dispatched),
    # 기억되지도(pendingRequest) 않았으면 조용히 지나가지 않는다(§2-6). 어느 층도
    # "청한 것이 답에 담겼나"를 보지 않던 구멍의 마지막 그물 — 경고는 로그·평가가 세는
    # 신호이지 답변 차단이 아니다(이미 나간 문장은 관찰 규칙의 note 가 설명했다).
    if plan is not None:
        remembered = str((session.get("pendingRequest") or {}).get("agent") or "")
        consented_plan = set(session.get("pendingConsent") or ())
        if dispatch.ask:
            # 부분 실행 턴은 아래 응답 조립 직전에 pendingConsent를 저장한다. M3 검사는
            # 그보다 먼저 실행되므로, 이번 턴에 이미 보존하기로 확정한 계획도 기억된 요청이다.
            consented_plan.update(dispatch.pending)
        for name in plan.requestedAgents:
            if name not in dispatched and name != remembered and name not in consented_plan:
                warnings.append({"code": "request_not_fulfilled",
                                 "message": f"청한 에이전트가 실행·기억 어느 쪽도 되지 않음: {name}"})
                log.warning("[%s] 요청 미완수 — %s (dispatched=%s)", session_id, name, dispatched)

    # 발화의 지속 사실(목표·제약·상황)을 세션에 누적한다(D82) — 다음 턴의 그라운딩.
    # 위에서 띄운 계산을 여기서 거둔다(D144): 에이전트가 도는 동안 이미 끝나 있으면 대기 0.
    facts, fact_warnings = _collect_user_facts(facts_job, session)
    warnings.extend(fact_warnings)      # 못 거둔 이유도 올린다 — 경고를 조건 안에 두면 삼킨다
    if facts is not None and facts != [
            str(f).strip() for f in (session.get("user_facts") or [])]:
        _stage({"user_facts": facts})
        trace.emit("user_facts", "발화의 지속 사실을 세션에 누적", {"facts": facts})
        log.info("[%s] user_facts: %d건 누적", session_id, len(facts))

    # 저확신으로 실행하지 않은 추측 계획(D124) — 대화(career_chat)가 발화에 답한 뒤, 추측이
    # 맞았을 때의 복구 경로를 **구조로** 남긴다: 확인 버튼(사용자 행동) + pendingConsent(다음
    # 턴 동의 게이트 통과) + 경고(계수 — 실사용 저확신 구간의 크기와 적중률은 이 코드가 센
    # 값으로만 알 수 있다, D117 과 같은 원리). 조용한 폐기는 흔적이 0이라 문턱 조정 근거를
    # 영영 못 만든다.
    if low_conf_guess and plan is not None:
        guess_label = " · ".join(agent_label(n) for n in low_conf_guess)
        if not any(str(q.get("field") or "") == "confirm_plan" for q in follow_up):
            follow_up.append({"field": "confirm_plan", "question": (
                f"혹시 원하신 작업이 {guess_label} 쪽이라면 말씀해 주세요 — 바로 진행할게요.")})
        _stage({"pendingConsent": list(low_conf_guess)})
        warnings.append({"code": "low_confidence_plan", "message": (
            f"플래너 확신 {plan.confidence:.2f} < {CONFIDENCE_THRESHOLD} — "
            f"추측 계획 {low_conf_guess} 을 실행하지 않고 확인 질문으로 대체")})
        trace.emit("low_confidence_plan", "저확신 추측 계획을 확인 질문으로 보존", {
            "agents": list(low_conf_guess), "confidence": plan.confidence})
        log.info("[%s] low_confidence_plan: %s (확신 %.2f) → 확인 버튼·pendingConsent 보존",
                 session_id, low_conf_guess, plan.confidence)

    # 미완수 요청이 남아 있으면 부족한 자료의 되묻기를 **구조로 보장**한다(D72) — 대체
    # 에이전트의 문장이 청했더라도 followUpQuestions(프론트 버튼)가 없으면 사용자는 무엇을
    # 줘야 하는지 행동으로 이어가지 못한다. 이미 같은 자산을 묻고 있으면 겹쳐 묻지 않는다.
    pending_now = session.get("pendingRequest") or {}
    if pending_now.get("agent") and pending_now.get("missing"):
        missing_field = str(pending_now["missing"])
        if not any(str(q.get("field") or "") == missing_field for q in follow_up):
            follow_up.append({"field": missing_field, "question": (
                f"{asset_label(missing_field)}를 보내주시면 "
                f"{agent_label(str(pending_now['agent']))}을 이어서 진행할게요.")})

    # 부분 실행 턴의 동의 질문(D158) — 가벼운 담당이 먼저 답하고, 무거운 작업의 동의는
    # **그 답 뒤에** 묻는다. 질문을 앞에 두면 사용자가 방금 낸 자료의 정리를 못 보고 결정해야
    # 한다. 대기 동의는 여기서 심는다(위 소진 분기를 통과했다).
    if dispatch.ask and dispatch.agents:
        _stage({"pendingConsent": list(dispatch.pending)})
        replies.append(dispatch.ask)
        said_sources.append(_src("orchestrator", "consent_gate", dispatch.ask))
        if not any(str(q.get("field") or "") == ask_field for q in follow_up):
            follow_up.append(_ask_card(ask_field, dispatch.ask, ask_options))
        trace.emit("consent_gate", "가벼운 담당은 실행하고 무거운 작업만 동의 대기", {
            "ask": dispatch.ask, "ran": list(dispatch.agents),
            "pendingConsent": list(dispatch.pending),
        })
        log.info("[%s] consent_gate: 부분 실행 — 실행=%s 대기=%s",
                 session_id, list(dispatch.agents), list(dispatch.pending))

    final_reply = compose_reply(acks, replies, ack=ack, note=dispatch.note,
                                steps=len(dispatch.agents), changed_by=changed_by)
    _finish(final_reply)

    # 문장별 화자 기록 — compose_reply 의 조립 순서(첨부 확인 → 계획 설명 → 한 말) 그대로.
    lead = lead_text(changed_by, ack, dispatch.note, len(dispatch.agents), replies)
    reply_sources = [_src("orchestrator", "attachment_ack", a) for a in acks]
    if lead:
        reply_sources.append(_src("orchestrator", "lead", lead))
    reply_sources.extend(said_sources)

    # **이 답변이 폴백임을 로그에 못 박는다.** structured.py 가 호출 단위로 남기는 WARNING 과
    # 별개로 한 줄 더 남기는 이유: 07-29 사고의 증상은 "호출 하나가 실패"가 아니라 "층이 죽었는데
    # 답변은 그럴듯했다"였다. 답변이 나갔다는 사실과 LLM 이 죽었다는 사실이 **같은 줄에** 있어야
    # 로그를 훑는 사람이 알아본다(재시도로 흡수된 실패는 여기 안 온다 — 경고가 안 달린다).
    failed_nodes = [w.get("message", "") for w in warnings if w.get("code") == "llm_call_failed"]
    if failed_nodes:
        log.error("[%s] LLM 이 죽은 채 답변이 나갔다 — 이 응답은 결정론 폴백이다. 실패 %d건: %s",
                  session_id, len(failed_nodes), " | ".join(failed_nodes))

    return ChatResponse(
        sessionId=session_id,
        reply=final_reply,
        intent=label,
        confidence=confidence,
        dispatched=dispatched,
        results=results,
        followUpQuestions=follow_up,
        warnings=warnings,
        replySources=reply_sources,
    )

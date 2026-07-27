"""분석 세션 실행 — 오케스트레이터에 맡기고, 그 과정을 웹 계약 메시지로 중계한다.

**브릿지는 흐름을 정하지 않는다.** "공고만 있으면 공고 정리부터, 이력서가 오면 판정" 같은 순서를
어디에도 적어 두지 않는다. 매 턴 무엇을 할지는 발화와 세션 상태를 함께 본 플래너(LLM)가 정하고,
실행 가능 여부만 검증기(orchestrator/router.py::validate_plan)가 확인한다. 여기서 순서를 박으면
에이전트가 늘어날 때마다 브릿지도 같이 고쳐야 하고, 오케스트레이터가 존재하는 이유가 사라진다.

    webbridge(전송)  →  handle_chat(판단·조합)  →  에이전트 / 판정 그래프
        ↑ trace sink 로 진행을 실시간 중계(PROGRESS)

세션 자산(job_posting·resume·analysis·roadmap)은 **사용자 세션**에 쌓인다. 그래서 분석이 끝난 뒤
"자소서 써줘"·"면접 질문 뽑아줘"를 대화(/chat)에서 바로 이어갈 수 있다 — 같은 세션을 공유한다.

판정 그래프는 동기 코드이고 질문이 생기면 사용자 답을 기다려야 하므로, 이 모듈은 워커 스레드에서
블로킹으로 돌고 WS 쪽(asyncio)과는 Channel 로만 만난다.

    WS 코루틴 ──emit(큐)──> 브라우저
        │  push_answer()          ▲
        ▼                         │ ask()
    Channel  <──────────  워커 스레드(run_session)
"""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from typing import Any, Callable, Optional

from jobis_ai import trace
from jobis_ai.contracts.api import ChatRequest
from jobis_ai.extract import extract_text
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.orchestrator.session import get_session_store
from jobis_ai.webbridge import protocol, store
from jobis_ai.webbridge.adapter import to_web_result

log = logging.getLogger(__name__)

# 답변 대기 한도(초). 초과 시 무응답으로 넘기고 진행한다(무한 대기 방지).
ANSWER_TIMEOUT_SEC = 180
# 이력서를 찾아 올리는 데는 시간이 걸린다 — 질문 답변보다 넉넉히 기다린다.
RESUME_TIMEOUT_SEC = 600
# 오케스트레이터 왕복 상한. 매 턴 되묻기만 반복하는 상황에서 세션이 끝나지 않는 것을 막는다.
MAX_TURNS = 4
# 이보다 짧으면 공고 본문이라기 어렵다 — 사이트 껍데기(메뉴·푸터)만 긁힌 경우다.
_THIN_POSTING_CHARS = 400

# 웹 버튼 한 번을 오케스트레이터가 알아들을 **발화**로 옮긴 것(사용자에게 보이는 문구가 아니다).
# 버튼에는 말이 없으니 이 번역은 브릿지의 일이다. 단, 발화는 사용자가 실제로 한 행동만 옮긴다 —
# "분석 시작" 버튼은 적합도 분석 요청이지만, 이력서 제출은 "자료를 줬다"까지다.
# 다음에 무엇을 할지는 플래너가 상태를 보고 정한다(여기서 다음 단계를 지시하면 흐름 하드코딩).
_ANALYZE_INTENT = "이 공고와 내 자료로 적합도를 분석해 주세요."
_RESUME_GIVEN = "방금 이력서를 드렸어요. 이어서 진행해 주세요."


class Channel:
    """워커 스레드 ↔ WS 코루틴 사이의 통로. 스레드 안전하게 쓰도록 이 메서드들만 노출한다."""

    def __init__(self, send: Callable[[dict], None]):
        # send 는 스레드에서 호출해도 안전해야 한다(app.py 가 asyncio 큐에 넣어 준다).
        self._send = send
        self._answers: queue.Queue[str] = queue.Queue()
        self.closed = threading.Event()

    def emit(self, message: dict) -> None:
        if not self.closed.is_set():
            self._send(message)

    def ask(self, message: dict, timeout: int = ANSWER_TIMEOUT_SEC) -> Optional[str]:
        """질문을 보내고 답을 기다린다(블로킹). 시간 초과·연결 종료면 None."""

        self.emit(message)
        try:
            return self._answers.get(timeout=timeout)
        except queue.Empty:
            return None

    def push_answer(self, text: str) -> None:
        self._answers.put(text)

    def close(self) -> None:
        self.closed.set()
        # 답을 기다리며 잠든 워커를 깨운다(빈 답 = 무응답으로 처리).
        self._answers.put("")


# ---------------------------------------------------------------------------
# START 해석 — 공고 원문과 이력 원천
# ---------------------------------------------------------------------------
def _posting_text(posting: dict) -> tuple[str, list[str]]:
    """분석에 쓸 공고 원문과, 원문이 없어 보완했을 때의 경고 문구.

    웹의 **샘플 공고**는 rawText 가 비어 있고 회사·직무·경력만 있을 수 있다. 원문이 없으면 파서가
    요건을 하나도 못 뽑아 판정이 전부 '판정불가'가 된다. 그래서 가진 필드로 최소한의 공고 문구를
    만들어 직무·연차만이라도 판정되게 하고, 근거가 빈약하다는 사실을 경고로 남긴다.
    """

    raw = (posting.get("rawText") or "").strip()
    if raw:
        return raw, []

    bits = [b for b in (posting.get("company"), posting.get("role")) if b]
    if not bits:
        return "", []

    career = posting.get("career") or ""
    text = f"{' '.join(bits)}\n\n자격 요건\n- 경력: {career}" if career else "\n".join(bits)
    return text, [
        "이 공고는 원문(본문)이 없어 회사·직무·경력만으로 판정했습니다. "
        "요건 대조 근거가 매우 빈약합니다 — 공고 원문을 붙여 넣고 다시 분석하면 정확해집니다."
    ]


def _resolve_posting(posting: dict) -> tuple[str, list[str]]:
    """분석에 넣을 공고 텍스트를 확정한다. URL 이면 여기서 한 번만 받아 온다.

    URL 을 그대로 넘기면 본문을 얼마나 가져왔는지 알 수 없다. 여기서 받아 보면 "본문이 사실상
    안 왔다"를 판정 전에 알 수 있고, 사용자에게 원문 붙여넣기를 권할 수 있다.
    """

    text, warnings = _posting_text(posting)
    if not text or not text.strip().lower().startswith(("http://", "https://")):
        return text, warnings

    result = extract_text({"sourceType": "url", "value": text.strip()})
    fetched = (result.text or "").strip()
    if not fetched:
        return "", warnings + ["공고 URL 에서 본문을 가져오지 못했어요. 공고 원문을 직접 붙여 넣어 주세요."]
    if len(fetched) < _THIN_POSTING_CHARS:
        warnings.append(
            f"공고 URL 에서 본문을 {len(fetched)}자만 가져왔어요 — 이 사이트는 상세요강을 "
            "스크립트로 그려서 요구사항이 빠진 것 같아요. 판정이 부실하면 공고 원문을 붙여 넣어 주세요."
        )
    return fetched, warnings


def _evidence_text(evidences: list[dict]) -> str:
    """웹 DB 의 자료 목록(kind/label/description) → 이력서 원문 대체 텍스트.

    웹은 이력서 파일을 통째로 넘기지 않고 "자료 조각"을 저장한다(evidences 테이블).
    그 구조를 그대로 두고 쓰기 위해 조각을 줄글로 이어 붙여 이력 원천 자리에 넣는다.
    """

    lines = []
    for e in evidences:
        label = (e.get("label") or "").strip()
        desc = (e.get("description") or "").strip()
        kind = (e.get("kind") or "").strip()
        if not (label or desc):
            continue
        head = f"[{kind}] {label}" if kind else label
        lines.append(f"{head}\n{desc}".strip())
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# 진행 중계 — 오케스트레이터·판정 그래프가 남기는 trace 를 웹 신호로 옮긴다
# ---------------------------------------------------------------------------
# 판정 그래프가 갱신하는 상태 키 중, 웹 리포트(adapter)에 필요한 것들.
_STATE_KEYS = ("normalizedJobPosting", "normalizedUserProfile", "gapAnalysisResult",
               "roadmapResult", "analysisResult", "alternativeJobs")


class _Relay:
    """trace 이벤트 → WS 신호. 판정 결과 조립에 필요한 상태도 함께 모은다."""

    def __init__(self, analysis_id: str, channel: Channel, hint: Optional[dict]):
        self.analysis_id = analysis_id
        self.channel = channel
        self.hint = hint or {}
        self.state: dict[str, Any] = {}
        self._prev_node: Optional[str] = None
        self._sent_context = False
        self._sent_profile = False

    def __call__(self, event: dict) -> None:
        kind = event.get("kind")
        detail = event.get("detail") or {}

        if kind == "node":
            node = detail.get("node") or ""
            update = detail.get("update") or {}
            for key in _STATE_KEYS:
                if update.get(key) is not None:
                    self.state[key] = update[key]
            # 공고 이해 결과는 나오는 즉시 보낸다 — 백엔드가 이걸 DB(company/role/stack)에 저장한다.
            posting = update.get("normalizedJobPosting")
            if posting and not self._sent_context:
                self.channel.emit(protocol.job_context(self.analysis_id, posting, hint=self.hint))
                self._sent_context = True
            # 이력 이해 결과도 나오는 즉시 보낸다 — 무엇을 근거로 판정하는지 화면에서 보이게.
            profile = update.get("normalizedUserProfile")
            if profile and not self._sent_profile:
                self.channel.emit(protocol.profile_context(self.analysis_id, profile))
                self._sent_profile = True
            if node:
                # 진행 문구는 노드가 toolLog 에 직접 쓴 것을 그대로 쓴다(브릿지가 짓지 않는다).
                logs = update.get("toolLog") or []
                said = str((logs[-1] or {}).get("message") or "") if logs else ""
                self.channel.emit(protocol.progress(
                    self.analysis_id, node, said, from_node=self._prev_node))
                self._prev_node = node

        elif kind == "agent_start":
            # 어떤 전담 에이전트가 도는지도 진행으로 보여준다(공고 정리·이력서 진단 등).
            agent = detail.get("agent") or ""
            if agent:
                # 레지스트리 description 은 개발자용 매니페스트라 넘기지 않는다.
                self.channel.emit(protocol.agent_progress(self.analysis_id, agent))

    def job_context_from(self, posting: dict) -> None:
        """그래프를 타지 않은 경로(공고 정리 에이전트)에서도 공고 이해 신호를 보낸다."""

        if posting and not self._sent_context:
            self.channel.emit(protocol.job_context(self.analysis_id, posting, hint=self.hint))
            self._sent_context = True


# ---------------------------------------------------------------------------
# 세션 한 건 (START ~ DONE)
# ---------------------------------------------------------------------------
def _session_id(start: dict) -> str:
    """사용자 세션 키. 분석과 대화가 같은 자산을 공유하도록 사용자 단위로 잡는다.

    userId 가 없으면(구버전 백엔드) 분석 단위로 격리한다 — 남의 자산과 섞이지 않는 쪽이 안전하다.
    """

    user_id = start.get("userId")
    if user_id:
        return f"user-{user_id}"
    return f"analysis-{start.get('analysisId') or uuid.uuid4()}"


def run_session(start: dict, channel: Channel) -> None:
    """분석 한 건을 끝까지 수행한다. 워커 스레드에서 블로킹으로 호출된다."""

    analysis_id = start.get("analysisId") or str(uuid.uuid4())
    hint = start.get("jobPosting") or {}
    session_id = _session_id(start)

    try:
        posting_text, posting_warnings = _resolve_posting(hint)
    except Exception as exc:   # URL 접속 실패 등 — 다음 행동을 알려주고 끝낸다.
        log.exception("[브릿지] 공고 원문 확보 실패")
        channel.emit(protocol.error(
            analysis_id, "POSTING_FETCH_FAILED",
            f"공고를 가져오지 못했어요({exc}). 공고 원문을 직접 붙여 넣어 주세요.",
            ["공고 원문 붙여넣기", "새 분석 시작"]))
        return

    if not posting_text:
        channel.emit(protocol.error(
            analysis_id, "EMPTY_POSTING",
            "공고 정보가 비어 있어 분석할 수 없어요. 공고 원문을 붙여 넣거나 공고 URL 을 입력해 주세요.",
            ["공고 원문 붙여넣기", "공고 URL 입력", "새 분석 시작"]))
        return

    for warning in posting_warnings:
        channel.emit(protocol.agent_message(analysis_id, warning, "parse_job_posting"))

    # 세션에 자산을 올린다. 이력서가 없으면 올리지 않는다 —
    # 그 상태를 보고 오케스트레이터가 "공고 정리부터"로 스스로 강등한다.
    updates: dict[str, Any] = {"job_posting": {"sourceType": "text", "value": posting_text}}
    resume_text = _evidence_text(start.get("evidences") or []).strip()
    if resume_text:
        updates["resume"] = {"sourceType": "text", "value": resume_text}
    if start.get("userId"):
        updates["userId"] = int(start["userId"])
    get_session_store().update(session_id, updates)

    relay = _Relay(analysis_id, channel, hint)
    message = _ANALYZE_INTENT

    for turn in range(MAX_TURNS):
        if channel.closed.is_set():
            return

        response = _run_orchestrator(session_id, message, relay, channel)
        if response is None or channel.closed.is_set():
            return
        _absorb_results(relay, response.results or {})

        # 에이전트가 한 말을 그대로 대화에 흘린다. 브릿지는 문구를 지어내지 않는다 —
        # 읽기 쉬운 길이·형식은 에이전트가 책임진다(상세 항목은 JOB_CONTEXT 로 패널에 간다).
        if response.reply:
            channel.emit(protocol.agent_message(analysis_id, response.reply,
                                                (response.dispatched or [None])[0]))

        # 판정이 나왔으면 리포트로 확정한다.
        if relay.state.get("analysisResult"):
            _finish(analysis_id, relay.state, session_id, channel)
            return

        # 아직 판정이 아니다 — 오케스트레이터가 더 필요한 것을 물어보라고 했는지 본다.
        follow_ups = list(response.followUpQuestions or [])
        if not follow_ups:
            log.info("[브릿지] 판정 없이 종료 (dispatched=%s)", response.dispatched)
            _finish_without_judgment(analysis_id, relay, channel, response.reply)
            return

        message = _collect_answers(analysis_id, follow_ups, session_id, channel)
        if message is None:
            _finish_without_judgment(analysis_id, relay, channel, response.reply)
            return

    log.info("[브릿지] 왕복 상한 도달 — 판정 없이 종료")
    _finish_without_judgment(analysis_id, relay, channel, "")


def _absorb_results(relay: _Relay, results: dict[str, Any]) -> None:
    """에이전트 산출물에서 리포트에 필요한 것을 챙긴다.

    trace 의 node 이벤트는 **판정 그래프를 탈 때만** 나온다. posting_analysis 처럼 노드를 직접
    부르는 에이전트의 결과는 여기서 받아야 리포트가 비지 않는다.
    """

    posting = (results.get("posting_analysis") or {}).get("postingAnalysis")
    if posting and not relay.state.get("normalizedJobPosting"):
        relay.state["normalizedJobPosting"] = posting
        relay.job_context_from(posting)

    # fit_analysis 는 AnalyzeResponse 를 그대로 돌려준다 — trace 가 놓쳤을 때의 안전망.
    fit = results.get("fit_analysis")
    if isinstance(fit, dict) and fit.get("status") and not relay.state.get("analysisResult"):
        if fit.get("status") == "completed":
            relay.state["analysisResult"] = fit


def _run_orchestrator(session_id: str, message: str, relay: _Relay, channel: Channel):
    """오케스트레이터 한 턴. trace 를 실시간으로 받아 진행을 중계한다."""

    try:
        with trace.recording(sink=relay):
            return handle_chat(ChatRequest(sessionId=session_id, message=message))
    except Exception as exc:   # noqa: BLE001 — 어떤 실패든 사용자에게 알리고 끝낸다
        log.exception("[브릿지] 오케스트레이터 실행 실패")
        channel.emit(protocol.error(
            relay.analysis_id, "AGENT_FAILED",
            f"분석 중 문제가 생겼어요({exc}). 다시 시도해 주세요.",
            ["다시 시도", "새 분석 시작"]))
        return None


def _collect_answers(analysis_id: str, follow_ups: list[dict], session_id: str,
                     channel: Channel) -> Optional[str]:
    """오케스트레이터의 되묻기를 사용자에게 전달하고, 답을 세션·발화로 되돌린다.

    이력서를 요구하는 질문(field == "resume")은 파일 업로드 카드로 띄운다 —
    그 답은 문장이 아니라 이력서 원문이라 세션 자산으로 직접 올린다.
    반환값: 다음 턴에 오케스트레이터로 보낼 발화. 답을 못 받으면 None.
    """

    answers: list[str] = []
    for index, question in enumerate(follow_ups):
        if channel.closed.is_set():
            return None

        field = str(question.get("field") or "")
        text = str(question.get("question") or question.get("text") or "")

        if field == "resume":
            resume = channel.ask(protocol.request_resume(analysis_id, text),
                                 timeout=RESUME_TIMEOUT_SEC)
            resume = (resume or "").strip()
            if not resume:
                return None
            get_session_store().update(session_id, {"resume": {"sourceType": "text", "value": resume}})
            return _RESUME_GIVEN

        answer = channel.ask(protocol.question(
            analysis_id,
            {**question, "text": text, "questionId": question.get("questionId") or f"q{index + 1}"},
            index, len(follow_ups)))
        if channel.closed.is_set():
            return None
        if answer and answer.strip():
            answers.append(f"{text} → {answer.strip()}" if text else answer.strip())

    if not answers:
        return None
    return " / ".join(answers)


def _finish(analysis_id: str, final_state: dict, session_id: str, channel: Channel) -> None:
    """판정 리포트로 세션을 닫는다. DONE.result 는 백엔드가 그대로 DB 에 저장한다."""

    # 웹 리포트의 "목표 상태"·"지원 경로"는 전담 에이전트가 만든다 — 브릿지가 문구를 지어내지 않는다.
    final_state["applicationPlan"] = _application_plan(analysis_id, session_id, final_state, channel)

    # 이어지는 단발 HTTP 요청(/roadmap, /roadmap-ask)이 같은 근거를 다시 쓸 수 있게 보관한다.
    store.remember(final_state)
    channel.emit(protocol.done(analysis_id, to_web_result(final_state)))


def _application_plan(analysis_id: str, session_id: str, final_state: dict,
                      channel: Channel) -> dict:
    """application_plan 에이전트 실행 → {decision, routes}.

    판정이 끝난 뒤에만 의미가 있어(전제: analysis) 여기서 부른다. 실패해도 리포트는 낸다 —
    목표 상태 칸이 '판정 보류'로 비는 것이 잘못된 문구를 지어내는 것보다 낫다.
    """

    from jobis_ai.agents import get_agent_registry

    result = final_state.get("analysisResult") or {}
    if result.get("status") != "completed":
        return {}

    spec = get_agent_registry().get("application_plan")
    if spec is None:
        return {}

    # 세션에 분석 결과를 올려 에이전트가 그것만 근거로 삼게 한다.
    store_ = get_session_store()
    store_.update(session_id, {"analysis": result})
    session = store_.get(session_id)
    session["_sessionId"] = session_id   # 에이전트가 캐시를 남길 수 있게(자산은 아니다)
    channel.emit(protocol.agent_progress(analysis_id, "application_plan"))
    try:
        outcome = spec.entry(session)
    except Exception:   # noqa: BLE001
        log.exception("[브릿지] 지원 경로 설계 실패 — 목표 상태 없이 리포트를 낸다")
        return {}
    if outcome.sessionUpdates:
        store_.update(session_id, outcome.sessionUpdates)
    return (outcome.data or {}).get("applicationPlan") or {}


def _finish_without_judgment(analysis_id: str, relay: _Relay, channel: Channel,
                             last_reply: str) -> None:
    """판정까지 못 갔을 때(공고 정리만 한 경우 등)의 종료.

    웹은 DONE 이나 ERROR 가 와야 실행을 닫는다. 여기서 ERROR 를 내면 "실패"로 기록되지만
    실제로는 공고 정리라는 결과를 냈다 — 그래서 판정 없는 리포트로 DONE 한다.
    적합도는 비워 두고(UI 는 '—' 로 표시) 왜 판정하지 않았는지 판정란에 남긴다.
    """

    posting = relay.state.get("normalizedJobPosting") or {}
    if posting:
        relay.job_context_from(posting)
    result = to_web_result({
        "analysisResult": {"status": "need_more_info", "summary": last_reply or "",
                           "meta": {}, "roadmap": [], "gaps": [], "alternativeJobs": [],
                           "sources": [], "warnings": []},
        "normalizedJobPosting": posting,
        "gapAnalysisResult": {"requirementStatus": _requirements_as_pending(posting)},
        "roadmapResult": {},
    })
    channel.emit(protocol.done(analysis_id, result))


def _requirements_as_pending(posting: dict) -> list[dict]:
    """공고 요건을 '아직 판정 안 함'으로 실어 보낸다.

    이력서가 없어 대조는 못 했지만, 공고가 무엇을 요구하는지는 알아냈다. 그 목록을 리포트에
    남겨야 사용자가 빈 화면을 보지 않는다. 충족/미충족으로 단정하지 않도록 uncertain 으로 둔다.
    """

    rows = []
    for req in list(posting.get("requiredRequirements") or []) + list(
            posting.get("preferredRequirements") or []):
        text = str(req.get("text") or "").strip()
        if not text:
            continue
        rows.append({
            "requirementId": req.get("requirementId") or text[:40],
            "type": req.get("type") or "required",
            "text": text,
            "status": "uncertain",
            "reason": "이력서를 주시면 이 요건을 대조해 드릴게요.",
            "matchedEvidenceIds": [],
            "confidence": 0.0,
        })
    return rows

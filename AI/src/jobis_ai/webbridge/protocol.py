"""웹 WS 계약 — fake-ai(:8000)가 쓰던 메시지 형태를 그대로 유지한다.

이 메시지는 백엔드가 원문 그대로 브라우저에 중계한다:
    webbridge ─WS─ Spring(FakeAgentClient.handle) ─STOMP /topic/analysis/{id}─ chat.html

따라서 필드 이름·값 도메인을 바꾸면 UI 가 조용히 깨진다. 계약의 출처는 다음 세 곳이고,
이 파일은 그걸 한 군데로 모아 둔 것이다:
  · fake-ai/server.js          — send() / sendAgentProgress() 가 만든 형태
  · FakeAgentClient.handle()   — JOB_CONTEXT/DONE 을 DB 에 저장할 때 읽는 키
  · chat.html                  — AGENT_META / AGENT_STAGE / onProgress / onQuestion / onDone

에이전트 키(agent)는 판정 그래프의 노드 이름을 그대로 쓴다. chat.html 의 AGENT_META·
AGENT_STAGE 키가 이미 그래프 노드명과 같아서(확인됨) 별도 매핑이 필요 없다.
"""

from __future__ import annotations

from typing import Optional

# 노드별 진행바 위치(%). 문구가 아니라 UI 기계값이다.
# 사람이 읽는 이름·문구는 브릿지가 만들지 않는다 — 이름은 UI(chat.html AGENT_META)가,
# 진행 문구는 노드가 toolLog 에 직접 쓴 것을 그대로 중계한다.
_NODE_PERCENT = {
    "parse_job_posting": 12, "build_user_profile": 24, "check_profile_completeness": 30,
    "check_sufficiency": 38, "ask_user": 44, "analyze_gap": 58, "plan_roadmap": 72,
    "find_alternatives": 82, "verify_result": 90, "assemble_output": 96,
}


def agent_name(agent: str) -> str:
    """에이전트 키 → 사람이 읽는 이름.

    **브릿지가 이름을 새로 정의하지 않는다.** 오케스트레이터가 이미 쓰는 라벨을 가져온다.
    그래프 노드(parse_job_posting 등)는 UI(chat.html AGENT_META)가 이름을 갖고 있어 키를 넘긴다.
    """

    from jobis_ai.orchestrator.router import agent_label

    return agent_label(agent)


def progress(analysis_id: str, node: str, message: str = "",
             from_node: Optional[str] = None) -> dict:
    """판정 그래프 노드의 진행 신호 (chat.html onProgress).

    message 는 **노드가 toolLog 에 직접 쓴 문구**를 그대로 받는다. 브릿지가 노드마다 문구를
    지어 두면 노드가 하는 일이 바뀌어도 화면 문구은 그대로 남아 사실과 어긋난다.
    이름은 UI 가 AGENT_META 로 붙이므로 agentName 을 싣지 않는다.

    stage/percent 는 agent 필드를 모르는 옛 렌더 경로(onProgressLegacy)를 위해 유지한다.
    """

    return {
        "type": "PROGRESS",
        "analysisId": analysis_id,
        "agent": node,
        "from": from_node,
        "to": node,
        "message": message,
        "stage": message,
        "percent": _NODE_PERCENT.get(node, 50),
    }


def agent_progress(analysis_id: str, agent: str, message: str = "") -> dict:
    """전담 에이전트 실행 신호. 문구는 오케스트레이터가 준 것만 쓴다.

    percent 는 알 수 없다(에이전트마다 길이가 다르고 순서도 오케스트레이터가 정한다).
    옛 진행바 하위호환을 위해 값은 넣되, 진행률로 읽히지 않게 낮게 유지한다.
    """

    name = agent_name(agent)
    return {
        "type": "PROGRESS",
        "analysisId": analysis_id,
        "agent": agent,
        "from": None,
        "to": agent,
        "agentName": name,
        "message": message or name,
        "stage": message or name,
        "percent": 10,
    }


def job_context(analysis_id: str, posting: dict, hint: Optional[dict] = None) -> dict:
    """공고 이해 결과 (FakeAgentClient 가 analysis_results 에 저장 + chat.html onJobContext).

    NormalizedJobPosting → 웹이 읽는 4개 키. 없는 값은 빈 문자열로 두고 추측하지 않는다.

    hint 는 START 로 받은 웹의 공고 정보다. 샘플 공고 경로에서는 웹이 이미 사람이 읽는 문구
    ("경력 3년 이상")를 갖고 있으므로 career 는 그걸 우선 쓴다 — 정규화 코드값(junior)이
    화면에 그대로 나가면 사용자에겐 뜻이 없는 문자열이 된다. 자유 입력 경로에서는 hint 가
    비어 있어 파싱 결과를 한국어로 옮겨 쓴다.
    """

    # 연차 한글 표기는 AI 의 role_taxonomy 가 이미 갖고 있다 — 브릿지가 다시 정의하지 않는다.
    from jobis_ai.role_taxonomy import SENIORITY_KO

    return {"type": "JOB_CONTEXT", "analysisId": analysis_id, **job_items(posting, hint)}


def job_items(posting: dict, hint: Optional[dict] = None) -> dict:
    """파싱한 공고 → 화면 항목. WS(JOB_CONTEXT)와 HTTP(/chat context)가 공유하는 순수 추출.

    파싱 결과를 **항목으로** 낸다 — UI 는 이걸 오른쪽 패널에 표로 그린다.
    백엔드는 company/role/career/stack 만 DB 에 저장하고 나머지는 그대로 중계한다(계약 유지).
    """

    from jobis_ai.role_taxonomy import SENIORITY_KO

    hint = hint or {}
    seniority = posting.get("seniority") or ""
    return {
        "company": posting.get("companyName") or hint.get("company") or "",
        "role": posting.get("jobTitle") or posting.get("roleCategory") or hint.get("role") or "",
        "career": hint.get("career") or SENIORITY_KO.get(seniority, seniority),
        "stack": list(posting.get("techStack") or []),
        "required": [r.get("text", "") for r in (posting.get("requiredRequirements") or []) if r.get("text")],
        "preferred": [r.get("text", "") for r in (posting.get("preferredRequirements") or []) if r.get("text")],
        "domains": list(posting.get("domainKeywords") or []),
    }


def profile_context(analysis_id: str, profile: dict) -> dict:
    """이력 이해 결과 — 이력서에서 뽑아낸 항목 (chat.html onProfileContext).

    JOB_CONTEXT 의 이력서 짝이다. 공고를 항목화해 보여주는 것과 같은 이유로, 내 이력서에서
    무엇을 읽어냈는지도 항목으로 보여준다(무엇을 근거로 판정했는지 사용자가 확인할 수 있어야 한다).
    파싱 결과만 옮긴다 — 없는 항목은 빈 목록으로 두고 추측하지 않는다.
    """

    return {"type": "PROFILE_CONTEXT", "analysisId": analysis_id, **profile_items(profile)}


def profile_items(profile: dict) -> dict:
    """파싱한 이력서 → 화면 항목. WS(PROFILE_CONTEXT)와 HTTP(/chat context)가 공유하는 순수 추출."""

    def _labels(items: list, *keys: str) -> list[str]:
        out = []
        for item in items or []:
            text = " ".join(str(item.get(k) or "").strip() for k in keys).strip()
            if text:
                out.append(text)
        return out

    return {
        "skills": [s.get("name", "") for s in (profile.get("skills") or []) if s.get("name")],
        "projects": _labels(profile.get("projects"), "title"),
        "experiences": _labels(profile.get("experiences"), "company", "role"),
        "education": _labels(profile.get("education"), "school", "major"),
        "certifications": _labels(profile.get("certifications"), "name"),
        "languages": _labels(profile.get("languages"), "name", "testName", "score"),
        # 판정이 인용할 근거 문장 수 — 이 값이 0 이면 대조가 사실상 불가능하다.
        "evidenceCount": len(profile.get("evidenceMap") or []),
    }


def question(analysis_id: str, item: dict, index: int, total: int) -> dict:
    """확인 질문 (chat.html onQuestion).

    판정 그래프의 followUpQuestions 항목은 {questionId, text, reason, relatedRequirementIds} 라
    선택지가 없다. UI 는 options 없는 자유입력 질문을 지원하므로 options 는 빈 배열로 보낸다.
    """

    return {
        "type": "QUESTION",
        "analysisId": analysis_id,
        "agent": "ask_user",
        "agentName": agent_name("ask_user"),
        "questionId": item.get("questionId") or f"q{index + 1}",
        "field": item.get("field") or "",
        "text": item.get("text") or "",
        "reason": item.get("reason") or "",
        "options": list(item.get("options") or []),
        "isBlocking": True,
        "index": index + 1,
        "total": total,
    }


def request_resume(analysis_id: str, question: str = "") -> dict:
    """이력서를 달라고 대화 중에 요청한다 (chat.html onRequestResume).

    문구는 **에이전트가 한 말을 그대로 쓴다**(posting_analysis 처럼 앞 단계 결과를 이어받아
    자연스럽게 묻는다). 브릿지가 문구를 박아 두면 맥락과 어긋난 말이 튀어나온다.

    QUESTION 과 같은 블로킹 신호이지만 답이 '문장'이 아니라 '이력서 원문'이다. UI 는 이걸 받으면
    파일 선택 + 원문 붙여넣기 카드를 띄우고, 사용자가 낸 텍스트를 USER_MESSAGE 로 되돌려준다
    (질문 답변과 같은 채널이라 백엔드는 바꿀 것이 없다).
    """

    # 문구는 에이전트가 한 말만 쓴다. 없으면 비워 둔다 — UI 는 직전 에이전트 발화를 이미 보여준다.
    text = (question or "").strip()
    return {
        "type": "REQUEST_RESUME",
        "analysisId": analysis_id,
        "agent": "build_user_profile",
        "agentName": agent_name("build_user_profile"),
        "text": text,
        # UI 파일 선택창의 허용 확장자. 텍스트 계열은 브라우저가 직접 읽고,
        # pdf·docx 는 서버(브릿지)가 추출한다.
        "accept": [".txt", ".md", ".html", ".pdf", ".docx"],
        "isBlocking": True,
    }


def agent_message(analysis_id: str, text: str, node: Optional[str] = None) -> dict:
    """에이전트가 사용자에게 직접 하는 말 (chat.html AGENT_MESSAGE)."""

    msg = {"type": "AGENT_MESSAGE", "analysisId": analysis_id, "text": text}
    if node:
        msg["agent"] = node
        msg["agentName"] = agent_name(node)
    return msg


def done(analysis_id: str, result: dict) -> dict:
    """최종 결과. result 는 그대로 analysis_results.result_json 에 저장된다."""

    return {"type": "DONE", "analysisId": analysis_id, "result": result}


def error(analysis_id: str, code: str, message: str, actions: Optional[list[str]] = None) -> dict:
    """오류 — 복구 가능 여부와 다음 행동을 함께 준다 (chat.html renderFailure)."""

    return {
        "type": "ERROR",
        "analysisId": analysis_id,
        "code": code,
        "message": message,
        "recoverable": True,
        "actions": actions or ["다시 시도", "공고 원문 붙여넣기", "새 분석 시작"],
    }

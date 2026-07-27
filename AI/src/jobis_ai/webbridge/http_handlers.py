"""웹백엔드가 부르는 단발 HTTP 요청 처리 (fake-ai 의 4개 라우트와 동일한 입출력).

계약 출처: fake-ai/server.js(extractEvidence/generateRoadmap/generateReassess/generateAsk),
호출부 EvidenceImportService·SavedRoadmapService, 렌더 static/roadmap.html·storage.html.

원칙:
  · 판정·추출은 판정 엔진과 같은 코드를 부른다(build_user_profile 등) — 여기서 새로 판단하지 않는다.
  · 근거가 없으면 만들어내지 않는다. 캐시된 분석이 없으면 일반적인 안내로 폴백하고 그 사실을 남긴다.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from jobis_ai import trace
from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.extract import extract_text
from jobis_ai.graph import nodes
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.structured import llm_unconfigured, run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS
from jobis_ai.webbridge import adapter, protocol, store

log = logging.getLogger(__name__)

# NormalizedUserProfile 의 항목 → 커리어 저장소의 자료 종류(EvidenceKind).
# 백엔드 enum 이 PROJECT/GITHUB/PORTFOLIO/STACK/EDU/CERT 뿐이라 그 안에서만 고른다.
_PRIORITY = {"high": "상", "medium": "중", "low": "하"}


# ---------------------------------------------------------------------------
# POST /extract — 자료 파편화
# ---------------------------------------------------------------------------
def extract_fragments(body: dict[str, Any]) -> dict[str, Any]:
    """이력서 원문 → 커리어 저장소 조각. {sourceType, content} → {fragments:[{kind,label,description}]}

    판정 엔진의 build_user_profile 을 그대로 불러 프로필을 만들고, 그 항목을 저장소 종류로 옮긴다.
    LLM 이 설정되지 않았거나 추출이 실패하면 **빈 목록**을 준다 — 샘플 데이터를 사용자의
    저장소에 넣으면 그 뒤 모든 판정이 남의 이력 위에서 돌아간다.
    """

    source_type = str(body.get("sourceType") or "TEXT").lower()
    content = body.get("content") or ""
    if not str(content).strip():
        return {"fragments": [], "warnings": [{"code": "empty_content", "message": "원문이 비어 있어요."}]}

    out = nodes.build_user_profile({
        "resumeInput": {"sourceType": _source_type(source_type), "value": content},
    })
    warnings = list(out.get("warnings") or [])
    if llm_unconfigured(warnings):
        log.warning("[/extract] LLM 미설정 — 샘플 폴백을 저장소로 내보내지 않고 빈 결과를 반환")
        return {"fragments": [], "warnings": warnings}

    profile = out.get("normalizedUserProfile") or {}
    return {"fragments": _profile_to_fragments(profile), "warnings": warnings}


def _source_type(raw: str) -> str:
    """웹의 sourceType(TEXT/FILE/URL) → extract 가 아는 값."""

    return {"file": "file", "url": "url"}.get(raw, "text")


# 이력서로 받을 파일. pdf·docx 는 브라우저가 읽을 수 없어 여기서 추출한다(extract.py 가 지원).
_RESUME_SUFFIXES = {".txt", ".md", ".html", ".htm", ".pdf", ".docx"}


def extract_uploaded_file(filename: str, payload: bytes) -> dict[str, Any]:
    """업로드된 이력서 파일 → {text, fragments}.

    임시 파일로 떨어뜨린 뒤 extract_text 에 파일 경로로 넘긴다(extract 는 경로 기반 API 다).
    처리 후 임시 파일은 지운다 — 이력서는 개인 정보라 서버에 남기지 않는다.
    """

    suffix = Path(filename).suffix.lower()
    if suffix not in _RESUME_SUFFIXES:
        return {"text": "", "fragments": [],
                "warnings": [{"code": "unsupported_file",
                              "message": f"지원하지 않는 형식이에요({suffix or '확장자 없음'}). "
                                         "txt·md·html·pdf·docx 를 올려주세요."}]}

    tmp = Path(tempfile.gettempdir()) / f"jobis-resume-{uuid.uuid4().hex}{suffix}"
    try:
        tmp.write_bytes(payload)
        result = extract_text({"sourceType": "file", "value": str(tmp)})
        text = (result.text or "").strip()
        warnings = list(result.warnings)
    finally:
        tmp.unlink(missing_ok=True)

    if not text:
        warnings.append({"code": "empty_extract",
                         "message": "파일에서 글자를 찾지 못했어요. 스캔 이미지 PDF 라면 "
                                    "원문을 붙여 넣어 주세요."})
        return {"text": "", "fragments": [], "warnings": warnings}

    fragments = extract_fragments({"sourceType": "TEXT", "content": text})
    return {"text": text, "fragments": fragments.get("fragments", []),
            "warnings": warnings + list(fragments.get("warnings") or [])}


def _frag(kind: str, label: str, description: str = "") -> dict[str, str]:
    return {"kind": kind, "label": label.strip(), "description": (description or "").strip()}


def _profile_to_fragments(profile: dict[str, Any]) -> list[dict[str, str]]:
    """정형 프로필 → 저장소 조각. 라벨이 없는 항목은 버린다(빈 카드가 생기지 않게)."""

    frags: list[dict[str, str]] = []

    for s in profile.get("skills") or []:
        if s.get("name"):
            frags.append(_frag("STACK", s["name"], s.get("level") or ""))

    for p in profile.get("projects") or []:
        if p.get("title"):
            bits = [p.get("projectType"), p.get("period"), p.get("summary")]
            frags.append(_frag("PROJECT", p["title"], " · ".join(b for b in bits if b)))

    # 재직 이력도 저장소에는 PROJECT 로 들어간다 — enum 에 경력 종류가 따로 없다.
    for e in profile.get("experiences") or []:
        label = " · ".join(b for b in (e.get("company"), e.get("role")) if b)
        if label:
            bits = [e.get("employmentType"), e.get("period"), e.get("summary")]
            frags.append(_frag("PROJECT", label, " · ".join(b for b in bits if b)))

    for ed in profile.get("education") or []:
        label = " ".join(b for b in (ed.get("school"), ed.get("major")) if b)
        if label:
            bits = [ed.get("degree"), ed.get("status"), ed.get("period")]
            frags.append(_frag("EDU", label, " · ".join(b for b in bits if b)))

    for b in profile.get("bootcamp") or []:
        if b.get("name"):
            bits = [b.get("organization"), b.get("track"), b.get("period"), b.get("summary")]
            frags.append(_frag("EDU", b["name"], " · ".join(x for x in bits if x)))

    for c in profile.get("certifications") or []:
        if c.get("name"):
            bits = [c.get("status"), c.get("acquiredDate")]
            frags.append(_frag("CERT", c["name"], " · ".join(x for x in bits if x)))

    for lang in profile.get("languages") or []:
        label = " ".join(b for b in (lang.get("name"), lang.get("testName")) if b)
        if label:
            bits = [lang.get("score"), lang.get("proficiency"), lang.get("testDate")]
            frags.append(_frag("CERT", label, " · ".join(x for x in bits if x)))

    # 수상 이력도 증빙 계열이라 CERT 로 둔다.
    for a in profile.get("awards") or []:
        if a.get("title"):
            bits = [a.get("organization"), a.get("date"), a.get("description")]
            frags.append(_frag("CERT", a["title"], " · ".join(x for x in bits if x)))

    return frags


# ---------------------------------------------------------------------------
# POST /chat — 일반 대화 (오케스트레이터)
# ---------------------------------------------------------------------------
def chat_turn(body: dict[str, Any]) -> dict[str, Any]:
    """자유 대화 한 턴. {sessionId, message, attachments} → ChatResponse dict.

    분석 WS 와 달리 여기는 **오케스트레이터**(플래너 → 검증기 → 에이전트)로 들어간다.
    "취업 준비 뭐부터 하죠?" 같은 일반 질문, 공고 추천, 이력서 진단, 면접 준비가 이 경로다.
    대화 이력은 sessionId 로 세션 저장소에 쌓인다(handle_chat 이 기록).
    """

    attachments = []
    for att in body.get("attachments") or []:
        kind = str(att.get("kind") or "").strip()
        value = str(att.get("value") or "")
        if kind in ("resume", "job_posting", "resume_extra") and value.strip():
            attachments.append(ChatAttachment(
                kind=kind,  # type: ignore[arg-type]
                sourceType=SourceType(str(att.get("sourceType") or "text")),
                value=value,
            ))

    message = str(body.get("message") or "")
    # 대화창에 공고를 그대로 붙여넣는 경우 — 그걸 첨부로 승격해 세션 자산으로 올린다.
    # 이 경로가 없으면 에이전트가 "공고를 주세요"라고 말할 수도, 받을 수도 없다.
    # 발화는 비워 둔다 — 무엇을 할지 지시하는 문장을 여기서 합성하면 흐름 하드코딩이다.
    # handle_chat 이 첨부만 온 턴의 중립 발화("이어서 진행해 주세요")를 합성하고 플래너가 정한다.
    posting = _posting_in_message(message)
    if posting and not any(a.kind == "job_posting" for a in attachments):
        attachments.append(ChatAttachment(
            kind="job_posting",
            sourceType=SourceType.url if posting.startswith(("http://", "https://")) else SourceType.text,
            value=posting,
        ))
        message = ""

    session_id = str(body.get("sessionId") or "").strip() or "web"
    request = ChatRequest(sessionId=session_id, message=message, attachments=attachments)

    # 판정 그래프가 파싱을 남기면(적합도 분석 경로) 화면 항목화에 쓴다 — trace 로 줍는다.
    parsed: dict[str, Any] = {}

    def _collect(event: dict) -> None:
        update = (event.get("detail") or {}).get("update") or {}
        for key in ("normalizedJobPosting", "normalizedUserProfile"):
            if update.get(key):
                parsed[key] = update[key]

    with trace.recording(sink=_collect):
        resp = handle_chat(request).model_dump()

    resp["context"] = _panel_context(session_id, resp, parsed)
    return resp


def _panel_context(session_id: str, resp: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    """이번 턴까지 파싱된 공고·이력서를 화면 항목으로 — 우측 패널이 그린다.

    항목 추출은 WS 경로(JOB_CONTEXT/PROFILE_CONTEXT)와 같은 코드(protocol.job_items/
    profile_items)를 쓴다 — 문구를 새로 만들지 않고 파싱 결과만 옮긴다.
    파싱된 공고는 세션에 캐시해(posting_summary) 다음 턴·새로고침에도 패널이 유지된다.
    """

    from jobis_ai.orchestrator.session import get_session_store

    store_ = get_session_store()

    # 공고: 이번 턴 파싱(그래프 or 공고 정리 에이전트) > 세션 캐시 순.
    posting = (
        parsed.get("normalizedJobPosting")
        or ((resp.get("results") or {}).get("posting_analysis") or {}).get("postingAnalysis")
    )
    if posting:
        store_.update(session_id, {"posting_summary": posting})
    else:
        posting = store_.get(session_id).get("posting_summary")

    # 이력서: 이번 턴 파싱 > 세션의 프로필 캐시(ensure_profile 이 저장) 순.
    profile = parsed.get("normalizedUserProfile") or store_.get(session_id).get("profile")

    context: dict[str, Any] = {}
    if posting:
        context["job"] = protocol.job_items(posting)
    if profile:
        context["profile"] = protocol.profile_items(profile)
    return context


# 공고 원문에서만 보이는 표지어. 이게 없는 긴 글은 공고로 보지 않는다(이력서·자기소개일 수 있다).
_POSTING_MARKERS = re.compile(
    r"(자격\s*요건|지원\s*자격|우대\s*사항|담당\s*업무|주요\s*업무|모집\s*부문|모집\s*분야|"
    r"직무\s*내용|채용\s*(공고|절차)|필수\s*요건|근무\s*조건)")
# 이보다 짧은 글은 공고 본문이라 보기 어렵다.
_POSTING_MIN_CHARS = 180


def _posting_in_message(message: str) -> str:
    """발화가 곧 공고인지 판별해, 공고면 그 원문(또는 URL)을 돌려준다.

    보수적으로 본다 — URL 이거나, 충분히 길고 공고 표지어가 있을 때만. 애매하면 일반 대화로 둔다
    (대화에서 "이 공고 분석해줘"로 이어갈 수 있으니 되돌리기 쉬운 쪽이다).
    """

    text = (message or "").strip()
    if not text:
        return ""
    if text.lower().startswith(("http://", "https://")) and len(text.split()) == 1:
        return text
    if len(text) >= _POSTING_MIN_CHARS and _POSTING_MARKERS.search(text):
        return text
    return ""


# ---------------------------------------------------------------------------
# POST /roadmap — 선택한 경로의 준비 로드맵
# ---------------------------------------------------------------------------
def build_roadmap(body: dict[str, Any]) -> dict[str, Any]:
    """{company, role, routeKind, goalCompany} → roadmap.html 이 렌더하는 스텝 목록.

    요청에 분석 결과가 없어서(웹 계약) 직전 분석을 store 에서 찾아 그 로드맵·요건 판정을 쓴다.
    찾지 못하면 근거 없는 개인화를 하지 않고 일반 준비 절차로 폴백한다.
    """

    company = str(body.get("company") or "").strip()
    role = str(body.get("role") or "").strip()
    route_kind = "as_is" if body.get("routeKind") == "as_is" else "reinforce"
    state = store.recall(company, role)

    if not state:
        log.info("[/roadmap] 캐시된 분석 없음 → 일반 준비 절차로 폴백 (company=%s)", company)
        return _generic_roadmap(company or "이 공고", route_kind)

    analysis = state.get("analysisResult") or {}
    gap = state.get("gapAnalysisResult") or {}
    req_status = list(gap.get("requirementStatus") or [])
    items = list(analysis.get("roadmap") or [])
    texts = {r.get("requirementId"): r.get("text") or "" for r in req_status}
    reasons = {r.get("requirementId"): r.get("reason") or "" for r in req_status}
    skills = {g.get("requirementId"): list(g.get("missingSkills") or [])
              for g in (analysis.get("gaps") or [])}

    top_gap = next((r.get("text") or "" for r in req_status
                    if r.get("status") in ("not_met", "partially_met")), "")
    strengths = [r.get("text") or "" for r in req_status if r.get("status") == "met"][:5]

    steps = []
    for i, item in enumerate(items, start=1):
        rids = list(item.get("relatedRequirementIds") or [])
        # 스텝이 겨냥하는 요건으로는 "대체 불가 조건"(경력 N년 등)을 앞세우지 않는다 —
        # 그 스텝을 끝내도 채워지지 않는 요건이라 "이 산출물로 충족"이 성립하지 않는다.
        candidates = [texts[r] for r in rids if texts.get(r)]
        req_text = next((t for t in candidates if not adapter.is_hard_constraint(t)),
                        next(iter(candidates), ""))
        keywords = [s for r in rids for s in skills.get(r, [])]
        tasks = list(item.get("tasks") or [])
        steps.append({
            "no": i,
            "title": item.get("title") or "",
            "duration": " ~ ".join(x for x in (item.get("startDate"), item.get("endDate")) if x),
            "difficulty": _PRIORITY.get(item.get("priority") or "medium", "중"),
            "meta": f"주 {item['estimatedHours']}시간" if item.get("estimatedHours") else "",
            "requirement": req_text,
            "gap": next((reasons[r] for r in rids if reasons.get(r)), item.get("goal") or ""),
            "artifact": tasks[0] if tasks else (item.get("title") or ""),
            "done": item.get("doneCriteria") or "",
            "hint": item.get("goal") or "",
            "keywords": keywords[:6],
            "resources": [],
            # 제출물 재진단(/reassess)이 링크에서 찾을 신호.
            "verifyHints": _verify_hints(keywords, [item.get("title"), *tasks,
                                                    item.get("doneCriteria")]),
        })

    if not steps:
        return _generic_roadmap(company or "이 공고", route_kind)

    rk = "지금 지원" if route_kind == "as_is" else "보강 후 지원"
    return {
        "title": f"{company or '이 공고'} · {rk} 로드맵",
        "intro": (analysis.get("summary") or "").strip() or (
            "현재 가진 증거를 정리해 바로 지원하는 준비 경로예요." if route_kind == "as_is"
            else "핵심 격차를 보완해 지원 경쟁력을 높이는 준비 경로예요."),
        "topGap": top_gap,
        "strengths": strengths,
        "steps": steps,
        "goalLink": str(body.get("goalCompany") or "") or None,
        "targetDate": (items[-1].get("endDate") if items else None),
        "today": (items[0].get("startDate") if items else None),
    }


# 링크에서 "무엇을 만들었나"를 가리지 못하는 토큰 — 힌트로 쓰면 아무 링크나 통과시키거나
# (호스트명·스킴) 아무 링크도 통과 못 시킨다(URL 같은 일반 명사).
_HINT_STOPWORDS = {
    "url", "http", "https", "www", "com", "net", "org", "github", "gitlab", "notion",
    "link", "and", "the", "for", "with", "만들기", "정리",
}
# 산출물이 있다는 일반 신호. 스텝 문구에서 쓸 만한 토큰을 못 뽑았을 때 보탠다.
_GENERIC_HINTS = ["project", "portfolio", "readme", "demo", "report"]


def _verify_hints(keywords: list[str], texts: list[Any]) -> list[str]:
    """제출 링크에서 찾을 신호 토큰.

    부족 스킬(keywords)이 있으면 그게 가장 정확한 신호다. 없으면 스텝 문구의 영문 토큰을 쓰고,
    쓸 만한 토큰이 거의 없으면 일반 산출물 신호를 보탠다 — 힌트가 비거나 무의미하면 /reassess 가
    무엇을 제출해도 "증거가 약하다"만 반복해 그 스텝을 끝낼 방법이 사라진다.
    """

    hints = [k.lower() for k in keywords if k]
    if hints:
        return hints[:8]

    joined = " ".join(str(t) for t in texts if t)
    seen, derived = set(), []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.]{2,}", joined):
        t = token.lower()
        if t in _HINT_STOPWORDS or t in seen:
            continue
        seen.add(t)
        derived.append(t)

    # 토큰이 한둘뿐이면(대개 한글 문구라 뽑힌 게 없다) 일반 신호를 함께 둔다.
    if len(derived) < 2:
        derived += [g for g in _GENERIC_HINTS if g not in seen]
    return derived[:8]


def _generic_roadmap(company: str, route_kind: str) -> dict[str, Any]:
    """분석 근거가 없을 때의 일반 준비 절차. fake-ai 의 폴백과 같은 형태·같은 3단계.

    **맞춤인 척하지 않는다.** 이 공고의 분석 결과를 찾지 못했을 때만 오는 경로이므로,
    intro 에 그 사실과 맞춤 로드맵을 받는 방법을 그대로 쓴다. 스텝은 공고와 무관하게
    성립하는 일반 절차(증거 정리 → 산출물 보완 → 지원)라 근거 없는 개인화가 아니다.
    """

    rk = "지금 지원" if route_kind == "as_is" else "보강 후 지원"
    return {
        "title": f"{company} · {rk} 로드맵",
        "intro": ("이 공고의 분석 결과를 찾지 못해 일반 준비 절차를 안내해요. "
                  "공고 적합도 분석을 실행하면 격차에 맞춘 로드맵으로 바꿔 드릴 수 있어요."),
        "topGap": "",
        "strengths": [],
        "goalLink": None,
        "steps": [
            {"no": 1, "title": "선택한 증거를 공고 요건에 맞춰 재정리", "duration": "3–4일",
             "difficulty": "하", "meta": "요구사항별 매칭", "requirement": "요건×증거 매칭",
             "gap": "공고 요건과 내 증거를 맞춰 정리해요.", "artifact": "요건×증거 매칭 자료",
             "done": "매칭표", "keywords": [], "resources": [],
             "verifyHints": ["match", "매칭", "대비표", "portfolio", "resume"]},
            {"no": 2, "title": "부족한 요건을 산출물로 보완", "duration": "1–2주",
             "difficulty": "중", "meta": "증거 만들기", "requirement": "부족 요건을 메우는 산출물",
             "gap": "미확인 요건을 작은 결과물로 메워요.", "artifact": "요건을 증명하는 산출물 1개",
             "done": "산출물 · 링크", "keywords": [], "resources": [],
             "verifyHints": ["project", "demo", "report", "portfolio", "app"]},
            {"no": 3, "title": "지원 + 회고", "duration": "1일", "difficulty": "하", "meta": "",
             "requirement": "지원 완료", "gap": "정리한 자료로 지원해요.",
             "artifact": "지원 완료 + 회고", "done": "지원 링크 · 회고",
             "keywords": [], "resources": [],
             "verifyHints": ["apply", "application", "review", "retro", "회고"]},
        ],
    }


# ---------------------------------------------------------------------------
# POST /reassess — 산출물 제출 → 요건 충족 재진단
# ---------------------------------------------------------------------------
_LINK = re.compile(r"^https?://[^\s]+\.[^\s]+")
_KNOWN_HOST = re.compile(
    r"(github\.com|gitlab\.com|vercel\.app|netlify\.app|notion\.(so|site)|tistory\.com|velog\.io|\.dev\b)"
)


def reassess_step(body: dict[str, Any]) -> dict[str, Any]:
    """제출 링크가 이 스텝의 요건을 증명하는지 본다.

    **규칙 판정이다(LLM 아님).** 링크 형식 + 스텝의 verifyHints 토큰이 링크에 보이는지만 확인한다.
    링크 내용을 열어 읽고 의미로 판정하는 것은 다음 단계 과제로 남겨 둔다 — 지금 단정하면
    "확인했다"는 말이 근거 없이 나간다. 판정 값(verdict/checks)은 웹 계약 그대로다.
    """

    step = body.get("step") or {}
    url = str(body.get("url") or "").strip()
    low = url.lower()
    requirement = step.get("requirement") or step.get("title") or "이 스텝의 핵심 증거"
    hints = [str(h).lower().strip() for h in (step.get("verifyHints") or []) if str(h).strip()]

    looks_like_link = bool(_LINK.match(low) or _KNOWN_HOST.search(low))
    if not looks_like_link:
        return {
            "verdict": "insufficient", "resolvedRequirement": None,
            "headline": "아직 제출물을 확인하지 못했어요",
            "detail": "GitHub 저장소나 배포·문서 링크를 붙여주시면 산출물을 근거로 다시 진단할 수 있어요.",
            "checks": [{"label": "제출 링크 형식", "ok": False},
                       {"label": f"{requirement} 증거", "ok": False}],
            "nextHint": f"완료 기준: {step.get('done') or '산출물 링크'} — 이걸 담은 링크를 제출해 주세요.",
        }

    # 짧은 영숫자 토큰(edr·elk 등)은 단어 경계로 본다 — 'velog'에서 'log'를 찾는 오탐 방지.
    def _hit(token: str) -> bool:
        if re.fullmatch(r"[a-z0-9]+", token) and len(token) <= 3:
            return bool(re.search(rf"(^|[^a-z0-9]){re.escape(token)}([^a-z0-9]|$)", low))
        return token in low

    if not any(_hit(h) for h in hints):
        return {
            "verdict": "insufficient", "resolvedRequirement": None,
            "headline": "링크는 확인했지만 이 요건의 증거가 약해요",
            "detail": f"“{requirement}”을(를) 보여주는 결과물인지 아직 분명하지 않아요.",
            "checks": [{"label": "제출 링크 형식", "ok": True},
                       {"label": f"{requirement} 증거", "ok": False}],
            "nextHint": (f"이런 산출물이면 확실해요: {step['artifact']}" if step.get("artifact")
                         else "이 스텝의 산출물을 담은 링크를 제출해 주세요."),
        }

    return {
        "verdict": "verified", "resolvedRequirement": requirement,
        "headline": f"“{requirement}” 증거를 확인했어요",
        "detail": "제출한 산출물에서 이 요건을 메우는 신호를 확인했어요. 요건 매트릭스에 반영할게요.",
        "checks": [{"label": "제출 링크 형식", "ok": True},
                   {"label": f"{requirement} 증거", "ok": True},
                   {"label": "완료 기준 충족", "ok": True}],
        "nextHint": None,
    }


# ---------------------------------------------------------------------------
# POST /submission-review — 산출물 제출 → 요건별 피드백
# ---------------------------------------------------------------------------
class _CheckWrite(BaseModel):
    """요건 한 건에 대한 판정."""

    requirement: str = Field(default="", description="대조한 공고 요건 문구를 그대로.")
    mark: str = Field(default="tri", description=(
        "ok=제출물에서 이 요건의 근거를 확인함 / tri=일부만 보임 또는 불확실 / "
        "no=근거를 찾지 못함. 링크에서 확인되지 않으면 ok 를 쓰지 않는다."))
    comment: str = Field(default="", description=(
        "왜 그렇게 봤는지 한 문장. 제출된 링크·메모에 실제로 있는 내용만 근거로 든다. "
        "없는 파일·수치를 있다고 쓰지 않는다."))


class _ReviewWrite(BaseModel):
    """제출물 리뷰 — 표현+대조. 합격 여부는 말하지 않는다."""

    summary: str = Field(default="", description=(
        "제출물이 어떤 요건을 메웠고 무엇이 남았는지 두세 문장. 합격 가능성은 단정하지 않는다."))
    checks: list[_CheckWrite] = Field(default_factory=list, description=(
        "입력으로 준 요건 목록 전부에 대해 한 건씩. 요건을 빼먹지 않는다."))


_REVIEW_SYSTEM = """너는 취업 준비생이 제출한 산출물(저장소·배포 링크·메모)을 공고 요건과 대조하는 검토자다.
- 링크 주소와 메모에 **실제로 드러난 것만** 근거로 삼는다. 링크 내용을 열어볼 수는 없으므로,
  주소·저장소명·메모에서 확인되는 신호만 인정한다.
- 확인되지 않으면 ok 를 주지 않는다(tri 또는 no). 모르면 모른다고 쓴다.
- 합격 가능성·적합도를 단정하지 않는다. 무엇이 확인됐고 무엇이 안 됐는지만 말한다.
- requirements 로 준 요건 전부를 checks 에 담는다."""


def review_submission(body: dict[str, Any]) -> dict[str, Any]:
    """{githubUrl, deployUrl, note, requirements[]} → {summary, checks[{mark,requirement,comment}]}

    LLM 호출은 한 번이다(요건별로 부르지 않는다 — 토큰 비용). 링크가 아예 없으면 LLM 을 부르지 않고
    규칙으로 끝낸다 — 제출물이 없는데 판정할 것이 없다.
    """

    github = str(body.get("githubUrl") or "").strip()
    deploy = str(body.get("deployUrl") or "").strip()
    note = str(body.get("note") or "").strip()
    requirements = [str(r).strip() for r in (body.get("requirements") or []) if str(r).strip()]

    links = [x for x in (github, deploy) if _LINK.match(x.lower()) or _KNOWN_HOST.search(x.lower())]
    if not links:
        return {
            "summary": "제출된 링크를 확인하지 못했어요. GitHub 저장소나 배포·문서 링크를 붙여주시면 "
                       "요건별로 대조해 드릴게요.",
            "checks": [{"mark": "no", "requirement": r,
                        "comment": "제출물이 없어 확인하지 못했어요."} for r in requirements],
        }

    read, warnings = run_structured(
        _ReviewWrite, _REVIEW_SYSTEM,
        json.dumps({"githubUrl": github, "deployUrl": deploy, "note": note,
                    "requirements": requirements}, ensure_ascii=False),
        node="submission_review",
    )
    if read is None or not read.checks:
        log.info("[/submission-review] LLM 판정 불가 → 규칙 응답 (warnings=%s)", warnings)
        return {
            "summary": "제출물 링크는 확인했지만, 요건별 대조 결과를 만들지 못했어요. 잠시 후 다시 시도해 주세요.",
            "checks": [{"mark": "tri", "requirement": r,
                        "comment": "링크는 확인했지만 이 요건의 근거를 판단하지 못했어요."} for r in requirements],
        }

    marks = {"ok", "tri", "no"}
    checks = [{
        "mark": c.mark if c.mark in marks else "tri",
        "requirement": c.requirement,
        "comment": c.comment,
    } for c in read.checks]
    summary = (read.summary or "").strip()
    if not summary or any(expr in summary for expr in FORBIDDEN_EXPRESSIONS):
        # 모델이 요약을 비워 보내는 일이 있다(checks 만 채움). 검사 결과로 직접 조립한다 —
        # 요약 하나 때문에 LLM 을 다시 부르지 않는다.
        summary = _review_summary(checks)
    return {"summary": summary, "checks": checks}


def _review_summary(checks: list[dict]) -> str:
    """검사 결과 → 한 줄 요약. 합격 여부는 말하지 않고 확인/미확인만 센다."""

    ok = [c["requirement"] for c in checks if c["mark"] == "ok"]
    rest = [c["requirement"] for c in checks if c["mark"] != "ok"]
    parts = [f"요건 {len(checks)}건 중 {len(ok)}건의 근거를 제출물에서 확인했어요."]
    if ok:
        parts.append(f"확인됨 — {', '.join(ok[:4])}.")
    if rest:
        parts.append(f"아직 확인되지 않음 — {', '.join(rest[:4])}.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# POST /roadmap-ask — 로드맵 Q&A
# ---------------------------------------------------------------------------
class _AskWrite(BaseModel):
    """표현 전용 — 판단 필드 없음(nl_render 패턴).

    description 없이 두면 구조화 출력에서 모델이 한 줄짜리 제목만 채운다(career_chat 실측).
    """

    answer: str = Field(default="", description=(
        "사용자에게 그대로 보여줄 답변. context 의 스텝·격차만 근거로 두세 문장으로 쓰고, "
        "지금 무엇부터 하면 되는지로 끝낸다. 없는 스텝·수치를 만들지 않는다."))


_ASK_SYSTEM = """너는 사용자의 준비 로드맵을 함께 보는 코치다. 사용자가 이 로드맵에 대해 묻는다.
- context 에 있는 사실(회사, 핵심 격차, 스텝 목록)만 근거로 답한다. 없는 스텝·수치를 만들지 않는다.
- 두세 문장으로 짧게, 지금 무엇부터 하면 되는지로 끝낸다.
- 합격 가능성·적합도를 단정하거나 보장하지 않는다.
- 시간이 부족하다는 질문이면 어느 스텝에 집중할지 골라 준다."""


def answer_roadmap_question(body: dict[str, Any]) -> dict[str, Any]:
    """{question, company, topGap, routeKind, userId?} → {question, answer}.

    userId 가 오면 **오케스트레이터**로 보낸다 — 그 사용자 세션에는 분석·로드맵 자산이 이미
    올라가 있어서 플래너가 roadmap_manager·career_chat 중 맥락에 맞는 것을 고른다.
    userId 가 없으면(웹이 아직 안 보내는 경로) 캐시된 분석을 맥락으로 직접 답한다.
    """

    question = str(body.get("question") or "").strip()
    user_id = body.get("userId")
    if question and user_id:
        try:
            response = handle_chat(ChatRequest(sessionId=f"user-{user_id}", message=question))
            answer = (response.reply or "").strip()
            if answer:
                return {"question": question, "answer": answer,
                        "dispatched": list(response.dispatched or [])}
        except Exception:   # noqa: BLE001 — 오케스트레이터 실패 시 아래 맥락 답변으로 폴백
            log.exception("[/roadmap-ask] 오케스트레이터 실패 → 맥락 답변으로 폴백")

    company = str(body.get("company") or "이 공고").strip() or "이 공고"
    top_gap = str(body.get("topGap") or "").strip()

    if not question:
        return {"question": "", "answer": "무엇이든 물어보세요 — 예: “2주밖에 없어, 압축해줘”, "
                                          "“가장 큰 격차가 뭐야?”, “이 스텝은 왜 필요해?”"}

    state = store.recall(company) or {}
    analysis = state.get("analysisResult") or {}
    steps = [{"title": i.get("title"), "goal": i.get("goal"),
              "done": i.get("doneCriteria"), "hours": i.get("estimatedHours")}
             for i in (analysis.get("roadmap") or [])][:6]
    if not top_gap:
        gapres = (state.get("gapAnalysisResult") or {}).get("requirementStatus") or []
        top_gap = next((r.get("text") or "" for r in gapres
                        if r.get("status") in ("not_met", "partially_met")), "")

    read, warnings = run_structured(
        _AskWrite, _ASK_SYSTEM,
        json.dumps({"question": question,
                    "context": {"company": company, "topGap": top_gap,
                                "routeKind": body.get("routeKind") or "",
                                "steps": steps}},
                   ensure_ascii=False),
        node="roadmap_ask",
    )
    answer = (read.answer or "").strip() if read is not None else ""
    if not answer or any(expr in answer for expr in FORBIDDEN_EXPRESSIONS):
        answer = _ask_fallback(company, top_gap, steps)
        if warnings:
            log.info("[/roadmap-ask] LLM 응답을 쓰지 못해 폴백 (warnings=%s)", warnings)
    return {"question": question, "answer": answer}


def _ask_fallback(company: str, top_gap: str, steps: list[dict]) -> str:
    """LLM 없이도 맥락에 맞는 답. 캐시된 스텝이 있으면 그걸 가리킨다."""

    if steps:
        first = steps[0].get("title") or "첫 스텝"
        gap = f"“{top_gap}”" if top_gap else "핵심 격차"
        return (f"이 로드맵은 {company}의 요건을 순서대로 산출물로 바꾸는 길이에요. "
                f"지금 가장 큰 격차는 {gap}이고, 그걸 정면으로 겨냥하는 건 “{first}”예요. "
                "시간이 빠듯하면 그 스텝 하나만 끝내도 지원 근거가 생겨요.")
    return ("이 로드맵은 공고 요건을 산출물로 바꾸는 순서예요. 각 스텝의 완료 기준을 보고 "
            "가장 부족한 항목부터 하나씩 채우면 돼요.")

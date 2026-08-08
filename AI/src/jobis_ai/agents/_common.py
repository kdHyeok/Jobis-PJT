"""에이전트 공용 헬퍼 — **여러 에이전트가 같은 것을 각자 다르게 틀렸던 지점**을 모은 곳.

이력서 전용이 아니다(공고 쪽이 오히려 더 많다). 들어오는 기준은 자산 종류가 아니라
"둘 이상이 같은 계산을 따로 구현하고 있는가" 다 — posting_identity 는 자소서가 회사명을
아예 안 읽고 application_plan 은 없는 칸에서 읽던 것을 하나로 모은 것이다.

  · 자산 확보(없으면 만들어 캐시): ensure_posting_text · ensure_profile
    — 캐시는 저장소를 거친다. 세션 dict 는 복사본이라 직접 고쳐도 안 남는다(session.py).
  · 세션 읽기: posting_identity · agent_arg · upsert_posting_library
  · 자기 루프에 줄 재료: grep_source_lines(원문 근거) · others_this_turn(이번 턴 계획)
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from jobis_ai.agents.agent_loop import TOOL_WARNINGS_KEY, ToolSpec
from jobis_ai.graph.nodes import build_user_profile
from jobis_ai.rag import get_rag_adapter

# 대화에서 정리했던 공고를 몇 개까지 기억하나 — 오래된 것부터 버린다(D86).
_POSTING_LIBRARY_MAX = 5
# 이력서도 같은 상한. 공고와 대칭으로 두는 이유는 §"둘 이상이 같은 계산" 이 아니라
# **사용자가 같은 것을 기대하기 때문**이다 — 공고는 기억하는데 이력서는 못 기억하면
# 그 비대칭 자체가 결함으로 읽힌다(D119).
_RESUME_LIBRARY_MAX = 5

# 원문 검색 도구가 한 번에 돌려주는 양 — 관찰이 루프 payload 를 삼키지 않게 자른다.
_GREP_MAX_LINES = 15
_GREP_MAX_CHARS = 1200

# 공고 검색 도구가 한 번에 돌려주는 양 — grep 과 같은 이유(관찰이 payload 를 삼키지 않게).
# 원문 발췌를 짧게 자르는 것은 **요약이 아니라 절단**이다: 판단은 루프가 하고, 더 봐야 하면
# 검색어를 좁혀 다시 부른다.
_SEARCH_TOP_K = 5
_SEARCH_SNIPPET_CHARS = 160
_SEARCH_MAX_CHARS = 1600


def grep_source_lines(text: str, arg: str, *, label: str) -> str:
    """원문에서 키워드가 든 줄을 찾아 **관찰 문자열**로 돌려준다(D97 — 대화형 담당의 근거).

    파싱 결과는 스키마에 칸이 있는 것만 담은 손실 있는 추출이다. 칸이 없는 것(공고의 전형
    절차·복리후생, 이력서의 서술형 자기소개)을 물으면 루프가 이걸로 원문을 본다.

    **못 찾으면 못 찾았다고 돌려준다.** 빈 관찰을 주면 LLM 이 그 자리를 사전지식으로
    채운다(§2-5 근거는 도구만 준다). 실패도 사실로 말하는 것이 이 함수의 계약이다.
    """

    body = str(text or "")
    if not body.strip():
        return f"{label} 원문이 세션에 없습니다."
    keywords = [k.strip() for k in (arg or "").split(",") if k.strip()]
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    hits = ([ln for ln in lines if any(k in ln for k in keywords)] if keywords
            else lines)[:_GREP_MAX_LINES]
    if not hits:
        return f"{label} 원문에서 '{', '.join(keywords)}' 를 찾지 못했습니다."
    return (f"{label} 원문에서 찾은 줄:\n" + "\n".join(hits))[:_GREP_MAX_CHARS]


def search_postings_tool(*, top_k: int = _SEARCH_TOP_K,
                         name: str = "search_postings") -> ToolSpec:
    """RAG 실공고 검색을 **자기 루프의 도구로** 연다.

    루프 하네스(`agent_loop`)는 이미 있었는데 등록된 도구가 전부 세션 내부 데이터
    읽기·쓰기였다 — `resume_diagnosis` 는 도구가 1개, `posting_analysis` 는 2개다.
    고를 것이 없으면 루프는 돌지 않는다. **자율성의 병목은 루프 구조가 아니라 도구
    목록이었다.** RAG 는 `job_recommend` 안의 결정론 단계로만 불려서, 루프를 도는
    담당이 "비슷한 공고는 뭘 요구하나"를 스스로 확인할 방법이 없었다.

    ToolSpec 규약 그대로다: 관찰은 **사실만**(판단·권유 없음), 실패는 예외 대신 관찰
    문자열, RAG 경고(`rag_http_failed`·`rag_not_connected`)는 삼키지 않고 올린다(§2-6)
    — 키워드 폴백으로 찾은 결과인지를 호출부가 알아야 사용자에게 명시할 수 있다(D90).
    """

    def run(state: dict[str, Any], arg: str) -> tuple[str, dict[str, Any]]:
        query = (arg or "").strip()
        if not query:
            return "검색어가 비어 있어 검색하지 않았습니다. 찾을 기술·직무를 적어 주세요.", {}
        try:
            result = get_rag_adapter().search(query, top_k=top_k)
        except Exception as exc:      # noqa: BLE001 — 도구 실패가 루프를 죽이지 않는다
            return f"공고 검색 실패: {exc}", {}

        data: dict[str, Any] = {}
        if result.warnings:
            data[TOOL_WARNINGS_KEY] = list(result.warnings)
        if not result.items:
            # 빈 결과를 빈 관찰로 주면 LLM 이 그 자리를 사전지식으로 채운다(§2-5).
            return f"'{query}' 로 찾은 공고가 없습니다.", data

        lines = []
        for item in result.items[:top_k]:
            company = str(item.get("companyName") or "").strip() or "(회사명 없음)"
            title = str(item.get("title") or "").strip()
            seniority = str(item.get("seniority") or "").strip()
            url = str(item.get("url") or "").strip()
            body = " ".join(str(item.get("text") or "").split())[:_SEARCH_SNIPPET_CHARS]
            head = " | ".join(p for p in (company, title, seniority, url) if p)
            lines.append(f"- {head}" + (f"\n    {body}" if body else ""))
        return (f"'{query}' 검색 결과 {len(lines)}건:\n" + "\n".join(lines))[:_SEARCH_MAX_CHARS], data

    return ToolSpec(
        name,
        "비슷한 실공고를 검색해 무엇을 요구하는지 확인한다. 이 공고 밖의 시장 사실이 "
        "필요할 때만 쓴다 — 지금 공고의 내용은 read_posting 이 본다.",
        run,
        "찾을 기술·직무를 짧게 적는다(예: 백엔드 Kafka, 프론트엔드 React 신입).",
    )


def upsert_posting_library(session: dict[str, Any], summary: dict) -> list[dict]:
    """정리된 공고를 라이브러리에 올린 목록을 돌려준다(같은 원문은 교체, 상한 초과는 오래된
    것부터 제거). **활성 공고(job_posting)는 하나지만, 정리했던 공고들의 지식은 화이트보드에
    남는다**(D86) — 실측: 두 번째 공고를 주자 첫 공고 질문에 "무관한 회사"라고 답했다."""

    src_hash = summary.get("_sourceHash")
    library = [p for p in (session.get("posting_library") or [])
               if p.get("_sourceHash") != src_hash]
    library.append(summary)
    return library[-_POSTING_LIBRARY_MAX:]


# ---------------------------------------------------------------------------
# 이력서 라이브러리 (D119) — 공고 라이브러리(D86/D88/D111)의 대칭
# ---------------------------------------------------------------------------
# 이력서는 한 대화에 여러 원천에서 온다. **어느 것으로 답했는지 사용자가 알 수 없던 것**이
# 출발점이다(실측 2026-08-02): 커리어 저장소 요약은 조각 제목+완료 노드뿐이라 붙여넣은
# 원문보다 훨씬 얇은데, 같은 질문에 다른 답이 나와도 이유가 화면에 없었다.
_RESUME_ORIGIN_KO = {
    "career_summary": "커리어 저장소",
    "uploaded": "올린 파일",
    "pasted": "붙여넣은 이력서",
}


def resume_identity(resume: dict | None) -> tuple[str, str]:
    """이력서 원천 → (origin 키, 사람이 읽는 라벨).

    **표식을 새로 심지 않는다** — 이미 있는 것에서 파생한다. 파일 업로드는
    `sourceType == "file"` 이 곧 증거이고, 커리어 저장소 요약은 v2bridge 가 이미
    `origin="career_summary"` 를 찍는다(무상태 계약에서 원문을 덮지 않으려고 만든 표식).
    나머지 텍스트는 사용자가 대화창에 넣은 것이다. 새 쓰기 지점이 생기지 않으므로
    다음 입구를 만드는 사람이 지켜야 할 규약도 늘지 않는다.
    """

    if not resume:
        return "", ""
    if (resume.get("sourceType") or "").lower() == "file":
        return "uploaded", (Path(str(resume.get("value") or "")).name or "올린 파일")
    origin = str(resume.get("origin") or "pasted")
    return origin, _RESUME_ORIGIN_KO.get(origin, origin)


def resume_source_hash(resume: dict | None) -> str:
    """이력서 원천의 동일성 키. 원천 종류가 달라도 값이 같으면 같은 이력서다."""

    value = str((resume or {}).get("value") or "")
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _unique_label(base: str, library: list[dict]) -> str:
    """같은 원천이 여럿이면 순번을 붙인다 — 실측(2026-08-02): 이력서 둘을 붙여넣자 라벨이
    둘 다 "붙여넣은 이력서"라 **비교 답변이 어느 쪽을 말하는지 알 수 없었다.**

    기존 항목의 이름은 바꾸지 않는다(첫 것은 접미사 없이 남는다) — 이미 화면에 나간 이름이
    나중에 달라지면 사용자가 부르던 이름이 사라진다. 안정성이 대칭보다 낫다.
    """

    taken = {str(r.get("_label") or "") for r in library}
    if base not in taken:
        return base
    n = 2
    while f"{base} #{n}" in taken:
        n += 1
    return f"{base} #{n}"


def upsert_resume_library(session: dict[str, Any], entry: dict) -> list[dict]:
    """이력서를 라이브러리에 올린 목록(같은 원문은 교체, 상한 초과는 오래된 것부터 제거).

    `upsert_posting_library` 와 같은 규약이다. 다른 점은 **덮어쓰기를 대신하는 것**이라는
    데 있다 — 공고 라이브러리는 "이전 지식을 기억"이지만, 이력서는 새 것이 오면 이전 것이
    통째로 사라지던 자리다.
    """

    src_hash = entry.get("_sourceHash")
    library = [r for r in (session.get("resume_library") or [])
               if r.get("_sourceHash") != src_hash]
    library.append({**entry, "_label": _unique_label(str(entry.get("_label") or ""), library)})
    return library[-_RESUME_LIBRARY_MAX:]


def preserve_active_resume(session: dict[str, Any]) -> list[dict]:
    """활성 이력서가 **교체되기 전에** 라이브러리에 넣은 목록을 돌려준다.

    등록은 평소 `ensure_profile` 한 곳에서만 한다(D119 — 입구마다 심으면 다음 입구를 만드는
    사람이 다시 지켜야 한다). 그런데 그건 **이력서 소비자가 실제로 돈 턴에만** 돈다. 붙여넣기
    직후 대화만 하고 끝난 턴 뒤에 다른 이력서가 오면 이전 원문이 라이브러리에 닿지 못한 채
    사라졌다. 여기는 등록 지점이 아니라 **파괴 직전의 회수 지점**이라 규약이 갈린다.
    """

    resume = session.get("resume")
    library = list(session.get("resume_library") or [])
    if not resume or not str(resume.get("value") or "").strip():
        return library
    src_hash = resume_source_hash(resume)
    if any(r.get("_sourceHash") == src_hash for r in library):
        return library          # 이미 등록됨 (ensure_profile 이 돌았다)
    origin, label = resume_identity(resume)
    return upsert_resume_library(session, {
        **(session.get("profile") or {}),
        "_sourceHash": src_hash,
        "_source": dict(resume),
        "_sourceText": resume_source_text(resume),
        "_origin": origin,
        "_label": label,
    })


# 한 공고에 몇 개의 판정을 기억하나 — 이력서별 비교(D119)가 최대 셋을 넘으면 읽을 수 없다.
_POSTING_ANALYSES_MAX = 3


def attach_analysis(session: dict[str, Any], posting_hash: str, analysis: dict,
                    resume_label: str, library: list[dict] | None = None) -> list[dict] | None:
    """판정 요약을 **그 공고의 라이브러리 항목**에 붙인 목록 (해당 공고가 없으면 None).

    활성 판정(`analysis`)은 슬롯 하나이고 공고·이력서가 바뀔 때마다 무효화된다 — 판정이
    이력서×공고의 함수라 그 무효화 자체는 옳다. 그러나 그래서 **수십 초짜리 판정이 대화에서
    통째로 사라졌다**: "아까 A 공고는 뭐였지?" 에 답할 근거가 0이었다(공고 원문·파싱은
    남는데 판정만 없었다). 라이브러리 항목이 이미 원문을 들고 있으므로 요약을 같이 둔다 —
    새 세션 키도 새 상한 로직도 필요 없다.

    **원본이 아니라 요약을 둔다.** 로드맵·대안 공고까지 5공고분 저장하면 세션이 부풀고,
    조회에 필요한 것은 등급·강점·갭이다. 근거가 필요하면 활성 판정을 다시 돌린다.
    """

    library = list(library if library is not None else (session.get("posting_library") or []))
    index = next((i for i, p in enumerate(library)
                  if p.get("_sourceHash") == posting_hash), None)
    if index is None:
        return None

    def _lines(items: list, *keys: str) -> list[str]:
        out = []
        for item in (items or [])[:3]:
            if isinstance(item, dict):
                out.append(str(next((item.get(k) for k in keys if item.get(k)), "")))
            else:
                out.append(str(item))
        return [t for t in out if t]

    record = {
        "resumeLabel": resume_label,
        "fitGrade": analysis.get("fitGrade"),
        "strengths": _lines(analysis.get("strengths"), "text"),
        "gaps": _lines(analysis.get("gaps"), "reason", "text"),
    }
    entry = dict(library[index])
    kept = [a for a in (entry.get("_analyses") or [])
            if a.get("resumeLabel") != resume_label]
    entry["_analyses"] = (kept + [record])[-_POSTING_ANALYSES_MAX:]
    library[index] = entry
    return library


def match_resume(name: str, library: list[dict]) -> dict | None:
    """지목한 이름 ↔ 라이브러리 항목 — 결정론.

    공고는 `companyName` 이라는 자연스러운 이름이 있지만 이력서에는 없다. 그래서 세 가지를
    받는다: 라벨 부분 일치("커리어 저장소", 파일명) · origin 키 · **1-기반 순번**("2번째").
    순번을 받는 이유는 사용자가 실제로 그렇게 부르기 때문이다.
    """

    key = (name or "").strip()
    if not key or not library:
        return None
    digits = "".join(c for c in key if c.isdigit())
    if digits and not any(c.isalpha() for c in key) and "#" not in key:
        index = int(digits) - 1
        return library[index] if 0 <= index < len(library) else None
    # 정확 일치를 먼저 본다 — 순번 접미사가 붙은 뒤에는 부분 일치만으로는 갈리지 않는다
    # ("붙여넣은 이력서 #2" 안에 "붙여넣은 이력서" 가 들어 있어 첫 항목이 잡혔다).
    for entry in library:
        if str(entry.get("_label") or "") == key:
            return entry
    for entry in library:
        label = str(entry.get("_label") or "")
        origin = str(entry.get("_origin") or "")
        # 사용자는 출처를 한국어로 부른다("커리어 저장소 이력서로 분석해줘") — origin 키
        # (career_summary)만 비교하면 절대 맞지 않는다(실측 2026-08-07 13:22).
        origin_ko = _RESUME_ORIGIN_KO.get(origin, "")
        if ((label and (key in label or label in key))
                or (origin and origin in key.lower())
                or (origin_ko and (origin_ko in key or key in origin_ko))):
            return entry
    return None


def switch_active_resume(session: dict[str, Any], name: str,
                         warnings: list[dict]) -> tuple[dict[str, Any], dict, bool]:
    """지목한 이력서 **하나**를 활성으로 갈아 끼운다. (세션 사본, sessionUpdates, 찾았는가)

    `fit_analysis._switch_active`(공고, D111)와 같은 원리다 — 하류 소비자는 활성 자산 하나만
    보므로, 대상을 바꾸려면 활성 자체를 바꿔야 한다. **`analysis` 는 무효화한다**: 판정은
    이력서×공고의 함수라, 이력서가 바뀌면 이전 판정은 다른 사람의 판정이다.

    못 찾으면 False 를 돌려준다 — 호출자가 활성 이력서로 강행하지 않고 되묻게(D126).
    강행하면 사용자는 그 답이 지목한 이력서의 것인 줄 안다.
    """

    entry = match_resume(name, session.get("resume_library") or [])
    if entry is None:
        warnings.append({
            "code": "resume_target_not_found",
            "message": f"'{name}' 이력서를 기록에서 찾지 못했습니다",
        })
        return session, {}, False
    source = entry.get("_source")
    if not source or source == session.get("resume"):
        return session, {}, True    # 이미 활성이거나, 원천 없이 저장된 옛 항목
    switched = {
        "resume": source,
        "profile": {k: v for k, v in entry.items() if not k.startswith("_")},
        "analysis": None,
    }
    return {**session, **switched}, switched, True


def others_this_turn(session: dict[str, Any], me: str) -> list[str]:
    """이번 턴에 **나 말고** 실행될 담당들의 라벨. 오케스트레이터가 계획을 사본에 실어 준다.

    자기 루프 에이전트는 기본적으로 자기가 턴을 독점한다고 가정하고 답한다. 계획에 여러
    담당이 있으면 그 가정이 사용자 눈에 모순으로 나온다 — 실측(2026-08-01): 사용자가 적합도를
    청한 턴에 정리 단계로 들어간 `resume_diagnosis` 가 "적합도는 제가 못 해요"라고 선언한
    **직후** `fit_analysis` 가 등급을 냈다.

    이건 프롬프트로 못 고친다. 에이전트가 계획을 **모르기** 때문이고, 없는 사실은 지시로
    메울 수 없다(§2-2 의 같은 원리 — 구조로 준다).
    """

    from jobis_ai.orchestrator.router import agent_label

    return [agent_label(n) for n in (session.get("_planThisTurn") or []) if n != me]


def posting_identity(session: dict[str, Any]) -> tuple[str, str]:
    """화이트보드의 **파싱된** 공고에서 (회사명, 직무) — 하류 생성 에이전트의 공통 입력.

    실측으로 찾은 결핍: `coverletter_draft` 의 facts 에 회사명·직무가 아예 없었다 —
    **어느 회사에 내는 자소서인지 모르고** 초안을 썼다. `application_plan` 은 읽으려 했지만
    `session["job_posting"].get("company")` 로 찾아서 늘 빈 값이었다(그 자산은
    `{sourceType, value}` 원천이라 회사명 칸이 없다). 두 곳이 같은 것을 다르게 틀렸다.

    출처 우선순위는 `posting_summary`(파싱 결과, D79 캐시) → `analysis`(판정 산출)다.
    판정을 안 한 상태에서도 공고만 정리하면 회사명이 있으므로 파싱 쪽이 먼저다.
    """

    summary = session.get("posting_summary") or {}
    analysis = session.get("analysis") or {}
    company = str(summary.get("companyName") or analysis.get("companyName") or "").strip()
    role = str(summary.get("jobTitle") or analysis.get("roleTitle") or "").strip()
    return company, role


def agent_arg(session: dict[str, Any], agent: str, name: str) -> str:
    """플래너(LLM)가 이 에이전트에 넘긴 인자 값. 없으면 빈 문자열.

    값이 없으면 에이전트는 **기존대로 세션 자산만 보고** 동작해야 한다 — 인자는 발화에
    값이 실제로 있을 때만 오는 선택 통로다(검증기가 선언된 이름만 통과시킨다).
    """

    args = session.get("_agentArgs") or {}
    return str((args.get(agent) or {}).get(name) or "").strip()


# 수집한 페이지가 공고인지 가르는 어휘. URL 은 주소만으로 공고로 확정되므로(D62,
# detect_posting_urls) 위키·기사·회사 소개 링크도 공고 자산이 된다 — 내용을 손에 쥐는
# 첫 지점이 여기라 여기서 거른다(D102).
_POSTING_MARKERS = (
    "자격요건", "자격 요건", "지원자격", "지원 자격", "우대사항", "우대 사항",
    "담당업무", "주요업무", "주요 업무", "모집부문", "채용", "모집", "전형", "지원방법",
    "responsibilities", "qualifications", "requirements", "we are looking for",
)


def _looks_like_posting(text: str) -> bool:
    """공고 어휘가 **하나라도** 있으면 통과 — 일부러 느슨하다.

    진짜 공고를 거절하는 쪽(가짜 음성)이 잘못된 페이지를 받는 쪽보다 훨씬 아프다.
    주 흐름이 통째로 막히기 때문이다. 정밀한 판별은 뒤의 posting_analysis 가 LLM 으로
    한다 — 여기는 "명백히 공고가 아닌 것"만 걷어내는 문턱이다.
    """

    lowered = (text or "").lower()
    return any(m in lowered for m in _POSTING_MARKERS)


def ensure_posting_text(session: dict[str, Any]) -> tuple[dict | None, list[dict]]:
    """job_posting 자산이 URL 원천이면 지금 수집해 **원문 텍스트 자산으로 승격**한다.

    URL 은 주소일 뿐 내용이 아니다 — 자산으로 남겨 두면 쓰는 곳(파싱·판정)마다 다시
    수집한다: 느리고, 페이지가 바뀌면 같은 대화 안에서 공고 내용이 갈린다. 첫 소비자가
    한 번 수집해 원문을 자산으로 굳히고, 어디서 왔는지는 `sourceUrl` 로 남긴다(D62).

    수집 실패 시 자산을 바꾸지 않는다(다음 턴 재시도 여지) — 경고만 올린다.
    **공고로 보이지 않는 페이지도 실패로 친다**(아래 _looks_like_posting).
    캐시 규약은 ensure_profile 과 같다(write-back 턴에서는 스테이징만).
    반환: (승격/기존 posting, warnings)
    """

    posting = session.get("job_posting")
    if not posting or (posting.get("sourceType") or "text").lower() != "url":
        return posting, []

    from jobis_ai.extract import extract_text  # 지연 임포트: url 자산일 때만 필요

    url = (posting.get("value") or "").strip()
    extracted = extract_text(posting)
    if not extracted.text:
        return posting, extracted.warnings
    if not _looks_like_posting(extracted.text):
        return posting, extracted.warnings + [{
            "code": "not_a_posting",
            "message": f"수집한 페이지에서 공고 어휘를 찾지 못함: {url}",
        }]

    promoted = {"sourceType": "text", "value": extracted.text, "sourceUrl": url}
    _stage(session, {"job_posting": promoted})
    return promoted, extracted.warnings


def _stage(session: dict[str, Any], updates: dict[str, Any]) -> None:
    """세션 사본과 영속 저장소 양쪽에 반영한다.

    캐시는 **저장소를 거쳐** 쓴다. 세션 dict 는 복사본이라 여기서 직접 고쳐도 남지 않는다
    (영속 저장소로 바뀌면서 생긴 규약 — session.py 참고). 저장 대상 세션을 알 수 있을 때만
    캐시하고, 모르면 이번 호출에만 쓰고 버린다.
    """

    session.update(updates)               # 이번 턴 안에서 뒤 단계가 바로 쓰도록
    staged = session.get("_stagedUpdates")
    if isinstance(staged, dict):
        # write-back 턴(chat.handle_chat) 안 — 저장은 턴 끝에 한 번, 여기서는 스테이징만.
        # 직접 store.update 를 하면 턴 끝 write-back 의 profile=None(첨부 무효화 표식)이
        # 방금 만든 캐시를 도로 덮어쓴다.
        staged.update(updates)
        return
    session_id = session.get("_sessionId")
    if session_id:
        from jobis_ai.orchestrator.session import get_session_store

        get_session_store().update(str(session_id), updates)


def resume_source_text(resume: dict | None) -> str:
    """이력서 원천 → 원문 텍스트. 파일이면 추출해서 돌려준다.

    `read_resume` grep 도구가 이걸 쓴다 — 전에는 `resume["value"]` 를 그대로 넘겨서
    **업로드 파일이면 경로 문자열 하나를 원문이라고 훑고 있었다.**
    """

    if not resume:
        return ""
    if (resume.get("sourceType") or "text").lower() == "text":
        return str(resume.get("value") or "")
    from jobis_ai.extract import extract_text

    return extract_text(resume).text


def ensure_profile(session: dict[str, Any]) -> tuple[dict, list[dict]]:
    """세션에서 정규화 프로필을 얻는다. 없으면 이력서 원천으로 빌드해 세션에 캐시한다.

    프로필 빌드는 기존 build_user_profile 노드를 그대로 재사용한다(추출 규율·환각 방어 포함).
    반환: (profile dict, warnings)

    **이력서 라이브러리 등록도 여기서 한다(D119).** 모든 이력서 소비자가 이 함수로 합류하므로
    쓰기 지점이 하나로 끝난다 — 입구(첨부·붙여넣기·커리어 요약)마다 등록을 심으면 다음 입구를
    만드는 사람이 그것을 다시 지켜야 하고, 공고 쪽에서 실제로 그렇게 흩어져 있었다.
    """

    resume = session.get("resume")
    profile = session.get("profile") or {}
    warnings: list[dict] = []
    if not profile:
        updates = build_user_profile({"resumeInput": resume})
        profile = updates.get("normalizedUserProfile") or {}
        warnings = updates.get("warnings") or []

    if not resume:
        return profile, warnings

    src_hash = resume_source_hash(resume)
    library = list(session.get("resume_library") or [])
    known = next((r for r in library if r.get("_sourceHash") == src_hash), None)
    if known is not None and session.get("profile"):
        return profile, warnings      # 이미 등록됐고 프로필도 캐시됨 — 할 일 없음

    origin, label = resume_identity(resume)
    entry = {
        **profile,
        "_sourceHash": src_hash,
        # 원천 dict 를 통째로 보존한다 — 활성 전환이 이걸 되돌려 놓으면 무손실이다
        # (공고는 URL 이 변하므로 텍스트로 굳혔지만, 이력서 원천은 세션 안에서 안정적이다).
        "_source": dict(resume),
        "_sourceText": (known or {}).get("_sourceText") or resume_source_text(resume),
        "_origin": origin,
        "_label": label,
    }
    _stage(session, {"profile": profile,
                     "resume_library": upsert_resume_library(session, entry)})
    return profile, warnings

"""공고 담당 에이전트 — 공고에 관한 **모든 질문**을 공고 원문을 근거로 받는다.

부분 자산의 우아한 대응(graceful degradation): 적합도 분석에는 이력서가 필요하지만,
공고만 있어도 "이 공고가 무엇을 요구하는가"는 알려줄 수 있다. 되묻기만 하고 끝나는 대신
**정리 결과를 먼저 주고** 이력서를 자연스럽게 요청한다 — 오케스트레이터가 존재하는 이유.

**도구에서 대화형 에이전트로 승격됐다(D97).** 계기는 실측이다(2026-07-31 로그): 공고를 정리한
뒤 사용자가 "이 공고 기준으로 어떤 스택을 공부하고 어떤 프로젝트를 하면 좋을까"를 물었는데,
어휘 11종 중 그 질문의 담당이 없어 플래너가 `fit_analysis`→`application_plan` 을 골랐고
이력서가 얇아 5개를 되물으며 끝났다(`요청 미완수 — application_plan`). 공고만으로 답할 수
있는 질문에 사용자 정보를 요구한 것이다.

승격의 규율 — **자율성은 표현에, 근거는 도구에.**
  · 파싱(`parse_job_posting`)·캐시·요약 표는 그대로 결정론이다. 루프가 다시 쓰지 않는다.
  · 루프의 LLM 은 파싱 사실과 `read_posting`(원문 검색)이 준 것만으로 말한다(§2-5).
  · LLM 이 없거나 검증을 통과 못 하면 승격 전과 **똑같이** `tool_render` 폴백으로 답한다.

판정하지 않는다 — 적합/불충분은 말하지 않는다(그건 판정 엔진의 일).
"""

from __future__ import annotations

import contextvars
import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import (
    ensure_posting_text,
    grep_source_lines,
    others_this_turn,
    upsert_posting_library,
)
from jobis_ai.agents.agent_loop import ToolSpec, run_agent_loop
from jobis_ai.graph.nodes import parse_job_posting


def _analyze_one_url(session: dict, url: str) -> tuple[dict | None, list[dict]]:
    """추가 공고 URL 하나 → 수집·파싱된 요약(해시 포함). 라이브러리에 같은 원문이 있으면 재사용."""

    from jobis_ai.extract import extract_text

    extracted = extract_text({"sourceType": "url", "value": url})
    if not extracted.text:
        return None, list(extracted.warnings) + [{
            "code": "extra_posting_fetch_failed",
            "message": f"추가 공고 수집 실패: {url}"}]
    source_hash = hashlib.md5(extracted.text.encode("utf-8")).hexdigest()
    cached = next((p for p in (session.get("posting_library") or [])
                   if p.get("_sourceHash") == source_hash), None)
    if cached:
        return dict(cached), list(extracted.warnings)
    update = parse_job_posting({
        "jobPostingInput": {"sourceType": "text", "value": extracted.text, "sourceUrl": url},
        "sources": [], "toolLog": [], "warnings": [], "retryCount": {},
    })
    posting = update.get("normalizedJobPosting") or {}
    warnings = list(extracted.warnings) + list(update.get("warnings") or [])
    if not any(posting.get(k) for k in ("requiredRequirements", "preferredRequirements",
                                        "techStack", "jobTitle")):
        return None, warnings + [{"code": "posting_unreadable",
                                  "message": f"추가 공고에서 요구사항을 읽지 못했습니다: {url}"}]
    return {**posting, "_sourceHash": source_hash, "_sourceText": extracted.text}, warnings


def _analyze_extra_urls(session: dict, urls: list[str]) -> tuple[list[dict], list[dict]]:
    """추가 공고 URL 들을 **병렬로** 수집·파싱한다(D94) — 두 공고를 한 턴에 냈는데 하나만
    처리되던 실측의 수정. 워커에 contextvars 를 복사해 trace·LLM 집계가 끊기지 않게 한다
    (orchestrator._run_parallel 과 같은 규율)."""

    if not urls:
        return [], []
    with ThreadPoolExecutor(max_workers=min(3, len(urls))) as pool:
        futures = [pool.submit(contextvars.copy_context().run, _analyze_one_url, session, u)
                   for u in urls]
        results = [f.result() for f in futures]
    summaries = [s for s, _ in results if s]
    warnings = [w for _, ws in results for w in ws]
    return summaries, warnings

def _parse(session: dict) -> tuple[dict, dict, dict, list[dict], str]:
    """세션의 공고 원문 → 파싱 결과. **결정론 — 여기까지가 근거다(LLM 은 파싱 1콜뿐).**

    반환: (활성 공고, AgentResult.data, sessionUpdates, warnings, 원문 텍스트)

    **같은 원문은 다시 파싱하지 않는다(D79)** — 파싱 결과를 세션(`posting_summary`)에
    해시와 함께 캐시하고, 원문이 같으면 재사용한다. 실측(2026-07-31): 앞 턴에 분석을
    끝낸 공고를 "필수 항목이 뭐였지?"로 되묻자 LLM 파싱이 통째로 다시 돌았다 —
    분석은 데이터로 담아 두고 다시 보는 것이지, 매번 다시 하는 것이 아니다.
    """

    # URL 자산이면 먼저 수집해 원문으로 승격한다(D62) — 이후 소비자는 재수집하지 않는다.
    posting_input, fetch_warnings = ensure_posting_text(session)
    source_hash = hashlib.md5(
        (posting_input.get("value") or "").encode("utf-8")).hexdigest()
    cached = session.get("posting_summary") or {}
    session_updates: dict = {}
    from_cache = cached.get("_sourceHash") == source_hash
    if from_cache:
        posting = {k: v for k, v in cached.items() if not k.startswith("_")}
        warnings = list(fetch_warnings)
    else:
        state = {
            "jobPostingInput": posting_input,
            "sources": [], "toolLog": [], "warnings": [], "retryCount": {},
        }
        update = parse_job_posting(state)
        posting = update.get("normalizedJobPosting") or {}
        warnings = fetch_warnings + update.get("warnings", [])
        if posting:
            # `_sourceText` — 라이브러리 항목이 원문을 들고 있어야 나중에 그 공고를 활성으로
            # 되돌릴 수 있다(fit_analysis._switch_active). 밑줄 키는 화면·프롬프트로 나가지
            # 않는다(소비자가 필드를 골라 쓴다 — posting_facts/job_items).
            summary = {**posting, "_sourceHash": source_hash,
                       "_sourceText": posting_input.get("value") or ""}
            session_updates = {"posting_summary": summary,
                               "posting_library": upsert_posting_library(session, summary)}
            # 새 공고가 들어온 시점에 RAG 캐시를 예열한다(D96) — 뒤에 올 대안 검색·추천의
            # 첫 쿼리 지연을 지금 백그라운드로 지불한다. 결과는 버린다.
            from jobis_ai.rag import warm_search_async

            warm_search_async(" ".join(filter(None, [
                str(posting.get("jobTitle") or ""),
                *[str(t) for t in (posting.get("techStack") or [])[:5]],
            ])))

    readable = any(
        posting.get(k)
        for k in ("requiredRequirements", "preferredRequirements", "techStack", "jobTitle")
    )
    if not readable:
        # 산출물 검증(M5) — 요건·스택을 하나도 못 읽었는데 조용히 완료로 흐르면
        # "정상처럼 보이는 빈 정리"가 된다(§2-6 폴백은 이유를 삼키지 않는다).
        warnings.append({"code": "posting_unreadable",
                         "message": "공고에서 요구사항·기술 스택을 하나도 읽지 못했습니다"})

    # 같은 턴에 URL 이 여러 개 왔으면(D94) 나머지를 병렬로 수집·파싱해 라이브러리로 승격.
    extra_summaries, extra_warnings = _analyze_extra_urls(
        session, list(session.get("_extraPostingUrls") or []))
    warnings.extend(extra_warnings)
    extra_postings: list[dict] = []
    if extra_summaries:
        lib_session = dict(session)
        lib_session["posting_library"] = (
            session_updates.get("posting_library") or session.get("posting_library") or [])
        for summary in extra_summaries:
            lib_session["posting_library"] = upsert_posting_library(lib_session, summary)
            extra_postings.append({k: v for k, v in summary.items() if not k.startswith("_")})
        session_updates["posting_library"] = lib_session["posting_library"]
        if "posting_summary" not in session_updates and not from_cache and posting:
            # 활성 공고 파싱이 비어도(희귀) 라이브러리 갱신은 유지한다.
            pass

    # fromCache — 이미 보여준 공고의 조회성 재실행 신호. 표를 다시 내지 않고 물은 것에만
    # 답하는 데 쓴다(D81).
    data = {"postingAnalysis": posting, "readable": readable, "fromCache": from_cache,
            "extraPostings": extra_postings}
    return posting, data, session_updates, warnings, str(posting_input.get("value") or "")


def _tool_read_posting(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """공고 **원문**에서 키워드가 든 줄을 찾는다 — 파싱 스키마에 칸이 없는 항목의 근거."""

    return grep_source_lines(state.get("_text") or "", arg, label="공고"), {}


def requirement_index(posting: dict) -> dict[str, str]:
    """요구사항 ID → 문장. 제안이 인용할 수 있는 **근거 목록**이다.

    파서가 이미 `req-1`·`pref-1` 같은 안정 ID 를 붙여 둔다 — 새로 만들지 않는다.

    **연차 요건은 빠진다.** 실측(2026-08-01): 첫 구현에서 루프가 "상담 데이터 RAG 파이프라인"
    프로젝트가 `req-1`("데이터 엔지니어링 또는 ML 엔지니어링 경력 3~7년")을 커버한다고 적었다.
    **프로젝트로 연차를 채울 수는 없다** — 외부 리뷰가 지적한 "포트폴리오가 연차를 대체할 수
    없다"가 그것이다. 커버 대상에서 빼면 루프가 그렇게 적을 수 없다(§2-2 — 하면 안 되는 것은
    선택지에서 뺀다).

    판정 기준은 `graph.nodes._build_comparison_requirements` 와 같다: 공고가 한 말
    (`yearsEvidence`)이 문장에 있고 기술 토큰이 함께 없으면 **순수 연차 줄**이다. 기술이 섞인
    줄("Python 경력 2년 이상")은 기술 요건이기도 하므로 남긴다.
    """

    evidence = str(posting.get("yearsEvidence") or "").strip()
    tech = [str(t).lower() for t in (posting.get("techStack") or [])]

    def _pure_years(text: str) -> bool:
        if not evidence or evidence not in text:
            return False
        rest = text.replace(evidence, " ").lower()
        return not any(t in rest for t in tech)

    return {
        str(r.get("requirementId") or ""): str(r.get("text") or "")
        for key in ("requiredRequirements", "preferredRequirements")
        for r in (posting.get(key) or [])
        if r.get("requirementId") and r.get("text") and not _pure_years(str(r["text"]))
    }


def _tool_save_plan(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """프로젝트 제안을 기록한다. **커버하는 요구사항 ID 를 못 대면 거부한다.**

    외부 리뷰(2026-08-01)의 지적: 제안된 프로젝트가 "거의 모든 AI/데이터 공고에 그대로 나올
    답"이었다. 리뷰의 처방은 "프롬프트에 근거 명시를 강제하라"였지만 그 방식은 §2-2·§3-1 이
    실측으로 부정했다 — **줄 수 없는 답은 스키마에서 필드를 뺀다.** 여기서는 반대로, 근거
    필드를 **필수로** 만들고 도구가 검증한다: 공고에 없는 ID 를 대면 기록되지 않는다.

    형식(블록 반복):

        프로젝트: 제목
        설명: 무엇을 만들고 무엇을 보여주나
        커버: req-1, pref-3
        완료: 무엇이 되면 끝났다고 볼 수 있나

    `완료`는 선택이다. **예상 소요 기간 칸은 두지 않는다** — 데이터가 없어 LLM 이 지어내게
    되고, 지어낸 값이 계획처럼 보이면 §2-1 위반이다(리뷰 제안 중 받지 않은 항목).
    """

    index: dict[str, str] = state.get("_requirements") or {}
    if not index:
        return "이 공고에서 요구사항을 읽어내지 못해 제안을 기록할 수 없습니다.", {}

    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in (arg or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        head, _, rest = line.partition(":")
        key, value = head.strip(), rest.strip()
        if key == "프로젝트":
            current = {"title": value, "detail": "", "covers": [], "done": ""}
            blocks.append(current)
        elif current is None:
            continue
        elif key == "설명":
            current["detail"] = value
        elif key == "커버":
            current["covers"] = [c.strip() for c in value.split(",") if c.strip()]
        elif key == "완료":
            current["done"] = value

    if not blocks:
        return ("형식이 맞지 않습니다. 블록마다 '프로젝트:', '설명:', '커버:'(요구사항 ID 를 "
                f"쉼표로), '완료:' 로 적어 주세요. 쓸 수 있는 ID: {', '.join(index)}"), {}

    # 검증은 결정론이다 — 근거를 못 대면 기록하지 않고 무엇이 틀렸는지 관찰로 돌려준다.
    rejected: list[str] = []
    accepted: list[dict[str, Any]] = []
    for block in blocks:
        title = block["title"] or "(제목 없음)"
        if not block["title"]:
            rejected.append(f"'{title}': 제목이 비었습니다")
            continue
        if not block["covers"]:
            rejected.append(f"'{title}': 커버하는 요구사항 ID 가 없습니다")
            continue
        unknown = [c for c in block["covers"] if c not in index]
        if unknown:
            rejected.append(f"'{title}': 이 공고에 없는 ID {unknown}")
            continue
        accepted.append(block)

    if accepted:
        state["plan"] = accepted
    if rejected:
        return (f"기록 거부 {len(rejected)}건 — " + " / ".join(rejected)
                + f". 쓸 수 있는 ID: {', '.join(index)}."
                + (f" (기록된 제안 {len(accepted)}건)" if accepted else "")), {}
    return (f"제안 {len(accepted)}건을 기록했습니다: "
            + " / ".join(f"{b['title']}(커버 {', '.join(b['covers'])})" for b in accepted)), {}


_TOOLS = {
    t.name: t for t in (
        ToolSpec("read_posting",
                 "공고 원문에서 키워드가 든 줄을 찾는다. 파싱 요약에 없는 항목을 확인할 때.",
                 _tool_read_posting,
                 "찾을 낱말을 쉼표로 구분해 적는다(예: 전형, 복리후생). 원문 앞부분을 그냥 "
                 "보려면 빈 문자열."),
        ToolSpec("save_plan",
                 "프로젝트 제안을 기록한다. **커버하는 요구사항 ID 를 대야 기록된다** — "
                 "공고에 없는 ID 나 빈 커버는 거부되고 이유를 알려준다.",
                 _tool_save_plan,
                 "블록마다 네 줄:\n프로젝트: 제목\n설명: 무엇을 만들고 무엇을 보여주나\n"
                 "커버: req-1, pref-3   (facts.requirements 의 ID 만)\n완료: 무엇이 되면 끝인가\n"
                 "여러 제안은 블록을 반복한다."),
    )
}

_GOAL_SYSTEM = """너는 취업 서비스의 **공고 담당** 상담원이다. 사용자가 이 공고에 관해 무엇을 묻든
공고에서 확인된 사실만을 근거로 답한다.

입력:
- facts.userMessage: 사용자가 물은 것. **이것에 대한 답이 응답의 본문이다.** 물은 것을
  "해드릴 수 있습니다"로 되돌려 묻지 않는다 — 물었으면 이번 턴에 답한다.
- facts.posting: 파싱된 활성 공고(필수 요건·우대 사항·요구 기술·요구 연차). 간단한 질문은 이것으로 답한다.
- facts.otherPostings: 이 대화의 다른 공고들(앞서 정리한 것 + 이번 턴에 함께 받은 것).
  사용자가 그 회사를 물으면 여기서 답한다. 여러 공고를 함께 물으면 회사별로 나눠 답한다.
- facts.othersThisTurn: **이번 턴에 이어서 실행되는 다른 담당들.** 비어 있지 않으면 사용자가
  물은 것 중 네 몫이 아닌 부분은 그들이 처리한다 — **"저는 그건 못 해요"라고 말하지 않는다.**
  네가 할 수 있는 부분만 답하고, 나머지를 언급하지 말고 넘긴다(그들의 답이 바로 뒤에 붙는다).
- facts.firstLook: true 면 이 공고를 **방금 받은** 턴이다. 사용자가 **아무것도 묻지 않았으면**
  (자료만 보냈으면) 무엇을 요구하는 공고인지 항목별 줄로 정리해 보여주는 것이 곧 답이다.
  이때는 **빠뜨리지 않는 것이 목적이다**: 필수 요건과 우대 사항을 하나도 빼지 말고 전부 적고,
  요구 연차는 facts.posting.yearsEvidence(공고가 한 말)로 적는다. 그리고 파싱 요약에 칸이
  없는 조건(고용 형태·계약 기간·근무지·근무 시간·마감일·접수 방법·전형 절차·복리후생)은
  **read_posting 으로 원문을 확인한 뒤** 있는 것만 함께 정리한다. 낱말 몇 개로 한 번에 끝내지
  말고, 안 걸린 항목은 다른 낱말로 한 번 더 찾아본다. 원문에 없는 항목은 그냥 뺀다 —
  **"…는 기재가 없습니다"라고 쓰지 않는다.** 못 찾은 것과 안 적힌 것을 구별할 수 없는데
  없다고 단정하면 사용자가 원문에 있는 조건을 놓친다(실측 2026-08-02: 근무시간·복리후생이
  원문에 있는데 "기재 없음"으로 나갔다).
  **물은 것이 있으면 그 답이 본문이고**, 요건은 답에 필요한 만큼만 인용한다(전체 목록을
  따로 낭독하지 않는다). false 면 이미 정리해 본 공고의 후속 질문이므로 물은 것만 답한다.

하는 일:
- **무엇을 공부할지·어떤 프로젝트를 만들지 물으면** 답한다. 근거는 공고가 요구한 항목이다 —
  필수 요건을 먼저, 우대 사항을 다음으로 두고 학습 순서를 세운다. 공고에 없는 기술을 끌어와
  추천하지 않는다(추상 요건을 구체 도구로 옮기는 것은 괜찮다 — "상태 관리 라이브러리" → Redux).
- **프로젝트를 제안할 때는 save_plan 으로 기록한다.** 제안마다 **커버하는 요구사항 ID**
  (facts.requirements 의 `req-*`·`pref-*`)를 대야 기록된다 — 어느 요건을 증명하는지 못 대는
  제안은 그 공고에서 나온 제안이 아니다. 기록된 제안은 시스템이 답변에 붙여 주므로
  **본문에서 다시 나열하지 않는다.** 도구가 거부하면 이유를 보고 고쳐 다시 부른다.
- 파싱 요약에 칸이 없는 것(전형 절차·근무 형태·복리후생·마감)을 물으면 read_posting 으로
  원문을 확인한 뒤 답한다. **원문에도 없으면 공고에 적혀 있지 않다고 말한다.**
- 요건의 뜻을 풀어 설명하거나 난이도·우선순위를 정리해 달라는 요청도 받는다.

하지 않는 일:
- 적합도·합격 가능성 판정. 이력서와 대조하는 것은 다른 담당의 일이다 — 사용자의 경력을
  모르는 상태에서 "충족한다/부족하다"를 말하지 않는다.
- 회사 평판·연봉 수준·조직 문화 추정. 공고에 적힌 것만 쓴다.
- 사용자의 이력·경력을 가정하기. 모르면 모르는 채로 공고 기준으로만 답한다.

답변은 사용자가 방금 한 말에 먼저 답하고, 필요하면 다음에 무엇을 해볼지 한 문장으로 제안한다.
목록이 길어지면 항목별 줄로 나눠 쓴다."""


def run(session: dict) -> AgentResult:
    """공고를 파싱해(결정론) 그 사실만으로 사용자의 질문에 답한다(루프).

    문장 조립 규칙 — 요약 표는 **처음 정리한 턴에만** 붙인다(D81 의 재낭독 금지를 승격 후에도
    유지). 후속 질문 턴은 루프의 답변만 나간다.

    루프가 검증 통과 문장을 못 만들면 `tool_render.render_posting_analysis` 로 폴백한다 —
    LLM 미설정 환경에서 승격 전과 동일하게 동작한다(§2-6: 폴백은 이유를 warnings 로 남긴다).
    """

    from jobis_ai.agents import tool_render

    posting, data, session_updates, warnings, text = _parse(session)
    readable, from_cache = data["readable"], data["fromCache"]

    # 카드에 실리는 질문은 **결정론**이다. 맥락을 살린 문장은 루프가 쓰고 대화 답변으로 나간다
    # — 데이터 계약(질문 카드)과 표현을 같은 문자열로 묶지 않는다.
    #
    # **이미 있는 이력서를 다시 청하지 않는다(D98).** 이 카드가 프론트의 자료 요청 슬롯을 열고,
    # 그 슬롯으로 들어온 짧은 대답이 저장된 이력서를 교체하던 것이 사고의 입구였다. 저장 쪽
    # 가드(`chat._apply_attachments`)와 **양쪽 다** 닫는다 — 하나만 닫으면 다음 카드가 같은
    # 슬롯을 다시 연다.
    has_resume = bool(session.get("resume") or session.get("profile"))
    follow_up = ([] if not readable or has_resume else [{
        "field": "resume",
        "question": "이 요건들과 대조해 적합도를 분석해 드릴게요. 이력서(또는 경력·기술 소개)를 주시겠어요?",
    }])

    def _fallback() -> AgentResult:
        reply, render_warnings = tool_render.render_posting_analysis(data, session)
        return AgentResult(reply=reply, data=data, sessionUpdates=session_updates,
                           warnings=warnings + render_warnings, followUpQuestions=follow_up)

    if not readable:
        # 읽어내지 못한 공고로는 대화할 근거가 없다 — 루프를 돌리지 않는다.
        return _fallback()

    # 활성 공고의 해시 — 세션이 아니라 **원문에서** 다시 센다. 캐시 미스 턴에는 세션의
    # posting_summary 가 아직 이전 공고이므로, 그걸 기준으로 걸러내면 활성 공고가
    # otherPostings 에 중복으로 실린다.
    source_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    # 제안이 인용할 근거 목록 — 도구가 이것으로 ID 를 검증한다(D103 의 짝).
    requirements = requirement_index(posting)
    state_plan: list[dict] = []
    loop_state = {"_session": dict(session), "_text": text,
                  "_requirements": requirements, "plan": state_plan}
    outcome = run_agent_loop(
        goal_system=_GOAL_SYSTEM,
        facts={
            "userMessage": str(session.get("last_message") or ""),
            "posting": tool_render.posting_facts(posting),
            # 다른 공고들 — 승격 전 `_posting_recall_answer` 가 하던 교차 조회를 루프가
            # 이어받는다(D81). 이게 없으면 "네이버는 뭐였지?"에 답할 근거가 사라진다.
            # **이번 턴에 함께 받은 공고(D94)를 세션에서 찾을 수 없다** — sessionUpdates 는
            # 턴 끝에 반영되므로 여기의 posting_library 는 아직 이전 턴 것이다. 그래서
            # extraPostings 를 직접 얹는다(두 공고를 한 턴에 냈는데 하나만 아는 것을 막는다).
            "otherPostings": ([tool_render.posting_facts(p) for p in data["extraPostings"]]
                              + [tool_render.posting_facts(p)
                                 for p in (session.get("posting_library") or [])
                                 if p.get("_sourceHash") != source_hash])[:5],
            "firstLook": not from_cache,
            "hasResume": bool(session.get("resume") or session.get("profile")),
            "othersThisTurn": others_this_turn(session, "posting_analysis"),
            # 프로젝트 제안이 커버 ID 로 인용할 수 있는 요구사항. save_plan 이 검증한다.
            "requirements": requirements,
        },
        tools=_TOOLS,
        state=loop_state,
        node="posting_analysis",
        session_id=str(session.get("_sessionId") or ""),
    )
    warnings.extend(outcome.warnings)
    if not outcome.reply:
        return _fallback()

    # **루프가 답하면 그 답이 전부다.** 결정론 요약 표를 앞에 붙이지 않는다 — 실측
    # (2026-08-01 로그): 표를 붙였더니 루프가 611자로 같은 요건을 다시 정리한 뒤 제안을
    # 이어 붙여 사용자가 같은 목록을 두 번 봤다. goal_system 에 "다시 나열하지 말라"고
    # 적어 뒀지만 안 지켜졌다 — 한 문장의 생산자가 둘이면 프롬프트로는 못 막는다(§2-2).
    # 표는 폴백(LLM 미설정) 경로에만 남는다. 항목의 완전성은 산문이 아니라 우측 패널의
    # 구조화 데이터(`data["postingAnalysis"]`)가 보장한다.
    data["loopSteps"] = outcome.steps
    plan = list(loop_state.get("plan") or [])
    if plan:
        # 제안 본문은 **결정론 조립**이다 — 커버하는 요건을 문장으로 펼쳐 사용자가 근거를
        # 눈으로 확인할 수 있게 한다. 루프가 자유 문장으로 다시 쓰면 근거 표시가 흐려진다.
        data["planProposals"] = plan
        blocks = []
        for i, item in enumerate(plan, start=1):
            covered = " · ".join(requirements.get(c, c) for c in item["covers"])
            lines = [f"{i}. **{item['title']}**"]
            if item.get("detail"):
                lines.append(f"   {item['detail']}")
            lines.append(f"   커버하는 요건: {covered}")
            if item.get("done"):
                lines.append(f"   완료 기준: {item['done']}")
            blocks.append("\n".join(lines))
        reply = outcome.reply + "\n\n프로젝트 제안\n" + "\n".join(blocks)
    else:
        reply = outcome.reply
    return AgentResult(reply=reply, data=data, sessionUpdates=session_updates,
                       warnings=warnings, followUpQuestions=follow_up)

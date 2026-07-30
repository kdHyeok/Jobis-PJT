"""도구 산출물 → 사용자향 문장. **표현 계층.**

도구는 말하지 않는다(`AgentSpec` docstring). 계산은 도구가 하고, 그 결과를 사람이 읽는
문장으로 바꾸는 책임은 여기에 있다. 그래서 도구는 데이터 계약만 지키면 되고, 문구를 고칠
때 계산 코드를 건드리지 않는다.

여기 함수들은 **도구가 낸 값만** 옮겨 적는다 — 새 판단·수치·회사명을 만들지 않는다.
대부분은 결정론 문자열 조립이고, LLM 표현이 필요한 자리도 여기다(`render_fit_analysis` 의
다음 행동 제안). LLM 을 쓰는 표현은 두 가지를 지킨다: **금지표현 검증을 통과해야 하고,
실패하면 결정론 폴백 + 그 이유(warnings)를 함께 돌려준다.** 그래서 모든 render 는
`(문장, 경고들)` 을 낸다 — 경고를 못 돌려주면 폴백 이유가 조용히 사라진다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jobis_ai.role_taxonomy import SENIORITY_KO
from jobis_ai.structured import run_streaming_text, run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS
from pydantic import BaseModel, Field

_MAX_ROADMAP_ITEMS_IN_REPLY = 5
_MAX_ALTERNATIVES_SHOWN = 3

_ALT_TYPE_LABEL = {
    "similar_role": "비슷한 직무",
    "lower_seniority": "요구 연차가 낮은 자리",
    "similar_stack": "기술 스택이 겹치는 자리",
    "stepping_stone": "징검다리 경로",
}

# 출력이 문장 하나뿐인 표현 — 구조화 출력 대신 토큰 스트리밍(평가 문서 §3-2).
# 문장 요건(질문형·분량)은 시스템 프롬프트가 담고, 검증은 완성본에 사후 수행한다.
_NEXT_SYSTEM = """너는 취업 서비스의 대화 상담원이다. 방금 공고×이력서 적합도 판정 결과를 사용자에게 보여줬다.
그 아래에 붙일 다음 행동 제안 문장만 출력한다 — 한두 문장.
- facts 의 grade(상/중/하)·topGap 에 맞는 다음 행동만 제안한다. 예: 격차가 크면 로드맵·대안 공고,
  적합도가 높으면 자소서·면접 준비.
- 제안 가능한 것: 준비 로드맵 확인, 자소서 초안 작성, 면접 예상 질문, 대안 공고 탐색.
- 응답은 무엇부터 할지 묻는 질문으로 끝난다. 두 문장 이내. 합격 가능성 단정 금지.
- 판정 내용을 다시 요약하지 않는다."""


def render_job_recommend(data: dict[str, Any], session: dict[str, Any]) -> tuple[str, list[dict]]:
    """공고 추천 결과 → 문장. 추천마다 URL 을 붙인다(붙여넣으면 그 공고 분석으로 이어진다)."""

    recommendations = list(data.get("recommendations") or [])
    pref_terms = list(data.get("preferenceTerms") or [])
    profile_known = bool(data.get("profileKnown"))
    dropped = int(data.get("droppedByExperience") or 0)
    user_years = data.get("userExperienceYears")

    if recommendations:
        pref_note = (
            f"말씀해주신 선호({', '.join(pref_terms[:4])})를 반영해 " if pref_terms else ""
        )
        lines = []
        for r in recommendations:
            link = f" — {r['url']}" if r.get("url") else ""
            # 이력서가 없으면 역량 일치 수를 세지 않았으니 적지 않는다 — 0 개로 적으면
            # "역량이 하나도 안 맞는다"는 없는 판정을 말하는 셈이 된다.
            gauge = (f" ({len(r['matchedSkills'])}개 역량 일치)" if profile_known
                     else (f" (선호 {len(r['matchedPreferences'])}개 일치)"
                           if r["matchedPreferences"] else ""))
            # 공고 표기 연차를 함께 보여준다 — 걸러낸 기준을 사용자가 눈으로 확인할 수 있게.
            years = f" · 연차 {r['experience']}" if r.get("experience") else ""
            lines.append(
                f"· **{r['companyName'] or r['title']}** | {r['title'][:40]}{gauge}{years}{link}")
        head = (f"{pref_note}보유 역량과 매칭되는 공고 {len(recommendations)}건을 찾았습니다."
                if profile_known else
                f"{pref_note}공고 {len(recommendations)}건을 찾았습니다. "
                "이력서를 아직 못 받아 보유 역량과의 일치는 계산하지 않았어요.")
        if dropped:
            head += f" 연차가 맞지 않는 공고 {dropped}건은 제외했어요."
        tail = ("\n\n관심 있는 공고의 URL 을 붙여넣으시면 그 공고로 상세 적합도 분석을 이어서 해드릴게요."
                if profile_known else
                "\n\n관심 있는 공고의 URL 과 이력서를 주시면 그 공고로 상세 적합도 분석까지 해드릴게요.")
        return head + "\n" + "\n".join(lines) + tail, []

    if data.get("emptyQuery"):
        return ("이력서에서 검색에 쓸 기술·직무 정보를 찾지 못했습니다. 이력서에 기술 스택이 담겨 있는지 확인해 주세요."
                if profile_known else
                "어떤 공고를 찾아드릴지 아직 단서가 없어요. 관심 직군이나 기술 스택, 지역을 알려주시면 찾아볼게요."), []

    if dropped:
        # 검색은 됐는데 연차로 전부 걸러진 경우 — "검색 결과가 없다"고 하면 사실과 다르다.
        level = "신입" if (user_years or 0) <= 0 else f"{user_years:g}년"
        return (f"찾은 공고 {dropped}건이 모두 {level} 조건과 맞지 않아 추천에서 제외했어요. "
                "조건을 넓혀볼까요? 관심 직군·기술을 조금 더 알려주시거나, 연차 조건 없이 보고 싶으면 말씀해 주세요."), []

    # 실공고 없이 추천을 지어내지 않는다.
    return ("실제 공고 검색(RAG)에서 결과를 얻지 못해 추천을 만들 수 없습니다. "
            "공고 데이터 연결 후 다시 시도해 주세요."), []


def render_roadmap_manager(data: dict[str, Any], session: dict[str, Any]) -> tuple[str, list[dict]]:
    """저장된 준비 로드맵 → 문장."""

    roadmap = list(data.get("roadmap") or [])
    if not roadmap:
        return "저장된 로드맵이 없습니다. 공고 적합도 분석을 실행하면 준비 로드맵이 함께 만들어져요.", []

    lines = []
    for item in roadmap[:_MAX_ROADMAP_ITEMS_IN_REPLY]:
        period = f"{item.get('startDate', '')}~{item.get('endDate', '')}".strip("~")
        lines.append(
            f"[{item.get('priority', 'medium')}] {item.get('title', '')}"
            + (f" ({period})" if period else "")
        )
    return (
        f"현재 로드맵에 {len(roadmap)}개 항목이 있습니다. "
        + " / ".join(lines)
        + (" …" if len(roadmap) > _MAX_ROADMAP_ITEMS_IN_REPLY else "")
        + " — 항목 수정이나 진척 체크 기능은 준비 중이에요."
    ), []


# --- fit_analysis — 판정(도구)의 표현 ---------------------------------------------
def _alternatives_block(alternative_jobs: list) -> str:
    """대안 공고를 답변에 붙일 블록으로. 없으면 빈 문자열(없는 걸 있다고 말하지 않는다).

    LLM 을 쓰지 않는다 — 판정 엔진이 낸 값을 표기만 바꿔 옮긴다.
    """

    if not alternative_jobs:
        return ""
    lines = []
    for job in alternative_jobs[:_MAX_ALTERNATIVES_SHOWN]:
        job = job if isinstance(job, dict) else job.model_dump()
        kind = _ALT_TYPE_LABEL.get(str(job.get("type") or ""), "대안 경로")
        name = str(job.get("companyName") or "").strip()
        title = str(job.get("title") or "").strip()
        head = f"{name} | {title}" if name else title
        link = f" — {job['url']}" if job.get("url") else ""
        reduced = job.get("reducedGaps") or []
        why = f" (부족했던 {len(reduced)}개 요건을 요구하지 않음)" if reduced else ""
        lines.append(f"· [{kind}] **{head}**{why}{link}")
    return ("\n\n지금 격차를 감안한 대안도 찾아봤어요.\n" + "\n".join(lines)
            + "\n(URL 이 있는 공고는 그대로 붙여넣으시면 그 공고로 분석해 드려요.)")


def _next_steps(facts: dict) -> tuple[str, list[dict]]:
    """다음 행동 제안 — LLM 표현(스트리밍) + 검증(금지표현·질문형), 실패 시 결정론 폴백."""

    fallback = ("이 결과로 준비 로드맵 확인, 자소서 초안, 면접 예상 질문, 대안 공고 탐색을 "
                "이어서 할 수 있어요. 무엇부터 해볼까요?")
    text, warnings = run_streaming_text(
        _NEXT_SYSTEM, json.dumps(facts, ensure_ascii=False),
        node="fit_analysis_next",
    )
    text = text.strip()
    if not text or "?" not in text or any(expr in text for expr in FORBIDDEN_EXPRESSIONS):
        return fallback, warnings
    return text, warnings


def render_fit_analysis(data: dict[str, Any], session: dict[str, Any]) -> tuple[str, list[dict]]:
    """적합도 판정 결과 → 문장. **판정은 한 줄도 하지 않는다** — 낸 값을 옮겨 적을 뿐이다."""

    if data.get("status") == "need_more_info":
        # 무엇이 부족한지 **그 자리에서** 말한다. "아래 질문에 답해 주세요"라고만 하고 질문을
        # 싣지 않으면(대화 채널에는 질문 카드가 없다) 사용자는 무엇을 해야 할지 알 수 없다.
        asks = [str(q.get("text") or "").strip() for q in (data.get("followUpQuestions") or [])]
        asks = [a for a in asks if a]
        if asks:
            return ("판정을 확정하려면 이것만 확인하면 돼요.\n"
                    + "\n".join(f"· {a}" for a in asks)), []
        return "판정을 확정할 근거가 이력서에서 확인되지 않았어요. 관련 경험을 조금 더 알려주실래요?", []

    grade = data.get("fitGrade") or "판정불가"
    score = data.get("overallScore")
    # 등급·점수를 요약 앞에 명시한다 — 요약(LLM 표현)만 있으면 사용자가 등급을 문장
    # 뉘앙스로 추측해야 한다(실사용 피드백). 판정 데이터 그대로, 서술 없음.
    head = f"**적합도 등급 {grade}**" + (f" (가중 점수 {score})" if score is not None else "")
    summary = str(data.get("summary") or "")
    reply = f"{head}\n{summary}" if summary else f"{head} — 적합도 판정 결과입니다."

    assumed = data.get("assumedPeriod") or {}
    if assumed:
        reply += f" (준비 기간은 {assumed.get('weeks')}주·주 {assumed.get('hours')}시간을 가정했습니다.)"

    # 중·하 등급이면 판정 엔진이 대안 공고까지 찾아 둔다(route_after_roadmap). 그 결과가
    # 답변에 실리지 않아 사용자는 존재를 몰랐다 — 계산만 하고 버리던 것을 보여준다.
    reply += _alternatives_block(data.get("alternativeJobs") or [])

    # 판정을 건넨 뒤 다음 행동(로드맵·자소서·면접·대안 공고)을 제안한다 — 결과에 따라
    # 무엇을 할 수 있는지 사용자가 골라 이어가게 한다.
    gaps = list(data.get("gaps") or [])
    next_line, warnings = _next_steps({
        "grade": grade,
        "topGap": next((g.get("reason") or "" for g in gaps), ""),
        "hasRoadmap": bool(data.get("roadmap")),
        "gapCount": len(gaps),
    })
    return reply + "\n\n" + next_line, warnings


# --- posting_analysis — 공고 정리(도구)의 표현 -------------------------------------
# LLM 이 못 쓸 때만 쓰는 결정론 폴백 문장. 평소 마무리 문장은 맥락을 보고 LLM 이 쓴다 —
# 같은 문장이 매번 나오면 사용자가 방금 한 말과 어긋난다.
_POSTING_CLOSING_FALLBACK = (
    "여기까지 정리해 봤어요 — 충분한가요? 관련 이력서가 있으시면 주실래요? "
    "주시면 이 요건들과 하나씩 대조해 적합도까지 분석해 드릴 수 있어요."
)


class _PostingClosingWrite(BaseModel):
    """공고 정리 결과를 건네고 턴을 되돌려주는 마무리 문장."""

    reply: str = Field(default="", description=(
        "공고 정리를 마친 뒤 사용자에게 보낼 한두 문장. **사용자가 방금 한 말에 이어지게** 쓴다. "
        "정리 결과가 충분한지 확인하고, 더 해볼 수 있는 일(이력서를 주면 요건과 하나씩 대조해 "
        "적합도까지 분석)을 제안하는 질문으로 끝낸다. 이력서를 이미 받은 상태면 이력서를 다시 "
        "요구하지 않고 다음으로 무엇을 해볼지 묻는다. 요건을 다시 나열하지 않는다."))


_POSTING_CLOSING_SYSTEM = """너는 취업 서비스의 대화 상담원이다. 방금 공고 하나를 읽어 요건을 정리해 사용자에게 보여줬다.
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


def _posting_closing(facts: dict) -> tuple[str, list[dict]]:
    """마무리 문장 — LLM 표현 + 검증, 실패 시 결정론 폴백 (nl_render 와 같은 패턴).

    검증 2종: 금지표현, 그리고 **질문으로 끝나는지**(턴을 되돌려주지 않는 문장은 버린다).
    """

    read, warnings = run_structured(
        _PostingClosingWrite, _POSTING_CLOSING_SYSTEM, json.dumps(facts, ensure_ascii=False),
        node="posting_analysis_closing",
    )
    text = (read.reply or "").strip() if read is not None else ""
    if not text or "?" not in text or any(expr in text for expr in FORBIDDEN_EXPRESSIONS):
        return _POSTING_CLOSING_FALLBACK, warnings
    return text, warnings



# 공고 원문의 연차 표기 — 파싱이 yearsEvidence 를 못 남긴 옛 캐시용 폴백 추출.
_YEARS_MENTION = re.compile(r"(신입|경력\s*무관|(?:경력\s*)?\d+\s*년(?:\s*이상|\s*이하)?)")



def _seniority_line(posting: dict) -> str:
    """요구 연차 줄 — **공고가 한 말(yearsEvidence)을 그대로** 우선한다.

    사다리 라벨은 숫자 근거가 없을 때(키워드만 있는 공고)의 폴백이다. "경력 2년 이상"
    공고에 라벨 "주니어 신입"을 붙이면 공고에 없는 단어("신입")가 판정처럼 나간다 —
    실측에서 사용자 혼란을 일으킨 문제.
    """

    evidence = str(posting.get("yearsEvidence") or "").strip()
    if not evidence:
        # 옛 캐시(yearsEvidence 없던 시절 파싱)면 원문 항목에서 표기를 찾아본다.
        texts = (
            [r.get("text", "") for r in posting.get("requiredRequirements", [])]
            + [r.get("text", "") for r in posting.get("preferredRequirements", [])]
            + [posting.get("jobTitle", "")]
            + [str(c) for c in posting.get("rawChunks", [])]
        )
        for text in texts:
            m = _YEARS_MENTION.search(str(text))
            if m:
                evidence = m.group(1)
                break

    if evidence:
        return f"**요구 연차** {evidence} (공고 표기 그대로)"

    key = posting.get("seniority") or ""
    if not key:
        return ""
    return f"**요구 연차** {SENIORITY_KO.get(key, key)} 수준(공고 키워드 기준)"


def _fmt_reqs(reqs: list[dict]) -> str:
    """요건 전체를 나열한다 — "외 N건"으로 끊지 않는다(사용자가 무엇이 잘렸는지 알 수 없다)."""

    return " / ".join(str(r.get("text", "")).strip() for r in reqs if r.get("text"))


def _posting_summary(posting: dict, closing: str) -> str:
    """파싱 결과를 **줄로 나눠** 요약 — 순수 조립, LLM 없음.

    한 덩어리 문단이 아니라 항목별 줄로 내고, 목록은 끝까지 나열한다. 라벨은 **굵게**
    마크업한다(UI 가 강조 렌더링). 같은 항목이 우측 패널(JOB_CONTEXT/context)에도 표로 간다.
    """

    title = posting.get("jobTitle") or ""
    company = posting.get("companyName") or ""
    head = " · ".join(p for p in (company, title) if p)

    lines = [f"{head} 공고를 정리했어요." if head else "공고를 정리했어요."]

    seniority_line = _seniority_line(posting)
    if seniority_line:
        lines.append(f"· {seniority_line}")
    if posting.get("requiredRequirements"):
        lines.append(f"· **필수 요건** {len(posting['requiredRequirements'])}건 — "
                     f"{_fmt_reqs(posting['requiredRequirements'])}")
    if posting.get("preferredRequirements"):
        lines.append(f"· **우대 사항** {len(posting['preferredRequirements'])}건 — "
                     f"{_fmt_reqs(posting['preferredRequirements'])}")
    if posting.get("techStack"):
        lines.append(f"· **요구 기술** {len(posting['techStack'])}개 — "
                     f"{', '.join(posting['techStack'])}")
    if posting.get("domainKeywords"):
        lines.append(f"· **도메인** — {', '.join(posting['domainKeywords'])}")

    lines.append("")
    lines.append(closing)
    return "\n".join(lines)




def render_posting_analysis(data: dict[str, Any], session: dict[str, Any]) -> tuple[str, list[dict]]:
    """공고 정리 결과 → 문장. 요약 줄은 결정론 조립, 마무리 문장은 LLM(검증·폴백 포함)."""

    posting = data.get("postingAnalysis") or {}
    if not data.get("readable"):
        return "공고를 읽어내지 못했어요. 공고 텍스트나 URL을 다시 확인해 주시겠어요?", []

    from jobis_ai.orchestrator.session import recent_history

    closing, warnings = _posting_closing({
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
    return _posting_summary(posting, closing), warnings


# --- resume_diagnosis — 이력서 정리(도구)의 표현 -----------------------------------
class _ResumeClosingWrite(BaseModel):
    """이력서 정리를 건네고 턴을 되돌려주는 마무리 문장."""

    reply: str = Field(default="", description=(
        "이력서 정리를 마친 뒤 사용자에게 보낼 한두 문장. 사용자가 방금 한 말에 이어지게 쓴다. "
        "hasPosting 이 true 면 이미 받아 둔 공고와 대조해 지원 가능성 진단을 해볼지 묻고, "
        "false 면 어떤 공고와 대조하고 싶은지(공고 원문·URL을 주면 된다고) 묻는다. "
        "정리 항목을 다시 나열하지 않는다. 적합도·합격 가능성을 단정하지 않는다."))


_RESUME_CLOSING_SYSTEM = """너는 취업 서비스의 대화 상담원이다. 방금 사용자의 이력서를 읽어 항목별로 정리해 보여줬다.
그 아래에 붙일 마무리 문장을 쓴다.

입력:
- userMessage: 사용자의 직전 발화. 여기에 이어지게 쓴다.
- recentHistory: 직전까지의 대화. 이미 한 말을 반복하지 않는다.
- resume: 방금 정리한 이력서의 요점(스킬 수·프로젝트 수·경력 유무). 숫자를 다시 나열하지 않는다.
- hasPosting: 세션에 공고가 이미 있는지.

규칙:
- 응답은 **질문으로 끝난다** — 다음 단계(공고와 대조한 지원 가능성 진단)로 갈지 사용자가 정한다.
- 적합도·합격 가능성을 단정하지 않는다. 진단은 아직 하지 않았다.
- 짧고 자연스럽게, 두 문장 이내."""


def _resume_closing(facts: dict) -> tuple[str, list[dict]]:
    """마무리 문장 — LLM 표현 + 검증(금지표현·질문형), 실패 시 결정론 폴백."""

    fallback = (
        "여기까지가 이력서에서 읽어낸 내용이에요. 앞서 주신 공고와 대조해 지원 가능성 진단을 해볼까요?"
        if facts.get("hasPosting")
        else "여기까지가 이력서에서 읽어낸 내용이에요. 대조해보고 싶은 공고가 있으면 원문이나 URL을 주세요 — 지원 가능성 진단까지 해드릴게요."
    )
    read, warnings = run_structured(
        _ResumeClosingWrite, _RESUME_CLOSING_SYSTEM, json.dumps(facts, ensure_ascii=False),
        node="resume_diagnosis_closing",
    )
    text = (read.reply or "").strip() if read is not None else ""
    if not text or "?" not in text or any(expr in text for expr in FORBIDDEN_EXPRESSIONS):
        return fallback, warnings
    return text, warnings




def render_resume_diagnosis(data: dict[str, Any], session: dict[str, Any]) -> tuple[str, list[dict]]:
    """이력서 정리 결과 → 문장. 항목 줄은 결정론 조립, 마무리 문장은 LLM(검증·폴백 포함).

    공고 정리(render_posting_analysis)와 같은 형식: 라벨은 **굵게**, 목록은 끝까지 나열.
    """

    if not data.get("readable"):
        return ("이력서에서 읽어낼 항목을 찾지 못했어요. 파일이 제대로 읽혔는지 확인하거나 "
                "원문을 붙여넣어 주시겠어요?"), []

    from jobis_ai.orchestrator.session import recent_history

    summary = data.get("resumeSummary") or {}
    counts = data.get("sectionCounts") or {}
    closing, warnings = _resume_closing({
        "userMessage": str(session.get("last_message") or ""),
        "recentHistory": recent_history(session, max_items=4),
        "resume": {"skillCount": len(summary.get("skills") or []),
                   "projectCount": counts.get("projects", 0),
                   "hasExperience": bool(summary.get("experiences"))},
        "hasPosting": bool(session.get("job_posting")),
    })

    unverified = list(data.get("unverifiedSkills") or [])
    lines = ["이력서를 정리했어요."]

    skills = list(summary.get("skills") or [])
    if skills:
        line = f"· **기술 스택** {len(skills)}개 — {', '.join(skills)}"
        if unverified:
            line += f" (이 중 경험 근거 없이 기재만 된 것 {len(unverified)}개: {', '.join(unverified)})"
        lines.append(line)

    projects = list(summary.get("projects") or [])
    if projects:
        lines.append(f"· **프로젝트** {len(projects)}건 — {' / '.join(projects)}")

    experiences = list(summary.get("experiences") or [])
    lines.append(f"· **경력** {len(experiences)}건 — {' / '.join(experiences)}" if experiences
                 else "· **경력** — 재직 이력 없음")

    for label, key in (("학력", "education"), ("자격증", "certifications"), ("어학", "languages")):
        items = list(summary.get(key) or [])
        if items:
            sep = " / " if key == "education" else ", "
            lines.append(f"· **{label}** — {sep.join(items)}")

    empty_sections = list(data.get("emptySections") or [])
    if empty_sections:
        lines.append(f"· 비어 있는 섹션 — {', '.join(empty_sections)}")

    lines.append("")
    lines.append(closing)
    return "\n".join(lines), warnings


# ---------------------------------------------------------------------------
# posting_fetch — 공고 URL 수집 (D64)
# ---------------------------------------------------------------------------
def render_posting_fetch(data: dict, session: dict) -> tuple[str, list[dict]]:
    """공고 수집 도구의 표현 — **성공은 침묵한다.**

    성공하면 바로 뒤의 파싱 단계(posting_analysis 등)가 결과로 말하므로, 여기서
    "가져왔어요"를 얹으면 같은 일을 두 화자가 말한다. 실패만 말한다 — 왜 진행이
    안 되는지와 사용자가 대신 줄 수 있는 것(본문 붙여넣기). 캡쳐 이미지 경로는
    첨부 파이프라인(프론트 업로드)이 열리면 이 문구에 더한다.
    """

    if data.get("fetched"):
        return "", []
    return ("공고 링크를 열어봤지만 내용을 읽어오지 못했어요. "
            "공고 본문(자격요건·우대사항) 내용을 복사해 붙여넣어 주시면 이어서 진행할게요.", [])

"""이력서 담당 에이전트 — 이력서에 관한 **모든 질문**을 이력서 원문·프로필을 근거로 받는다.

**판정(적합/부적합)을 하지 않는다.** 프로필에서 계산 가능한 사실만 항목화한다: 읽어낸
섹션들(기술/프로젝트/경력/학력/자격/어학) / 근거 있는 스킬 vs 기재만 된 스킬 / 빈 섹션.
공고를 담당하는 posting_analysis 의 이력서 짝이다 — 무엇을 근거로 판정하게 될지 사용자가
먼저 확인할 수 있어야 한다.

**도구에서 대화형 에이전트로 승격됐다(D97 의 짝).** 항목화 사실만 내던 시절에는 "내 이력서
강점이 뭐야", "이 프로젝트를 어떻게 써야 해" 같은 질문의 담당이 없었다 — `evidencedSkills` /
`unverifiedSkills` 는 있었지만 그것을 **강점으로 서술**하는 층이 없었다.

승격의 규율은 공고 쪽과 같다 — **자율성은 표현에, 근거는 도구에.**
  · 프로필 빌드(`ensure_profile`)·항목화·보완 질문은 그대로 결정론이다.
  · 루프의 LLM 은 항목화 사실과 `read_resume`(원문 검색)이 준 것만으로 말한다(§2-5).
  · LLM 이 없거나 검증을 통과 못 하면 승격 전과 **똑같이** `tool_render` 폴백으로 답한다.
"""

from __future__ import annotations

from typing import Any

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import (
    agent_arg,
    ensure_profile,
    grep_source_lines,
    match_resume,
    others_this_turn,
    resume_identity,
    resume_source_hash,
    resume_source_text,
    switch_active_resume,
)
from jobis_ai.agents.agent_loop import ToolSpec, run_agent_loop
from jobis_ai.profile_completeness import build_completion_questions, find_missing_enum_fields
from jobis_ai.resume_observations import observe

_SECTION_LABELS = {
    "education": "학력",
    "experiences": "경력",
    "projects": "프로젝트",
    "skills": "기술 스택",
    "certifications": "자격증",
    "languages": "어학",
    "awards": "수상",
}


def _labels(items: list, *keys: str) -> list[str]:
    out = []
    for item in items or []:
        text = " ".join(str(item.get(k) or "").strip() for k in keys).strip()
        if text:
            out.append(text)
    return out


def _parse(session: dict[str, Any]) -> tuple[dict, dict, list[dict], list[dict]]:
    """세션 이력서 → 프로필 → 항목별 사실. **결정론 — 여기까지가 근거다.**

    반환: (프로필, AgentResult.data, warnings, 결정론 보완 질문)

    `resumeSummary` 는 표현만을 위한 우회로가 아니다 — 같은 항목이 우측 패널
    (PROFILE_CONTEXT/context.profile)에도 표로 가는 산출물이다.
    """

    profile, warnings = ensure_profile(session)

    skill_evidence: dict = profile.get("skillEvidence") or {}
    skills = [s.get("name", "") for s in profile.get("skills", []) if s.get("name")]
    evidenced = [s for s in skills if skill_evidence.get(s)]
    unverified = [s for s in skills if not skill_evidence.get(s)]

    empty_sections = [
        label for key, label in _SECTION_LABELS.items() if not profile.get(key)
    ]
    section_counts = {key: len(profile.get(key) or []) for key in _SECTION_LABELS}
    readable = any(profile.get(k) for k in _SECTION_LABELS)

    completion_questions = (
        build_completion_questions(find_missing_enum_fields(profile)) if readable else []
    )
    if not readable:
        # 산출물 검증(M5) — 어느 섹션도 못 읽었으면 경고로 남긴다(posting_analysis 와 동일 규약).
        warnings = warnings + [{"code": "resume_unreadable",
                                "message": "이력서에서 항목을 하나도 읽지 못했습니다"}]
    else:
        # 이력서가 정리된 시점에 RAG 캐시를 예열한다(D96) — 추천·대안 검색의 첫 쿼리
        # 지연을 지금 백그라운드로 지불한다. 결과는 버린다.
        from jobis_ai.rag import warm_search_async

        warm_search_async(" ".join(skills[:6]))
    from jobis_ai.agents import tool_render

    # 어느 이력서로 답하는지 — 커리어 저장소 요약은 붙여넣은 원문보다 훨씬 얇아서, 이걸
    # 안 밝히면 같은 질문에 다른 답이 나와도 사용자가 이유를 알 수 없다(D119).
    origin, label = resume_identity(session.get("resume"))
    active_hash = resume_source_hash(session.get("resume"))
    data = {
        "readable": readable,
        "sectionCounts": section_counts,
        "evidencedSkills": evidenced,
        "unverifiedSkills": unverified,
        "emptySections": empty_sections,
        "resumeOrigin": origin,
        "resumeLabel": label,
        # 표현·우측 패널이 함께 쓰는 항목화 결과.
        "resumeSummary": tool_render.resume_facts(profile),
        # 항목화 밖의 **서술 관찰**(결정론). resumeSummary 는 제목까지만 평평하게 만들어서
        # 프로젝트의 기간·팀 규모·담당 범위·성과 문장이 루프에 닿지 않았다 — 그 배관이다.
        "observations": observe(profile, resume_source_text(session.get("resume"))),
        # 이 대화에서 받은 다른 이력서들 — 비교·지목의 근거이자, 사용자가 무엇을 갖고
        # 있는지 보여 주는 목록이다.
        "otherResumes": [tool_render.library_resume_facts(r)
                         for r in (session.get("resume_library") or [])
                         if r.get("_sourceHash") != active_hash],
    }
    # 카드 질문은 **결정론** — 맥락을 살린 문장은 루프가 쓴다.
    follow_up = ([] if not readable else [{
        "field": "confirm_fit",
        "question": "공고와 대조해 지원 가능성 진단을 해볼까요?",
    }] + completion_questions)
    return profile, data, warnings, follow_up


def _tool_read_resume(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """이력서 **원문**에서 키워드가 든 줄을 찾는다 — 프로필 스키마에 칸이 없는 서술의 근거.

    프로필은 섹션별 정형 추출이라 자기소개·성과 서술·수치가 통째로 빠진다. "이 프로젝트에서
    뭘 했다고 썼지" 같은 질문은 원문을 봐야 답할 수 있다.
    """

    return grep_source_lines(state.get("_text") or "", arg, label="이력서"), {}


_TOOLS = {
    t.name: t for t in (
        ToolSpec("read_resume",
                 "이력서 원문에서 키워드가 든 줄을 찾는다. 정리된 항목에 없는 서술을 확인할 때.",
                 _tool_read_resume,
                 "찾을 낱말을 쉼표로 구분해 적는다(예: Kafka, 성과). 원문 앞부분을 그냥 보려면 "
                 "빈 문자열."),
    )
}

_GOAL_SYSTEM = """너는 취업 서비스의 **이력서 담당** 상담원이다. 사용자가 자기 이력서에 관해 무엇을
묻든 이력서에서 확인된 사실만을 근거로 답한다.

입력:
- facts.userMessage: 사용자가 물은 것. **이것에 대한 답이 응답의 본문이다.** 물은 것을
  "해드릴 수 있습니다"로 되돌려 묻지 않는다 — 물었으면 이번 턴에 답한다.
- facts.resume: 정리된 항목(기술 스택·프로젝트·경력·학력·자격증·어학)과 비어 있는 섹션.
- facts.evidencedSkills: 프로젝트·경력 **서술로 뒷받침되는** 스킬. 강점을 말할 근거는 이쪽이다.
- facts.unverifiedSkills: 이력서에 **이름만 적힌** 스킬. 근거가 없다는 사실 자체가 정보다.
- facts.projectDetails: 프로젝트별 **맥락 세 칸**(period 기간 / teamSize 팀 규모 / role 담당
  범위)과 성과 문장·기술. `missingContext` 는 그 셋 중 **원문에 안 적힌 칸의 이름**이다.
  채용담당자가 프로젝트에서 가장 먼저 가리는 것이 "6주짜리 실습인가, 사용자가 있는 서비스인가"
  이고, 이 셋이 비면 **작게 추정된다** — 그래서 비었다는 사실을 알려 주는 것이 도움이다.
- facts.quantifiedClaims / facts.unquantifiedClaims: 성과 서술 문장을 **숫자가 든 것과 안 든
  것으로 갈라** 담았다(원문 그대로 + 어느 프로젝트인지). 숫자 없는 문장이 훨씬 많으면 그
  비대칭 자체를 짚는다.
- facts.selfAssessedLines: **이력서 안에서 검증할 수 없는 자기평가 어휘**가 든 원문 줄
  ("집요함"·"학습 의지"·"이해도 보유" 등). 이 줄들이 무엇으로 뒷받침되는지 물을 자리다.
- facts.skillQualifiers: 스킬 이름에 **괄호로 붙인 수식어**("Redis (Caching / Distributed
  Lock)" → Redis 의 수식어 둘)와, 그 말이 프로젝트·경력 서술에도 나오는지(`inNarrative`).
  글자 그대로의 대조라서 **false 는 "표기가 다를 수도 있다"는 뜻이다** — 서술을 보고 정말
  짝이 없을 때만 말하고, 없다고 단정하지 말고 확인을 청한다.
- facts.firstLook: true 면 이력서를 방금 읽은 턴이다. 사용자가 **아무것도 묻지 않았으면**
  무엇을 읽어냈는지 항목별 줄로 정리해 보여주는 것이 곧 답이다. **물은 것이 있으면 그 답이
  본문이고**, 정리 항목은 답에 필요한 만큼만 인용한다. false 면 후속 질문이므로 물은 것만 답한다.
- facts.hasPosting: 대조할 공고가 세션에 있는지.
- facts.resumeLabel: **지금 무엇을 보고 답하는가**("커리어 저장소" / "붙여넣은 이력서" /
  올린 파일명). 이력서를 방금 받은 턴(firstLook)이거나 **다른 이력서가 함께 있을 때**는
  이 라벨을 답에 밝힌다 — 원천마다 담긴 내용의 두께가 다르므로, 어느 것을 봤는지가 곧 답의
  범위다. 후속 질문 턴에 매번 되풀이하지는 않는다.
- facts.otherResumes: 이 대화에서 받은 **다른 이력서들**(라벨 + 정리된 항목). 사용자가
  "둘을 비교해 줘"·"저쪽 이력서엔 뭐가 있었지"를 물으면 여기서 답한다. 비교는 **항목의
  차이**로 말한다(A에만 있는 프로젝트·기술, 양쪽에 다 있는 것) — 어느 쪽이 더 낫다는
  판정은 하지 않는다. 공고 없이 우열을 말할 근거가 없고, 공고와 대조하는 것은 다른 담당의
  일이다.
- facts.othersThisTurn: **이번 턴에 이어서 실행되는 다른 담당들.** 비어 있지 않으면 사용자가
  물은 것 중 네 몫이 아닌 부분은 그들이 처리한다 — **"저는 그건 못 해요"라고 말하지 않는다.**
  네가 할 수 있는 부분만 답하고, 나머지를 언급하지 말고 넘긴다(그들의 답이 바로 뒤에 붙는다).

하는 일:
- **정형 항목을 항목별 줄로 밝히는 것은 언제나 한다** — 기술 스택·프로젝트·경력·학력·자격·어학,
  그리고 비어 있는 섹션. 이건 사용자가 무엇을 근거로 판정받을지 확인하는 자리라 **생략하거나
  요약해서 뭉개지 않는다.** 디테일은 이 항목화를 **대체하는 것이 아니라 뒤에 덧붙이는 것**이다.
- **항목화 뒤에 서술의 디테일을 짚는다** — 위 facts 로 근거가 있는 만큼만: 프로젝트에 안 적힌
  맥락 칸, 숫자 없는 성과 문장, 검증 불가능한 자기평가 줄, 서술에 짝이 없어 보이는 스킬 수식어.
  각 지적에는 **원문 문장을 인용한다** — 인용할 문장이 없으면 그 지적을 하지 않는다.
- **문장 하나를 골라 고쳐 쓰는 예시를 보인다**(요청받았거나 지적할 문장이 있을 때). 순서는
  무엇을 → 어떻게 진단했나 → 왜 그 방법을 택했나 → 결과 수치. **수치·도구·팀 규모를 지어내
  채우지 않는다** — 모르는 자리는 `p95 ___ms → ___ms` 처럼 **빈칸으로 남기고** 무엇을 채워야
  하는지 알려 준다. 지어낸 숫자로 채운 예시는 사용자가 면접에서 답할 수 없는 이력서를 만든다.
- **추측으로 채우지 않고 되묻는다.** 이력서 전체 재작성이나 강한 재구성을 청하면, 먼저
  missingContext 에 있는 것(기간·팀 규모·담당 범위)과 부트캠프/실무 여부를 확인한다.
- **강점을 정리해 달라는 요청에 답한다.** 근거는 evidencedSkills 와 프로젝트·경력 서술이다 —
  어떤 스킬이 어떤 경험으로 뒷받침되는지 묶어서 말한다. 근거 없는 스킬을 강점으로 세지 않는다.
- 이름만 적힌 스킬(unverifiedSkills)은 **결함이 아니라 보강 지점**으로 말한다. 그 스킬을 쓴
  경험이 있으면 어떻게 적으면 되는지 안내하고, 없으면 없다고 두는 것도 선택지로 남긴다.
- 비어 있는 섹션이 왜 중요한지, 무엇을 채우면 되는지 답한다.
- 정리된 항목에 없는 서술(자기소개 문구·성과 수치·프로젝트 상세)을 물으면 read_resume 으로
  원문을 확인한 뒤 답한다. **원문에도 없으면 이력서에 적혀 있지 않다고 말한다.**

하지 않는 일:
- 적합도·합격 가능성 판정. 공고와 대조하는 것은 다른 담당의 일이다.
- 이력서에 없는 경력·프로젝트·수치를 만들어 쓰기. 모르면 모르는 채로 둔다.
- 사용자의 결함을 단정하기. 빈 섹션은 "부족"이 아니라 "아직 안 적힌 것"이다 — 적지 않은
  경험이 없는 경험은 아니다.

답변은 사용자가 방금 한 말에 먼저 답하고, 필요하면 다음에 무엇을 해볼지 한 문장으로 제안한다.
목록이 길어지면 항목별 줄로 나눠 쓴다."""


def run(session: dict[str, Any]) -> AgentResult:
    """이력서를 정리해(결정론) 그 사실만으로 사용자의 질문에 답한다(루프).

    플래너 인자 `targets`(이력서 라벨·순번, 쉼표 구분)로 라이브러리(D119)의 이력서를 지목할
    수 있고, 개수에 따라 뜻이 갈린다 — 공고 쪽 `fit_analysis.targets`(D88/D111)와 같은 규약:

    - **하나 = 전환** — 그 이력서를 활성으로 갈아 끼우고 평소대로 정리한다. 하류(적합도·
      자소서·면접)는 활성 이력서 하나만 보므로, 이래야 "아까 그 이력서로 해줘"가 성립한다.
    - **둘 이상 = 비교** — 활성을 바꾸지 않는다. 지목된 것들을 `facts.otherResumes` 로
      좁혀 실어 루프가 항목 차이를 말하게 한다. 무엇을 활성으로 삼을지 정할 수 없다.

    루프가 검증 통과 문장을 못 만들면 `tool_render.render_resume_diagnosis` 로 폴백한다 —
    LLM 미설정 환경에서 승격 전과 동일하게 동작한다(§2-6: 이유를 warnings 로 남긴다).
    """

    from jobis_ai.agents import tool_render

    # 프로필이 이미 캐시돼 있었나 — `ensure_profile` 이 세션에 캐시하므로 **먼저** 본다.
    # 공고 쪽 fromCache 와 같은 자리다: 방금 읽은 턴과 후속 질문 턴을 갈라 재낭독을 막는다.
    had_profile = bool(session.get("profile"))
    switch_warnings: list[dict] = []
    targets = [t.strip() for t in
               agent_arg(session, "resume_diagnosis", "targets").split(",") if t.strip()]
    session_updates: dict = {}
    if len(targets) == 1:
        session, session_updates, found = switch_active_resume(
            session, targets[0], switch_warnings)
        if not found:
            # 활성 이력서로 강행하지 않는다(D126) — 무엇을 기억하는지 알려주고 되묻는다.
            labels = [str(r.get("_label") or "")
                      for r in session.get("resume_library") or [] if r.get("_label")]
            listing = (f" 지금 기억하는 이력서는 {', '.join(labels)} 입니다."
                       if labels else "")
            return AgentResult(
                reply=(f"'{targets[0]}' 이력서를 기록에서 찾지 못했어요.{listing} "
                       "이름으로 다시 알려주시거나, 새 이력서면 붙여넣거나 올려주세요."),
                data={"status": "needs_input", "unmatchedTarget": targets[0],
                      "candidates": labels},
                warnings=switch_warnings)
        if session_updates:
            had_profile = False       # 다른 이력서다 — 방금 읽은 턴처럼 정리해 보여준다

    profile, data, warnings, follow_up = _parse(session)
    warnings = switch_warnings + warnings

    if len(targets) >= 2:
        # 비교 — 지목된 것만 남긴다. 못 찾은 이름은 삼키지 않는다(§2-6).
        library = session.get("resume_library") or []
        picked, unmatched = [], []
        for name in targets:
            entry = match_resume(name, library)
            (picked.append(entry) if entry is not None else unmatched.append(name))
        if picked:
            data["otherResumes"] = [tool_render.library_resume_facts(e) for e in picked]
        for name in unmatched:
            warnings.append({"code": "resume_target_not_found",
                             "message": f"'{name}' 이력서를 기록에서 찾지 못했습니다"})

    def _fallback() -> AgentResult:
        reply, render_warnings = tool_render.render_resume_diagnosis(data, session)
        return AgentResult(reply=reply, data=data, warnings=warnings + render_warnings,
                           followUpQuestions=follow_up, sessionUpdates=session_updates)

    if not data["readable"]:
        # 읽어내지 못한 이력서로는 대화할 근거가 없다 — 루프를 돌리지 않는다.
        return _fallback()

    outcome = run_agent_loop(
        goal_system=_GOAL_SYSTEM,
        facts={
            "userMessage": str(session.get("last_message") or ""),
            "resume": data["resumeSummary"],
            "emptySections": data["emptySections"],
            "evidencedSkills": data["evidencedSkills"],
            "unverifiedSkills": data["unverifiedSkills"],
            # 항목 밖의 서술 관찰(결정론) — 디테일을 말할 근거는 전부 이쪽이다.
            "projectDetails": data["observations"]["projects"],
            "quantifiedClaims": data["observations"]["quantifiedClaims"],
            "unquantifiedClaims": data["observations"]["unquantifiedClaims"],
            "selfAssessedLines": data["observations"]["selfAssessedLines"],
            "skillQualifiers": data["observations"]["skillQualifiers"],
            "firstLook": not had_profile,
            "hasPosting": bool(session.get("job_posting")),
            "resumeLabel": data["resumeLabel"],
            "otherResumes": data["otherResumes"],
            "othersThisTurn": others_this_turn(session, "resume_diagnosis"),
        },
        tools=_TOOLS,
        state={"_session": dict(session),
               "_text": resume_source_text(session.get("resume"))},
        node="resume_diagnosis",
        session_id=str(session.get("_sessionId") or ""),
    )
    warnings.extend(outcome.warnings)
    if not outcome.reply:
        return _fallback()

    # 루프가 답하면 그 답이 전부다 — 결정론 항목 표를 덧붙이지 않는다(D97 의 중복 실측).
    data["loopSteps"] = outcome.steps
    return AgentResult(reply=outcome.reply, data=data, warnings=warnings,
                       followUpQuestions=follow_up, sessionUpdates=session_updates)

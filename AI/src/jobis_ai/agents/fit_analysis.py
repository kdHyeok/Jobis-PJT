"""fit_analysis 도구 — 기존 판정 엔진(build_graph)의 대화 진입 래퍼.

판정 로직은 한 줄도 없다. 세션 자산(이력서·공고)을 AnalyzeRequest/GraphState 로 변환해
판정 파이프라인을 부르고, 결과를 그대로 전달한다(dispatch만, judge 금지).

**도구다 — 말하지 않는다.** 등급·요약·대안 공고·다음 행동 제안은 전부 표현이므로
`tool_render.render_fit_analysis` 로 옮겼다(A단계 구분: 말을 하는가). 여기 남은 것은
"무엇을 계산했나"뿐이고, 문구를 고칠 때 이 파일을 건드릴 일은 없다.

이 도구의 결과는 **뒤에 예정된 단계의 타당성을 바꾼다** — 등급이 낮거나 판정이 완료되지
않으면 그 위에서 도는 자소서·면접은 근거가 없다. 그 전이는 `orchestrator/observe_rules.py`
가 결정론으로 처리한다(등급 하·판정불가면 생성 단계를 지원 경로 설계로 교체, 판정이
승격되지 않으면 전제 붕괴로 제외). 여기서 판단하지 않는다.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import ensure_posting_text
from jobis_ai.contracts.api import AnalyzeOptions, AnalyzeRequest, JobPostingInput
from jobis_ai.service import request_to_state, run_pipeline_with_state

# 대화 경로에는 준비 기간 입력 폼이 없으므로 기본값을 가정하고, 가정임을 응답에 명시한다.
DEFAULT_WEEKS = 8
DEFAULT_HOURS = 10


def _match_library(name: str, library: list[dict]) -> dict | None:
    """지목한 회사명 ↔ 라이브러리 항목 — 부분 일치(결정론)."""

    key = name.strip()
    for entry in library:
        company = str(entry.get("companyName") or "").strip()
        if company and (key in company or company in key):
            return entry
    return None


def _match_recommendation(name: str, recommendations: list[dict]) -> dict | None:
    """지목한 이름·순번 ↔ 추천 공고(D125 — 프로토타입 2.0.0 registry 이식).

    순번("2")은 **추천 목록에만** 해석한다 — 화면에 번호 목록으로 나간 것이 추천뿐이라,
    라이브러리에도 순번을 받으면 같은 "2"가 두 목록을 가리켜 엉뚱한 공고가 잡힌다.
    """

    key = (name or "").strip()
    if not key or not recommendations:
        return None
    digits = "".join(c for c in key if c.isdigit())
    if digits and not any(c.isalpha() for c in key) and "#" not in key:
        index = int(digits) - 1
        return recommendations[index] if 0 <= index < len(recommendations) else None
    for rec in recommendations:
        company = str(rec.get("companyName") or "").strip()
        title = str(rec.get("title") or "").strip()
        if (company and (key in company or company in key)) or (title and key in title):
            return rec
    return None


def _known_posting_names(session: dict[str, Any]) -> list[str]:
    """되묻기에 실을 후보 — 라이브러리 회사명 + 추천 공고 회사명(중복 제거, 순서 유지)."""

    names = [str(p.get("companyName") or "").strip()
             for p in session.get("posting_library") or []]
    names += [str(r.get("companyName") or r.get("title") or "").strip()
              for r in session.get("recommendations") or []]
    seen: set[str] = set()
    return [n for n in names if n and not (n in seen or seen.add(n))]


def _switch_active(session: dict[str, Any], name: str, posting_input: dict | None,
                   warnings: list[dict]) -> tuple[dict[str, Any], dict | None, dict, dict | None]:
    """지목한 공고 **하나**를 활성 공고로 갈아 끼운다.
    반환: (세션 사본, 공고 원천, sessionUpdates, 되묻기 데이터 | None)

    실측 결함(2026-08-02): `targets` 가 하나면 `_run_multi` 에 들어가지도 못하고 활성 공고가
    그대로 판정됐다 — "예전에 본 그 공고로 자소서 써줘" 가 **다른 회사 자소서**를 냈다.
    하류 생성 에이전트(coverletter_draft·interview_prep)는 `posting_summary`/`analysis` 하나만
    보고 라이브러리(D86)를 모른다. 그래서 대상을 바꾸려면 활성 공고 자체를 바꿔야 한다.

    **원문을 되돌려 놓는 방식**이라 무손실이다 — 아래 단일 경로가 평소대로(대안 공고·로드맵
    포함) 판정하고, 해시가 맞아 재파싱도 없다(D79). 원문 grep 도구도 그대로 산다.
    지목이 둘 이상이면 그것은 비교이지 전환이 아니므로 `_run_multi` 가 따로 처리한다.

    라이브러리에 없으면 **추천 공고(D125)** 에서 찾아 URL 을 지금 수집해 활성으로 굳힌다.
    어디에도 없으면 활성 공고로 강행하지 않고 되묻는다(D126) — "없는회사 공고 분석해줘"에
    활성 공고 판정이 나가면 사용자는 그것이 지목한 공고의 판정인 줄 안다(§2-1 되묻는다).
    """

    entry = _match_library(name, session.get("posting_library") or [])
    if entry is not None:
        text = str(entry.get("_sourceText") or "")
        if not text or text == (posting_input or {}).get("value"):
            # 이미 활성이거나, 원문 없이 저장된 옛 항목(이 필드 도입 전) — 그대로 둔다.
            return session, posting_input, {}, None
        switched = {"job_posting": {"sourceType": "text", "value": text},
                    "posting_summary": dict(entry)}
        return {**session, **switched}, switched["job_posting"], switched, None

    rec = _match_recommendation(name, session.get("recommendations") or [])
    if rec is not None:
        url = str(rec.get("url") or "").strip()
        label = str(rec.get("companyName") or rec.get("title") or name)
        if url:
            candidate = {**session, "job_posting": {"sourceType": "url", "value": url}}
            promoted, fetch_warnings = ensure_posting_text(candidate)
            warnings.extend(fetch_warnings)
            if promoted and (promoted.get("sourceType") or "").lower() == "text":
                switched = {"job_posting": promoted}
                return {**session, **switched}, promoted, switched, None
            # 수집 실패 — 엉뚱한 공고(기존 활성)로 강행하지 않는다. 이유는 warnings 에 이미 있다.
            return session, posting_input, {}, {
                "unmatchedTarget": label, "reason": "fetch_failed"}
        return session, posting_input, {}, {"unmatchedTarget": label, "reason": "no_url"}

    warnings.append({"code": "fit_target_not_found",
                     "message": f"'{name}' 공고가 정리된 기록·추천 목록에 없어 되묻습니다"})
    return session, posting_input, {}, {
        "unmatchedTarget": name, "reason": "not_found",
        "candidates": _known_posting_names(session)}


def _needs_input(ask: dict, warnings: list[dict], axis: str = "posting") -> AgentResult:
    """지목 해석 실패 → 판정하지 않고 되묻는다(D126). 문장은 render 가 만든다."""

    return AgentResult(
        reply="",
        data={"status": "needs_input", "axis": axis, **ask},
        warnings=warnings,
        followUpQuestions=[],
        sessionUpdates={},
    )


def _archive(session: dict[str, Any], session_updates: dict, posting_hash: str,
             analysis: dict, resume_label: str = "") -> None:
    """판정 요약을 공고 라이브러리 항목에 남긴다 — 활성 슬롯이 무효화돼도 조회 가능하게.

    승격(`analysis`)과 달리 **활성 여부를 가리지 않는다**: 비교로 돌린 판정도 사용자가
    나중에 물어본다. 같은 턴에 라이브러리를 갱신했으면 그 목록 위에 얹는다(두 쓰기가
    서로를 덮지 않게).
    """

    from jobis_ai.agents._common import attach_analysis, resume_identity

    library = attach_analysis(
        session, posting_hash, analysis,
        resume_label or resume_identity(session.get("resume"))[1] or "활성 이력서",
        library=session_updates.get("posting_library"))
    if library is not None:
        session_updates["posting_library"] = library


def run(session: dict[str, Any]) -> AgentResult:
    """세션의 이력서+공고로 적합도 판정을 실행하고 결과를 세션에 남긴다.

    플래너 인자 `targets`(회사명 쉼표 구분)로 공고 라이브러리(D86)의 공고를 지목할 수 있고,
    개수에 따라 뜻이 갈린다:

    - **둘 이상 = 비교(D88)** — 대상별로 파싱본을 그래프에 시드해 반복 판정한다(파싱은 멱등).
      무엇을 활성으로 삼을지 정할 수 없으므로 활성 공고를 바꾸지 않고, `analysis` 자산도
      **활성 공고의 판정일 때만** 승격한다(자소서·면접의 근거가 엉뚱한 공고와 짝지어지면 안 된다).
    - **하나 = 전환** — 그 공고를 활성으로 갈아 끼우고(`_switch_active`) 평소 경로로 판정한다.
      하류 생성 에이전트는 활성 공고 하나만 보므로, 이래야 "예전 그 공고로 자소서"가 성립한다.

    **판정은 이력서×공고라 축이 둘이다(D119).** `resumeTargets` 가 이력서 축이고 규약은 같다
    (둘 이상 = 비교, 하나 = 전환). 두 축을 동시에 펼치지는 않는다 — 조합이 곱으로 늘고
    사용자가 읽을 수 없는 표가 된다. 공고 비교가 지목되면 그쪽이 이기고, 이력서 축은
    경고와 함께 접는다(§2-6 — 접었다는 사실을 삼키지 않는다).
    """

    from jobis_ai.agents._common import agent_arg, switch_active_resume

    # URL 자산이면 먼저 수집해 원문으로 승격한다(D62) — 판정 파이프라인이 재수집하지 않는다.
    posting_input, fetch_warnings = ensure_posting_text(session)

    targets = [t.strip() for t in
               agent_arg(session, "fit_analysis", "targets").split(",") if t.strip()]
    resume_targets = [t.strip() for t in
                      agent_arg(session, "fit_analysis", "resumeTargets").split(",") if t.strip()]
    if len(targets) >= 2:
        if resume_targets:
            fetch_warnings.append({
                "code": "resume_axis_folded",
                "message": ("공고 비교와 이력서 비교를 함께 청해 공고 비교로 진행합니다 — "
                            "이력서별 비교는 공고 하나를 정한 뒤 다시 청해 주세요"),
            })
        return _run_multi(session, posting_input, fetch_warnings, targets)
    # 하나만 지목했으면 그 공고를 활성으로 바꾸고, 아래 단일 경로가 평소대로 판정한다.
    switched: dict = {}
    if targets:
        session, posting_input, switched, ask = _switch_active(
            session, targets[0], posting_input, fetch_warnings)
        if ask is not None:
            # 지목을 해석하지 못했다 — 활성 공고로 강행하면 사용자는 그것이 지목한
            # 공고의 판정인 줄 안다. 판정하지 않고 되묻는다(D126).
            return _needs_input(ask, fetch_warnings)
    if len(resume_targets) >= 2:
        return _run_multi_resume(session, posting_input, fetch_warnings,
                                 resume_targets, switched)
    if resume_targets:
        session, resume_switched, found = switch_active_resume(
            session, resume_targets[0], fetch_warnings)
        if not found:
            labels = [str(r.get("_label") or "")
                      for r in session.get("resume_library") or []]
            return _needs_input({"unmatchedTarget": resume_targets[0],
                                 "reason": "not_found",
                                 "candidates": [l for l in labels if l]},
                                fetch_warnings, axis="resume")
        switched = {**switched, **resume_switched}

    request = AnalyzeRequest(
        userId=int(session.get("userId") or 0),
        jobPostingInput=JobPostingInput(**session["job_posting"]),
        preparationPeriodWeeks=int(session.get("preparationPeriodWeeks") or DEFAULT_WEEKS),
        availableHoursPerWeek=int(session.get("availableHoursPerWeek") or DEFAULT_HOURS),
        options=AnalyzeOptions(includeAlternatives=True),
    )
    state = request_to_state(request, str(uuid.uuid4()))
    if session.get("resume"):
        state["resumeInput"] = session["resume"]

    # 화이트보드 → 그래프(D84): 다른 도구가 이미 만든 지식(공고 파싱·프로필)을 다시 만들지
    # 않는다. parse_job_posting/build_user_profile 은 멱등이라 상태에 실으면 그대로 재사용한다.
    source_hash = hashlib.md5(
        ((posting_input or {}).get("value") or "").encode("utf-8")).hexdigest()
    cached_posting = session.get("posting_summary") or {}
    seeded_posting = cached_posting.get("_sourceHash") == source_hash
    if seeded_posting:
        state["normalizedJobPosting"] = {
            k: v for k, v in cached_posting.items() if not k.startswith("_")}
    if session.get("profile"):
        state["normalizedUserProfile"] = session["profile"]

    response, final_state = run_pipeline_with_state(state)
    result = response.model_dump()

    # 완료된 분석만 세션 자산으로 승격한다 — need_more_info 의 미완성 결과를 저장하면
    # 다음 턴 라우터가 "분석 있음"으로 오판해 자소서·면접 에이전트가 빈 근거 위에서 돈다.
    session_updates: dict = dict(switched)      # 활성 공고 전환도 함께 영속화한다
    # 그래프 → 화이트보드(D84): 그래프가 새로 만든 지식을 공유 자산으로 승격 — 다음 턴의
    # 조회·대화·다른 도구가 재생산 없이 쓴다. 내용이 실제로 있는 것만(빈 파싱·폴백 제외).
    built_posting = final_state.get("normalizedJobPosting") or {}
    if not seeded_posting and any(built_posting.get(k) for k in (
            "requiredRequirements", "preferredRequirements", "techStack", "jobTitle")):
        from jobis_ai.agents._common import upsert_posting_library

        summary = {**built_posting, "_sourceHash": source_hash,
                   "_sourceText": (posting_input or {}).get("value") or ""}
        session_updates["posting_summary"] = summary
        session_updates["posting_library"] = upsert_posting_library(session, summary)
    built_profile = final_state.get("normalizedUserProfile") or {}
    if not session.get("profile") and any(built_profile.get(k) for k in (
            "skills", "experiences", "projects", "education")):
        session_updates["profile"] = built_profile
    if response.status == "completed":
        session_updates["analysis"] = result
        _archive(session, session_updates, source_hash, result)
        if response.roadmap:
            # 로드맵도 세션 자산으로 승격 — roadmap_manager 가 대화로 조회한다.
            session_updates["roadmap"] = result["roadmap"]

    # 표현이 알아야 하지만 판정 결과에는 없는 것 — 준비 기간을 사용자가 준 게 아니라
    # 우리가 가정했는지. 세션 자산(analysis)에는 넣지 않는다(판정 산출물을 오염시키지 않는다).
    data = dict(result)
    if not session.get("preparationPeriodWeeks"):
        data["assumedPeriod"] = {"weeks": DEFAULT_WEEKS, "hours": DEFAULT_HOURS}

    return AgentResult(
        reply="",                       # 도구는 말하지 않는다 — 문장은 render 가 만든다
        data=data,
        warnings=fetch_warnings + list(response.warnings),
        followUpQuestions=list(response.followUpQuestions),
        sessionUpdates=session_updates,
    )


def _run_multi_resume(session: dict[str, Any], posting_input: dict | None,
                      fetch_warnings: list[dict], targets: list[str],
                      switched: dict) -> AgentResult:
    """같은 공고를 **이력서별로** 판정한다(D119) — `_run_multi` 의 이력서 축 대칭.

    "A 이력서와 B 이력서 중 이 공고에 뭐가 나아?" 는 공고 축 반복으로는 답할 수 없다.
    활성 이력서는 바꾸지 않는다(무엇을 활성으로 삼을지 정할 수 없다) — `analysis` 자산도
    **활성 이력서의 판정일 때만** 승격한다. 자소서·면접의 근거가 다른 사람의 이력서와
    짝지어지면 안 된다(`_run_multi` 가 공고 축에서 지키는 것과 같은 규율).
    """

    from jobis_ai.agents._common import match_resume, resume_source_hash

    library = session.get("resume_library") or []
    active_hash = resume_source_hash(session.get("resume"))

    warnings = list(fetch_warnings)
    results: list[dict] = []
    unmatched: list[str] = []
    session_updates: dict = dict(switched)

    for name in targets:
        entry = match_resume(name, library)
        if entry is None:
            unmatched.append(name)
            warnings.append({"code": "resume_target_not_found",
                             "message": f"'{name}' 이력서를 기록에서 찾지 못했습니다"})
            continue
        request = AnalyzeRequest(
            userId=int(session.get("userId") or 0),
            jobPostingInput=JobPostingInput(**(posting_input or session["job_posting"])),
            preparationPeriodWeeks=int(session.get("preparationPeriodWeeks") or DEFAULT_WEEKS),
            availableHoursPerWeek=int(session.get("availableHoursPerWeek") or DEFAULT_HOURS),
            options=AnalyzeOptions(includeAlternatives=False),
        )
        state = request_to_state(request, str(uuid.uuid4()))
        state["resumeInput"] = entry.get("_source") or session.get("resume")
        # 라이브러리 프로필을 시드 — build_user_profile 은 멱등이라 재추출하지 않는다(D84).
        state["normalizedUserProfile"] = {
            k: v for k, v in entry.items() if not k.startswith("_")}
        cached_posting = session.get("posting_summary") or {}
        if cached_posting.get("_sourceHash") == hashlib.md5(
                ((posting_input or {}).get("value") or "").encode("utf-8")).hexdigest():
            state["normalizedJobPosting"] = {
                k: v for k, v in cached_posting.items() if not k.startswith("_")}

        response, _final = run_pipeline_with_state(state)
        label = str(entry.get("_label") or name)
        results.append({"label": label, "resume": label, **response.model_dump()})
        warnings.extend(response.warnings)
        if response.status == "completed":
            _archive(session, session_updates, hashlib.md5(
                ((posting_input or {}).get("value") or "").encode("utf-8")).hexdigest(),
                response.model_dump(), label)
        if entry.get("_sourceHash") == active_hash and response.status == "completed":
            session_updates["analysis"] = response.model_dump()
            if response.roadmap:
                session_updates["roadmap"] = response.model_dump()["roadmap"]

    return AgentResult(
        reply="",
        data={"status": "completed" if results else "failed",
              "multiFit": results, "multiFitAxis": "resume", "unmatchedTargets": unmatched},
        warnings=warnings,
        followUpQuestions=[],
        sessionUpdates=session_updates,
    )


def _run_multi(session: dict[str, Any], posting_input: dict | None,
               fetch_warnings: list[dict], targets: list[str]) -> AgentResult:
    """지목된 공고들을 각각 판정한다(D88). 도구 내부 반복 — 오케스트레이터 큐는 불변."""

    library = session.get("posting_library") or []
    active_hash = hashlib.md5(
        ((posting_input or {}).get("value") or "").encode("utf-8")).hexdigest()

    warnings = list(fetch_warnings)
    results: list[dict] = []
    unmatched: list[str] = []
    session_updates: dict = {}

    for name in targets:
        entry = _match_library(name, library)
        if entry is None:
            unmatched.append(name)
            warnings.append({"code": "fit_target_not_found",
                             "message": f"'{name}' 공고가 정리된 기록(라이브러리)에 없습니다"})
            continue
        request = AnalyzeRequest(
            userId=int(session.get("userId") or 0),
            jobPostingInput=JobPostingInput(
                sourceType="text",
                value=f"[정리된 공고 재사용] {entry.get('companyName') or name}"),
            preparationPeriodWeeks=int(session.get("preparationPeriodWeeks") or DEFAULT_WEEKS),
            availableHoursPerWeek=int(session.get("availableHoursPerWeek") or DEFAULT_HOURS),
            options=AnalyzeOptions(includeAlternatives=False),
        )
        state = request_to_state(request, str(uuid.uuid4()))
        if session.get("resume"):
            state["resumeInput"] = session["resume"]
        if session.get("profile"):
            state["normalizedUserProfile"] = session["profile"]
        # 라이브러리 파싱본을 시드 — parse_job_posting 은 멱등이라 재파싱하지 않는다(D84).
        state["normalizedJobPosting"] = {
            k: v for k, v in entry.items() if not k.startswith("_")}

        response, _final = run_pipeline_with_state(state)
        company = str(entry.get("companyName") or name)
        item = {"company": company, "label": company, **response.model_dump()}
        results.append(item)
        warnings.extend(response.warnings)
        if response.status == "completed":
            _archive(session, session_updates, str(entry.get("_sourceHash") or ""),
                     response.model_dump())
        # analysis 자산은 활성 공고의 판정일 때만 승격 — 근거-대상 불일치 방지.
        if entry.get("_sourceHash") == active_hash and response.status == "completed":
            session_updates["analysis"] = response.model_dump()
            if response.roadmap:
                session_updates["roadmap"] = item["roadmap"]

    return AgentResult(
        reply="",
        data={"status": "completed" if results else "failed",
              "multiFit": results, "multiFitAxis": "posting", "unmatchedTargets": unmatched},
        warnings=warnings,
        followUpQuestions=[],
        sessionUpdates=session_updates,
    )

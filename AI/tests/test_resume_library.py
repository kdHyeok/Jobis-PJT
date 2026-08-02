"""이력서 라이브러리 (D119) — 공고 라이브러리(D86/D88/D111)의 이력서 축 대칭.

출발점은 실측이다(2026-08-02): 이력서 슬롯이 하나뿐이라 커리어 저장소 요약·붙여넣은 원문·
올린 파일이 서로를 덮었고, **어느 것으로 답했는지 사용자가 알 수 없었다.** 원천마다 담긴
내용의 두께가 달라 같은 질문에 다른 답이 나오는데 이유가 화면에 없었다.

LLM 을 부르지 않는다 — 프로필 빌드는 가짜로 대신하고, 라이브러리·지목·전환의 결정론만 잰다.
"""

from __future__ import annotations

import pytest

from jobis_ai.agents import _common


@pytest.fixture(autouse=True)
def _no_llm_profile_build(monkeypatch):
    """`build_user_profile` 은 LLM 을 쓴다 — 원문에서 스킬 하나를 떼는 가짜로 바꾼다."""

    def fake_build(state):
        text = str((state.get("resumeInput") or {}).get("value") or "")
        return {"normalizedUserProfile": {"skills": [{"name": text.split()[0]}] if text else []}}

    monkeypatch.setattr(_common, "build_user_profile", fake_build)


def _session(resume: dict | None = None, **extra):
    return {"resume": resume, "_sessionId": "", **extra}


# --- 1단계: 출처를 말한다 --------------------------------------------------
def test_resume_identity_derives_origin_without_new_write_sites():
    """표식을 새로 심지 않고 이미 있는 것에서 파생한다 — 파일은 sourceType, 커리어 요약은
    v2bridge 가 찍은 origin, 나머지는 사용자가 대화창에 넣은 것."""
    assert _common.resume_identity(
        {"sourceType": "file", "value": "C:/tmp/내이력서_v3.pdf"}) == ("uploaded", "내이력서_v3.pdf")
    assert _common.resume_identity(
        {"sourceType": "text", "value": "…", "origin": "career_summary"}
    ) == ("career_summary", "커리어 저장소")
    assert _common.resume_identity(
        {"sourceType": "text", "value": "…"}) == ("pasted", "붙여넣은 이력서")
    assert _common.resume_identity(None) == ("", "")


# --- 2단계: 라이브러리 -----------------------------------------------------
def test_ensure_profile_registers_resume_so_the_next_one_does_not_erase_it():
    """새 이력서가 와도 이전 것이 남는다 — 전에는 슬롯 하나를 덮어써서 통째로 사라졌다."""
    session = _session({"sourceType": "text", "value": "Python 이력서 A"})
    _common.ensure_profile(session)
    first = list(session["resume_library"])
    assert len(first) == 1

    # 새 이력서 도착(chat 이 하는 것과 같은 무효화) — 라이브러리는 건드리지 않는다
    session = _session({"sourceType": "text", "value": "Java 이력서 B"},
                       profile=None, resume_library=first)
    _common.ensure_profile(session)
    labels = [e["_sourceText"] for e in session["resume_library"]]
    assert labels == ["Python 이력서 A", "Java 이력서 B"]


def test_same_resume_twice_is_one_entry():
    session = _session({"sourceType": "text", "value": "Python 이력서 A"})
    _common.ensure_profile(session)
    session["profile"] = None
    _common.ensure_profile(session)
    assert len(session["resume_library"]) == 1


def test_library_keeps_the_source_dict_so_switching_is_lossless():
    """공고는 URL 이 변해서 텍스트로 굳혔지만, 이력서 원천은 세션 안에서 안정적이라
    dict 를 그대로 보존한다 — 되돌려 놓으면 무손실이다."""
    source = {"sourceType": "text", "value": "Python 이력서 A"}
    session = _session(source)
    _common.ensure_profile(session)
    assert session["resume_library"][0]["_source"] == source


# --- 3단계: 지목·전환 ------------------------------------------------------
def _two_resume_session():
    session = _session({"sourceType": "text", "value": "Python 이력서 A"})
    _common.ensure_profile(session)
    session = _session({"sourceType": "text", "value": "Java 이력서 B",
                        "origin": "career_summary"},
                       resume_library=list(session["resume_library"]))
    _common.ensure_profile(session)
    return session


def test_match_resume_by_label_and_by_ordinal():
    """사용자는 라벨로도 순번으로도 부른다 — 이력서에는 회사명 같은 자연스러운 이름이 없다."""
    library = _two_resume_session()["resume_library"]
    assert _common.match_resume("커리어 저장소", library)["_origin"] == "career_summary"
    assert _common.match_resume("붙여넣은", library)["_origin"] == "pasted"
    assert _common.match_resume("1", library)["_origin"] == "pasted"
    assert _common.match_resume("2", library)["_origin"] == "career_summary"
    assert _common.match_resume("없는이름", library) is None


def test_switch_active_resume_swaps_source_and_invalidates_analysis():
    """판정은 이력서×공고의 함수다 — 이력서가 바뀌면 이전 판정은 다른 사람의 판정이다."""
    session = _two_resume_session()
    session["analysis"] = {"fitGrade": "상"}
    warnings: list[dict] = []
    switched, updates = _common.switch_active_resume(session, "붙여넣은 이력서", warnings)
    assert updates["resume"]["value"] == "Python 이력서 A"
    assert updates["analysis"] is None
    assert switched["resume"]["value"] == "Python 이력서 A"
    assert not warnings


def test_unknown_target_warns_instead_of_silently_using_the_active_one():
    """폴백은 이유를 삼키지 않는다(§2-6)."""
    session = _two_resume_session()
    warnings: list[dict] = []
    _, updates = _common.switch_active_resume(session, "없는이력서", warnings)
    assert updates == {}
    assert [w["code"] for w in warnings] == ["resume_target_not_found"]


# --- grep 도구: 업로드 파일 원문 -------------------------------------------
def test_resume_source_text_reads_the_file_not_the_path(tmp_path):
    """전에는 `resume["value"]` 를 그대로 넘겨서 **경로 문자열 하나를 원문이라고 훑고 있었다.**"""
    path = tmp_path / "이력서.txt"
    path.write_text("Kafka 파이프라인을 운영했습니다", encoding="utf-8")
    text = _common.resume_source_text({"sourceType": "file", "value": str(path)})
    assert "Kafka" in text


# --- 4단계: 적합도를 이력서 축으로 반복 ------------------------------------
class _Resp:
    status = "completed"
    roadmap = ()
    warnings = ()
    followUpQuestions = ()

    @staticmethod
    def model_dump():
        return {"status": "completed", "fitGrade": "중", "overallScore": 0.6,
                "summary": "요약", "gaps": [{"reason": "격차1"}], "roadmap": []}


def test_fit_analysis_repeats_over_resumes_for_one_posting(monkeypatch):
    """"A와 B 중 이 공고에 뭐가 나아?" 는 공고 축 반복으로는 답할 수 없다(D119).

    활성 이력서는 바꾸지 않고, `analysis` 자산도 활성 이력서의 판정일 때만 승격한다 —
    자소서·면접의 근거가 다른 사람의 이력서와 짝지어지면 안 된다.
    """
    from jobis_ai.agents import fit_analysis, tool_render

    seeded: list = []

    def fake_pipeline(state):
        seeded.append(state["normalizedUserProfile"]["skills"][0]["name"])
        return _Resp(), dict(state)

    monkeypatch.setattr("jobis_ai.agents.fit_analysis.run_pipeline_with_state", fake_pipeline)
    session = _two_resume_session()          # 활성 = "Java 이력서 B"(커리어 저장소)
    session["job_posting"] = {"sourceType": "text", "value": "공고 원문"}
    session["_agentArgs"] = {"fit_analysis": {
        "resumeTargets": "붙여넣은 이력서, 커리어 저장소, 없는이력서"}}

    out = fit_analysis.run(session)

    assert seeded == ["Python", "Java"]                    # 이력서별로 프로필을 시드해 반복
    assert [r["label"] for r in out.data["multiFit"]] == ["붙여넣은 이력서", "커리어 저장소"]
    assert out.data["multiFitAxis"] == "resume"
    assert out.data["unmatchedTargets"] == ["없는이력서"]
    assert out.sessionUpdates.get("analysis")              # 활성(커리어 저장소) 판정만 승격
    assert "resume" not in out.sessionUpdates              # 활성 이력서는 안 바뀐다

    reply, _ = tool_render.render_fit_analysis(out.data, session)
    assert "**붙여넣은 이력서**" in reply and "**커리어 저장소**" in reply
    assert "없는이력서" in reply and "이력서는 기록이 없어요" in reply


def test_posting_comparison_wins_and_says_it_folded_the_resume_axis(monkeypatch):
    """두 축을 동시에 펼치면 조합이 곱으로 늘어 읽을 수 없는 표가 된다 — 접되 삼키지 않는다."""
    from jobis_ai.agents import fit_analysis

    monkeypatch.setattr("jobis_ai.agents.fit_analysis.run_pipeline_with_state",
                        lambda state: (_Resp(), dict(state)))
    session = _two_resume_session()
    session["job_posting"] = {"sourceType": "text", "value": "공고 원문"}
    session["posting_library"] = [{"_sourceHash": "a", "companyName": "원더스랩"},
                                  {"_sourceHash": "b", "companyName": "오로라월드"}]
    session["_agentArgs"] = {"fit_analysis": {"targets": "원더스랩, 오로라월드",
                                              "resumeTargets": "1, 2"}}

    out = fit_analysis.run(session)

    assert out.data["multiFitAxis"] == "posting"
    assert "resume_axis_folded" in [w["code"] for w in out.warnings]


def test_same_origin_twice_gets_a_distinguishing_ordinal():
    """실측(2026-08-02 스모크): 이력서 둘을 붙여넣자 라벨이 둘 다 "붙여넣은 이력서"라
    **비교 답변이 어느 쪽을 말하는지 알 수 없었다.** 기존 이름은 바꾸지 않는다."""
    session = _session({"sourceType": "text", "value": "Python 이력서 A"})
    _common.ensure_profile(session)
    session = _session({"sourceType": "text", "value": "Java 이력서 B"},
                       resume_library=list(session["resume_library"]))
    _common.ensure_profile(session)

    library = session["resume_library"]
    assert [e["_label"] for e in library] == ["붙여넣은 이력서", "붙여넣은 이력서 #2"]
    # 접미사가 붙어도 지목이 갈린다 — 정확 일치를 먼저 본다
    assert _common.match_resume("붙여넣은 이력서 #2", library)["_sourceText"] == "Java 이력서 B"
    assert _common.match_resume("붙여넣은 이력서", library)["_sourceText"] == "Python 이력서 A"

"""판정·이력서가 활성 슬롯에서 밀려나도 그 대화 안에서는 남아 있는가.

활성 슬롯(`analysis`·`resume`)의 무효화 자체는 규약이다(판정은 이력서×공고의 함수).
여기서 지키는 것은 **무효화가 곧 소멸이면 안 된다**는 것 — 라이브러리가 받아 둔다.
"""

from jobis_ai.agents._common import attach_analysis, preserve_active_resume


def test_attach_analysis_puts_summary_on_the_matching_posting():
    session = {"posting_library": [{"companyName": "A", "_sourceHash": "h1"},
                                   {"companyName": "B", "_sourceHash": "h2"}]}
    library = attach_analysis(session, "h2", {
        "fitGrade": "중",
        "strengths": [{"text": "파이썬"}],
        "gaps": [{"reason": "K8s 경험 없음"}],
    }, "붙여넣은 이력서")
    assert library[0].get("_analyses") is None
    assert library[1]["_analyses"] == [{
        "resumeLabel": "붙여넣은 이력서", "fitGrade": "중",
        "strengths": ["파이썬"], "gaps": ["K8s 경험 없음"]}]


def test_attach_analysis_keeps_one_record_per_resume():
    session = {"posting_library": [{"_sourceHash": "h1"}]}
    library = attach_analysis(session, "h1", {"fitGrade": "상"}, "이력서 A")
    session["posting_library"] = library
    library = attach_analysis(session, "h1", {"fitGrade": "중"}, "이력서 B")
    session["posting_library"] = library
    library = attach_analysis(session, "h1", {"fitGrade": "하"}, "이력서 A")   # 갱신
    grades = {a["resumeLabel"]: a["fitGrade"] for a in library[0]["_analyses"]}
    assert grades == {"이력서 A": "하", "이력서 B": "중"}


def test_attach_analysis_returns_none_for_unknown_posting():
    assert attach_analysis({"posting_library": []}, "nope", {"fitGrade": "상"}, "x") is None


def test_preserve_active_resume_recovers_a_resume_no_agent_consumed():
    session = {"resume": {"sourceType": "text", "value": "파이썬 백엔드 3년 " * 20}}
    library = preserve_active_resume(session)
    assert len(library) == 1
    assert library[0]["_source"] == session["resume"]
    assert library[0]["_sourceText"] == session["resume"]["value"]


def test_preserve_active_resume_is_idempotent_and_empty_safe():
    session = {"resume": {"sourceType": "text", "value": "이력서 원문"}}
    session["resume_library"] = preserve_active_resume(session)
    assert len(preserve_active_resume(session)) == 1
    assert preserve_active_resume({}) == []

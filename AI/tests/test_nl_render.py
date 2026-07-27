"""nl_render 유닛 테스트 — 말하기 계층의 안전장치를 못 박는다 (설계 §3.9 / §5.6).

conftest 가 LLM 을 강제 미설정으로 만들므로, 기본적으로 결정론 요약 경로를 탄다.
LLM 이 규칙을 어겼을 때의 동작은 가짜 LLM 을 주입해 검증한다.
"""

from jobis_ai.nl_render import _Summary, render_summary

_GAP = {
    "requirementStatus": [
        {"requirementId": "req-1", "status": "met"},
        {"requirementId": "req-2", "status": "partially_met"},
        {"requirementId": "req-3", "status": "uncertain"},
    ],
    "gaps": [{"requirementId": "req-2", "reason": "근거 부족"}],
    "strengths": [{"requirementId": "req-1", "text": "MySQL 설계"}],
}
_ROADMAP = {"roadmap": [{"title": "SQLD 취득"}], "totalWeeks": 16}
_POSTING = {"jobTitle": "백엔드 개발자"}


def _fake_llm(monkeypatch, summary_text):
    """지정한 문장을 뱉는 가짜 LLM 을 structured 계층에 주입한다."""
    import jobis_ai.structured as st

    class FakeLLM:
        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            return _Summary(summary=summary_text)

    monkeypatch.setattr(st, "get_llm", lambda *a, **k: FakeLLM())


# --- 폴백: LLM 이 없어도 문장이 나온다 -------------------------------------
def test_falls_back_to_deterministic_summary_without_llm():
    """요약은 결과의 얼굴이라 비어 있으면 제품이 고장 난 것처럼 보인다."""
    summary, _ = render_summary(_GAP, _ROADMAP, _POSTING)
    assert summary, "LLM 이 없어도 빈 문자열을 내지 않는다"
    assert "3건 중 1건" in summary
    assert "16주" in summary


def test_deterministic_summary_reports_undecided_separately():
    """'판정 불가'를 '부족'이라고 바꿔 말하지 않는다."""
    summary, _ = render_summary(_GAP, _ROADMAP, _POSTING)
    assert "미확정" in summary or "판정할 수 없어" in summary


def test_empty_analysis_still_produces_a_sentence():
    summary, _ = render_summary({}, {}, {})
    assert summary.strip()


# --- 정책 게이트: 말하기도 검증을 면제받지 않는다 (§5.6) -------------------
def test_llm_summary_with_forbidden_expression_is_rejected(monkeypatch):
    """LLM 이 "합격 가능합니다"를 붙이면 규칙이 잡아내고 결정론 요약으로 되돌린다."""
    _fake_llm(monkeypatch, "이 정도면 합격 가능성이 높습니다. 무조건 지원하세요.")

    summary, warnings = render_summary(_GAP, _ROADMAP, _POSTING)

    assert "합격 가능" not in summary
    assert any(w["code"] == "summary_policy_violation" for w in warnings)
    assert "3건 중 1건" in summary, "결정론 요약으로 대체됐어야 한다"


def test_clean_llm_summary_is_used_as_is(monkeypatch):
    clean = "요구사항 3건 중 1건이 근거로 확인됐고, 나머지는 학습 계획으로 보완합니다."
    _fake_llm(monkeypatch, clean)

    summary, warnings = render_summary(_GAP, _ROADMAP, _POSTING)

    assert summary == clean
    assert not any(w["code"] == "summary_policy_violation" for w in warnings)


def test_blank_llm_summary_falls_back(monkeypatch):
    _fake_llm(monkeypatch, "   ")
    summary, _ = render_summary(_GAP, _ROADMAP, _POSTING)
    assert summary.strip(), "LLM 이 빈 문장을 줘도 폴백한다"


# --- 스키마가 판정을 못 바꾼다 ---------------------------------------------
def test_render_schema_exposes_only_summary_field():
    """판정 필드를 주지 않으면 판정을 바꿀 수 없다 — 프롬프트로 부탁하는 것보다 확실하다.

    이 테스트가 깨졌다면 누군가 렌더러 스키마에 판정 필드를 추가한 것이고,
    그 순간 LLM 이 다시 판단할 수 있게 된다(설계 §0 위반).
    """
    assert set(_Summary.model_fields) == {"summary"}

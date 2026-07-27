"""verify_result 유닛 테스트 (설계 12장, 결정적 규칙).

핵심: evidenceMap 에 없는 근거 id(환각)를 걸러내는 근거 검사.
"""

from jobis_ai.graph.nodes import verify_result


def _profile(evidence_ids):
    return {"evidenceMap": [{"evidenceId": e} for e in evidence_ids]}


def _status(rid, ids, status="met", conf=0.9):
    return {
        "requirementId": rid, "type": "required", "text": rid,
        "status": status, "matchedEvidenceIds": ids, "reason": "근거", "confidence": conf,
    }


def test_hallucinated_evidence_is_removed():
    state = {
        "preparationPeriodWeeks": 16,
        "normalizedUserProfile": _profile(["ev-1", "ev-2"]),
        "gapAnalysisResult": {"requirementStatus": [_status("req-1", ["ev-1", "ev-99"])],
                              "strengths": [], "gaps": []},
        "retryCount": {},
    }
    out = verify_result(state)

    rs = out["gapAnalysisResult"]["requirementStatus"][0]
    assert rs["matchedEvidenceIds"] == ["ev-1"], "존재하는 근거만 남아야 한다"
    types = {v["type"] for v in out["verification"]["violations"]}
    assert "no_evidence" in types


def test_all_evidence_hallucinated_downgrades_met_to_uncertain():
    state = {
        "preparationPeriodWeeks": 16,
        "normalizedUserProfile": _profile(["ev-1"]),
        "gapAnalysisResult": {"requirementStatus": [_status("req-1", ["ev-77"], status="met", conf=0.9)],
                              "strengths": [], "gaps": []},
        "retryCount": {},
    }
    out = verify_result(state)

    rs = out["gapAnalysisResult"]["requirementStatus"][0]
    assert rs["status"] == "uncertain", "근거가 전부 환각이면 met 을 강등해야 한다"
    assert rs["matchedEvidenceIds"] == []
    assert rs["confidence"] <= 0.3


def test_forbidden_expression_is_flagged_and_softened():
    state = {
        "preparationPeriodWeeks": 16,
        "normalizedUserProfile": _profile(["ev-1"]),
        "gapAnalysisResult": {
            "requirementStatus": [_status("req-1", ["ev-1"])],
            "strengths": [{"requirementId": "req-1", "text": "이 회사에 반드시 합격 가능"}],
            "gaps": [],
        },
        "retryCount": {},
    }
    out = verify_result(state)

    types = {v["type"] for v in out["verification"]["violations"]}
    assert "forbidden_expression" in types
    codes = {w["code"] for w in out["warnings"]}
    assert "softened_expression" in codes


def test_period_mismatch_is_inconsistent():
    state = {
        "preparationPeriodWeeks": 16,
        "normalizedUserProfile": _profile(["ev-1"]),
        "gapAnalysisResult": {"requirementStatus": [_status("req-1", ["ev-1"])], "strengths": [], "gaps": []},
        "roadmapResult": {"totalWeeks": 10, "roadmap": []},
        "retryCount": {},
    }
    out = verify_result(state)

    types = {v["type"] for v in out["verification"]["violations"]}
    assert "inconsistent" in types


def test_retry_signal_increments_retrycount_and_targets_gap():
    # no_evidence 3건 → 구조 결함으로 판단 → 재시도
    state = {
        "preparationPeriodWeeks": 16,
        "normalizedUserProfile": _profile(["ev-1"]),
        "gapAnalysisResult": {"requirementStatus": [
            _status("req-1", ["ev-90"]), _status("req-2", ["ev-91"]), _status("req-3", ["ev-92"]),
        ], "strengths": [], "gaps": []},
        "retryCount": {},
    }
    out = verify_result(state)

    signal = out["verification"]["retrySignal"]
    assert signal["required"] is True
    assert signal["targetAgent"] == "analyze_gap"
    assert out["retryCount"]["verify_result"] == 1, "재시도 시 카운트가 올라 무한루프를 막아야 한다"


def test_no_retry_when_budget_exhausted():
    # 이미 1회 재시도했으면(retryCount=1) 더는 재시도하지 않는다
    state = {
        "preparationPeriodWeeks": 16,
        "normalizedUserProfile": _profile(["ev-1"]),
        "gapAnalysisResult": {"requirementStatus": [
            _status("req-1", ["ev-90"]), _status("req-2", ["ev-91"]), _status("req-3", ["ev-92"]),
        ], "strengths": [], "gaps": []},
        "retryCount": {"verify_result": 1},
    }
    out = verify_result(state)

    assert out["verification"]["retrySignal"]["required"] is False
    assert "retryCount" not in out, "재시도하지 않으면 카운트를 건드리지 않는다"


def test_clean_result_passes():
    state = {
        "preparationPeriodWeeks": 16,
        "normalizedUserProfile": _profile(["ev-1"]),
        "gapAnalysisResult": {"requirementStatus": [_status("req-1", ["ev-1"])], "strengths": [], "gaps": []},
        "roadmapResult": {"totalWeeks": 16, "roadmap": []},
        "retryCount": {},
    }
    out = verify_result(state)

    assert out["verification"]["passed"] is True
    assert out["verification"]["retrySignal"]["required"] is False

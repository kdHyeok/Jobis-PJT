"""검증 재시도 루프 통합 테스트 (설계 13.4 / 16.1).

verify_result 가 구조 결함으로 analyze_gap 재시도를 요청했을 때,
컴파일된 그래프가 재시도→재검증 후 **반드시 종료**(무한루프 없음)하는지 검증한다.
retryCount 가드(MAX_VERIFY_RETRY=1)가 실제 그래프에서 동작함을 보장한다.
"""

from jobis_ai.graph import builder, nodes
from jobis_ai.graph.state import Status


def _init_state():
    return {
        "analysisId": "test-retry",
        "userId": 1,
        "jobPostingInput": {"sourceType": "text", "value": "백엔드 개발자 공고 본문"},
        "selectedExperienceIds": [],
        "preparationPeriodWeeks": 16,
        "availableHoursPerWeek": 20,
        "includeAlternatives": False,
        "followUpQuestions": [],
        "sources": [],
        "toolLog": [],
        "warnings": [],
        "retryCount": {},
        "isComplete": False,
    }


def test_retry_loop_runs_once_and_terminates(monkeypatch):
    """analyze_gap 이 항상 환각 근거를 내도 그래프는 1회 재시도 후 종료해야 한다."""

    calls = {"n": 0}

    def hallucinating_gap(state):
        # evidenceMap(mock 프로필은 ev-1 만 보유)에 없는 근거를 3건에 인용 → no_evidence≥3
        calls["n"] += 1
        return {
            "status": Status.ANALYZING_GAP,
            "gapAnalysisResult": {
                "requirementStatus": [
                    {"requirementId": f"req-{i}", "type": "required", "text": "x",
                     "status": "met", "matchedEvidenceIds": ["ev-90", "ev-91"],
                     "reason": "r", "confidence": 0.9}
                    for i in range(1, 4)
                ],
                "strengths": [], "gaps": [],
            },
            "toolLog": [],
        }

    # 그래프 빌드 시점에 바인딩되므로, 패치 후 fresh 그래프를 컴파일한다.
    monkeypatch.setattr(nodes, "analyze_gap", hallucinating_gap)
    app = builder.build_graph()

    out = app.invoke(_init_state())

    assert calls["n"] == 2, "최초 1회 + 재시도 1회, 그 이상 재시도하지 않아야 한다"
    assert out.get("isComplete") is True, "재시도 후 그래프가 종료(assemble)되어야 한다"
    # 재시도 예산 소진 후에는 통과 처리되어 최종 조립까지 도달
    assert out.get("analysisResult")


def test_no_retry_on_clean_run_uses_mock(monkeypatch):
    """환각이 없으면(=mock 폴백 정상) 재시도 없이 한 번에 완료된다."""

    app = builder.build_graph()
    out = app.invoke(_init_state())

    assert out.get("isComplete") is True
    assert (out.get("retryCount") or {}).get("verify_result", 0) == 0


# ---------------------------------------------------------------------------
# 오케스트라의 노드별 산출물 검증·재지시 (설계 16.2)
# ---------------------------------------------------------------------------
def test_route_after_gap_redispatches_then_proceeds():
    # 실패 + 예산 남음 → 같은 에이전트 재지시
    assert nodes.route_after_gap({"nodeFailed": {"analyze_gap": True}, "retryCount": {"analyze_gap": 1}}) == "analyze_gap"
    # 실패했지만 예산 소진 → 다음 에이전트로 진행
    assert nodes.route_after_gap({"nodeFailed": {"analyze_gap": True}, "retryCount": {"analyze_gap": 2}}) == "plan_roadmap"
    # 성공 → 다음 에이전트로
    assert nodes.route_after_gap({"nodeFailed": {"analyze_gap": False}}) == "plan_roadmap"


def test_orchestrator_redispatches_failed_agent_then_continues(monkeypatch):
    """대체 경로 에이전트가 1회 생성 실패하면 오케스트라가 같은 에이전트에게 다시 지시하고,
    2회차에 성공하면 그 결과로 다음 단계로 넘어간다(빈 답으로 그냥 진행하지 않는다)."""

    calls = {"n": 0}

    def flaky_alternatives(state):
        calls["n"] += 1
        failed = calls["n"] < 2  # 1회차 실패, 2회차 성공
        jobs = [] if failed else [{"type": "similar_role", "companyName": "", "reason": "진짜 답"}]
        out = {"status": Status.FINDING_ALTERNATIVES, "alternativeJobs": jobs, "toolLog": []}
        out.update(nodes._gen_retry_updates("find_alternatives", state, failed))
        return out

    monkeypatch.setattr(nodes, "find_alternatives", flaky_alternatives)
    app = builder.build_graph()

    init = _init_state()
    init["includeAlternatives"] = True
    out = app.invoke(init)

    assert calls["n"] == 2, "실패 1회 + 오케스트라 재지시 1회"
    assert out.get("isComplete") is True
    assert out["analysisResult"]["alternativeJobs"], "재지시로 얻은 진짜 답이 결과에 실려야 한다"

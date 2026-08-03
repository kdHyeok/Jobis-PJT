"""배치 의미 판정이 흔들려도 분석이 무너지지 않는다 (`gap_matcher._retry_missing_topics`).

실측 2026-08-03: 같은 공고·같은 이력서를 두 번 분석했는데 한 번은 200, 한 번은 503 이었다.
원인은 **LLM 배치 호출 하나가 서술형 요구사항 전부를 결정하는 구조**였다 — 그 한 번이
실패하면 전부 uncertain 이 되고, 충분성 게이트가 "판정 불가 50% 초과"로 분석을 멈춰
사용자에게 5건을 되물었다. 판정할 자료가 있는데 못 읽어서 사람에게 떠넘긴 것이다.

여기서 검사하는 것: 묶음이 실패해도 **개별로 다시 물어** 판정을 되찾는가, 그리고 그
재시도가 폭주하지 않는가.
"""

from __future__ import annotations

from jobis_ai import gap_matcher as gm

_EVIDENCE = [
    {"evidenceId": "e1", "text": "주문·재고 도메인 REST API 를 설계하고 운영했습니다."},
    {"evidenceId": "e2", "text": "결제 정산 배치를 만들고 테스트를 작성했습니다."},
]
_REQS = [
    {"requirementId": "r1", "type": "required", "text": "대규모 트래픽 운영 경험"},
    {"requirementId": "r2", "type": "required", "text": "도메인 주도 설계 경험"},
    {"requirementId": "r3", "type": "required", "text": "결제 도메인 이해"},
]
_PROFILE = {
    "skills": [], "projects": [], "experiences": [], "certifications": [],
    "awards": [], "education": [], "languages": [],
    "evidenceMap": _EVIDENCE, "skillEvidence": {},
}


def _match(monkeypatch, batch_result, single_results):
    """배치는 `batch_result`, 개별 호출은 `single_results` 를 순서대로 돌려준다."""

    calls = {"batch": 0, "single": 0}

    def fake(topics, texts):
        if len(topics) > 1:
            calls["batch"] += 1
            return batch_result
        calls["single"] += 1
        value = single_results.pop(0) if single_results else None
        return None if value is None else {0: value}

    monkeypatch.setattr(gm, "judge_topics_relevance", fake)
    report = gm.get_gap_matcher().match(_REQS, _PROFILE)
    return report, calls


def test_batch_failure_is_recovered_one_by_one(monkeypatch):
    """묶음이 통째로 실패해도 개별 판정으로 되살린다 — 되묻기로 떠넘기지 않는다."""

    report, calls = _match(monkeypatch, None, [[0], [], [1]])
    assert calls == {"batch": 1, "single": 3}
    statuses = {m.requirementId: m.status for m in report.matches}
    assert statuses == {"r1": "met", "r2": "not_met", "r3": "met"}
    assert not any(m.status == "uncertain" for m in report.matches)


def test_partial_batch_only_retries_the_gaps(monkeypatch):
    """배치가 일부만 답하면 **못 준 것만** 다시 묻는다 — 성공분을 다시 부르지 않는다."""

    report, calls = _match(monkeypatch, {0: [0], 2: []}, [[1]])
    assert calls == {"batch": 1, "single": 1}, "빠진 1건만 개별 호출"
    statuses = {m.requirementId: m.status for m in report.matches}
    assert statuses == {"r1": "met", "r2": "met", "r3": "not_met"}


def test_provider_down_stops_after_one_probe(monkeypatch):
    """첫 재시도가 실패하면 멈춘다 — 흔들림이 아니라 공급자가 내려간 것이다.

    LLM 이 없는데 요구사항 수만큼 더 부르는 것은 시간만 버린다.
    """

    report, calls = _match(monkeypatch, None, [None, [0], [0]])
    assert calls["single"] == 1, "한 번 찔러 보고 그만둔다"
    assert all(m.status == "uncertain" for m in report.matches)
    assert any(w["code"] == "undecidable_requirements" for w in report.warnings)


def test_retry_is_capped(monkeypatch):
    """요구사항이 많은 공고에서 개별 호출이 폭주하지 않는다(배치를 만든 이유가 그것이었다)."""

    many = [{"requirementId": f"r{i}", "type": "required", "text": f"서술형 요건 {i}"}
            for i in range(gm._SEMANTIC_RETRY_MAX + 5)]

    calls = {"single": 0}

    def fake(topics, texts):
        if len(topics) > 1:
            return None
        calls["single"] += 1
        return {0: [0]}

    monkeypatch.setattr(gm, "judge_topics_relevance", fake)
    report = gm.get_gap_matcher().match(many, _PROFILE)
    assert calls["single"] == gm._SEMANTIC_RETRY_MAX
    # 상한을 넘긴 건은 uncertain 으로 남고, 남았다는 사실이 경고에 있다.
    assert sum(1 for m in report.matches if m.status == "uncertain") == 5
    assert any(w["code"] == "undecidable_requirements" for w in report.warnings)

"""평가 지표 순수 함수 유닛 테스트 (설계 18.1). LLM 불필요·결정적."""

from jobis_ai.eval import metrics


# --- requirement_f1 ------------------------------------------------------
def test_f1_perfect_match():
    gold = ["Java/Spring 개발 경험", "SQL 활용 능력"]
    pred = ["Java/Spring 개발 경험", "SQL 활용 능력"]
    r = metrics.requirement_f1(pred, gold)
    assert r["f1"] == 1.0 and r["tp"] == 2 and r["fp"] == 0 and r["fn"] == 0


def test_f1_fuzzy_and_partial():
    gold = ["Java/Spring Boot 기반 웹 백엔드 개발 경험", "RDBMS 설계 및 SQL 활용 능력"]
    pred = ["Java Spring Boot 백엔드 개발 경험", "전혀 다른 무관한 항목"]
    r = metrics.requirement_f1(pred, gold)
    assert r["tp"] == 1, "유사 문장은 매칭, 무관 항목은 미매칭"
    assert r["fp"] == 1 and r["fn"] == 1


def test_f1_empty_predicted():
    r = metrics.requirement_f1([], ["A", "B"])
    assert r["recall"] == 0.0 and r["f1"] == 0.0


# --- groundedness --------------------------------------------------------
def test_groundedness_all_valid():
    rs = [{"matchedEvidenceIds": ["ev-1", "ev-2"]}]
    r = metrics.groundedness(rs, ["ev-1", "ev-2", "ev-3"])
    assert r["groundedness"] == 1.0 and r["hallucinated"] == 0


def test_groundedness_detects_hallucination():
    rs = [{"matchedEvidenceIds": ["ev-1", "ev-99"]}, {"matchedEvidenceIds": ["ev-77"]}]
    r = metrics.groundedness(rs, ["ev-1"])
    assert r["citations"] == 3 and r["grounded"] == 1 and r["hallucinated"] == 2
    assert r["groundedness"] == round(1 / 3, 4)


def test_groundedness_no_citations_is_one():
    r = metrics.groundedness([{"matchedEvidenceIds": []}], ["ev-1"])
    assert r["groundedness"] == 1.0


# --- policy_violations ---------------------------------------------------
def test_policy_detects_forbidden():
    r = metrics.policy_violations(["이 회사에 반드시 합격 가능합니다", "정상 문장"])
    assert r["violations"] >= 1
    assert "반드시" in r["matched"] or "합격 가능" in r["matched"]


def test_policy_clean_text():
    r = metrics.policy_violations(["요구사항을 충족하는 근거가 있습니다"])
    assert r["violations"] == 0


# --- roadmap_compliance --------------------------------------------------
def test_roadmap_within_budget_and_complete():
    roadmap = {"roadmap": [
        {"title": "A", "startDate": "2026-08-01", "endDate": "2026-08-14",
         "doneCriteria": "산출물", "estimatedHours": 40},
    ]}
    r = metrics.roadmap_compliance(roadmap, weeks=16, weekly_hours=20)  # 예산 320h
    assert r["overBudget"] is False and r["missingFields"] == 0 and r["compliant"] is True


def test_roadmap_over_budget_flagged():
    roadmap = {"roadmap": [
        {"title": "A", "startDate": "2026-08-01", "endDate": "2026-08-14",
         "doneCriteria": "x", "estimatedHours": 500},
    ]}
    r = metrics.roadmap_compliance(roadmap, weeks=16, weekly_hours=20)  # 예산 320h
    assert r["overBudget"] is True and r["compliant"] is False


def test_roadmap_missing_fields_flagged():
    roadmap = {"roadmap": [
        {"title": "A", "startDate": "", "endDate": "2026-08-14",
         "doneCriteria": "", "estimatedHours": 10},
    ]}
    r = metrics.roadmap_compliance(roadmap, weeks=16, weekly_hours=20)
    assert r["missingFields"] == 2 and r["compliant"] is False


# --- provenance — baseline 이 "무엇으로 잰 수치인가"를 스스로 말해야 한다 (§4-3) -----
def test_active_model_follows_the_provider(monkeypatch):
    """모델명은 **프로바이더 분기를 아는 한 곳**에서만 나온다.

    이게 없던 동안 하네스가 `llm_model` 을 무조건 적어 Claude 로 돌린 baseline 에
    `"model": "gpt-4.1-mini"` 가 박혔다(오귀속). get_llm 과 같은 사전을 쓰므로 갈라질 수 없다.
    """

    from dataclasses import replace

    from jobis_ai.config import get_settings

    base = get_settings()
    gms = replace(base, llm_provider="openai", llm_model="gpt-4.1", llm_model_light="gpt-4.1-mini")
    assert (gms.active_model(), gms.active_model("light")) == ("gpt-4.1", "gpt-4.1-mini")

    cli = replace(base, llm_provider="claude_code",
                  claude_code_model="sonnet", claude_code_model_light="haiku")
    assert (cli.active_model(), cli.active_model("light")) == ("sonnet", "haiku")
    assert cli.active_model() != cli.llm_model, "CLI 로 돌렸는데 GMS 모델명이 나오면 그게 오귀속이다"


def test_provenance_records_provider_model_and_time():
    """baseline 파일에 박히는 최소 정보 — 없으면 수치를 나중에 비교할 수 없다."""

    from jobis_ai.eval import provenance

    meta = provenance(mode="테스트")
    assert set(meta) >= {"provider", "model", "modelLight", "temperature", "measuredAt"}
    assert meta["mode"] == "테스트"          # 하네스별 추가 정보가 실린다
    assert meta["measuredAt"][:2] == "20"    # ISO 날짜 — "언제 잰 수치인가"

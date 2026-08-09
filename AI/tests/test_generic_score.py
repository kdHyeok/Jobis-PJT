"""제네릭 점수 하네스 테스트 — 지표 로직과 정직성 (LLM·임베딩 없음).

실측은 CLI 가 담당. 여기서는 **delta 정의가 맞는지**와 **못 잴 때 지어내지 않는지**만 본다.
"""

from __future__ import annotations

import json
from pathlib import Path

from jobis_ai.eval.generic_score import score_question

_DATASET = Path(__file__).resolve().parents[1] / "evals" / "generic_dataset.json"

_POSTINGS = [
    {"id": "a", "label": "A", "text": "백엔드 채용. 자격요건: Java, Spring, MySQL."},
    {"id": "b", "label": "B", "text": "프론트엔드 채용. 자격요건: React, TypeScript."},
]
_QUESTION = {"id": "q", "text": "뭘 공부하면 좋을까요?"}


_POSTING_SIM = {"a|b": 0.3}       # 기준선(공고 요건 유사도) — 호출부가 준다(D108)


def _score(question=None, postings=None, posting_sim=None):
    return score_question(question or _QUESTION, postings or _POSTINGS,
                          _POSTING_SIM if posting_sim is None else posting_sim)


def _stub(monkeypatch, answers: dict[str, str], sims: dict[tuple[str, str], float] | None):
    """답변과 유사도를 주입한다 — 지표 계산만 검증한다."""

    monkeypatch.setattr("jobis_ai.eval.generic_score._answer",
                        lambda text, q: (answers[text[:2]], []))

    class _Embedder:
        def similarity_matrix(self, lefts, rights):
            if sims is None:
                return None
            keys = [t[:2] for t in lefts]
            return [[1.0 if i == j else sims[tuple(sorted((keys[i], keys[j])))]
                     for j in range(len(keys))] for i in range(len(keys))]

    monkeypatch.setattr("jobis_ai.embed.get_embedder", lambda: _Embedder())


def test_generic_score_is_answer_sim_minus_posting_sim(monkeypatch):
    """delta = 답변 유사도 - 공고 유사도. **원시 유사도가 아니라 차이**가 지표다.

    비슷한 공고 둘이 비슷한 답을 받는 것은 정상이므로 그 정상분을 빼야 해석이 된다.
    """

    # 답변끼리 0.9 로 비슷한데 공고끼리는 0.3 뿐 → 공고를 안 읽은 것(제네릭).
    _stub(monkeypatch, {"백엔": "AB답변", "프론": "AB답변2"},
          {("백엔", "프론"): 0.3})

    class _E:
        def similarity_matrix(self, lefts, rights):
            # 답변 호출(짧은 텍스트)과 공고 호출(긴 텍스트)을 길이로 가른다.
            sim = 0.9 if max(len(t) for t in lefts) < 20 else 0.3
            n = len(lefts)
            return [[1.0 if i == j else sim for j in range(n)] for i in range(n)]

    monkeypatch.setattr("jobis_ai.embed.get_embedder", lambda: _E())
    r = _score()
    assert r["measured"] is True
    assert r["meanAnswerSim"] == 0.9 and r["meanPostingSim"] == 0.3
    assert r["genericScore"] == 0.6, "delta 가 지표다 — 0.9 를 그대로 쓰면 해석할 수 없다"


def test_unmeasurable_does_not_invent_a_score(monkeypatch):
    """임베딩 미연결이면 **점수를 만들지 않는다** — 지어낸 0.0 은 개선으로 읽힌다(§2-1)."""

    _stub(monkeypatch, {"백엔": "x", "프론": "y"}, None)
    r = _score()
    assert r["measured"] is False
    assert "genericScore" not in r
    assert "임베딩" in r["reason"]


def test_empty_answers_are_reported_not_hidden(monkeypatch):
    """빈 답변은 유사도를 왜곡한다(빈 문자열끼리는 비슷하다) — 숨기면 점수가 거짓말한다."""

    monkeypatch.setattr("jobis_ai.eval.generic_score._answer",
                        lambda text, q: ("" if text.startswith("백엔") else "답변", []))

    class _E:
        def similarity_matrix(self, lefts, rights):
            n = len(lefts)
            return [[1.0 if i == j else 0.5 for j in range(n)] for i in range(n)]

    monkeypatch.setattr("jobis_ai.embed.get_embedder", lambda: _E())
    r = _score()
    assert r["emptyAnswers"] == ["a"]


def test_dataset_is_real_postings_across_domains():
    """평가셋은 **실공고**여야 하고 도메인이 갈려 있어야 한다.

    - 8개 이상: 쌍이 28개가 되어야 한 쌍이 평균을 못 흔든다(4개=쌍 6개일 때 노이즈 바닥이
      회차마다 두 배로 흔들려 전후 비교가 불가능했다).
    - **실공고**: 합성 공고 8개는 한 사람이 써서 문체·서식까지 비슷해 공고 유사도 기준선이
      실제보다 높게 깔렸다 → delta 가 관대해진다. 그래서 RAG DB 실공고로 바꿨다.
    - **회사 중복 금지**: 같은 회사 공고 둘은 서식이 같아 유사도를 부풀린다.
    """

    data = json.loads(_DATASET.read_text(encoding="utf-8"))
    postings = data["postings"]
    assert len(postings) >= 8 and len(data["questions"]) >= 2

    companies, categories = [], set()
    for p in postings:
        src = p.get("source")
        assert src, f"{p['id']}: 실공고 출처(source)가 없다 — 어느 공고로 쟀는지 확인 불가"
        assert src.get("url") and src.get("uid"), f"{p['id']}: 출처에 uid·url 이 있어야 한다"
        companies.append(src.get("company"))
        categories.add(src.get("roleCategory"))
        assert len(p["text"]) >= 400, f"{p['id']}: 원문이 너무 짧다"
    assert len(set(companies)) == len(companies), f"회사가 중복됐다: {companies}"
    assert len(categories) >= 6, f"도메인이 좁다: {categories}"

    for question in data["questions"]:
        assert question.get("note"), "질문마다 왜 넣었는지 적는다(평가셋이 거울이 되지 않게)"


def test_posting_baseline_mirrors_answer_facts():
    """기준선은 **파서가 뽑은 요구사항**만으로 만든다(D108) — 원문 상용구를 안 들인다.

    처음에는 원문에서 서식 낱말을 지워 썼는데 실공고로 바꾸자 무너졌다: 공고 유사도가 합성 8공고
    0.5122 → 실공고 8건 **0.5525** 로 올라갔다. 실공고에는 회사 소개·복리후생·지원방법이 길게
    붙고 그 부분이 직무와 무관하게 닮았는데, 섹션 제목 낱말만 지우는 필터로는 못 걷어낸다.
    부풀린 기준선을 delta 에서 빼면 지표가 관대해진다.
    """

    from jobis_ai.eval.generic_score import requirement_baseline_text

    parsed = {
        "companyName": "㈜무언가", "jobTitle": "백엔드 개발자",
        "requiredRequirements": [{"requirementId": "req-1", "text": "Java 경력 3년 이상"}],
        "preferredRequirements": [{"requirementId": "pref-1", "text": "Kafka 경험"}],
        "techStack": ["Java", "Spring"],
        "domainKeywords": ["커머스", "결제"],
        "yearsEvidence": "경력 3년 이상",
    }
    out = requirement_baseline_text(parsed)
    assert "Java 경력 3년 이상" in out and "Kafka 경험" in out
    assert "Spring" in out
    # **답변 쪽 facts 와 대칭**: 직무명·도메인·연차도 요구다. 실측에서 자격요건이 "학력무관"
    # 한 줄뿐인 공고의 기준선이 64자로 나왔는데, 그 공고를 가르는 정보(Flutter / IoT·가전·
    # 헬스케어)는 jobTitle·domainKeywords 에 이미 정형화돼 있었다 — 새 칸이 필요한 게 아니라
    # 있는 칸을 안 쓴 것이었다.
    assert "백엔드 개발자" in out
    assert "커머스" in out and "결제" in out
    assert "경력 3년 이상" in out
    # 회사명은 넣지 않는다 — 요구가 아니라 신원이고, 회사명이 다 달라 기준선을 인위적으로 낮춘다.
    assert "㈜무언가" not in out
    # 요구사항을 못 읽은 공고는 빈 문자열 — 호출부가 경고로 남긴다(조용히 넘기지 않는다).
    assert requirement_baseline_text({}) == ""


def test_baseline_is_frozen_in_the_dataset():
    """기준선은 데이터셋에 **박혀** 있어야 한다 — 눈금자가 측정마다 흔들리면 안 된다(D109).

    실측(2026-08-01, 같은 8공고·같은 코드): 측정마다 LLM 으로 다시 파싱했더니 기준선 공고
    유사도가 0.5271 → 0.5156 으로 움직였고, delta 이동 +0.032 중 **0.0115(3분의 1)가 기준선이
    내려간 몫**이었다 — 답변이 하나도 안 변해도 점수가 움직인다는 뜻이다.
    """

    from jobis_ai.eval.generic_score import posting_baseline

    data = json.loads(_DATASET.read_text(encoding="utf-8"))
    for posting in data["postings"]:
        assert posting.get("baselineText"), (
            f"{posting['id']}: baselineText 가 없다 — `--refresh-baseline` 으로 뽑는다")

    texts, warnings = posting_baseline(data["postings"])
    assert len(texts) == len(data["postings"]) and not warnings
    # 두 번 불러도 같다(= LLM 을 안 부른다). 이게 눈금자의 정의다.
    assert posting_baseline(data["postings"])[0] == texts


def test_missing_baseline_stops_instead_of_scoring_silently():
    """기준선이 없으면 **멈춘다.** 빈 문자열끼리는 비슷해서 조용히 점수를 왜곡한다(§2-1)."""

    import pytest

    from jobis_ai.eval.generic_score import posting_baseline

    with pytest.raises(SystemExit, match="refresh-baseline"):
        posting_baseline([{"id": "a", "text": "x"}])


def test_spread_reports_sem_not_just_range():
    """문턱은 **SEM** 이다 — 범위(max−min)는 표본이 늘면 커져서 문턱으로 쓸 수 없다.

    실측(2026-08-01): runs 3→5 로 늘렸더니 key-requirement 의 범위가 0.0186 → 0.0375 로 두 배가
    됐고 그걸 보고 "표본을 늘려도 안 좁아진다"고 잘못 판단했다. 같은 데이터의 SEM 은 study-plan
    에서 0.0081 → 0.0041 로 **반이 됐다** — runs 를 늘린 효과는 실제로 있었다.
    """

    from jobis_ai.eval.generic_score import _spread

    out = _spread([0.10, 0.20, 0.30])
    assert out["mean"] == 0.2 and out["range"] == 0.2 and out["n"] == 3
    assert out["sd"] == 0.1 and out["sem"] == round(0.1 / 3 ** 0.5, 4)
    # 같은 흩어짐인데 표본이 많으면 SEM 은 줄고 범위는 안 줄어든다.
    wide = _spread([0.10, 0.20, 0.30, 0.10, 0.20, 0.30])
    assert wide["range"] == out["range"] and wide["sem"] < out["sem"]


def test_threshold_comes_from_pooled_sigma_not_this_measurement():
    """문턱은 **합동 σ 로 정한 상수**다 — 측정마다 SEM 으로 잡으면 문턱이 3배 흔들린다.

    실측(2026-08-02): 같은 질문의 σ 가 두 측정에서 0.0091 과 0.0267 로 나왔다(2.9배). n=5 의
    σ 추정 90% 구간이 ×0.60~×2.37 이므로 그건 노이즈가 변한 게 아니라 추정 오차다.
    """

    from jobis_ai.eval.generic_score import _POOLED_SD, comparison_threshold

    assert comparison_threshold(5) == round(2 * _POOLED_SD / 5 ** 0.5, 4)
    # runs 를 늘리면 √runs 로 좁아진다 — 그게 문턱을 줄이는 유일한 손잡이다.
    assert comparison_threshold(20) < comparison_threshold(5)
    assert abs(comparison_threshold(20) - comparison_threshold(5) / 2) < 1e-4


def test_answers_are_kept_for_human_verification(monkeypatch):
    """답변을 결과에 남긴다 — 수치만 있으면 사람이 "이 점수가 맞나"를 확인할 수 없다."""

    monkeypatch.setattr("jobis_ai.eval.generic_score._answer",
                        lambda text, q: (f"{text[:2]} 답변", []))

    class _E:
        def similarity_matrix(self, lefts, rights):
            n = len(lefts)
            return [[1.0 if i == j else 0.5 for j in range(n)] for i in range(n)]

    monkeypatch.setattr("jobis_ai.embed.get_embedder", lambda: _E())
    r = _score()
    assert r["answers"] == {"a": "백엔 답변", "b": "프론 답변"}


def test_off_posting_skill_rate_is_immune_to_phrasing():
    """공고 밖 기술 비율은 **문장 틀에 면역**이다 — 어떻게 말했는지가 아니라 무엇을 말했는지만 본다.

    실측(2026-08-01): key-requirement 답변 네 개가 각 공고의 요건을 정확히 인용했는데도 임베딩
    유사도가 높았다. 문장 틀이 같고 답변이 짧아 틀이 임베딩을 지배했기 때문이다 — 그 지표만
    쓰면 표현만 바꿔 점수를 올릴 수 있다(Goodhart). 이 짝 지표가 그걸 막는다.
    """

    from jobis_ai.eval.generic_score import off_posting_skill_rate

    posting = "백엔드 채용. 자격요건: Java, Spring, MySQL 경험."
    # 같은 내용을 다른 틀로 말해도 값이 같다.
    assert off_posting_skill_rate("Java 와 Spring 이 필수입니다.", posting) == 0.0
    assert off_posting_skill_rate("핵심은 Java, Spring 이에요.", posting) == 0.0
    # 공고에 없는 기술을 끌어오면 올라간다(제네릭·환각 방향).
    assert off_posting_skill_rate("Java 와 Kubernetes 를 공부하세요.", posting) == 0.5
    # 기술을 못 찾으면 **점수를 만들지 않는다**(§2-1).
    assert off_posting_skill_rate("요건이 명확합니다.", posting) is None

    # **공고의 기술 어휘가 빈약하면 비율을 만들지 않는다.** 실측(8공고): 보안 공고는 taxonomy 가
    # 아는 기술이 0개여서 답변의 모든 기술이 "밖"으로 잡혀 rate 1.0 이 됐고, 그 값이 전체 평균을
    # 끌어올려 품질 수치처럼 보였다 — 답변 결함이 아니라 분모가 없는 것이다.
    thin = "정보보안 담당자 채용. 자격요건: 웹 취약점 이해, 보안 관제 경험."
    assert off_posting_skill_rate("Python 과 Bash 로 자동화하세요.", thin) is None


def test_answer_scaffold_is_stripped_symmetrically():
    """답변에서도 **우리가 넣은 라벨**을 걷어낸다 — 공고 쪽만 걷어내면 비대칭이다.

    실측(2026-08-01, 8공고): 답변 내용은 완전히 도메인별로 갈렸는데(OWASP/DVWA vs
    Swift/StoreKit) 답변 유사도가 공고 유사도보다 높았다. 겹친 것은 `save_plan` 산출물을 조립할
    때 붙이는 고정 라벨이었다. **제품에서 라벨을 빼는 것은 답이 아니다**(사용자가 근거를 확인하는
    장치다, D104) — 지표를 대칭으로 만든다.
    """

    from jobis_ai.eval.generic_score import _content_only

    reply = ("필수 요건부터 보세요.\n\n프로젝트 제안\n1. **적재 파이프라인**\n   주기 수집\n"
             "   커버하는 요건: Python 데이터 처리\n   완료 기준: 매일 성공")
    out = _content_only(reply)
    for label in ("프로젝트 제안", "커버하는 요건:", "완료 기준:"):
        assert label not in out, f"조립 라벨이 남았다: {label}"
    # LLM 이 쓴 문장과 공고별 내용은 **남는다** — 그게 같으면 실제로 같은 답을 쓴 것이다.
    assert "필수 요건부터 보세요." in out
    assert "적재 파이프라인" in out and "Python 데이터 처리" in out and "매일 성공" in out

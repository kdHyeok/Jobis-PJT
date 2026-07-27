"""스켈레톤 스모크 테스트 — 그래프가 계약 응답까지 정상적으로 도는지 확인."""

from jobis_ai.contracts.api import AnalyzeOptions, AnalyzeRequest, JobPostingInput
from jobis_ai.graph import nodes
from jobis_ai.service import run_analysis


def _base_request(**overrides) -> AnalyzeRequest:
    # 네트워크에 의존하지 않도록 text 소스타입을 쓴다(공고 본문을 직접 제공).
    kwargs = dict(
        userId=1,
        jobPostingInput=JobPostingInput(
            sourceType="text",
            value="백엔드 개발자 채용. 자격요건: Java, Spring Boot, MySQL 개발 경험. 우대: AWS 배포 경험.",
        ),
        selectedExperienceIds=[3, 7, 9],
        preparationPeriodWeeks=16,
        availableHoursPerWeek=20,
    )
    kwargs.update(overrides)
    return AnalyzeRequest(**kwargs)


def test_happy_path_completes():
    """충분한 정보 → completed, 요구사항·종합 등급·진단이 채워진다."""

    resp = run_analysis(_base_request())

    assert resp.status == "completed"
    assert resp.analysisId
    assert resp.requirements, "요구사항이 조립되어야 한다"
    assert resp.fitGrade in ("상", "중", "하"), "종합 등급이 매겨져야 한다"
    assert resp.summary, "진단/요약 문장이 있어야 한다"
    assert resp.meta.generatedAt


def test_high_grade_gives_diagnosis_only_no_roadmap():
    """상 등급이면 로드맵 없이 진단만 낸다 (2026-07-21). mock 프로필은 상으로 판정된다."""

    resp = run_analysis(_base_request())

    assert resp.fitGrade == "상"
    assert resp.roadmap == [], "상 등급은 부족 역량을 채우는 로드맵을 만들지 않는다"
    assert "충족" in resp.summary, "상 등급 진단 문장이 요약에 들어가야 한다"


def test_mid_low_grade_gets_roadmap_and_alternatives(monkeypatch):
    """중·하 등급이면 진단과 함께 로드맵·대안 공고까지 제공한다 (2026-07-21).

    mock 프로필이 상으로 판정되므로, 등급 산출만 중으로 강제해 라우팅을 검증한다.
    """

    monkeypatch.setattr(nodes, "overall_fit", lambda _basis: (0.5, "중"))
    resp = run_analysis(_base_request())

    assert resp.fitGrade == "중"
    assert resp.roadmap, "중·하 등급은 부족 역량을 채우는 로드맵을 제공한다"
    assert resp.alternativeJobs, "중·하 등급은 대안 공고까지 추천한다(옵션 없이도)"


def test_high_grade_honors_explicit_alternatives_request():
    """상 등급이어도 사용자가 대안을 명시 요청하면 대안은 보여준다(로드맵은 여전히 생략)."""

    resp = run_analysis(_base_request(options=AnalyzeOptions(includeAlternatives=True)))

    assert resp.fitGrade == "상"
    assert resp.alternativeJobs, "includeAlternatives=True 이면 상 등급이라도 대안을 보여준다"
    assert resp.roadmap == [], "상 등급은 대안을 보여줘도 로드맵은 만들지 않는다"


def test_alternatives_skipped_by_default():
    """상 등급 + 옵션 미지정이면 대체 경로 노드를 건너뛴다."""

    resp = run_analysis(_base_request())

    assert resp.alternativeJobs == []

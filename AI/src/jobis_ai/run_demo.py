"""스켈레톤이 전체적으로 도는지 눈으로 확인하는 데모 실행기.

    python -m jobis_ai.run_demo
"""

from __future__ import annotations

import json

from jobis_ai.contracts.api import AnalyzeOptions, AnalyzeRequest, JobPostingInput
from jobis_ai.service import run_analysis


_SAMPLE_JOB = (
    "백엔드 개발자 채용 (신입~주니어)\n"
    "주요업무: Java·Spring Boot 기반 REST API 설계/개발, MySQL 모델링·쿼리 최적화, Redis 캐싱\n"
    "자격요건: Java/Spring Boot 웹 백엔드 개발 경험, RDBMS 설계·SQL 활용, Git 협업\n"
    "우대사항: AWS 배포 경험, Docker, 대용량 트래픽/성능 최적화\n"
    "도메인: 이커머스"
)


def main() -> None:
    # 네트워크에 의존하지 않도록 text 소스타입으로 샘플 공고를 넣는다.
    request = AnalyzeRequest(
        userId=1,
        jobPostingInput=JobPostingInput(sourceType="text", value=_SAMPLE_JOB),
        selectedExperienceIds=[3, 7, 9],
        preparationPeriodWeeks=16,
        availableHoursPerWeek=20,
        options=AnalyzeOptions(includeAlternatives=True),
    )

    response = run_analysis(request)

    print("=== AnalyzeResponse ===")
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

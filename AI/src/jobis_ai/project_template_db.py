"""프로젝트 과제 템플릿 DB (project_template_db) — 자격증으로 못 메우는 gap 담당.

설계 §3.6-④ / '커버리지 한계'. 자격증은 만능이 아니다. "MSA 운영 경험",
"이벤트 드리븐 아키텍처 설계" 같은 경험형 gap 에는 마땅한 자격증이 없다.
이런 gap 은 **직접 만들어 본 산출물**로 증명하는 게 맞고, 그 과제를 여기서 꺼낸다.

역할 경계:
- **순수 내부 정형 DB.** LLM/RAG 없음. 과제 문구를 LLM 이 지어내면 doneCriteria 가
  "이해한다" 같은 측정 불가능한 문장이 된다. 여기 템플릿의 doneCriteria 는 전부
  **산출물·수치·URL 로 확인 가능**하게 미리 적어 둔다.
- 매칭되는 템플릿이 없으면 빈 목록. 아무 과제나 갖다 붙이지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class ProjectTemplate:
    """프로젝트 과제 1건.

    targetSkills : 이 과제로 증명되는 표준 스킬 key 들
    doneCriteria : **측정 가능한** 완료 기준 (산출물/수치/URL). 여기가 이 DB 의 존재 이유다.
    estimatedHours: 표준 추정 소요 시간. 스케줄러의 배치 근거.
    """

    key: str
    title: str
    targetSkills: tuple[str, ...]
    goal: str
    tasks: tuple[str, ...]
    doneCriteria: str
    estimatedHours: int
    difficulty: str = "intermediate"


_TEMPLATES: tuple[ProjectTemplate, ...] = (
    ProjectTemplate(
        key="docker-containerize",
        title="기존 프로젝트 컨테이너화 및 로컬 오케스트레이션",
        targetSkills=("docker",),
        goal="애플리케이션과 DB 를 컨테이너로 묶어 한 번의 명령으로 재현 가능한 개발환경을 만든다",
        tasks=(
            "애플리케이션 Dockerfile 작성 (멀티스테이지 빌드로 이미지 크기 축소)",
            "docker-compose 로 앱 + DB + 캐시 구성",
            "환경변수/볼륨으로 설정과 데이터 분리",
            "이미지 빌드 시간과 최종 용량 측정·기록",
        ),
        doneCriteria="`docker compose up` 한 번으로 전체 스택이 기동되는 저장소 URL + 이미지 용량 최적화 전후 수치",
        estimatedHours=20,
        difficulty="beginner",
    ),
    ProjectTemplate(
        key="k8s-deploy",
        title="쿠버네티스 클러스터에 서비스 배포",
        targetSkills=("kubernetes",),
        goal="컨테이너화된 서비스를 k8s 에 올리고 무중단 배포와 오토스케일을 구성한다",
        tasks=(
            "Deployment/Service/Ingress 매니페스트 작성",
            "ConfigMap·Secret 으로 설정 분리",
            "HPA(오토스케일) 구성 후 부하를 걸어 스케일 동작 확인",
            "롤링 업데이트로 무중단 배포 검증",
        ),
        doneCriteria="매니페스트가 포함된 저장소 URL + 부하 시 파드 수 변화 그래프 + 무중단 배포 로그",
        estimatedHours=35,
    ),
    ProjectTemplate(
        key="msa-decompose",
        title="모놀리식 서비스를 마이크로서비스로 분리",
        targetSkills=("msa",),
        goal="도메인 경계를 기준으로 서비스를 나누고 서비스 간 통신·장애 격리를 구현한다",
        tasks=(
            "도메인 경계 식별 후 서비스 분리 설계도 작성",
            "서비스 2개 이상으로 분리하고 REST 또는 gRPC 로 통신",
            "API Gateway 도입 및 서비스 디스커버리 구성",
            "서킷 브레이커로 장애 전파 차단 구현 후 장애 주입 테스트",
        ),
        doneCriteria="분리 전후 아키텍처 다이어그램 + 저장소 URL + 한 서비스 강제 종료 시 나머지가 살아남는 테스트 결과",
        estimatedHours=50,
        difficulty="advanced",
    ),
    ProjectTemplate(
        key="event-driven",
        title="이벤트 드리븐 아키텍처로 비동기 처리 전환",
        targetSkills=("kafka", "rabbitmq", "msa"),
        goal="동기 호출로 묶여 있던 처리를 이벤트 기반 비동기로 바꿔 결합도를 낮춘다",
        tasks=(
            "동기 호출 구간 식별 후 이벤트 흐름 설계",
            "Kafka(또는 RabbitMQ) 프로듀서·컨슈머 구현",
            "멱등성 보장과 재처리(DLQ) 전략 구현",
            "전환 전후 응답시간·처리량 측정",
        ),
        doneCriteria="이벤트 흐름도 + 저장소 URL + 전환 전후 응답시간/처리량 비교 수치 + 중복 이벤트 재처리 테스트 결과",
        estimatedHours=45,
        difficulty="advanced",
    ),
    ProjectTemplate(
        key="perf-tuning",
        title="대용량 트래픽 대응 성능 최적화",
        targetSkills=("redis", "elasticsearch"),
        goal="병목을 측정으로 찾아내고 캐싱·인덱싱으로 개선한 뒤 수치로 증명한다",
        tasks=(
            "부하 테스트 도구(k6/JMeter)로 현재 처리량·응답시간 기준선 측정",
            "APM 또는 쿼리 로그로 병목 지점 특정",
            "캐시 계층(Redis) 도입 및 캐시 무효화 전략 구현",
            "개선 후 동일 조건으로 재측정해 비교",
        ),
        doneCriteria="부하 테스트 스크립트 + 개선 전후 TPS/p95 응답시간 비교표 + 병목 분석 문서",
        estimatedHours=40,
    ),
    ProjectTemplate(
        key="cicd-pipeline",
        title="CI/CD 파이프라인 구축",
        targetSkills=("cicd", "jenkins", "github-actions"),
        goal="커밋부터 배포까지 자동화해 수동 배포를 없앤다",
        tasks=(
            "PR 시 자동 테스트·린트 실행 워크플로 작성",
            "main 머지 시 이미지 빌드 후 레지스트리 푸시",
            "스테이징 자동 배포 및 배포 실패 시 롤백 구성",
            "파이프라인 소요 시간 측정·단축",
        ),
        doneCriteria="워크플로 설정 파일이 포함된 저장소 URL + 자동 배포 성공 기록 + 파이프라인 소요 시간",
        estimatedHours=25,
    ),
    ProjectTemplate(
        key="rest-api",
        title="REST API 설계·구현 및 문서화",
        targetSkills=("rest-api", "spring-boot", "spring", "django", "fastapi", "express", "nestjs"),
        goal="리소스 중심으로 API 를 설계하고 문서·테스트까지 갖춘 서버를 만든다",
        tasks=(
            "리소스·HTTP 메서드·상태코드 규칙을 정한 API 설계서 작성",
            "CRUD 엔드포인트 구현 및 입력 검증·에러 응답 표준화",
            "OpenAPI(Swagger) 문서 자동화",
            "주요 엔드포인트 통합 테스트 작성",
        ),
        doneCriteria="배포된 Swagger 문서 URL + 저장소 URL + 통합 테스트 통과 결과",
        estimatedHours=30,
        difficulty="beginner",
    ),
    ProjectTemplate(
        key="monitoring",
        title="서비스 모니터링·알림 체계 구축",
        targetSkills=("grafana",),
        goal="장애를 사용자보다 먼저 아는 상태를 만든다",
        tasks=(
            "메트릭 수집(Prometheus) 및 대시보드(Grafana) 구성",
            "핵심 지표(에러율·지연·처리량) 패널 작성",
            "임계값 초과 시 알림 연동",
            "장애 상황을 인위적으로 만들어 알림 동작 검증",
        ),
        doneCriteria="대시보드 스크린샷 + 알림 발송 기록 + 설정 파일 저장소 URL",
        estimatedHours=25,
    ),
    ProjectTemplate(
        key="frontend-spa",
        title="프론트엔드 SPA 구현 및 상태관리",
        targetSkills=("react", "vue", "angular", "svelte", "nextjs", "typescript"),
        goal="컴포넌트 구조와 상태관리를 갖춘 화면을 만들고 성능까지 챙긴다",
        tasks=(
            "컴포넌트 계층·상태 흐름 설계",
            "전역 상태관리 도입 및 서버 상태와 분리",
            "코드 스플리팅·이미지 최적화 적용",
            "Lighthouse 로 성능 점수 측정·개선",
        ),
        doneCriteria="배포된 서비스 URL + 저장소 URL + Lighthouse 개선 전후 점수",
        estimatedHours=35,
    ),
    ProjectTemplate(
        key="git-collaboration",
        title="Git 브랜치 전략 기반 협업 경험 만들기",
        targetSkills=("git",),
        goal="혼자 커밋하는 수준을 넘어 리뷰·병합 흐름을 갖춘 협업 이력을 만든다",
        tasks=(
            "브랜치 전략(GitHub Flow) 문서화 후 저장소에 적용",
            "기능 단위 브랜치 → PR → 리뷰 → Squash merge 흐름 반복",
            "커밋 메시지 컨벤션 적용",
            "오픈소스 저장소에 PR 1건 이상 기여",
        ),
        doneCriteria="머지된 PR 목록 URL(리뷰 코멘트 포함) + 컨벤션이 지켜진 커밋 히스토리",
        estimatedHours=20,
        difficulty="beginner",
    ),
    ProjectTemplate(
        key="evidence-portfolio",
        title="기존 경험의 근거 보강 및 포트폴리오화",
        targetSkills=(),  # 특정 스킬용이 아닌 폴백 과제
        goal="이미 해본 일을 채용담당자가 검증할 수 있는 형태로 정리한다",
        tasks=(
            "프로젝트별로 문제-조치-성과를 수치와 함께 정리",
            "본인이 맡은 범위와 기술적 의사결정 근거 명시",
            "코드 저장소 README 에 아키텍처·실행 방법 정리",
            "성과를 증명할 지표(응답시간·처리량·사용자 수 등) 수집",
        ),
        doneCriteria="프로젝트별 문제-조치-성과가 수치와 함께 정리된 포트폴리오 URL",
        estimatedHours=15,
        difficulty="beginner",
    ),
)

# 스킬이 특정되지 않는 gap(근거 부족형)에 쓸 폴백 과제 key
_FALLBACK_KEY = "evidence-portfolio"


class ProjectTemplateDB:
    """프로젝트 과제 조회기."""

    def __init__(self) -> None:
        self._by_key = {t.key: t for t in _TEMPLATES}
        self._by_skill: dict[str, list[ProjectTemplate]] = {}
        for template in _TEMPLATES:
            for skill in template.targetSkills:
                self._by_skill.setdefault(skill, []).append(template)

    def get(self, key: str) -> ProjectTemplate | None:
        return self._by_key.get(key)

    def for_skill(self, skill_key: str) -> list[ProjectTemplate]:
        """표준 스킬 key → 그 스킬을 증명하는 과제들. 없으면 빈 목록."""

        return list(self._by_skill.get((skill_key or "").strip().lower(), []))

    def best_for_skill(self, skill_key: str) -> ProjectTemplate | None:
        """해당 스킬에 가장 적합한 과제. 없으면 None(폴백은 호출부가 정한다).

        **관련성이 비용보다 우선한다.** 정렬 순서:
          1. 이 스킬이 과제의 주 대상인가 (targetSkills 에서의 위치)
          2. 과제가 얼마나 좁게 겨냥하는가 (targetSkills 개수 — 적을수록 전용 과제)
          3. 난이도 → 4. 소요 시간
        시간만 보고 고르면 "MSA 부족" 에 5시간 짧다는 이유로 MSA 전용 과제 대신
        '이벤트 드리븐 전환' 과제가 뽑힌다 — 더 싸지만 겨냥이 빗나간 처방이다.
        """

        key = (skill_key or "").strip().lower()
        candidates = self.for_skill(key)
        if not candidates:
            return None
        rank = {"beginner": 0, "intermediate": 1, "advanced": 2}
        return min(candidates, key=lambda t: (
            t.targetSkills.index(key) if key in t.targetSkills else len(t.targetSkills),
            len(t.targetSkills),
            rank.get(t.difficulty, 1),
            t.estimatedHours,
        ))

    def fallback(self) -> ProjectTemplate:
        """스킬을 특정할 수 없는 gap(예: '기재됐으나 근거 없음')용 과제."""

        return self._by_key[_FALLBACK_KEY]


@lru_cache(maxsize=1)
def get_project_template_db() -> ProjectTemplateDB:
    """프로세스당 하나를 재사용한다."""

    return ProjectTemplateDB()

"""IT 자격증 정형 DB (cert_db) — 로드맵의 '무엇을 언제까지' 를 실데이터로 확정한다.

설계 §3.6. 로드맵을 RAG 가 아니라 정형 DB 로 푸는 이유:
- 강의·아티클은 **무한·휘발성**이라 벡터 DB 스냅샷과 상충하고 재색인 부담이 크다.
- IT 자격증은 반대로 **개수 유한·시험범위 안정·완전 정형·스킬 매핑 명확**이라
  정형 DB 조회 한 방으로 끝난다.
덤으로 doneCriteria 가 "자격증 취득"이라 **진짜 측정 가능**해지고, prepHours 가
실측 기반이라 예산 재적합이 정확하며, 시험 일정으로 **역산 배치**까지 가능하다.

역할 경계:
- **순수 내부 정형 DB.** LLM/RAG/임베딩 없음.
- 자격증이 만능은 아니다. 자격증으로 못 메우는 경험형 gap("MSA 운영")은
  `project_template_db` 가 맡는다(§3.6 커버리지 한계).

데이터 신뢰도(중요):
- `prepHours` 는 **표준 추정치**다. 개인 배경에 따라 크게 다르므로 정밀한 값이 아니라
  '규모 감각'으로 쓴다. 스케줄러도 이 값을 상대적 비교에만 쓴다.
- `examDates` 는 **비워 뒀다.** 시험 일정은 해마다 바뀌어서 코드에 박으면 반드시
  낡는다. 운영에서 채우거나 외부 로드로 교체하고, 비어 있으면 스케줄러는 일정 역산을
  건너뛰고 prepHours 기반 순차 배치로 폴백한다(없는 날짜를 지어내지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

CertLevel = str  # "beginner" | "intermediate" | "advanced"


@dataclass(frozen=True)
class Certification:
    """자격증 1건.

    key            : 내부 표준 키
    name           : 정식 명칭 (doneCriteria 에 그대로 쓴다)
    issuer         : 발급 기관
    level          : 난이도
    prepHours      : 표준 준비 시간(추정). 스케줄러의 주차 배치 근거.
    subjects       : 시험 과목 — 로드맵 항목의 tasks 로 그대로 쓴다(지어내지 않아도 된다).
    examWindowsPerYear: 연간 시행 횟수. 0 이면 `alwaysAvailable` 참고.
    alwaysAvailable: 상시 응시 가능 여부(글로벌 벤더 자격증). True 면 시험일 압박이 없다.
    examDates      : 다음 시험일들(YYYY-MM-DD). **기본 비어 있음** — 위 '데이터 신뢰도' 참고.
    url            : 공식 안내 페이지
    """

    key: str
    name: str
    issuer: str
    level: CertLevel
    prepHours: int
    subjects: tuple[str, ...] = ()
    examWindowsPerYear: int = 0
    alwaysAvailable: bool = False
    examDates: tuple[str, ...] = field(default_factory=tuple)
    url: str = ""


# 국내 IT 취업에서 실제로 통용되는 자격증 시드.
# 확장 시 여기에 추가하거나 외부 DB 로드로 교체하되, CertDB 의 공개 메서드는 유지한다.
_CERTS: tuple[Certification, ...] = (
    Certification(
        key="info-processing-engineer",
        name="정보처리기사",
        issuer="한국산업인력공단",
        level="intermediate",
        prepHours=120,
        subjects=("소프트웨어 설계", "소프트웨어 개발", "데이터베이스 구축",
                  "프로그래밍 언어 활용", "정보시스템 구축관리"),
        examWindowsPerYear=3,
        url="https://www.q-net.or.kr",
    ),
    Certification(
        key="sqld",
        name="SQLD(SQL 개발자)",
        issuer="한국데이터산업진흥원",
        level="beginner",
        prepHours=40,
        subjects=("데이터 모델링의 이해", "SQL 기본 및 활용"),
        examWindowsPerYear=4,
        url="https://www.dataq.or.kr",
    ),
    Certification(
        key="sqlp",
        name="SQLP(SQL 전문가)",
        issuer="한국데이터산업진흥원",
        level="advanced",
        prepHours=150,
        subjects=("데이터 모델링의 이해", "SQL 기본 및 활용", "SQL 고급 활용 및 튜닝"),
        examWindowsPerYear=2,
        url="https://www.dataq.or.kr",
    ),
    Certification(
        key="adsp",
        name="ADsP(데이터분석 준전문가)",
        issuer="한국데이터산업진흥원",
        level="beginner",
        prepHours=30,
        subjects=("데이터 이해", "데이터 분석 기획", "데이터 분석"),
        examWindowsPerYear=4,
        url="https://www.dataq.or.kr",
    ),
    Certification(
        key="bigdata-engineer",
        name="빅데이터분석기사",
        issuer="한국데이터산업진흥원",
        level="intermediate",
        prepHours=100,
        subjects=("빅데이터 분석 기획", "빅데이터 탐색", "빅데이터 모델링", "빅데이터 결과 해석"),
        examWindowsPerYear=2,
        url="https://www.dataq.or.kr",
    ),
    Certification(
        key="linux-master-2",
        name="리눅스마스터 2급",
        issuer="한국정보통신진흥협회",
        level="beginner",
        prepHours=50,
        subjects=("리눅스 운영 및 관리", "리눅스 활용"),
        examWindowsPerYear=4,
        url="https://www.ihd.or.kr",
    ),
    Certification(
        key="network-admin-2",
        name="네트워크관리사 2급",
        issuer="한국정보통신자격협회",
        level="beginner",
        prepHours=50,
        subjects=("TCP/IP", "네트워크 일반", "NOS", "네트워크 운용기기"),
        examWindowsPerYear=4,
        url="https://www.icqa.or.kr",
    ),
    Certification(
        key="security-engineer",
        name="정보보안기사",
        issuer="한국인터넷진흥원",
        level="advanced",
        prepHours=150,
        subjects=("시스템 보안", "네트워크 보안", "애플리케이션 보안",
                  "정보보안 일반", "정보보안 관리 및 법규"),
        examWindowsPerYear=2,
        url="https://www.q-net.or.kr",
    ),
    Certification(
        key="aws-saa",
        name="AWS Certified Solutions Architect – Associate",
        issuer="Amazon Web Services",
        level="intermediate",
        prepHours=80,
        subjects=("보안 아키텍처 설계", "복원력 있는 아키텍처 설계",
                  "고성능 아키텍처 설계", "비용 최적화 아키텍처 설계"),
        alwaysAvailable=True,
        url="https://aws.amazon.com/certification/",
    ),
    Certification(
        key="aws-dva",
        name="AWS Certified Developer – Associate",
        issuer="Amazon Web Services",
        level="intermediate",
        prepHours=70,
        subjects=("AWS 서비스 기반 개발", "보안", "배포", "문제 해결 및 최적화"),
        alwaysAvailable=True,
        url="https://aws.amazon.com/certification/",
    ),
    Certification(
        key="cka",
        name="CKA(Certified Kubernetes Administrator)",
        issuer="CNCF",
        level="advanced",
        prepHours=90,
        subjects=("클러스터 아키텍처·설치·구성", "워크로드 및 스케줄링",
                  "서비스 및 네트워킹", "스토리지", "트러블슈팅"),
        alwaysAvailable=True,
        url="https://www.cncf.io/training/certification/cka/",
    ),
    Certification(
        key="ckad",
        name="CKAD(Certified Kubernetes Application Developer)",
        issuer="CNCF",
        level="intermediate",
        prepHours=70,
        subjects=("애플리케이션 설계 및 빌드", "애플리케이션 배포",
                  "관찰 가능성 및 유지보수", "애플리케이션 환경·설정·보안", "서비스 및 네트워킹"),
        alwaysAvailable=True,
        url="https://www.cncf.io/training/certification/ckad/",
    ),
    Certification(
        key="ocjp",
        name="Oracle Certified Professional: Java SE Programmer",
        issuer="Oracle",
        level="intermediate",
        prepHours=60,
        subjects=("Java 언어 기초", "객체지향 설계", "제네릭·컬렉션", "동시성", "스트림 API"),
        alwaysAvailable=True,
        url="https://education.oracle.com",
    ),
)


class CertDB:
    """자격증 조회기."""

    def __init__(self) -> None:
        self._by_key = {c.key: c for c in _CERTS}

    def get(self, key: str) -> Certification | None:
        return self._by_key.get((key or "").strip().lower())

    def get_many(self, keys: list[str]) -> list[Certification]:
        """키 목록 → 자격증들. 모르는 키는 조용히 건너뛴다(없는 자격증을 지어내지 않는다)."""

        out: list[Certification] = []
        for key in keys:
            cert = self.get(key)
            if cert and cert not in out:
                out.append(cert)
        return out

    def all(self) -> list[Certification]:
        return list(_CERTS)

    def easiest(self, certs: list[Certification]) -> Certification | None:
        """후보 중 가장 진입 부담이 적은 것 (난이도 → 준비시간 순).

        로드맵은 '따게 만드는 것'이 목적이므로, 같은 스킬을 커버한다면 가벼운 쪽을 권한다.
        (SQL gap 에 SQLP(150h)보다 SQLD(40h)를 먼저 권하는 게 맞다)
        """

        if not certs:
            return None
        rank = {"beginner": 0, "intermediate": 1, "advanced": 2}
        return min(certs, key=lambda c: (rank.get(c.level, 1), c.prepHours))


@lru_cache(maxsize=1)
def get_cert_db() -> CertDB:
    """프로세스당 하나를 재사용한다.

    운영 전환 시 여기서 외부 DB 로드 구현체를 반환하도록 바꾸면 노드 코드는 불변.
    """

    return CertDB()

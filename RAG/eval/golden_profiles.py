"""입력 B(이력서 profile JSON) 골든 표본 12건 — 명세서 `_UserProfileRead` 스키마 준수.

용도: 명세서가 규정한 **실입력 경로**로 검색 품질을 재기 위한 평가 입력.
기존 15종 트랙(`spec_anchor.SPEC_QUERIES`)은 `spec_adapter`가 내부적으로 만들어내는
QuerySpec을 흉내낸 것이어서 입력 A도 B도 아니었다 — 매핑 단계
(`_profile_tech`·`_total_exp_years`·`classify`)가 통째로 측정에서 빠져 있었다.

설계 원칙:
- **합성 데이터임을 명시한다.** 실제 이력서가 아니라 명세서 예시 구조를 따라 저자가 작성했다.
  회사·학교명은 익명 표기. 실사용 분포 대표성은 주장할 수 없다.
- 직군 12종을 1건씩 덮고, 연차는 신입~7년으로 분산한다.
- 기술·연차를 기존 15종 트랙의 대응 항목과 **일치**시켜 3자 비교가 가능하게 한다
  (같은 조건을 A: 직업명만 / B: profile / 15종: 합성 중간형으로 넣었을 때의 차이를 본다).
- `period`는 `_PERIOD_RE`(`YYYY.M ~ YYYY.M`)가 파싱할 수 있는 형식만 쓴다.
  연차는 `_total_exp_years`가 **재직기간 합산 // 12**로 계산하므로 의도한 연차가 나오도록 맞춘다.
- `evidenceMap`/`uncertainties`는 명세서대로 검색 신호에 쓰이지 않지만 스키마 준수를 위해 채운다.
"""
from __future__ import annotations

SYNTHETIC_NOTE = ("저자 작성 합성 표본 (실제 이력서 아님). 명세서 _UserProfileRead 스키마·예시 준수. "
                  "실사용 이력서 분포 대표성은 주장하지 않는다.")


def _p(pid: str, role: str, category: str, target_years: int | None,
       skills: list[str], stack: list[str], major="컴퓨터공학") -> dict:
    """연차 target_years가 나오도록 재직기간을 역산해 profile을 조립한다."""
    if target_years is None:                     # 신입 — 재직이력 없음
        experiences = []
    else:
        # 2024.01 시작으로 target_years*12 개월 근무 -> 합산 연차 = target_years
        end_y = 2024 + target_years
        experiences = [{
            "id": "exp-1", "company": "OO테크", "role": role,
            "employmentType": "정규직", "period": f"2024.01 ~ {end_y}.01",
            "summary": f"{role}로 서비스 개발 및 운영 담당",
        }]
    return {
        "_meta": {"id": pid, "role": role, "category": category,
                  "target_exp_years": target_years, "synthetic": True},
        "education": [{
            "id": "edu-1", "school": "OO대학교", "major": major,
            "degree": "학사", "status": "졸업", "period": "2018.03 ~ 2022.02",
        }],
        "experiences": experiences,
        "projects": [{
            "id": "prj-1", "title": f"{role} 담당 프로젝트", "projectType": "실무",
            "period": "2023.01 ~ 2023.08", "teamSize": 5, "role": role,
            "summary": f"{role} 역할로 참여한 프로젝트",
            "techStack": stack,
            "achievements": ["처리량 개선", "운영 자동화"],
        }],
        "skills": [{"name": s, "level": "상" if i < 2 else "중"}
                   for i, s in enumerate(skills)],
        "certifications": [],
        "languages": [{"id": "lang-1", "name": "영어", "testName": "TOEIC",
                       "score": "850", "testDate": "2023.05", "proficiency": "업무 가능"}],
        "bootcamp": [],
        "awards": [],
        "evidenceMap": [{"evidenceId": "ev-1", "source": "prj-1",
                         "text": f"{role} 업무를 수행했습니다."}],
        "uncertainties": [],
    }


# 기존 15종 트랙(SPEC_QUERIES)의 직군·기술·연차에 대응시킨 12건.
# 입력 A는 여기서 role 문자열만 떼어 쓴다 — 같은 조건의 세 입력 형태 비교가 성립한다.
GOLDEN_PROFILES = [
    _p("GB01", "백엔드 개발자", "backend", 3,
       ["Java", "Spring Boot", "JPA", "MySQL"], ["Java", "Spring Boot", "JPA", "MySQL"]),
    _p("GB02", "프론트엔드 개발자", "frontend", 2,
       ["React", "TypeScript", "Next.js"], ["React", "TypeScript", "Next.js"]),
    _p("GB03", "풀스택 개발자", "fullstack", 4,
       ["React", "Node.js", "MySQL"], ["React", "Node.js", "MySQL"]),
    _p("GB04", "안드로이드 개발자", "mobile", 3,
       ["Kotlin", "Android"], ["Kotlin", "Android"]),
    _p("GB05", "DevOps 엔지니어", "devops", 5,
       ["Docker", "Kubernetes", "AWS", "Jenkins"], ["Docker", "Kubernetes", "AWS", "Jenkins"]),
    _p("GB06", "SRE 엔지니어", "sre", 4,
       ["Kubernetes", "Linux", "Terraform"], ["Kubernetes", "Linux", "Terraform"]),
    _p("GB07", "데이터 엔지니어", "data_engineer", 3,
       ["Python", "Kafka", "SQL"], ["Python", "Kafka", "SQL"]),
    _p("GB08", "데이터 사이언티스트", "data_scientist", 2,
       ["Python", "TensorFlow"], ["Python", "TensorFlow"], major="통계학"),
    _p("GB09", "머신러닝 엔지니어", "ml_engineer", 3,
       ["Python", "PyTorch", "LLM"], ["Python", "PyTorch", "LLM"]),
    _p("GB10", "데이터 분석가", "data_analyst", None,
       ["SQL", "Python"], ["SQL", "Python"], major="산업공학"),
    _p("GB11", "QA 엔지니어", "qa", 2,
       ["Python", "Git"], ["Python", "Git"]),
    _p("GB12", "보안 엔지니어", "security", 3,
       ["Linux"], ["Linux"], major="정보보호학"),

    # ── 확장분 GB13~GB36 (직군당 3건으로 균형) ─────────────────────────
    # 왜 늘리는가: 12건에서는 쌍대 부트스트랩 CI 반폭이 너무 넓어, 질의 텍스트
    # 구성을 바꿔도 개선이 검출되지 않는다(작업3 사전등록 §3 참고). 36건이면
    # CI가 대략 1/sqrt(3) 배로 좁아진다.
    # 기술 개수를 1~8로 분산시킨 것도 의도적이다 — 임베딩 희석의 용량-반응을
    # profile 트랙에서도 볼 수 있게 하려고 SA16~SA60의 조합에 맞췄다.
    _p("GB13", "서버 개발자", "backend", 1,
       ["Java", "Spring"], ["Java", "Spring"]),
    _p("GB14", "백엔드 엔지니어", "backend", 5,
       ["Node.js", "TypeScript", "MongoDB", "Redis", "AWS", "Docker"],
       ["Node.js", "TypeScript", "MongoDB", "Redis", "AWS", "Docker"]),
    _p("GB15", "프론트엔드 엔지니어", "frontend", 5,
       ["React", "TypeScript"], ["React", "TypeScript"]),
    _p("GB16", "웹 개발자", "frontend", 1,
       ["JavaScript", "HTML", "CSS", "jQuery"], ["JavaScript", "HTML", "CSS", "jQuery"]),
    _p("GB17", "풀스택 엔지니어", "fullstack", 6,
       ["Python", "Django", "Vue"], ["Python", "Django", "Vue"]),
    _p("GB18", "웹 풀스택 개발자", "fullstack", 4,
       ["TypeScript", "Next.js", "Node.js", "PostgreSQL", "Docker", "AWS"],
       ["TypeScript", "Next.js", "Node.js", "PostgreSQL", "Docker", "AWS"]),
    _p("GB19", "iOS 개발자", "mobile", 3,
       ["iOS"], ["iOS"]),
    _p("GB20", "모바일 앱 개발자", "mobile", 5,
       ["Kotlin", "Android", "iOS", "Flutter", "React Native"],
       ["Kotlin", "Android", "iOS", "Flutter", "React Native"]),
    _p("GB21", "클라우드 엔지니어", "devops", 7,
       ["AWS", "Terraform", "Kubernetes"], ["AWS", "Terraform", "Kubernetes"]),
    _p("GB22", "플랫폼 엔지니어", "devops", 4,
       ["Kubernetes", "GitHub Actions", "Ansible", "Docker", "AWS", "Linux",
        "Python", "Terraform"],
       ["Kubernetes", "GitHub Actions", "Ansible", "Docker", "AWS", "Linux",
        "Python", "Terraform"]),
    _p("GB23", "SRE", "sre", 6,
       ["Kubernetes", "Linux"], ["Kubernetes", "Linux"]),
    _p("GB24", "신뢰성 엔지니어", "sre", 5,
       ["Linux", "Python", "Ansible"], ["Linux", "Python", "Ansible"]),
    _p("GB25", "데이터 파이프라인 엔지니어", "data_engineer", 2,
       ["Python", "Kafka"], ["Python", "Kafka"]),
    _p("GB26", "데이터 엔지니어", "data_engineer", 7,
       ["SQL", "PostgreSQL", "Python", "AWS", "Docker", "Kafka", "Elasticsearch", "Linux"],
       ["SQL", "PostgreSQL", "Python", "AWS", "Docker", "Kafka", "Elasticsearch", "Linux"]),
    _p("GB27", "데이터 사이언티스트", "data_scientist", 3,
       ["Python", "TensorFlow", "PyTorch", "SQL", "LLM", "RAG"],
       ["Python", "TensorFlow", "PyTorch", "SQL", "LLM", "RAG"], major="통계학"),
    _p("GB28", "데이터 사이언티스트", "data_scientist", None,
       ["Python"], ["Python"], major="통계학"),
    _p("GB29", "AI 엔지니어", "ml_engineer", 2,
       ["LLM", "LangChain", "RAG", "Python"], ["LLM", "LangChain", "RAG", "Python"]),
    _p("GB30", "MLOps 엔지니어", "ml_engineer", 4,
       ["Kubernetes", "Docker", "Python", "AWS"], ["Kubernetes", "Docker", "Python", "AWS"]),
    _p("GB31", "데이터 애널리스트", "data_analyst", 5,
       ["SQL", "Python", "Elasticsearch"], ["SQL", "Python", "Elasticsearch"],
       major="산업공학"),
    _p("GB32", "비즈니스 데이터 분석가", "data_analyst", None,
       ["SQL", "Python", "Oracle", "MS-SQL", "Elasticsearch", "Git"],
       ["SQL", "Python", "Oracle", "MS-SQL", "Elasticsearch", "Git"], major="경영학"),
    _p("GB33", "테스트 엔지니어", "qa", 3,
       ["Java", "Python", "Git", "Jenkins"], ["Java", "Python", "Git", "Jenkins"]),
    _p("GB34", "품질보증 엔지니어", "qa", None,
       ["Python", "Git", "Docker", "Linux", "Jenkins", "SQL"],
       ["Python", "Git", "Docker", "Linux", "Jenkins", "SQL"]),
    _p("GB35", "정보보안 엔지니어", "security", 5,
       ["Linux", "Python"], ["Linux", "Python"], major="정보보호학"),
    _p("GB36", "클라우드 보안 엔지니어", "security", 7,
       ["AWS", "Linux", "Kubernetes", "Python", "Terraform", "Docker"],
       ["AWS", "Linux", "Kubernetes", "Python", "Terraform", "Docker"], major="정보보호학"),
]

# 입력 A: 직업명 문자열만. 명세서 "데이터 엔지니어" / "백엔드 개발자" 예시 형태.
INPUT_A_QUERIES = [{"id": f"GA{p['_meta']['id'][2:]}",
                    "query": p["_meta"]["role"],
                    "category": p["_meta"]["category"]}
                   for p in GOLDEN_PROFILES]


def profile_payload(p: dict) -> dict:
    """_meta를 뗀 순수 명세서 페이로드 — 어댑터에 넘길 형태."""
    return {k: v for k, v in p.items() if k != "_meta"}

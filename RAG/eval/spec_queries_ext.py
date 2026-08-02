"""정규화 질의 확장 45종 (SA16~SA60) — arm 간 구분 검정력 확보용.

왜 필요한가
-----------
15종에서는 `rrf_vs_rrf_ce`와 `bm25_vs_rrf_ce`가 **어느 k에서도 유의하지 않았다**.
쌍대 부트스트랩 CI 반폭이 표본 수의 대략 1/sqrt(n)로 줄기 때문에, 15 -> 60은 CI를
절반으로 좁힌다. 이게 "최적 arm 미확정"을 해소하는 유일한 사람-비의존 수단이다
(사람 앵커 확장은 현재 불가 — 사용자 확인).

설계
----
- **SA01~SA15는 동결한다.** 사람이 손수 라벨링한 118쌍이 (qid, uid)로 묶여 있어
  id를 재배치하면 그 라벨이 전부 무효가 된다. 확장분은 SA16부터 붙인다.
- 직군 12종을 **각 5건**으로 균형 (기존 편중: backend 3 / 나머지 1~2).
- 두 축을 의도적으로 분산시킨다:
  · **기술 개수 1~8** — `text = role + tech[:8]` 희석 효과의 용량-반응을 볼 수 있게
  · **연차 None(신입)~7년** — 연차 필터 경로가 실제로 밟히게
- 직군명 표기도 흔들어 넣는다("서버 개발자"/"백엔드 엔지니어"/"웹 개발자").
  같은 직군을 한 표기로만 쓰면 제목 어휘 매칭에 유리한 쪽으로 지표가 부풀 수 있다.
- 기술명은 whitelist 표준명만 사용한다(60종). 비표준명은 extract_tech가 버린다.
"""
from __future__ import annotations

SPEC_QUERIES_EXT = [
    # ── backend (기존 3 + 2 = 5) ──
    {"id": "SA16", "role": "서버 개발자", "category": "backend",
     "tech": ["Java", "Spring"], "exp_years": 1},
    {"id": "SA17", "role": "백엔드 엔지니어", "category": "backend",
     "tech": ["Node.js", "TypeScript", "MongoDB", "Redis", "AWS", "Docker"], "exp_years": 5},

    # ── frontend (기존 2 + 3 = 5) ──
    {"id": "SA18", "role": "프론트엔드 엔지니어", "category": "frontend",
     "tech": ["React", "TypeScript"], "exp_years": 5},
    {"id": "SA19", "role": "웹 개발자", "category": "frontend",
     "tech": ["JavaScript", "HTML", "CSS", "jQuery"], "exp_years": 1},
    {"id": "SA20", "role": "프론트엔드 개발자", "category": "frontend",     # 기술 8개 — 희석 상한
     "tech": ["Next.js", "React", "TypeScript", "Vue", "JavaScript", "CSS", "HTML", "Git"],
     "exp_years": 3},

    # ── fullstack (기존 1 + 4 = 5) ──
    {"id": "SA21", "role": "풀스택 개발자", "category": "fullstack",
     "tech": ["Java", "Spring Boot", "React", "MySQL"], "exp_years": 2},
    {"id": "SA22", "role": "풀스택 엔지니어", "category": "fullstack",
     "tech": ["Python", "Django", "Vue"], "exp_years": 6},
    {"id": "SA23", "role": "웹 풀스택 개발자", "category": "fullstack",
     "tech": ["TypeScript", "Next.js", "Node.js", "PostgreSQL", "Docker", "AWS"],
     "exp_years": 4},
    {"id": "SA24", "role": "풀스택 개발자", "category": "fullstack",
     "tech": ["PHP", "MySQL", "jQuery"], "exp_years": None},

    # ── mobile (기존 1 + 4 = 5) ──
    {"id": "SA25", "role": "iOS 개발자", "category": "mobile",
     "tech": ["iOS"], "exp_years": 3},
    {"id": "SA26", "role": "플러터 개발자", "category": "mobile",
     "tech": ["Flutter"], "exp_years": 2},
    {"id": "SA27", "role": "모바일 앱 개발자", "category": "mobile",
     "tech": ["Kotlin", "Android", "iOS", "Flutter", "React Native"], "exp_years": 5},
    {"id": "SA28", "role": "안드로이드 개발자", "category": "mobile",
     "tech": ["Kotlin", "Android", "Java", "Git"], "exp_years": None},

    # ── devops (기존 1 + 4 = 5) ──
    {"id": "SA29", "role": "인프라 엔지니어", "category": "devops",
     "tech": ["Linux", "Docker"], "exp_years": 3},
    {"id": "SA30", "role": "클라우드 엔지니어", "category": "devops",
     "tech": ["AWS", "Terraform", "Kubernetes"], "exp_years": 7},
    {"id": "SA31", "role": "플랫폼 엔지니어", "category": "devops",        # 기술 8개
     "tech": ["Kubernetes", "GitHub Actions", "Ansible", "Docker", "AWS", "Linux",
              "Python", "Terraform"], "exp_years": 4},
    {"id": "SA32", "role": "DevOps 엔지니어", "category": "devops",
     "tech": ["Jenkins", "GitLab"], "exp_years": None},

    # ── sre (기존 1 + 4 = 5) ──
    {"id": "SA33", "role": "SRE", "category": "sre",
     "tech": ["Kubernetes", "Linux"], "exp_years": 6},
    {"id": "SA34", "role": "Site Reliability Engineer", "category": "sre",
     "tech": ["Terraform", "AWS", "Kubernetes", "Linux"], "exp_years": 3},
    {"id": "SA35", "role": "신뢰성 엔지니어", "category": "sre",
     "tech": ["Linux", "Python", "Ansible"], "exp_years": 5},
    {"id": "SA36", "role": "SRE 엔지니어", "category": "sre",
     "tech": ["GCP", "Kubernetes", "Terraform", "Docker", "Git", "Linux", "Python"],
     "exp_years": 2},

    # ── data_engineer (기존 1 + 4 = 5) ──
    {"id": "SA37", "role": "데이터 엔지니어", "category": "data_engineer",
     "tech": ["Kafka", "Python", "SQL", "Elasticsearch"], "exp_years": 5},
    {"id": "SA38", "role": "데이터 파이프라인 엔지니어", "category": "data_engineer",
     "tech": ["Python", "Kafka"], "exp_years": 2},
    {"id": "SA39", "role": "데이터 엔지니어", "category": "data_engineer",   # 기술 8개
     "tech": ["SQL", "PostgreSQL", "Python", "AWS", "Docker", "Kafka",
              "Elasticsearch", "Linux"], "exp_years": 7},
    {"id": "SA40", "role": "빅데이터 엔지니어", "category": "data_engineer",
     "tech": ["Python", "SQL"], "exp_years": None},

    # ── data_scientist (기존 1 + 4 = 5) ──
    {"id": "SA41", "role": "데이터 사이언티스트", "category": "data_scientist",
     "tech": ["Python", "PyTorch", "SQL"], "exp_years": 5},
    {"id": "SA42", "role": "데이터 사이언티스트", "category": "data_scientist",
     "tech": ["Python"], "exp_years": None},
    {"id": "SA43", "role": "데이터 과학자", "category": "data_scientist",
     "tech": ["Python", "TensorFlow", "PyTorch", "SQL", "LLM", "RAG"], "exp_years": 3},
    {"id": "SA44", "role": "데이터 사이언티스트", "category": "data_scientist",
     "tech": ["SQL", "Python", "TensorFlow"], "exp_years": 7},

    # ── ml_engineer (기존 1 + 4 = 5) ──
    {"id": "SA45", "role": "머신러닝 엔지니어", "category": "ml_engineer",
     "tech": ["PyTorch", "Python"], "exp_years": 5},
    {"id": "SA46", "role": "AI 엔지니어", "category": "ml_engineer",
     "tech": ["LLM", "LangChain", "RAG", "Python"], "exp_years": 2},
    {"id": "SA47", "role": "MLOps 엔지니어", "category": "ml_engineer",
     "tech": ["Kubernetes", "Docker", "Python", "AWS"], "exp_years": 4},
    {"id": "SA48", "role": "딥러닝 엔지니어", "category": "ml_engineer",     # 기술 8개
     "tech": ["PyTorch", "TensorFlow", "Python", "LLM", "RAG", "LangGraph",
              "Linux", "Git"], "exp_years": None},

    # ── data_analyst (기존 1 + 4 = 5) ──
    {"id": "SA49", "role": "데이터 분석가", "category": "data_analyst",
     "tech": ["SQL"], "exp_years": 2},
    {"id": "SA50", "role": "데이터 애널리스트", "category": "data_analyst",
     "tech": ["SQL", "Python", "Elasticsearch"], "exp_years": 5},
    {"id": "SA51", "role": "데이터 분석가", "category": "data_analyst",
     "tech": ["SQL", "MySQL", "Python"], "exp_years": 4},
    {"id": "SA52", "role": "비즈니스 데이터 분석가", "category": "data_analyst",
     "tech": ["SQL", "Python", "Oracle", "MS-SQL", "Elasticsearch", "Git"],
     "exp_years": None},

    # ── qa (기존 1 + 4 = 5) ──
    {"id": "SA53", "role": "QA 엔지니어", "category": "qa",
     "tech": ["Python"], "exp_years": 5},
    {"id": "SA54", "role": "테스트 엔지니어", "category": "qa",
     "tech": ["Java", "Python", "Git", "Jenkins"], "exp_years": 3},
    {"id": "SA55", "role": "품질보증 엔지니어", "category": "qa",           # 범용 기술만 — 희석 프로브
     "tech": ["Python", "Git", "Docker", "Linux", "Jenkins", "SQL"], "exp_years": None},
    {"id": "SA56", "role": "QA 엔지니어", "category": "qa",
     "tech": ["JavaScript", "TypeScript"], "exp_years": 2},

    # ── security (기존 1 + 4 = 5) ──
    {"id": "SA57", "role": "정보보안 엔지니어", "category": "security",
     "tech": ["Linux", "Python"], "exp_years": 5},
    {"id": "SA58", "role": "보안 관제 엔지니어", "category": "security",
     "tech": ["Linux"], "exp_years": None},
    {"id": "SA59", "role": "모의해킹 전문가", "category": "security",
     "tech": ["Linux", "Python", "Git"], "exp_years": 3},
    {"id": "SA60", "role": "클라우드 보안 엔지니어", "category": "security",
     "tech": ["AWS", "Linux", "Kubernetes", "Python", "Terraform", "Docker"],
     "exp_years": 7},
]


def all_queries() -> list[dict]:
    """SA01~SA60. 앞 15종은 동결분이므로 순서·id를 절대 바꾸지 않는다."""
    from .spec_anchor import SPEC_QUERIES
    return list(SPEC_QUERIES) + list(SPEC_QUERIES_EXT)

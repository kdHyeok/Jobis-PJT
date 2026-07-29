"""직군 분류 — 12종 roleCategory 룰 기반 태깅.

find_alternatives / RagAdapter 계약이 요구하는 roleCategory는 원본 데이터에
없다. LLM으로 매 공고를 분류하면 판단 계층에 LLM이 들어와 설계 원칙(판단은
룰/DB)이 깨지므로, title/detail_text 키워드 + tech 스택 룰로 분류한다.
키워드에 안 걸리면 분류하지 않는다(빈 문자열) — 잘못된 라벨을 강제로 붙이는
대신 "미분류"로 남겨 검색 필터에서 자연히 빠지게 한다.
"""
from __future__ import annotations

import re

ROLE_CATEGORIES = (
    "backend", "frontend", "fullstack", "mobile", "devops", "sre",
    "data_engineer", "data_scientist", "ml_engineer", "data_analyst",
    "qa", "security",
)

# 순서가 우선순위 — 특이 직군을 먼저 걸러야 "백엔드"라는 일반 단어에 흡수되지 않는다.
# (예: "데이터 엔지니어(백엔드 경력 우대)" 가 backend로 오분류되면 안 됨)
_KEYWORDS: dict[str, list[str]] = {
    "security": ["보안", "시큐리티", "security", "모의해킹", "침해대응", "정보보호", "취약점진단"],
    "qa": ["qa엔지니어", "품질보증", "테스트엔지니어", "qualityassurance", "sqa"],
    "sre": ["sre", "sitereliability", "신뢰성엔지니어"],
    "devops": ["devops", "데브옵스", "인프라엔지니어", "플랫폼엔지니어", "cloudengineer", "클라우드엔지니어"],
    "data_engineer": ["데이터엔지니어", "dataengineer", "데이터파이프라인", "datapipeline"],
    "ml_engineer": ["머신러닝엔지니어", "mlengineer", "딥러닝엔지니어", "ai엔지니어",
                    "인공지능엔지니어", "llm엔지니어", "mlops"],
    "data_scientist": ["데이터사이언티스트", "datascientist"],
    "data_analyst": ["데이터분석가", "dataanalyst", "데이터애널리스트"],
    "mobile": ["안드로이드", "android", "ios개발", "flutter", "모바일개발", "앱개발자", "reactnative"],
}

_FULLSTACK_WORDS = ("풀스택", "fullstack", "full-stack", "full stack")
_FRONTEND_WORDS = ("프론트엔드", "frontend", "프런트엔드", "웹퍼블리셔")
_BACKEND_WORDS = ("백엔드", "backend", "서버개발", "서버사이드")

_FRONTEND_TECH = {"React", "Vue", "Next.js", "jQuery", "HTML", "CSS"}
_BACKEND_TECH = {
    "Java", "Kotlin", "Python", "Go", "PHP", "JSP", "Spring Boot", "Spring", "JPA",
    "MyBatis", "Node.js", "Django", "FastAPI", "Flask", ".NET", "MySQL", "PostgreSQL",
    "Oracle", "MS-SQL", "MariaDB", "MongoDB", "Redis", "Kafka",
}

_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS_RE.sub("", s or "").lower()


def classify(title: str, detail_text: str = "", tech: list[str] | None = None) -> str:
    """제목/본문 앞부분/기술스택 -> roleCategory. 못 정하면 "" (미분류)."""
    hay = _norm(f"{title} {(detail_text or '')[:500]}")
    for cat, words in _KEYWORDS.items():
        if any(w in hay for w in words):
            return cat

    if any(_norm(w) in hay for w in _FULLSTACK_WORDS):
        return "fullstack"

    tech_set = set(tech or [])
    is_frontend = any(_norm(w) in hay for w in _FRONTEND_WORDS) or bool(tech_set & _FRONTEND_TECH)
    is_backend = any(_norm(w) in hay for w in _BACKEND_WORDS) or bool(tech_set & _BACKEND_TECH)
    if is_frontend and is_backend:
        return "fullstack"
    if is_frontend:
        return "frontend"
    if is_backend:
        return "backend"
    return ""

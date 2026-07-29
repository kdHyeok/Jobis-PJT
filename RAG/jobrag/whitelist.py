"""기술 화이트리스트 — 표준명 + 별칭.

용도 두 가지:
  1. detail_text/title에서 기술 추출 (경량 정규화)
  2. 프리픽스에 "표준명(별칭)" 병기 → 인덱스 측 별칭 확장으로
     부정확한 질의(스프링부트, 리액트 등)를 쿼리 정규화 없이 커버.
한 글자 별칭 금지(C, R 등은 오탐이 심해 단어 경계 매칭으로만).
"""
from __future__ import annotations

import re

# 표준명 -> 별칭 목록 (한글 표기 포함). 검색은 대소문자 무시.
TECH: dict[str, list[str]] = {
    "Java": ["자바"],
    "Kotlin": ["코틀린"],
    "Python": ["파이썬"],
    "JavaScript": ["자바스크립트", "JS"],
    "TypeScript": ["타입스크립트", "TS"],
    "C++": [],
    "C#": [],
    "Go": ["golang", "고랭"],
    "PHP": [],
    "JSP": [],
    "Spring Boot": ["스프링부트", "springboot", "spring-boot"],
    "Spring": ["스프링", "Spring Framework"],
    "JPA": ["hibernate", "하이버네이트"],
    "MyBatis": ["마이바티스"],
    "Node.js": ["노드", "nodejs", "node js"],
    "React": ["리액트", "react.js", "reactjs"],
    "Next.js": ["넥스트", "nextjs"],
    "Vue": ["vue.js", "vuejs"],
    "jQuery": ["제이쿼리"],
    "Django": ["장고"],
    "FastAPI": [],
    "Flask": [],
    ".NET": ["닷넷", "dotnet", "ASP.NET", "WinForm"],
    "Android": ["안드로이드"],
    "iOS": [],
    "Flutter": ["플러터"],
    "React Native": ["리액트네이티브", "리액트 네이티브"],
    "MySQL": [],
    "PostgreSQL": ["postgres", "포스트그레"],
    "Oracle": ["오라클"],
    "MS-SQL": ["mssql", "sql server"],
    "MariaDB": [],
    "MongoDB": ["몽고디비", "몽고DB"],
    "Redis": ["레디스"],
    "Kafka": ["카프카"],
    "Elasticsearch": ["엘라스틱서치", "ELK"],
    "Docker": ["도커"],
    "Kubernetes": ["쿠버네티스", "k8s"],
    "Jenkins": ["젠킨스"],
    "AWS": ["아마존웹서비스"],
    "GCP": ["구글클라우드"],
    "Azure": [],
    "NCP": ["네이버클라우드"],
    "Terraform": [],
    "Ansible": [],
    "Git": [],
    "GitLab": ["깃랩"],
    "GitHub Actions": [],
    "Linux": ["리눅스"],
    "TensorFlow": ["텐서플로우", "텐서플로"],
    "PyTorch": ["파이토치"],
    "LangChain": ["랭체인"],
    "LangGraph": ["랭그래프"],
    "LLM": [],
    "RAG": [],
    "SQL": [],
    "HTML": [],
    "CSS": [],
    "Unity": ["유니티"],
    "Unreal": ["언리얼"],
}

# 매칭 패턴 사전 컴파일: 긴 별칭 우선 매칭(스프링부트가 스프링보다 먼저)
_PATTERNS: list[tuple[str, re.Pattern]] = []
for std, aliases in TECH.items():
    for name in [std] + aliases:
        if len(name) < 2:  # 한 글자 별칭 금지 (오탐: 리뷰→Vue 등)
            continue
        esc = re.escape(name)
        # 영숫자로 시작/끝나는 이름만 단어 경계 요구 (C++, .NET 등은 그대로)
        pat = re.compile(
            (r"(?<![A-Za-z0-9])" if name[0].isalnum() and name[0].isascii() else "")
            + esc
            + (r"(?![A-Za-z0-9])" if name[-1].isalnum() and name[-1].isascii() else ""),
            re.IGNORECASE,
        )
        _PATTERNS.append((std, pat))
_PATTERNS.sort(key=lambda x: -len(x[1].pattern))

# 상위 기술에 포함되는 경우 하위만 남김 (Spring Boot 있으면 Spring 중복 제거)
_SUBSUMES = {"Spring": ["Spring Boot"], "SQL": ["MySQL", "MS-SQL", "PostgreSQL", "Oracle", "MariaDB"]}


def extract_tech(text: str) -> list[str]:
    found: list[str] = []
    for std, pat in _PATTERNS:
        if std not in found and pat.search(text):
            found.append(std)
    for parent, children in _SUBSUMES.items():
        if parent in found and any(c in found for c in children):
            found.remove(parent)
    return found


def with_aliases(std: str) -> str:
    """프리픽스 병기용: 'Spring Boot(스프링부트)'. 한글 별칭 1개만 병기."""
    ko = [a for a in TECH.get(std, []) if any("가" <= ch <= "힣" for ch in a)]
    return f"{std}({ko[0]})" if ko else std

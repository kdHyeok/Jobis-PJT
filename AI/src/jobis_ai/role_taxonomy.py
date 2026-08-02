"""직무 taxonomy (role_taxonomy) — roleCategory·seniority 를 룰로 확정.

지금까지 직무 카테고리와 연차는 LLM 이 "추정"했다. 그건 **판단**이고, 판단은 결정론이어야 한다
(설계 §0 3계층: 읽기/판단/말하기). 이 모듈이 그 판단을 규칙으로 가져온다.
(설계: agent-derivation-and-tools.md §3.1)

역할 경계:
- **순수 내부 정형 DB + 룰**. LLM/RAG/임베딩 없음.
- 이 모듈은 직무 어휘(role 키·한국어 라벨·별칭, 연차 사다리)의 **단일 소유자**다.
  `career_graph` 는 여기서 어휘를 가져다 쓰고, 자신은 전이 관계(feeders)만 소유한다.
  사전이 두 벌로 갈라지면 "backend" 와 "web-backend" 가 서로 다른 직군이 되는 사고가 난다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# 연차 사다리 (낮음 → 높음). career_graph 의 lower_seniority 도출이 이 순서를 쓴다.
SENIORITY_LADDER: tuple[str, ...] = ("intern", "junior", "mid", "senior", "lead")

# 연차 한국어 라벨 (검색 쿼리 조립·표시용)
SENIORITY_KO: dict[str, str] = {
    "intern": "인턴",
    "junior": "주니어 신입",
    "mid": "미들",
    "senior": "시니어",
    "lead": "리드",
}

# 연차 원문 표기 → 사다리 키
_SENIORITY_ALIASES: dict[str, str] = {
    "intern": "intern", "인턴": "intern", "체험형": "intern", "현장실습": "intern",
    "junior": "junior", "신입": "junior", "주니어": "junior", "entry": "junior",
    "entry-level": "junior", "초급": "junior", "신입/주니어": "junior",
    "mid": "mid", "middle": "mid", "미들": "mid", "중급": "mid",
    "senior": "senior", "시니어": "senior", "고급": "senior",
    "lead": "lead", "리드": "lead", "principal": "lead", "staff": "lead",
    "팀장": "lead", "테크리드": "lead", "tech lead": "lead",
}

# 경력 연차(년) → 사다리 키. 국내 채용 관행 기준 구간.
_YEARS_TO_SENIORITY: tuple[tuple[int, str], ...] = (
    (0, "junior"),   # 0년(신입)
    (2, "junior"),   # 1~2년
    (6, "mid"),      # 3~6년
    (9, "senior"),   # 7~9년
)
_YEARS_SENIORITY_TOP = "lead"  # 10년 이상


@dataclass(frozen=True)
class Role:
    """표준 직무 1건.

    key     : 내부 표준 키(career_graph·RAG 쿼리의 기준값)
    labelKo : 사람이 읽는 한국어 직군명
    aliases : 공고/입력 원문에서 이 직군을 가리킬 수 있는 표기들
    """

    key: str
    labelKo: str
    aliases: tuple[str, ...] = ()


# 표준 직무 사전. career_graph 의 _ROLE_GRAPH 는 이 key 집합 위에 전이 관계만 얹는다.
_ROLES: tuple[Role, ...] = (
    Role("backend", "백엔드",
         ("backend", "back-end", "web-backend", "server", "server-side",
          "백엔드", "서버", "서버개발", "서버 개발", "웹 백엔드", "api 개발")),
    Role("frontend", "프론트엔드",
         ("frontend", "front-end", "web-frontend", "client", "client-side",
          "프론트엔드", "프론트", "웹 프론트엔드", "퍼블리셔", "웹 퍼블리셔", "ui 개발")),
    Role("fullstack", "풀스택",
         ("fullstack", "full-stack", "full stack", "풀스택", "풀 스택", "웹 개발자")),
    Role("mobile", "모바일",
         ("mobile", "android", "ios", "react native", "flutter",
          "모바일", "안드로이드", "아이오에스", "앱 개발")),
    Role("devops", "데브옵스",
         ("devops", "dev-ops", "infra", "infrastructure", "platform engineer",
          "데브옵스", "인프라", "플랫폼 엔지니어", "클라우드 엔지니어")),
    Role("sre", "SRE",
         ("sre", "site reliability", "site reliability engineer", "신뢰성 엔지니어")),
    Role("data_engineer", "데이터 엔지니어",
         ("data engineer", "data-engineer", "data_engineer", "de",
          "데이터 엔지니어", "데이터엔지니어", "데이터 파이프라인")),
    Role("data_scientist", "데이터 사이언티스트",
         ("data scientist", "data-scientist", "data_scientist", "ds",
          "데이터 사이언티스트", "데이터사이언티스트")),
    Role("ml_engineer", "ML 엔지니어",
         ("ml engineer", "ml-engineer", "ml_engineer", "mlops", "machine learning",
          "ai engineer", "머신러닝", "머신 러닝", "ml 엔지니어", "인공지능", "ai 엔지니어")),
    Role("data_analyst", "데이터 분석가",
         ("data analyst", "data-analyst", "data_analyst", "bi",
          "데이터 분석", "데이터 분석가", "데이터분석가")),
    Role("qa", "QA",
         ("qa", "quality assurance", "test engineer", "sdet",
          "테스트", "테스트 엔지니어", "품질 관리")),
    Role("security", "보안",
         ("security", "security engineer", "infosec", "보안", "정보보안", "보안 엔지니어")),
)

# 직군 미상일 때의 값. 빈 문자열로 두어 "모른다"를 정직하게 표현한다(추측하지 않는다).
UNKNOWN_ROLE = ""


def _role_index() -> dict[str, Role]:
    index: dict[str, Role] = {}
    for role in _ROLES:
        for alias in (role.key, role.labelKo, *role.aliases):
            index.setdefault(alias.strip().lower(), role)
    return index


def _role_pattern(index: dict[str, Role]) -> re.Pattern[str]:
    """원문에서 직군 별칭을 찾는 정규식. 긴 별칭 우선(= "data engineer" 가 "data" 보다 먼저)."""

    aliases = sorted(index, key=len, reverse=True)
    body = "|".join(re.escape(a) for a in aliases)
    return re.compile(rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])", re.IGNORECASE)


# 경력 연차 추출용 — "경력 3년 이상", "3~5년", "3년+" 등. rule_extractor 와 공유되는 관심사지만,
# 여기서는 연차→seniority 판정에만 쓰는 최소 패턴을 둔다(추출의 정본은 rule_extractor).
_YEARS_HINT = re.compile(r"(\d{1,2})\s*(?:~\s*\d{1,2}\s*)?년")


class RoleTaxonomy:
    """직무 분류기. 원문 → roleCategory / seniority 를 규칙으로 확정."""

    def __init__(self) -> None:
        self._index = _role_index()
        self._pattern = _role_pattern(self._index)

    # --- 정규화 (이미 값이 있을 때 표준형으로) ---
    def normalize_role(self, raw: str) -> str:
        """roleCategory 원문 → 표준 role 키. 모르면 소문자 원문을 그대로 돌려준다.

        "senior backend" 처럼 연차가 붙어 와도 토큰 단위로 재시도해 흡수한다.
        """

        text = (raw or "").strip().lower()
        if not text:
            return UNKNOWN_ROLE
        role = self._index.get(text)
        if role:
            return role.key
        match = self._pattern.search(text)
        if match:
            found = self._index.get(match.group(0).lower())
            if found:
                return found.key
        return text

    def normalize_seniority(self, raw: str) -> str:
        """seniority 원문 → 사다리 키. 모르면 빈 문자열(추측하지 않는다)."""

        return _SENIORITY_ALIASES.get((raw or "").strip().lower(), "")

    # --- 분류 (원문에서 룰로 도출) ---
    def classify_role(self, job_title: str, body: str = "") -> str:
        """직무명(+본문) → 표준 role 키.

        직무명이 본문보다 신뢰도가 높으므로 **직무명을 먼저** 본다. 직무명에서 못 찾으면
        본문에서 가장 많이 등장한 직군을 택한다. 둘 다 실패면 UNKNOWN_ROLE(빈 문자열).
        """

        for match in self._pattern.finditer(job_title or ""):
            role = self._index.get(match.group(0).lower())
            if role:
                return role.key

        counts: dict[str, int] = {}
        for match in self._pattern.finditer(body or ""):
            role = self._index.get(match.group(0).lower())
            if role:
                counts[role.key] = counts.get(role.key, 0) + 1
        if counts:
            return max(counts, key=lambda k: counts[k])
        return UNKNOWN_ROLE

    def classify_seniority(self, job_title: str, body: str = "", *, years: int | None = None) -> str:
        """직무명·본문·요구 연차 → 사다리 키.

        우선순위: ① 요구 연차(years) → ② 명시 키워드("신입","시니어") → ③ 본문 연차 힌트.
        아무 근거도 없으면 빈 문자열 — **모르면 모른다고 둔다.** 여기서 "junior" 로 찍으면
        그건 근거 없는 판단이고, 뒤의 career_graph 가 그 위에 경로를 쌓아 오류가 증폭된다.

        **연차가 키워드를 이긴다(D118).** 키워드는 본문 어디에 있든 걸리는 반면 years 는
        "지원 자격으로 요구한 연차"를 읽어낸 값이라 근거가 분명하다. 실측(잡코리아
        Gno=49638113): 경력 3년 공고가 회사 소개 "Global **Lead**ing DX Company" 때문에
        `lead`(10년+)로 분류돼 4년 경력자가 미달로 판정될 수 있었다.

        ASCII 별칭은 **단어 경계**로만 맞춘다 — 한글은 교착어라 경계가 없으므로 그대로 포함
        검사한다("신입사원"의 "신입"은 맞는 매칭이다).
        """

        haystack = f"{job_title or ''} {body or ''}".lower()
        if years is None:
            match = _YEARS_HINT.search(body or "")
            if match:
                years = int(match.group(1))
        if years is not None:
            return self.seniority_from_years(years)

        for alias, key in _SENIORITY_ALIASES.items():
            hit = (re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", haystack)
                   if alias.isascii() else alias in haystack)
            if hit:
                return key
        return ""

    def seniority_from_years(self, years: int) -> str:
        """요구 경력 연차 → 사다리 키."""

        for threshold, key in _YEARS_TO_SENIORITY:
            if years <= threshold:
                return key
        return _YEARS_SENIORITY_TOP

    # --- 조회 ---
    def label_of(self, role_key: str) -> str:
        """표준 role 키 → 한국어 라벨. 모르면 키 그대로."""

        role = self._index.get((role_key or "").strip().lower())
        return role.labelKo if role else (role_key or "")

    def is_known_role(self, role_key: str) -> bool:
        return (role_key or "").strip().lower() in self._index

    def all_role_keys(self) -> list[str]:
        return [r.key for r in _ROLES]


@lru_cache(maxsize=1)
def get_role_taxonomy() -> RoleTaxonomy:
    """프로세스당 하나를 재사용한다.

    운영 전환 시 여기서 외부 DB 로드 구현체를 반환하도록 바꾸면 노드 코드는 불변.
    """

    return RoleTaxonomy()

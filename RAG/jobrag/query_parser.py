"""자연어 질의 -> 검색 조건 (규칙 기반).

챗 에이전트가 붙으면 LLM 재작성이 앞단에 오지만, 규칙 파서가 먼저 시도하고
LLM은 실패·모호할 때만 호출하는 구조를 전제로 한다(결정적·무비용 경로 확보).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .whitelist import extract_tech

# 연차는 "경력"을 가리키는 문맥에서만 인정한다. 아무 "N년"이나 집으면
# "설립 10년 된 회사" 같은 표현이 경력 10년으로 둔갑한다.
_EXP_PATTERNS = (
    re.compile(r"(\d+)\s*년\s*차"),                       # 3년차
    re.compile(r"경력\s*(?:이)?\s*(\d+)\s*년"),            # 경력 3년
    re.compile(r"(\d+)\s*년\s*(?:이상|넘게)?\s*(?:의)?\s*경력"),  # 3년 이상 경력
    re.compile(r"(\d+)\s*년\s*이상\s*(?:개발|경험)"),        # 3년 이상 개발
)
# 구직 질의에서 "N년 이상"은 사실상 항상 경력 조건("5년 이상 AWS 엔지니어").
# 단 회사 업력("설립 10년 이상 된")과 구분하려고 앞 문맥에 업력 표현이 있으면 무시한다.
_EXP_OVER_RE = re.compile(r"(\d+)\s*년\s*이상")
_COMPANY_AGE_RE = re.compile(r"(?:설립|창립|창업|업력|운영)\D{0,6}\d+\s*년")
_FRESH_WORDS = ("신입", "주니어")
# "경력무관"은 조건을 넓히는 표현 — 연차 0(=신입만)으로 좁히면 의미가 정반대가 된다.
_EXP_ANY_RE = re.compile(r"경력\s*무관|경력\s*상관\s*없|연차\s*무관")
_SENIOR_HINT = re.compile(r"시니어|리드|팀장")


@dataclass
class QuerySpec:
    text: str
    tech: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)   # postings.regions와 같은 표기
    exp_years: int | None = None                       # 지원자의 연차 (공고 요구치가 아님)
    # 자연어에서 뽑지 않음 — 호출측(RagAdapter 등)이 직접 채우는 하드필터.
    # region/exp와 달리 완화 대상이 아니다(직군을 완화하면 대체경로 검색 의미가 사라짐).
    role_category: str | None = None

    def summary(self) -> str:
        parts = []
        if self.regions:
            parts.append("지역=" + "/".join(self.regions))
        if self.exp_years is not None:
            parts.append(f"연차={self.exp_years}")
        if self.tech:
            parts.append("기술=" + ",".join(self.tech))
        if self.role_category:
            parts.append("직군=" + self.role_category)
        return " · ".join(parts) or "조건 없음"


# 행정구역명이 아니어서 DB에서 유도할 수 없는 생활권 지명. 구직자가 실제로 쓰는 말.
_LANDMARKS = {
    "판교": "경기 성남시", "분당": "경기 성남시", "정자동": "경기 성남시",
    "여의도": "서울 영등포구", "가산": "서울 금천구", "가산디지털단지": "서울 금천구",
    "구로디지털단지": "서울 구로구", "상암": "서울 마포구", "역삼": "서울 강남구",
    "삼성동": "서울 강남구", "선릉": "서울 강남구", "테헤란로": "서울 강남구",
    "양재": "서울 서초구", "판교테크노밸리": "경기 성남시", "마곡": "서울 강서구",
}


def load_region_vocab(conn) -> dict[str, str]:
    """DB의 실제 regions 값으로 어휘 사전 구성.

    세 계층을 등록한다. 저장 표기는 "서울 강남구"인데 사용자는 "강남구"라고 쓰고,
    실제로는 접미사를 뗀 "강남"이 훨씬 흔하며, "판교"처럼 행정구역이 아닌
    생활권 지명도 자주 쓴다. 어느 한 계층만 있으면 지역 필터가 거의 안 걸린다.
    모호한 이름(여러 시도에 존재하는 중구 등)은 오귀속을 막기 위해 제외한다.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT unnest(regions) FROM postings WHERE is_active")
        canon = [r[0] for r in cur.fetchall()]
    vocab: dict[str, str] = {c: c for c in canon}
    sido = {c for c in canon if " " not in c}

    def register(alias: str, targets: set[str]) -> None:
        # 여러 지역을 가리키거나 시/도 이름과 충돌하면 모호 — 등록하지 않는다
        if len(targets) == 1 and alias not in vocab and alias not in sido:
            vocab[alias] = next(iter(targets))

    full_by_short: dict[str, set[str]] = {}
    full_by_bare: dict[str, set[str]] = {}
    for c in canon:
        if " " not in c:
            continue
        short = c.split(" ", 1)[1]              # "강남구"
        full_by_short.setdefault(short, set()).add(c)
        bare = re.sub(r"[시군구]$", "", short)   # "강남"
        if len(bare) >= 2:
            full_by_bare.setdefault(bare, set()).add(c)

    for alias, targets in full_by_short.items():
        register(alias, targets)
    for alias, targets in full_by_bare.items():
        register(alias, targets)
    for alias, target in _LANDMARKS.items():
        if target in vocab:                     # 데이터에 없는 지역은 등록하지 않음
            register(alias, {target})
    return vocab


def parse_exp(text: str) -> int | None:
    """지원자 연차. None은 '연차 조건 없음'(필터 미적용)을 뜻한다."""
    if _EXP_ANY_RE.search(text):
        return None          # "경력무관" = 조건 없음. 0으로 잡으면 신입 공고만 남는다
    for pat in _EXP_PATTERNS:
        m = pat.search(text)
        if m:
            return int(m.group(1))
    if not _COMPANY_AGE_RE.search(text):
        m = _EXP_OVER_RE.search(text)
        if m:
            return int(m.group(1))
    if any(w in text for w in _FRESH_WORDS):
        return 0
    if _SENIOR_HINT.search(text):
        return 7  # 시니어 표현은 연차 미상 — 상한 넓게 잡아 후보를 죽이지 않음
    return None


def parse_regions(text: str, vocab: dict[str, str]) -> list[str]:
    """긴 표기부터 매칭 — "서울 강남구"가 "서울"보다 먼저 잡혀야 한다."""
    found: list[str] = []
    for name in sorted(vocab, key=len, reverse=True):
        if name in text:
            canon = vocab[name]
            if canon not in found:
                found.append(canon)
    # "서울 강남" 같은 질의는 시도와 시군구가 둘 다 잡힌다. 필터가 배열 겹침(&&)이라
    # 시도가 남아 있으면 시군구 조건이 통째로 희석되므로(강남 39건 -> 서울 124건),
    # 더 구체적인 지역이 있는 시도는 제거한다.
    specific_sidos = {f.split(" ", 1)[0] for f in found if " " in f}
    return [f for f in found if " " in f or f not in specific_sidos]


def parse_query(text: str, region_vocab: dict[str, str] | None = None) -> QuerySpec:
    return QuerySpec(
        text=text,
        tech=extract_tech(text),
        regions=parse_regions(text, region_vocab or {}),
        exp_years=parse_exp(text),
    )

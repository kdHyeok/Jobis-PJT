"""직업군 전이 그래프 (career_graph) — 대체 경로 탐색의 '하위 직업군 도출' 담당.

`find_alternatives` 앞단에서, 목표 직업군(roleCategory)에 도달하기 위해 경력을 쌓을 수 있는
**하위/징검다리 직업군**을 도출한다. RAG(`search`)는 이 하위 직업군들로 조립된 query 로
실존 공고를 검색한다. (설계: agent-derivation-and-tools.md §3.7, rag-team-interface-spec.md §3)

역할 경계:
- 이 모듈은 **순수 내부 정형 DB**다. LLM/RAG/임베딩을 쓰지 않는다 — 전이 관계는 결정론 규칙.
- "실존 공고 검색"은 여기서 하지 않는다. 여기는 "어떤 직업군으로 검색할지"만 정한다.
- 직무 어휘(role 키·라벨·별칭, 연차 사다리)는 **`role_taxonomy` 가 소유**한다. 이 모듈은
  그 위에 **전이 관계(feeders)만** 얹는다. 사전을 두 벌로 두면 갈라져서 반드시 어긋난다.

스캐폴딩 단계: 시드 데이터는 대표 IT 직군만 담았다. 실제 운영 시 `_FEEDERS` 를 확장하거나
외부 DB 로드로 교체하되, `derive_sub_roles()` 시그니처는 유지한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from jobis_ai.role_taxonomy import SENIORITY_KO, SENIORITY_LADDER, get_role_taxonomy

SubRoleRelation = Literal["lower_seniority", "stepping_stone"]

# 직업군 전이 그래프 시드: 목표 직군 → 그 직군으로 넘어오기 좋은 '피더(징검다리) 직군'들.
# 낮은 진입장벽으로 경력을 쌓아 목표 직군으로 이동 가능한 경로를 뜻한다.
# key 는 role_taxonomy 의 표준 role 키와 일치해야 한다.
_FEEDERS: dict[str, tuple[str, ...]] = {
    "backend":        ("fullstack",),
    "frontend":       ("fullstack",),
    "fullstack":      ("frontend", "backend"),
    "mobile":         ("frontend",),
    "devops":         ("backend", "sre"),
    "sre":            ("backend", "devops"),
    "data_engineer":  ("backend", "data_analyst"),
    "data_scientist": ("data_analyst", "ml_engineer"),
    "ml_engineer":    ("data_engineer", "backend"),
    "data_analyst":   (),
    "qa":             ("backend",),
    "security":       ("backend", "devops"),
}


@dataclass(frozen=True)
class SubRole:
    """도출된 하위/징검다리 직업군 1건.

    roleCategory: 표준 role 키(예: "backend")
    seniority:    권장 진입 연차(예: "junior")
    relation:     lower_seniority(같은 직군 낮은 연차) | stepping_stone(인접 피더 직군)
    label:        query 조립·표시용 한국어 라벨(예: "백엔드 주니어 신입")
    """

    roleCategory: str
    seniority: str
    relation: SubRoleRelation
    label: str


class CareerGraph:
    """직업군 전이 그래프 조회기. 목표 직군 → 하위/징검다리 직군 도출."""

    def derive_sub_roles(
        self, role_category: str, seniority: str = "", *, max_roles: int = 6
    ) -> list[SubRole]:
        """목표 직업군으로 도달하기 위한 하위/징검다리 직업군 목록을 도출한다.

        1) lower_seniority: 같은 직군의 목표보다 낮은 연차 (senior → mid → junior → intern)
        2) stepping_stone : 인접 피더 직군의 진입 연차(junior)
        결과는 우선순위(가까운 경로 먼저) 순으로 정렬 후 max_roles 로 자른다.
        RAG(search)는 이 목록으로 조립된 query 로 실존 공고를 검색한다.

        연차가 미상이면 lower_seniority 는 건너뛰고 징검다리 직군만 낸다. 미상을 'mid' 로
        가정하면 근거 없이 "인턴/주니어 자리를 노려라"는 경로를 지어내게 된다.
        """

        roles = get_role_taxonomy()
        role = roles.normalize_role(role_category)
        target_sen = roles.normalize_seniority(seniority)

        out: list[SubRole] = []
        seen: set[tuple[str, str]] = set()

        def _add(rc: str, sen: str, rel: SubRoleRelation, label: str) -> None:
            key = (rc, sen)
            if key in seen:
                return
            seen.add(key)
            out.append(SubRole(roleCategory=rc, seniority=sen, relation=rel, label=label))

        role_ko = roles.label_of(role)

        # 1) 같은 직군의 낮은 연차 (목표에 가까운 연차부터 한 칸씩 아래로).
        #    직군·연차 어느 쪽이든 미상이면 라벨이 무의미하므로 건너뛴다.
        if role and target_sen in SENIORITY_LADDER:
            below = SENIORITY_LADDER[: SENIORITY_LADDER.index(target_sen)]
            for sen in reversed(below):
                _add(role, sen, "lower_seniority", f"{role_ko} {SENIORITY_KO[sen]}")

        # 2) 인접 피더 직군의 진입 연차 (징검다리)
        for feeder_key in _FEEDERS.get(role, ()):
            _add(feeder_key, "junior", "stepping_stone",
                 f"{roles.label_of(feeder_key)} {SENIORITY_KO['junior']}")

        return out[:max_roles]

    def to_query_terms(self, sub_roles: list[SubRole]) -> list[str]:
        """하위 직업군 목록을 검색 쿼리에 넣을 텍스트 조각으로 변환한다."""

        return [sr.label for sr in sub_roles]


@lru_cache(maxsize=1)
def get_career_graph() -> CareerGraph:
    """프로세스당 하나의 CareerGraph 를 재사용한다.

    운영 전환 시 여기서 외부 DB 로드 구현체를 반환하도록 바꾸면 노드 코드는 불변.
    """

    return CareerGraph()

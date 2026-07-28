"""스킬 → 자격증 매핑 (skill_to_cert).

설계 §3.6-②. `gap_matcher` 가 계산한 `missingSkills` 를 받아 관련 IT 자격증을 찾는다.
`cert_db` 위에 얹히는 얇은 매핑 레이어다.

역할 경계:
- **순수 매핑 테이블.** LLM/RAG 없음.
- **매핑이 없는 게 정상이다.** 대부분의 실무 스킬(Docker, MSA, 이벤트 드리븐)에는
  마땅한 자격증이 없다. 억지로 갖다 붙이면 "MSA 를 배우려면 정보처리기사를 따세요"
  같은 헛소리가 나온다. 없으면 빈 목록을 돌려주고, 호출부는 `project_template_db` 로
  넘긴다(§3.6 커버리지 한계).

키는 `skill_taxonomy` 의 표준 스킬 key, 값은 `cert_db` 의 자격증 key 다.
"""

from __future__ import annotations

from functools import lru_cache

from jobis_ai.cert_db import Certification, get_cert_db
from jobis_ai.skill_taxonomy import get_skill_taxonomy

# 스킬 key → 자격증 key 들. **그 자격증이 실제로 그 스킬을 검증할 때만** 넣는다.
# 관련 없는 매핑은 사용자 시간을 낭비시키므로, 애매하면 비워 두고 프로젝트 과제로 넘긴다.
_SKILL_TO_CERT: dict[str, tuple[str, ...]] = {
    # 데이터베이스 — 국내에서 실제로 인정받는 매핑
    "sql": ("sqld", "sqlp"),
    "rdbms": ("sqld", "info-processing-engineer"),
    "mysql": ("sqld",),
    "mariadb": ("sqld",),
    "postgresql": ("sqld",),
    "oracle": ("sqld", "sqlp"),

    # 언어
    "java": ("ocjp",),

    # 클라우드
    "aws": ("aws-saa", "aws-dva"),

    # 컨테이너/오케스트레이션
    "kubernetes": ("cka", "ckad"),

    # 인프라
    "linux": ("linux-master-2",),

    # 보안
    "security": ("security-engineer",),

    # 데이터
    "spark": ("bigdata-engineer",),
    "hadoop": ("bigdata-engineer",),
    "pandas": ("adsp",),

    # 매핑이 의도적으로 **없는** 대표 스킬들 (project_template_db 가 담당):
    #   docker, msa, kafka, spring, spring-boot, react, rest-api, cicd, redis ...
    #   → 이들에는 국내에서 통용되는 검증 자격증이 사실상 없다. 억지 매핑 금지.
}


class SkillToCert:
    """스킬 → 자격증 조회기."""

    def __init__(self) -> None:
        self._taxonomy = get_skill_taxonomy()
        self._certs = get_cert_db()

    def _key_of(self, skill_name: str) -> str:
        """표시명("MySQL") → taxonomy 표준 key("mysql")."""

        skill = self._taxonomy.resolve(skill_name)
        return skill.key if skill else (skill_name or "").strip().lower()

    def certs_for(self, skill_name: str) -> list[Certification]:
        """스킬 1건 → 관련 자격증들. 없으면 빈 목록."""

        return self._certs.get_many(list(_SKILL_TO_CERT.get(self._key_of(skill_name), ())))

    def recommend(self, skill_names: list[str]) -> dict[str, Certification]:
        """스킬 목록 → {스킬 표시명: 권장 자격증 1건}.

        한 스킬에 여러 자격증이 걸리면 가장 가벼운 것을 고른다(cert_db.easiest).
        자격증이 없는 스킬은 **결과에 아예 넣지 않는다** — 호출부가 그걸 보고
        프로젝트 과제로 돌린다.
        """

        out: dict[str, Certification] = {}
        for name in skill_names:
            best = self._certs.easiest(self.certs_for(name))
            if best:
                out[name] = best
        return out

    def uncovered(self, skill_names: list[str]) -> list[str]:
        """자격증으로 커버되지 않는 스킬들 → project_template_db 로 넘길 대상."""

        return [n for n in skill_names if not self.certs_for(n)]


@lru_cache(maxsize=1)
def get_skill_to_cert() -> SkillToCert:
    """프로세스당 하나를 재사용한다."""

    return SkillToCert()

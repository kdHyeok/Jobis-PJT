"""실제 에이전트의 공고 요건을 서비스 로드맵 taxonomy로 옮기는 결정론 분류기.

실제 에이전트는 공고 원문을 ``RequirementStatus``까지 정규화하지만 서비스가 요구하는
``stage/kind/roadmapEligible``은 산출하지 않는다. 이 모듈은 새 사실을 만들거나 사용자의
충족 여부를 다시 판단하지 않고, 이미 추출된 요건과 공용 ``skill_taxonomy``를 서비스의
표시 분류로 번역한다.

중요한 경계:
- LLM을 호출하지 않는다. 같은 입력은 항상 같은 결과를 낸다.
- 분류할 근거가 없는 문장은 DOMAIN으로 밀어 넣지 않고 로드맵 제외로 남긴다.
- 경력 연차는 JobContext의 경력 관문이 담당하므로 일반 역량 노드로 만들지 않는다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Iterable

from jobis_ai.skill_taxonomy import Skill, get_skill_taxonomy


_NON_WORD = re.compile(r"[^0-9a-zA-Z가-힣+#.]+")
_SLUG_NON_WORD = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class CompetencyClassification:
    canonical_key: str
    title: str
    domain: str
    kind: str
    stage: str
    scope_definition: str
    required_level: int
    roadmap_eligible: bool
    verification_method: str | None

    def detail(self) -> dict:
        return asdict(self)


def is_synthetic_requirement(requirement_id: str) -> bool:
    return requirement_id.startswith(("tech-", "domain-", "seniority-"))


def is_redundant_synthetic(requirement: dict, all_requirements: list[dict]) -> bool:
    """원문 요건에 이미 들어 있는 tech/domain 합성 항목은 제안에서 한 번만 표현한다."""

    requirement_id = str(requirement.get("requirementId") or "")
    if not requirement_id.startswith(("tech-", "domain-")):
        return False
    needle = _identity_text(str(requirement.get("text") or ""))
    if not needle:
        return False
    for other in all_requirements:
        other_id = str(other.get("requirementId") or "")
        if is_synthetic_requirement(other_id):
            continue
        haystack = _identity_text(str(other.get("text") or ""))
        if needle in haystack:
            return True
    return False


def classify_requirement(
    posting: dict,
    requirement: dict,
    missing_skills: Iterable[str] = (),
) -> list[CompetencyClassification]:
    """요건 한 건을 1개 이상의 서비스 역량으로 분해·분류한다.

    ``Java와 Spring``처럼 독립된 표준 기술이 함께 나온 문장은 두 역량으로 나눈다. 반대로
    ``Clean Code와 테스트 자동화``처럼 하나의 검증 활동을 말하는 문장은 하나의 PRACTICE로
    유지한다.
    """

    text = " ".join(str(requirement.get("text") or "").split()).strip()
    if not text:
        return []
    requirement_id = str(requirement.get("requirementId") or "")
    relation = str(requirement.get("type") or "required")
    domain = _roadmap_domain(posting)
    lower = text.lower()

    if requirement_id.startswith("seniority-") or _is_pure_seniority(text, posting):
        return [_make(
            key="career.seniority",
            title="경력 요건",
            domain=domain,
            kind="EXPERIENCE",
            stage="EXPERIENCE",
            text=text,
            relation=relation,
            eligible=False,
        )]

    if _contains_any(lower, _CREDENTIAL_MARKERS):
        return [_make(
            key=_concept_key("credential", text),
            title=_compact_title(text, "자격·학력 요건"),
            domain=domain,
            kind="CREDENTIAL",
            stage="CREDENTIAL",
            text=text,
            relation=relation,
        )]

    if _is_domain_experience(lower):
        return [_make(
            key=_concept_key("experience", text),
            title=_compact_title(text, "관련 실무 경험"),
            domain=domain,
            kind="EXPERIENCE",
            stage="EXPERIENCE",
            text=text,
            relation=relation,
            eligible=False,
        )]

    special = _special_classification(domain, text, lower, relation, requirement_id)
    if special is not None:
        return [special]

    skills = _known_skills(text, missing_skills)
    if skills:
        web_standard = _contains_any(lower, ("웹 표준", "web standard", "w3c"))
        results = [
            _make(
                key="foundation.git-terminal" if skill.key == "git" else f"skill.{skill.key}",
                title="Git · 터미널" if skill.key == "git" else skill.canonical,
                domain=domain,
                kind="PRACTICE" if skill.category == "testing" else "TECHNOLOGY",
                stage=_stage_for_skill(skill, lower, web_standard),
                text=text,
                relation=relation,
            )
            for skill in skills
        ]
        return _dedupe(results)

    if _is_qualitative_only(lower):
        title, key = _qualitative_identity(lower)
        return [_make(
            key=key,
            title=title,
            domain=domain,
            kind="PRACTICE",
            stage="QUALITY",
            text=text,
            relation=relation,
            eligible=False,
        )]

    if _contains_any(lower, _SCALE_MARKERS):
        return [_make(
            _concept_key("scale", text),
            _compact_title(text, "성능·분산 시스템"),
            domain, "TECHNOLOGY", "SCALE", text, relation,
        )]
    if _contains_any(lower, _OPERATIONS_MARKERS):
        return [_make(
            _concept_key("operations", text),
            _compact_title(text, "배포·운영"),
            domain, "TECHNOLOGY", "OPERATIONS", text, relation,
        )]
    if _contains_any(lower, _DATA_MARKERS):
        return [_make(
            _concept_key("data", text),
            _compact_title(text, "데이터·영속성"),
            domain, "TECHNOLOGY", "DATA", text, relation,
        )]
    if _contains_any(lower, _WEB_MARKERS):
        return [_make(
            _concept_key("web", text),
            _compact_title(text, "웹·API 개발"),
            domain, "TECHNOLOGY", "WEB", text, relation,
        )]

    if requirement_id.startswith("domain-") or _mentions_posting_domain(lower, posting):
        return [_make(
            key=_concept_key("domain", text),
            title=_compact_title(text, "산업 도메인 이해"),
            domain=domain,
            kind="DOMAIN_KNOWLEDGE",
            stage="DOMAIN",
            text=text,
            relation=relation,
        )]

    if requirement_id.startswith("tech-"):
        # techStack으로 이미 추출된 항목은 기술이라는 사실만 확정되어 있다. 알려지지 않은
        # 신기술을 DOMAIN으로 오분류하지 않고 서비스 개발 단계의 기술로 보존한다.
        return [_make(
            key=_concept_key("skill", text),
            title=_compact_title(text, "기술 활용"),
            domain=domain,
            kind="TECHNOLOGY",
            stage="FRAMEWORK",
            text=text,
            relation=relation,
        )]

    if _contains_any(lower, _VERIFIABLE_TASK_MARKERS):
        stage = "OPERATIONS" if _contains_any(lower, _OPERATIONS_MARKERS) else "FRAMEWORK"
        return [_make(
            key=_concept_key("task", text),
            title=_compact_title(text, "개발 업무 수행"),
            domain=domain,
            kind="TASK",
            stage=stage,
            text=text,
            relation=relation,
        )]

    # 분류 근거가 없는 문장은 분석 조건에는 남기되 로드맵에는 넣지 않는다. 이전 구현처럼
    # 모르는 것을 DOMAIN으로 간주하면 모든 항목이 "도메인 이해"에 모인다.
    return [_make(
        key=_concept_key("unclassified", text),
        title=_compact_title(text, "검토 필요 조건"),
        domain=domain,
        kind="KNOWLEDGE",
        stage="DOMAIN",
        text=text,
        relation=relation,
        eligible=False,
    )]


def classify_legacy_node(node) -> CompetencyClassification:
    """taxonomy metadata가 없는 구 ChangeProposal을 안전하게 번역한다."""

    text = (node.scope_definition or node.title or "").strip()
    if node.kind == "FOUNDATION":
        return _make(
            key=node.canonical_key,
            title=node.title,
            domain=_normalize_domain(node.domain),
            kind="KNOWLEDGE",
            stage="FOUNDATION",
            text=text,
            relation="required",
        )
    if node.kind == "CREDENTIAL":
        return _make(
            key=node.canonical_key,
            title=node.title,
            domain=_normalize_domain(node.domain),
            kind="CREDENTIAL",
            stage="CREDENTIAL",
            text=text,
            relation="required",
        )
    if node.kind == "EXPERIENCE":
        return _make(
            key=node.canonical_key,
            title=node.title,
            domain=_normalize_domain(node.domain),
            kind="EXPERIENCE",
            stage="EXPERIENCE",
            text=text,
            relation="required",
        )
    classified = classify_requirement(
        {"roleCategory": node.domain},
        {"requirementId": "legacy", "type": "required", "text": text},
    )
    return classified[0]


def _special_classification(
    domain: str,
    text: str,
    lower: str,
    relation: str,
    requirement_id: str,
) -> CompetencyClassification | None:
    if _contains_any(lower, ("자료구조", "알고리즘", "네트워크", "운영체제", "computer science", "cs 기초")):
        return _make("foundation.cs", "CS 기초", domain, "KNOWLEDGE", "FOUNDATION", text, relation)
    if _contains_any(lower, ("웹 표준", "web standard", "w3c")):
        return _make("web.web-standards", "웹 표준 이해", domain, "KNOWLEDGE", "WEB", text, relation)
    if _contains_any(lower, ("db 스키마", "database schema", "데이터베이스 스키마", "트랜잭션 무결성")):
        return _make(
            "backend.data.transaction-schema",
            "트랜잭션 기반 DB 스키마 설계",
            domain, "TECHNOLOGY", "DATA", text, relation,
        )
    if _contains_any(lower, _QUALITY_MARKERS):
        return _make(
            _quality_key(lower),
            _quality_title(lower),
            domain, "PRACTICE", "QUALITY", text, relation,
        )
    if _contains_any(lower, ("풀노드", "full node", "geth", "parity")) and _contains_any(
        lower, ("운영", "operation", "관리")
    ):
        return _make(
            "domain.blockchain.full-node-operations",
            "블록체인 풀노드 운영",
            domain, "TECHNOLOGY", "OPERATIONS", text, relation,
        )
    if _contains_any(lower, ("vasp", "가상자산 거래소")) and _contains_any(lower, ("지갑", "wallet")):
        return _make(
            "experience.vasp.wallet",
            "VASP 지갑 업무 경험",
            domain, "EXPERIENCE", "EXPERIENCE", text, relation,
        )
    if _contains_any(lower, ("스마트 컨트랙트", "smart contract")) and _contains_any(lower, ("dapp", "디앱", "개발")):
        return _make(
            "domain.blockchain.smart-contract-dapp",
            "스마트 컨트랙트 · dApp 개발",
            domain, "TECHNOLOGY", "FRAMEWORK", text, relation,
        )
    if _contains_any(lower, ("erc", "토큰 표준")):
        return _make(
            "domain.blockchain.erc-token-standard",
            "ERC 토큰 표준",
            domain, "DOMAIN_KNOWLEDGE", "DOMAIN", text, relation,
        )
    if _contains_any(lower, ("nonce", "서명", "트랜잭션 관리")) and _contains_any(
        lower, ("전송", "트랜잭션", "transaction")
    ):
        return _make(
            "domain.blockchain.transaction-management",
            "블록체인 트랜잭션 관리",
            domain, "TECHNOLOGY", "FRAMEWORK", text, relation,
        )
    if _contains_any(lower, ("블록체인", "reorg", "proof of stake", "proof of work", " pos", " pow")):
        return _make(
            "domain.blockchain.core",
            "블록체인 핵심 원리 이해",
            domain, "DOMAIN_KNOWLEDGE", "DOMAIN", text, relation,
        )
    # 특정 산업/업무 수행 경험은 학습 기술과 구분한다. 단순 "Java 경험"은 아래의 표준
    # 스킬 분류가 담당해야 하므로 알려진 기술이 없는 문장에만 이 규칙이 도달한다.
    if _contains_any(lower, ("업무 경험", "실무 경험", "프로젝트 경험", "참여한 분", "런칭된")):
        return _make(
            _concept_key("experience", text),
            _compact_title(text, "관련 실무 경험"),
            domain, "EXPERIENCE", "EXPERIENCE", text, relation,
            eligible=False,
        )
    return None


def _known_skills(text: str, missing_skills: Iterable[str]) -> list[Skill]:
    taxonomy = get_skill_taxonomy()
    names: list[str] = []
    for raw in missing_skills:
        names.extend(taxonomy.find_in_text(str(raw)))
    names.extend(taxonomy.find_in_text(text))
    out: list[Skill] = []
    seen: set[str] = set()
    for name in names:
        skill = taxonomy.resolve(name)
        if skill is not None and skill.key not in seen:
            seen.add(skill.key)
            out.append(skill)
    return out


def _stage_for_skill(skill: Skill, text: str, web_standard: bool) -> str:
    if web_standard and skill.key in {"html", "css", "javascript", "typescript"}:
        return "WEB"
    if skill.key in {"git"}:
        return "FOUNDATION"
    if skill.key in {"sql", "jpa", "mybatis"}:
        return "DATA"
    if skill.key in {"redis", "memcached", "kafka", "rabbitmq", "msa"}:
        return "SCALE"
    if skill.key in {"rest-api", "graphql", "grpc"}:
        return "FRAMEWORK"
    if skill.key in {"oauth", "websocket", "jwt", "openapi", "webrtc"}:
        return "WEB"
    return {
        "language": "LANGUAGE",
        "framework": "FRAMEWORK",
        "database": "DATA",
        "cloud": "OPERATIONS",
        "devops": "OPERATIONS",
        "data": "DATA",
        "testing": "QUALITY",
        "etc": "FRAMEWORK",
    }.get(skill.category, "FRAMEWORK")


def _make(
    key: str,
    title: str,
    domain: str,
    kind: str,
    stage: str,
    text: str,
    relation: str,
    eligible: bool = True,
) -> CompetencyClassification:
    return CompetencyClassification(
        canonical_key=key[:160],
        title=title[:160],
        domain=_normalize_domain(domain),
        kind=kind,
        stage=stage,
        scope_definition=text[:4000],
        required_level=_required_level(text, relation, stage),
        roadmap_eligible=eligible,
        verification_method=_verification_method(stage) if eligible else None,
    )


def _required_level(text: str, relation: str, stage: str) -> int:
    lower = text.lower()
    if _contains_any(lower, ("기본", "기초", "관심", "이해가 있는")):
        level = 1
    else:
        level = 2
    if relation == "preferred":
        level = max(level, 2)
    if _contains_any(lower, ("깊은 이해", "설계", "구축", "운영 경험", "실무 경험", "자동화", "런칭")):
        level = max(level, 3)
    if stage == "SCALE" and _contains_any(lower, ("대용량", "분산", "아키텍처", "고가용성")):
        level = 4
    return min(5, level)


def _verification_method(stage: str) -> str:
    return {
        "FOUNDATION": "핵심 개념 설명과 적용 예시를 함께 확인",
        "WEB": "프로토콜·웹 동작 설명과 구현 결과를 함께 확인",
        "LANGUAGE": "해당 언어로 구현한 코드와 실행 결과를 확인",
        "FRAMEWORK": "기능 구현 코드, 실행 방법, 테스트 결과를 확인",
        "DATA": "스키마·쿼리·영속성 코드와 테스트 결과를 확인",
        "QUALITY": "테스트 코드·리뷰 기록·개선 전후 결과를 확인",
        "OPERATIONS": "배포·운영 구성과 재현 가능한 실행 기록을 확인",
        "SCALE": "부하 측정과 성능·장애 개선 전후 결과를 확인",
        "DOMAIN": "도메인 요구사항을 반영한 설계·코드·설명을 확인",
        "EXPERIENCE": "프로젝트·경력 이력과 실제 담당 범위 근거를 확인",
        "CREDENTIAL": "발급 기관과 식별 가능한 자격 증빙을 확인",
    }[stage]


def _roadmap_domain(posting: dict) -> str:
    raw = str(posting.get("roleCategory") or posting.get("jobTitle") or "COMMON").upper()
    if raw in {"GAME", "QA", "EMBEDDED"}:
        return raw
    if "BACK" in raw or "백엔드" in raw or "FULL" in raw or "풀스택" in raw:
        return "BACKEND"
    if "FRONT" in raw or "프론트" in raw:
        return "FRONTEND"
    for value in ("DATA", "DEVOPS", "CLOUD", "SECURITY", "AI", "MOBILE", "GAME", "QA", "EMBEDDED"):
        if value in raw:
            return value
    if "데이터" in raw:
        return "DATA"
    if "보안" in raw:
        return "SECURITY"
    if "게임" in raw:
        return "GAME"
    return "COMMON"


def _normalize_domain(raw: str) -> str:
    value = (raw or "COMMON").upper()
    if value == "FULLSTACK":
        return "BACKEND"
    allowed = {"COMMON", "BACKEND", "FRONTEND", "DATA", "DEVOPS", "CLOUD", "SECURITY", "AI", "MOBILE", "GAME", "QA", "EMBEDDED", "DOMAIN", "CAREER"}
    return value if value in allowed else "COMMON"


def _is_pure_seniority(text: str, posting: dict) -> bool:
    evidence = str(posting.get("yearsEvidence") or "").strip()
    if evidence and (evidence in text or text.startswith("요구 연차:")):
        known = get_skill_taxonomy().find_in_text(text.replace(evidence, " "))
        return not known
    return bool(re.search(r"(?:경력|실무)\s*\d+\s*년\s*(?:이상|이하)?", text)) and not get_skill_taxonomy().find_in_text(text)


def _is_qualitative_only(lower: str) -> bool:
    if not _contains_any(lower, _QUALITATIVE_MARKERS):
        return False
    if _contains_any(lower, _QUALITY_MARKERS):
        return False
    # "사용자 경험을 기준으로 설계하는 자세"처럼 동사가 있어도 검증 가능한 업무가
    # 아니라 태도 자체를 요구하는 문장은 로드맵 기술이 아니다. 반면 "협업하여 API를
    # 개발"처럼 실제 산출 행위가 적힌 문장은 아래 업무/기술 분류로 보낸다.
    behavioral_frame = _contains_any(
        lower,
        ("자세", "태도", "마인드", "성향", "열정", "책임감", "커뮤니케이션 역량"),
    )
    if behavioral_frame:
        return True
    return not _contains_any(lower, _VERIFIABLE_TASK_MARKERS)


def _qualitative_identity(lower: str) -> tuple[str, str]:
    if _contains_any(lower, ("커뮤니케이션", "소통")):
        return "커뮤니케이션", "qualitative.communication"
    if _contains_any(lower, ("협업", "팀워크")):
        return "협업 태도", "qualitative.collaboration"
    if _contains_any(lower, ("책임감", "성실")):
        return "책임감", "qualitative.responsibility"
    if _contains_any(lower, ("사용자 경험", "제품 목표", "고객 가치")):
        return "사용자·제품 중심 태도", "qualitative.product-mindset"
    if _contains_any(lower, ("문제 해결", "개선 제안")):
        return "문제 해결 태도", "qualitative.problem-solving"
    return "업무 태도", "qualitative.work-attitude"


def _is_domain_experience(lower: str) -> bool:
    """특정 산업 경험을 일반 기술명과 분리한다.

    단순한 "Java 개발 경험"은 Java 기술 노드로 남아야 한다. 라이브 서비스·장르·출시처럼
    학습만으로 즉시 대체할 수 없는 수행 이력이 명시된 경우에만 경험 관문으로 본다.
    """

    has_experience = _contains_any(
        lower,
        ("개발 경험", "운영 경험", "출시 경험", "런칭 경험", "상용화 경험", "참여 경험"),
    )
    if not has_experience:
        return False
    return _contains_any(
        lower,
        (
            "라이브 서비스", "상용 서비스", "2d 게임", "3d 게임", "mmorpg", "rpg",
            "모바일 게임", "콘솔 게임", "게임 프로젝트", "게임 개발", "게임 서버",
        ),
    )


def _mentions_posting_domain(lower: str, posting: dict) -> bool:
    return any(str(keyword).strip().lower() in lower for keyword in posting.get("domainKeywords", []) if str(keyword).strip())


def _concept_key(prefix: str, text: str) -> str:
    ascii_slug = _SLUG_NON_WORD.sub("-", text.lower()).strip("-")
    if ascii_slug and re.search(r"[a-z]", ascii_slug):
        return f"{prefix}.{ascii_slug[:120]}"[:160]
    digest = hashlib.sha256(_identity_text(text).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}.text-{digest}"


def _identity_text(text: str) -> str:
    return _NON_WORD.sub("", (text or "").lower())


def _compact_title(text: str, fallback: str) -> str:
    value = re.sub(r"^(?:요구\s*연차\s*:\s*)", "", text).strip()
    value = re.sub(
        r"\s*(?:능력|역량|경험|지식|이해)?(?:을|를|이|가)?\s*(?:보유하신|보유한|갖추신|갖춘|가능하신|가능한|있는)\s*분\s*$",
        "",
        value,
    ).strip(" ,.-")
    return value or fallback


def _quality_key(lower: str) -> str:
    if "tdd" in lower or "테스트 주도" in lower:
        return "practice.tdd"
    if "리팩터" in lower or "refactor" in lower:
        return "practice.refactoring"
    if "코드 리뷰" in lower or "code review" in lower or "페어" in lower:
        return "practice.code-review"
    return "practice.test-automation-clean-code"


def _quality_title(lower: str) -> str:
    if "tdd" in lower or "테스트 주도" in lower:
        return "TDD"
    if "리팩터" in lower or "refactor" in lower:
        return "리팩터링"
    if "코드 리뷰" in lower or "code review" in lower or "페어" in lower:
        return "코드 리뷰 · 협업 개발"
    if "clean code" in lower:
        return "Clean Code · 테스트 자동화"
    return "테스트 자동화"


def _dedupe(values: Iterable[CompetencyClassification]) -> list[CompetencyClassification]:
    out: list[CompetencyClassification] = []
    seen: set[str] = set()
    for value in values:
        if value.canonical_key in seen:
            continue
        seen.add(value.canonical_key)
        out.append(value)
    return out


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    return any(marker in text for marker in markers)


_QUALITATIVE_MARKERS = (
    "커뮤니케이션", "소통", "협업", "팀워크", "책임감", "성실", "열정", "몰입",
    "적극적", "주도적", "긍정적", "유연한", "원활한", "도전 정신",
    "사용자 경험", "제품 목표", "고객 가치", "문제 해결", "개선 제안", "자세", "태도",
)
_QUALITY_MARKERS = (
    "테스트", "testing", "test automation", "tdd", "clean code", "클린 코드",
    "리팩터", "refactor", "코드 리뷰", "code review", "페어 프로그래밍", "pair programming",
)
_CREDENTIAL_MARKERS = (
    "자격증", "자격 보유", "certificate", "certification", "정보처리기사", "학위", "학사", "석사", "박사", "졸업",
)
_DATA_MARKERS = (
    "database", "데이터베이스", " db ", "db ", "스키마", "sql", "rdbms", "orm", "jpa", "hibernate", "영속성",
)
_WEB_MARKERS = (
    "http", "웹 표준", "web standard", "rest api", "graphql", "websocket", "네트워크 프로토콜",
)
_SCALE_MARKERS = (
    "대용량", "트래픽", "성능 튜닝", "performance tuning", "캐시", "cache", "redis", "kafka",
    "메시지 큐", "message queue", "분산 시스템", "distributed", "msa", "microservice", "동시성", "고가용성",
)
_OPERATIONS_MARKERS = (
    "ci/cd", "cicd", "배포", "deployment", "docker", "kubernetes", "k8s", "jenkins", "terraform",
    "aws", "gcp", "azure", "cloud", "클라우드", "linux", "운영", "monitoring", "모니터링", "인프라",
)
_VERIFIABLE_TASK_MARKERS = (
    "개발", "구현", "설계", "구축", "운영", "관리", "분석", "최적화", "자동화", "작성", "적용",
)

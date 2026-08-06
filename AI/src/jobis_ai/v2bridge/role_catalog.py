"""서비스 경계의 직무 정규화와 모호성 판정.

핵심 에이전트가 읽어 낸 ``roleCategory``를 서비스의 고정 트랙으로 번역하되, 원문에
서로 다른 지원 경로가 함께 적힌 경우 하나를 임의로 고르지 않는다. 이 모듈의 어휘는
자유 입력 전체를 열거하는 화이트리스트가 아니다. 서비스가 화면과 DB에서 지원하는
상위 경로와, 그 경로를 구분하는 강한 근거만 소유한다.

개별 기술은 ``skill_taxonomy``가 다루며 사전에 없는 기술도 원문 그대로 보존된다.
여기서는 "서버" 한 단어처럼 범위가 넓은 표현을 단독 근거로 쓰지 않는다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from jobis_ai.v2bridge.models import AnalysisQuestion, AnalysisQuestionOption


@dataclass(frozen=True)
class RoleCandidate:
    track: str
    specialization: str
    label: str
    evidence: tuple[str, ...]

    def detail(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RoleResolution:
    primary_track: str
    specialization: str
    candidates: tuple[RoleCandidate, ...]
    selected_by_user: bool = False

    def detail(self) -> dict:
        return {
            "primaryTrack": self.primary_track,
            "specialization": self.specialization,
            "selectedByUser": self.selected_by_user,
            "candidates": [candidate.detail() for candidate in self.candidates],
        }


# 에이전트 코어가 이미 의미를 읽고 고른 표준 키를 서비스 트랙으로 번역한다. 이 표는
# 자유 원문의 모든 단어가 아니라 두 계약 사이의 enum 대응표다.
_ENGINE_TRACK = {
    "backend": ("BACKEND", "WEB_BACKEND", "백엔드"),
    "frontend": ("FRONTEND", "WEB_FRONTEND", "프론트엔드"),
    "fullstack": ("FULLSTACK", "WEB_FULLSTACK", "풀스택"),
    "mobile": ("MOBILE", "MOBILE_APP", "모바일"),
    "devops": ("DEVOPS", "DEVOPS_ENGINEER", "DevOps"),
    "sre": ("DEVOPS", "SRE", "SRE"),
    "data_engineer": ("DATA", "DATA_ENGINEER", "데이터 엔지니어링"),
    "data_scientist": ("DATA", "DATA_SCIENTIST", "데이터 사이언스"),
    "data_analyst": ("DATA", "DATA_ANALYST", "데이터 분석"),
    "ml_engineer": ("AI", "ML_ENGINEER", "AI·머신러닝"),
    "security": ("SECURITY", "SECURITY_ENGINEER", "보안"),
    "qa": ("QA", "QA_AUTOMATION", "QA·테스트 자동화"),
    # 최신 코어가 이 값을 보존하는 경우를 위한 계약 호환. 구 코어가 버리더라도 원문
    # 근거로 아래의 게임/임베디드 분기가 복구한다.
    "game": ("GAME", "GAME_DEVELOPMENT", "게임 개발"),
    "embedded": ("EMBEDDED", "EMBEDDED_SOFTWARE", "임베디드·펌웨어"),
}

_SELECTIONS = {
    "backend": ("BACKEND", "WEB_BACKEND", "백엔드"),
    "frontend": ("FRONTEND", "WEB_FRONTEND", "프론트엔드"),
    "fullstack": ("FULLSTACK", "WEB_FULLSTACK", "풀스택"),
    "game_client": ("GAME", "GAME_CLIENT", "게임 클라이언트"),
    "unity_client": ("GAME", "UNITY_CLIENT", "Unity 클라이언트"),
    "unreal_client": ("GAME", "UNREAL_CLIENT", "Unreal 클라이언트"),
    "game_server": ("GAME", "GAME_SERVER", "실시간 게임 서버"),
    "game_platform": ("BACKEND", "GAME_PLATFORM_BACKEND", "게임 플랫폼 백엔드"),
    "mobile": ("MOBILE", "MOBILE_APP", "모바일"),
    "data": ("DATA", "DATA_ENGINEER", "데이터"),
    "data_engineer": ("DATA", "DATA_ENGINEER", "데이터 엔지니어링"),
    "data_scientist": ("DATA", "DATA_SCIENTIST", "데이터 사이언스"),
    "data_analyst": ("DATA", "DATA_ANALYST", "데이터 분석"),
    "ai": ("AI", "ML_ENGINEER", "AI·머신러닝"),
    "devops": ("DEVOPS", "DEVOPS_ENGINEER", "DevOps·SRE"),
    "sre": ("DEVOPS", "SRE", "SRE"),
    "cloud": ("CLOUD", "CLOUD_ENGINEER", "클라우드"),
    "security": ("SECURITY", "SECURITY_ENGINEER", "보안"),
    "qa": ("QA", "QA_AUTOMATION", "QA·테스트 자동화"),
    "embedded": ("EMBEDDED", "EMBEDDED_SOFTWARE", "임베디드·펌웨어"),
}

_SELECTION_TEXT_ALIASES = {
    "웹 백엔드": "backend",
    "백엔드": "backend",
    "웹 프론트엔드": "frontend",
    "프론트엔드": "frontend",
    "풀스택": "fullstack",
    "게임 클라이언트": "game_client",
    "unity 클라이언트": "unity_client",
    "unreal 클라이언트": "unreal_client",
    "실시간 게임 서버": "game_server",
    "게임 서버": "game_server",
    "게임 플랫폼 백엔드": "game_platform",
    "모바일": "mobile",
    "데이터 엔지니어": "data_engineer",
    "데이터 사이언티스트": "data_scientist",
    "데이터 분석가": "data_analyst",
    "머신러닝": "ai",
    "ai": "ai",
    "devops": "devops",
    "sre": "sre",
    "클라우드": "cloud",
    "보안": "security",
    "qa": "qa",
    "임베디드": "embedded",
    "펌웨어": "embedded",
}


def selected_role(answers: Iterable[object]) -> tuple[str, str, str] | None:
    for answer in answers:
        key = str(getattr(answer, "question_key", "") or "")
        if key != "target_track":
            continue
        value = str(getattr(answer, "answer_value", "") or "").strip().lower()
        selected = _SELECTIONS.get(value)
        if selected is not None:
            return selected
        for alias, selection_key in sorted(
            _SELECTION_TEXT_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if alias in value:
                return _SELECTIONS[selection_key]
        return None
    return None


def resolve(
    posting: dict,
    *,
    raw_text: str = "",
    answers: Iterable[object] = (),
) -> RoleResolution:
    """공고의 상위 트랙과 세부 직무를 근거와 함께 정규화한다."""

    selected = selected_role(answers)
    candidates = candidates_for(posting, raw_text=raw_text)
    if selected is not None:
        track, specialization, label = selected
        chosen = RoleCandidate(
            track=track,
            specialization=specialization,
            label=label,
            evidence=("사용자가 분석 기준 직무를 선택함",),
        )
        return RoleResolution(track, specialization, (chosen, *candidates), True)

    if candidates:
        first = candidates[0]
        return RoleResolution(
            first.track,
            first.specialization,
            candidates,
            False,
        )

    raw_role = str(posting.get("roleCategory") or "").strip().lower()
    mapped = _ENGINE_TRACK.get(raw_role)
    if mapped is not None:
        track, specialization, label = mapped
        candidate = RoleCandidate(
            track,
            specialization,
            label,
            (f"AI가 추출한 직무 분류: {raw_role}",),
        )
        return RoleResolution(track, specialization, (candidate,), False)

    raise ValueError(
        "공고의 주 직무를 서비스 경로로 정규화할 근거가 부족합니다. "
        "직무명을 확인하거나 분석 기준 직무를 선택해 주세요."
    )


def candidates_for(posting: dict, *, raw_text: str = "") -> tuple[RoleCandidate, ...]:
    role = str(posting.get("roleCategory") or "").strip().lower()
    title = str(posting.get("jobTitle") or "").strip()
    source = "\n".join(part for part in (_posting_facts(posting), raw_text) if part)
    lower = source.lower()
    title_lower = title.lower()
    candidates: list[RoleCandidate] = []
    suppress_engine_track = False

    explicit_fullstack = _has_any(
        lower,
        ("fullstack", "full-stack", "풀스택", "풀 스택"),
    )
    game_context = _has_any(
        lower,
        ("게임", "game", "unity", "unreal", "mmorpg", "rpg", "게임플레이", "gameplay"),
    )
    game_client = game_context and _has_any(
        lower,
        ("unity", "unreal", "클라이언트", "client", "게임플레이", "gameplay", "렌더링"),
    )
    game_server = game_context and _has_any(
        lower,
        (
            "게임 서버", "game server", "실시간 서버", "매칭 서버", "전투 서버",
            "상태 동기화", "세션 서버", "룸 서버", "tcp", "udp",
        ),
    )
    game_platform = game_context and _has_any(
        lower,
        (
            "게임 포털", "게임 커뮤니티", "계정 서버", "인증 서버", "결제", "과금",
            "운영자 도구", "백오피스", "portal", "billing", "payment",
        ),
    )

    if game_client:
        if "unity" in lower and "unreal" not in lower:
            specialization, label = "UNITY_CLIENT", "Unity 클라이언트"
        elif "unreal" in lower and "unity" not in lower:
            specialization, label = "UNREAL_CLIENT", "Unreal 클라이언트"
        else:
            specialization, label = "GAME_CLIENT", "게임 클라이언트"
        candidates.append(RoleCandidate(
            "GAME", specialization, label,
            (_first_evidence(source, ("Unity", "Unreal", "클라이언트", "게임플레이")),),
        ))
    if game_server:
        candidates.append(RoleCandidate(
            "GAME", "GAME_SERVER", "실시간 게임 서버",
            (_first_evidence(source, ("게임 서버", "실시간 서버", "매칭", "상태 동기화", "TCP", "UDP")),),
        ))
    if game_platform and not game_server:
        candidates.append(RoleCandidate(
            "BACKEND", "GAME_PLATFORM_BACKEND", "게임 플랫폼 백엔드",
            (_first_evidence(source, ("게임 포털", "계정", "결제", "과금", "커뮤니티")),),
        ))
    if game_context and not (game_client or game_server or game_platform):
        candidates.append(RoleCandidate(
            "GAME", "GAME_DEVELOPMENT", "게임 개발",
            (_first_evidence(source, ("게임", "game")),),
        ))
    if game_context and role in {"backend", "frontend", "fullstack"}:
        # 구 코어의 넓은 server/client 별칭 때문에 생긴 후보는 게임 문맥의 세부 근거보다
        # 약하다. 게임 플랫폼 업무가 실제로 있으면 위에서 BACKEND 후보를 별도로 만들었다.
        suppress_engine_track = True

    if not explicit_fullstack and not game_context:
        frontend = role == "frontend" or _has_any(
            lower,
            ("frontend", "front-end", "프론트엔드", "웹 프론트"),
        )
        backend = role == "backend" or _has_any(
            lower,
            ("backend", "back-end", "백엔드", "웹 백엔드", "서버 개발자"),
        )
        if frontend:
            candidates.append(RoleCandidate(
                "FRONTEND", "WEB_FRONTEND", "프론트엔드",
                (_first_evidence(title or source, ("프론트엔드", "frontend", "front-end")),),
            ))
        if backend:
            candidates.append(RoleCandidate(
                "BACKEND", "WEB_BACKEND", "백엔드",
                (_first_evidence(title or source, ("백엔드", "backend", "back-end", "API")),),
            ))

    if explicit_fullstack:
        candidates.append(RoleCandidate(
            "FULLSTACK", "WEB_FULLSTACK", "풀스택",
            (_first_evidence(title, ("풀스택", "fullstack", "full-stack")),),
        ))

    if not game_context:
        cloud_title = _has_any(lower, ("클라우드 엔지니어", "cloud engineer", "cloud architect"))
        if cloud_title:
            candidates.append(RoleCandidate(
                "CLOUD", "CLOUD_ENGINEER", "클라우드",
                (_first_evidence(title or source, ("클라우드 엔지니어", "cloud engineer")),),
            ))
            if role == "devops":
                suppress_engine_track = True

        mobile_role = role == "mobile" or _has_any(
            lower,
            ("모바일 앱 개발자", "안드로이드 개발자", "android engineer", "ios engineer", "ios 개발자"),
        )
        if mobile_role:
            candidates.append(RoleCandidate(
                "MOBILE", "MOBILE_APP", "모바일",
                (_first_evidence(source, ("모바일 앱 개발자", "안드로이드 개발자", "Android", "iOS")),),
            ))

        data_roles = (
            ("data_engineer", "DATA_ENGINEER", "데이터 엔지니어링", ("데이터 엔지니어", "data engineer")),
            ("data_scientist", "DATA_SCIENTIST", "데이터 사이언스", ("데이터 사이언티스트", "data scientist")),
            ("data_analyst", "DATA_ANALYST", "데이터 분석", ("데이터 분석가", "data analyst")),
        )
        for role_key, specialization, label, markers in data_roles:
            if role == role_key or _has_any(lower, markers):
                candidates.append(RoleCandidate(
                    "DATA", specialization, label,
                    (_first_evidence(source, markers),),
                ))

        if role == "ml_engineer" or _has_any(
            lower,
            ("머신러닝 엔지니어", "machine learning engineer", "ml engineer", "ai 엔지니어", "ai engineer"),
        ):
            candidates.append(RoleCandidate(
                "AI", "ML_ENGINEER", "AI·머신러닝",
                (_first_evidence(source, ("머신러닝 엔지니어", "ML Engineer", "AI 엔지니어")),),
            ))

        if not cloud_title and (
            role in {"devops", "sre"}
            or _has_any(
                lower,
                ("devops 엔지니어", "devops engineer", "sre 엔지니어", "site reliability engineer", "인프라 엔지니어"),
            )
        ):
            specialization = "SRE" if role == "sre" or _has_any(lower, ("sre 엔지니어", "site reliability engineer")) else "DEVOPS_ENGINEER"
            label = "SRE" if specialization == "SRE" else "DevOps"
            candidates.append(RoleCandidate(
                "DEVOPS", specialization, label,
                (_first_evidence(source, ("DevOps 엔지니어", "SRE", "Site Reliability", "인프라 엔지니어")),),
            ))

        if role == "security" or _has_any(
            lower,
            ("보안 엔지니어", "security engineer", "정보보안 담당자", "모의해킹 전문가"),
        ):
            candidates.append(RoleCandidate(
                "SECURITY", "SECURITY_ENGINEER", "보안",
                (_first_evidence(source, ("보안 엔지니어", "Security Engineer", "정보보안", "모의해킹")),),
            ))

        qa_title = role == "qa" or _has_any(
            lower,
            ("qa 엔지니어", "qa engineer", "sdet", "테스트 자동화 엔지니어"),
        )
        if qa_title:
            candidates.append(RoleCandidate(
                "QA", "QA_AUTOMATION", "QA·테스트 자동화",
                (_first_evidence(title or source, ("QA", "SDET", "테스트 자동화")),),
            ))

        embedded_title = role == "embedded" or _has_any(
            lower,
            ("임베디드", "펌웨어", "embedded", "firmware", "iot 개발"),
        )
        if embedded_title:
            candidates.append(RoleCandidate(
                "EMBEDDED", "EMBEDDED_SOFTWARE", "임베디드·펌웨어",
                (_first_evidence(title or source, ("임베디드", "펌웨어", "embedded", "firmware")),),
            ))

    # 게임·웹 혼합 공고가 아니면 코어가 의미로 고른 직군을 우선 후보로 보존한다.
    mapped = None if suppress_engine_track else _ENGINE_TRACK.get(role)
    if mapped is not None and not any(item.track == mapped[0] for item in candidates):
        track, specialization, label = mapped
        candidates.append(RoleCandidate(
            track,
            specialization,
            label,
            (f"AI가 추출한 직무 분류: {role}",),
        ))

    return _dedupe(candidates)


def clarification_question(
    posting: dict,
    *,
    raw_text: str = "",
    answers: Iterable[object] = (),
) -> AnalysisQuestion | None:
    """경로가 실제로 갈리는 혼합 공고일 때만 사용자 선택 질문을 만든다."""

    if selected_role(answers) is not None:
        return None
    candidates = candidates_for(posting, raw_text=raw_text)
    identities = {(item.track, item.specialization) for item in candidates}
    if len(identities) < 2:
        return None

    # 같은 트랙 안에서도 게임 클라이언트와 서버는 학습 경로가 크게 다르다. 웹의
    # BACKEND+FRONTEND도 회사가 한 사람이 모두 하는 풀스택이라고 명시하지 않았다면 묻는다.
    material = (
        any(item.specialization.endswith("CLIENT") for item in candidates)
        and any(item.specialization == "GAME_SERVER" for item in candidates)
    ) or len({item.track for item in candidates}) > 1
    if not material:
        return None

    options: list[AnalysisQuestionOption] = []
    value_by_specialization = {
        "WEB_BACKEND": "backend",
        "WEB_FRONTEND": "frontend",
        "WEB_FULLSTACK": "fullstack",
        "GAME_CLIENT": "game_client",
        "UNITY_CLIENT": "unity_client",
        "UNREAL_CLIENT": "unreal_client",
        "GAME_SERVER": "game_server",
        "GAME_PLATFORM_BACKEND": "game_platform",
        "MOBILE_APP": "mobile",
        "DATA_ENGINEER": "data_engineer",
        "DATA_SCIENTIST": "data_scientist",
        "DATA_ANALYST": "data_analyst",
        "ML_ENGINEER": "ai",
        "DEVOPS_ENGINEER": "devops",
        "SRE": "sre",
        "CLOUD_ENGINEER": "cloud",
        "SECURITY_ENGINEER": "security",
        "QA_AUTOMATION": "qa",
        "EMBEDDED_SOFTWARE": "embedded",
    }
    for candidate in candidates:
        value = value_by_specialization.get(candidate.specialization)
        if value is None or any(option.value == value for option in options):
            continue
        evidence = next((item for item in candidate.evidence if item), "공고의 담당 업무")
        options.append(AnalysisQuestionOption(
            value=value,
            label=candidate.label,
            description=f"{evidence[:220]}을 기준으로 준비 경로를 만들어요.",
        ))
    if len(options) > 4:
        labels = ", ".join(candidate.label for candidate in candidates[:8])
        return AnalysisQuestion(
            key="target_track",
            text="여러 개발 직무를 함께 모집하는 공고입니다. 분석할 직무명을 입력해 주세요.",
            reason=f"확인된 직무: {labels}. 선택에 따라 필요한 기술과 회사 맞춤 프로젝트가 달라집니다.",
            input_type="TEXT",
            options=[],
            related_requirement_ids=[],
            absence_scope="NONE",
        )
    if len(options) < 2:
        return None
    return AnalysisQuestion(
        key="target_track",
        text="이 공고는 서로 다른 개발 경로를 함께 모집합니다. 어떤 직무를 기준으로 분석할까요?",
        reason="선택에 따라 필요한 기술과 회사 맞춤 프로젝트가 달라집니다.",
        input_type="CHOICE",
        options=options,
        related_requirement_ids=[],
        absence_scope="NONE",
    )


def enrich_posting(
    posting: dict,
    *,
    raw_text: str = "",
    answers: Iterable[object] = (),
) -> tuple[dict, RoleResolution]:
    resolution = resolve(posting, raw_text=raw_text, answers=answers)
    enriched = dict(posting)
    enriched["engineRoleCategory"] = posting.get("roleCategory") or ""
    enriched["roleCategory"] = resolution.primary_track
    enriched["roleSpecialization"] = resolution.specialization
    enriched["roleResolution"] = resolution.detail()
    return enriched, resolution


def _posting_facts(posting: dict) -> str:
    requirements = [
        str(item.get("text") or "")
        for key in ("requiredRequirements", "preferredRequirements")
        for item in (posting.get(key) or [])
        if isinstance(item, dict)
    ]
    values = [
        str(posting.get("jobTitle") or ""),
        str(posting.get("roleCategory") or ""),
        *requirements,
        *(str(item) for item in (posting.get("techStack") or [])),
        *(str(item) for item in (posting.get("domainKeywords") or [])),
    ]
    return "\n".join(value for value in values if value.strip())


def _has_any(text: str, markers: Iterable[str]) -> bool:
    return any(marker.lower() in text for marker in markers)


def _first_evidence(text: str, markers: Iterable[str]) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        lower = line.lower()
        if any(marker.lower() in lower for marker in markers):
            return line[:300]
    return "공고에서 관련 업무를 확인함"


def _dedupe(candidates: Iterable[RoleCandidate]) -> tuple[RoleCandidate, ...]:
    out: list[RoleCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        identity = (candidate.track, candidate.specialization)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(candidate)
    return tuple(out)

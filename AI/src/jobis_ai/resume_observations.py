"""이력서 서술의 **관찰** — 정형 항목 밖의 사실을 룰로 센다 (AGENTS §1 판단 계층).

`resume_diagnosis` 가 항목 **개수**까지만 말할 수 있었던 이유는 프롬프트가 아니라 배관이다:
항목화(`tool_render.resume_facts`)가 프로젝트를 **제목 문자열**로 평평하게 만들어, `period`·
`teamSize`·`role`·`achievements` 가 루프의 LLM 에 애초에 도달하지 않았다. 없는 사실은 어떤
프롬프트로도 말할 수 없다.

여기서 하는 일은 전부 **셈과 대조**다 — 어느 칸이 비었나, 어느 문장에 숫자가 있나, 스킬 표기의
괄호 수식어가 서술에도 나오나. **무엇이 결함인지는 정하지 않는다**(§2-1: 안 적힌 것은 없는 것이
아니다). 어느 관찰을 말할지는 루프가 고르고, 없는 근거를 만들지 못하도록 **원문 문장을 그대로**
실어 준다(§2-5).
"""

from __future__ import annotations

import re
from typing import Any

# 채용담당자가 프로젝트에서 가장 먼저 찾는 세 칸. 비어 있으면 규모를 낮게 추정하므로,
# "안 적혔다"는 사실 자체가 사용자에게 정보다.
_CONTEXT_LABELS = {"period": "기간", "teamSize": "팀 규모", "role": "담당 범위"}

# "숫자가 있다"가 아니라 **측정값이 있다**를 본다. 실측(2026-08-04): `\d` 하나로는
# "ORM N+1 문제 해결 … API Latency 대폭 단축"이 N+1 의 1 때문에 정량 문장으로 잡혔다 —
# 다른 LLM 이 대표적 모호 문장으로 짚은 바로 그 줄이다. 단위나 화살표가 붙어야 측정이다.
_MEASURED = re.compile(
    r"\d\s*(?:%|퍼센트|ms|초|분|시간|배|건|명|개월|주|년|회|원|만|천|억|점|위|"
    r"[KkMG]B|[Tt]ps|[Qq]ps|rps|x)|\d\s*(?:→|->|~>)")

# 문장 쪼개기 — 성과 서술은 마침표 없이 줄로 끊는 경우가 많아 개행도 경계로 본다.
# 중점(·)은 경계가 아니다: "공간·건축 디자인"이 "공간"으로 잘려 나갔다(같은 실측).
_SENTENCE_SPLIT = re.compile(r"[.\n]+")

# 자기평가 어휘. **부족을 단정하는 목록이 아니다** — 근거(§3-4): 이 낱말들은 이력서 안에
# 대응하는 사실 서술을 요구하지 않아서 **이력서만으로는 검증할 수 없다.** 루프가 "이 줄은
# 무엇으로 뒷받침되나"를 물을 자리를 가리키는 데만 쓴다.
_SELF_ASSESSED = (
    "집요", "열정", "의지", "적응력", "책임감", "성실", "꼼꼼", "주도적",
    "이해도 보유", "능력 보유", "즉시", "자신 있", "빠르게 습득", "학습 능력",
)

# "Redis (Caching / Distributed Lock)" 처럼 **스킬 이름에 괄호로 붙인 수식어**. 스킬명은
# 목록에 이름만 오르지만 수식어는 "그것까지 해봤다"는 주장이라, 서술에 짝이 있는지가 갈린다.
_QUALIFIED_SKILL = re.compile(r"([A-Za-z][A-Za-z0-9.+#\-/ ]{1,30}?)\s*\(([^)]{2,60})\)")

_MAX_LINE = 160


def _clip(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:_MAX_LINE]


def _is_acronym(claim: str, skill: str) -> bool:
    """"Django REST Framework (DRF)" 처럼 괄호가 **같은 것의 약어**인가.

    약어는 "그것까지 해봤다"는 주장이 아니라 표기라서, 서술에 짝이 없어도 물을 것이 없다.
    """

    letters = claim.replace(".", "").strip()
    if not (2 <= len(letters) <= 6 and letters.isalpha() and letters.isupper()):
        return False
    initials = "".join(word[0] for word in re.split(r"[\s\-]+", skill) if word)
    return letters.lower() == initials.lower()


def _claims(profile: dict[str, Any]) -> list[dict[str, str]]:
    """프로젝트·경력의 **성과 서술 문장**을 출처 라벨과 함께 모은다."""

    out: list[dict[str, str]] = []
    for project in profile.get("projects") or []:
        label = _clip(project.get("title"))
        for raw in [project.get("summary"), *(project.get("achievements") or [])]:
            for piece in _SENTENCE_SPLIT.split(str(raw or "")):
                text = _clip(piece)
                if len(text) >= 8:
                    out.append({"source": label, "text": text})
    for experience in profile.get("experiences") or []:
        label = _clip(" ".join(x for x in (experience.get("company"),
                                           experience.get("role")) if x))
        for piece in _SENTENCE_SPLIT.split(str(experience.get("summary") or "")):
            text = _clip(piece)
            if len(text) >= 8:
                out.append({"source": label, "text": text})
    return out


def observe(profile: dict[str, Any], resume_text: str) -> dict[str, Any]:
    """정형 프로필 + 원문 → 서술 관찰. **결정론 — 여기까지가 근거다.**

    반환 키는 전부 "무엇이 적혀 있나"이지 "무엇이 부족한가"가 아니다:
      · projects            항목별 맥락 세 칸(기간·팀 규모·담당 범위)과 **빈 칸의 이름**
      · quantifiedClaims    숫자가 든 성과 문장(원문 그대로)
      · unquantifiedClaims  숫자가 없는 성과 문장(원문 그대로)
      · selfAssessedLines   자기평가 어휘가 든 원문 줄
      · skillQualifiers     스킬 이름에 괄호로 붙은 수식어 + 그 말이 서술에도 나오는지
    """

    projects = []
    for project in profile.get("projects") or []:
        title = _clip(project.get("title"))
        if not title:
            continue
        context = {key: _clip(project.get(key)) for key in _CONTEXT_LABELS}
        projects.append({
            "title": title,
            "projectType": _clip(project.get("projectType")),
            **context,
            "achievements": [_clip(a) for a in (project.get("achievements") or []) if _clip(a)],
            "techStack": [_clip(t) for t in (project.get("techStack") or []) if _clip(t)],
            "missingContext": [label for key, label in _CONTEXT_LABELS.items()
                               if not context[key]],
        })

    claims = _claims(profile)
    quantified = [c for c in claims if _MEASURED.search(c["text"])]
    unquantified = [c for c in claims if not _MEASURED.search(c["text"])]

    self_assessed = []
    for line in str(resume_text or "").splitlines():
        text = _clip(line)
        if len(text) >= 8 and any(word in text for word in _SELF_ASSESSED):
            self_assessed.append(text)

    # 수식어가 **서술에도** 나오나 — 스킬 목록 줄이 아니라 프로젝트·경력 서술에서 찾는다.
    # 글자 그대로의 대조다(퍼지 매칭 없음): "있다"는 확실하지만 "없다"는 표기가 다를 수도
    # 있다는 뜻이라, 루프가 서술을 보고 판단하도록 사실만 넘긴다.
    narrative = " ".join(c["text"] for c in claims).lower()
    qualifiers, seen_qualifiers = [], set()
    for skill, inner in _QUALIFIED_SKILL.findall(str(resume_text or "")):
        skill = _clip(skill).lstrip(",·:").strip()
        for claim in re.split(r"[/,·]", inner):
            claim = _clip(claim)
            # 라틴 문자가 없으면 수식어가 아니다 — "(주니어)" 같은 제목 괄호를 걸러낸다.
            if not skill or not claim or not re.search(r"[A-Za-z]", claim):
                continue
            if _is_acronym(claim, skill):
                continue      # "Django REST Framework (DRF)" — 같은 것의 약어일 뿐이다
            key = (skill.lower(), claim.lower())
            if key in seen_qualifiers:
                continue
            seen_qualifiers.add(key)
            qualifiers.append({"skill": skill, "qualifier": claim,
                               "inNarrative": claim.lower() in narrative})

    return {
        "projects": projects,
        "quantifiedClaims": quantified,
        "unquantifiedClaims": unquantified,
        "selfAssessedLines": self_assessed,
        "skillQualifiers": qualifiers[:20],
    }

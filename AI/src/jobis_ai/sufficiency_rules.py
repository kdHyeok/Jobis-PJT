"""정보 충분성 룰 (sufficiency_rules) + 결측 → 질문 템플릿 매핑.

설계 §3.3(충분성 분기)과 §3.4(추가 질문)를 담당한다. **LLM 을 호출하지 않는다** —
"무엇이 비었는지"와 "무엇을 물을지"는 전부 룰이 정한다.

이 모듈이 답하는 질문 (헷갈리면 안 되는 경계):
    ✅ "이 사람을 **분석하기에 정보가 충분한가?**"
    ❌ "이 사람이 **이 공고에 충분한가?**"

둘은 완전히 다르다. 근거가 풍부한데 요구사항을 못 갖춘 사람은 **정보는 충분**하다 —
그냥 아직 준비가 덜 된 것이고, 그건 갭 분석이 답할 일이지 질문을 더 던질 일이 아니다.
반대로 근거가 없어서 판정을 못 한 경우에만 물어야 한다. 이 구분을 놓치면
역량이 부족한 사용자에게 "정보를 더 주세요"라고 되묻는 무례한 제품이 된다.

따라서 부족 판정 기준은 **오직 정보 결핍**이다:
  - 근거(evidence)가 아예 없거나 너무 적다
  - 필수 요구사항을 **판정조차 못 했다**(uncertain) → 사용자에게 직접 묻는다
  - 스킬을 주장했는데 뒷받침 경험이 없다 → 그 경험을 묻는다
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jobis_ai.gap_matcher import MatchReport
from jobis_ai.skill_taxonomy import get_skill_taxonomy

# 최소 근거 개수. 이보다 적으면 무엇을 판정하든 신뢰할 수 없다.
_MIN_EVIDENCE_COUNT = 2

# 필수 요구사항 중 '판정 불가' 비율이 이 이상이면 정보 부족으로 본다.
# 절반을 못 읽었으면 분석이라 부를 수 없다.
_MAX_UNDECIDABLE_RATIO = 0.5

# 한 번에 던질 질문 수 상한. 너무 많이 물으면 사용자가 이탈한다.
_MAX_QUESTIONS = 5


@dataclass(frozen=True)
class MissingInfo:
    """정보 결핍 1건.

    code    : 결핍 유형 (질문 템플릿 선택 키)
    detail  : 사람이 읽는 설명
    subject : 무엇에 대한 결핍인가 (스킬명·요구사항 텍스트 등). 질문 문장에 끼워 넣는다.
    blocking: **이것 때문에 분석을 멈춰야 하는가.**

    `blocking` 이 이 모듈의 핵심 구분이다. 스킬 하나에 근거가 없는 건 분석을 막을 일이
    아니다 — 갭 분석이 "기재됐으나 근거 없음"이라고 이미 알려주기 때문이다. 그걸로 분석을
    멈추고 되물으면, 근거가 충분한 사용자한테까지 질문을 퍼붓게 된다.
    분석 자체가 불가능한 결핍(근거 없음·판정 불가)만 blocking 이다.
    """

    code: str
    detail: str
    subject: str = ""
    blocking: bool = True
    relatedRequirementIds: tuple[str, ...] = ()


@dataclass
class SufficiencyResult:
    """충분성 판정 결과."""

    sufficient: bool = True
    missing: list[MissingInfo] = field(default_factory=list)
    evidenceCount: int = 0
    undecidableRequiredCount: int = 0

    @property
    def reasons(self) -> list[str]:
        return [m.detail for m in self.missing]

    @property
    def blocking(self) -> list[MissingInfo]:
        return [m for m in self.missing if m.blocking]


# 결측 코드 → 질문 템플릿 (§3.4). `{subject}` 는 MissingInfo.subject 로 채운다.
# 질문 문구를 여기 모아 두는 이유: 무엇을 물을지는 룰이 정하고, LLM 은 나중에 이 문장을
# 자연스럽게 다듬기만 한다(nl_render). 질문 자체를 LLM 이 만들면 엉뚱한 걸 묻는다.
_QUESTION_TEMPLATES: dict[str, tuple[str, str]] = {
    "no_evidence": (
        "지금까지 진행한 프로젝트나 업무 경험을 한 가지만 구체적으로 알려주실 수 있을까요? "
        "무엇을 만들었고 어떤 기술을 썼는지가 있으면 좋습니다.",
        "이력서에서 판정 근거로 쓸 경험 문장을 찾지 못했습니다.",
    ),
    "few_evidence": (
        "추가로 진행하신 프로젝트나 업무가 있다면 알려주세요. 맡은 역할과 사용 기술을 함께 적어주시면 좋습니다.",
        "판정 근거가 되는 경험이 부족해 분석 신뢰도가 낮습니다.",
    ),
    "undecidable_requirement": (
        "공고의 '{subject}' 항목과 관련해 본인의 경험을 알려주실 수 있을까요?",
        "이 요구사항은 이력서만으로 충족 여부를 판정할 수 없었습니다.",
    ),
    "unevidenced_claim": (
        "'{subject}' 을(를) 사용해 본 경험을 구체적으로 알려주세요. 어떤 프로젝트에서 무엇을 하셨나요?",
        "기술스택에 기재되어 있으나 이를 뒷받침하는 경험이 이력서에 없습니다.",
    ),
}


def assess(report: MatchReport, profile: dict) -> SufficiencyResult:
    """매칭 결과 + 프로필 → 정보 충분성 판정.

    `report` 는 gap_matcher 를 **룰 모드로 미리 돌린 결과**다. 여기서 다시 매칭하지 않는다.
    """

    evidence_count = len(profile.get("evidenceMap") or [])
    required = [m for m in report.matches if m.type == "required"]
    undecidable = [m for m in required if m.status == "uncertain"]

    result = SufficiencyResult(
        evidenceCount=evidence_count,
        undecidableRequiredCount=len(undecidable),
    )

    # 1) 근거 결핍 — 가장 치명적. 근거가 없으면 어떤 판정도 의미가 없다.
    if evidence_count == 0:
        result.missing.append(MissingInfo(
            code="no_evidence",
            detail="이력서에서 판정 근거(경험 문장)를 추출하지 못했습니다.",
        ))
    elif evidence_count < _MIN_EVIDENCE_COUNT:
        # **막지 않는다**(2026-08-03). 근거가 1건이라도 있으면 판정할 재료는 있는 것이고,
        # 신뢰도가 낮다는 사실은 이미 `confidence` 와 이 경고에 남는다. 근거 1건 때문에
        # 분석을 멈추면 사용자는 "이력서를 냈는데 아무것도 안 나온다"를 겪는다 — 실측
        # (2026-08-03)에서 지도가 통째로 안 생긴 경로가 이것이었다.
        # 0건(위)은 여전히 막는다. 그건 신뢰도가 낮은 게 아니라 잴 것이 없는 것이다.
        result.missing.append(MissingInfo(
            code="few_evidence",
            detail=f"판정 근거가 {evidence_count}건뿐이라 분석 신뢰도가 낮습니다.",
            blocking=False,
        ))

    # 2) 필수 요구사항을 판정조차 못 한 경우.
    #
    # 전에는 이게 **무조건 blocking** 이었고 주석에 "사용자에게 직접 묻는 게 유일한 해결책"
    # 이라고 적혀 있었다. 그 전제가 두 번 틀렸다:
    #
    #   · 유일하지 않다. `gap_matcher` 가 이미 LLM 으로 두 번 읽는다 — 배치 의미 판정
    #     (`judge_topics_relevance`)과, 배치가 실패한 건에 대한 개별 재시도. 여기까지 와서
    #     남은 uncertain 은 "아직 안 물어봐서 모르는 것"이 아니라 **읽어도 모르는 것**이다.
    #   · 되물어도 못 묻는다. 이 결핍이 만드는 질문에는 선택지가 없어서 v2 계약의
    #     `NEEDS_INPUT`(선택지 2~4개 필수)으로 나갈 수 없다 → 서비스가 스스로 "정보 없음"
    #     으로 답하며 같은 턴을 왕복 상한까지 반복하고 분석이 통째로 실패한다
    #     (2026-08-03 실측: 스트림으로 fit_analysis 가 4회 반복되는 것을 확인).
    #
    # 그래서 **근거가 있으면 막지 않는다.** 못 읽은 요구사항은 `uncertain` 으로 남고,
    # uncertain 은 점수 분모에서 빠지므로(`_STATUS_SCORE`) 미충족으로 둔갑하지도 않는다
    # (§2-1 모른다 ≠ 아니다). 한 줄을 못 읽었다고 지도를 통째로 안 만드는 것이 더 나쁘다.
    #
    # 근거가 아예 없을 때(1번)는 여전히 막는다 — 그건 판정할 재료 자체가 없는 것이다.
    if required and len(undecidable) / len(required) >= _MAX_UNDECIDABLE_RATIO:
        readable = evidence_count > 0
        for match in undecidable:
            result.missing.append(MissingInfo(
                code="undecidable_requirement",
                detail=f"'{match.text}' 의 충족 여부를 판정하지 못했습니다.",
                subject=match.text,
                blocking=not readable,
                relatedRequirementIds=(match.requirementId,),
            ))

    # 3) 주장만 있고 근거가 없는 스킬 — 물어보면 좋지만 **분석을 막지는 않는다**(blocking=False).
    #    갭 분석이 이미 "기재됐으나 근거 없음"으로 보고하므로, 이것만으로 되묻는 건 중복이다.
    #    다만 위 1·2번 때문에 어차피 멈춰서 물어야 한다면, 이것도 같이 묻는 게 이득이다.
    for skill in _unevidenced_claimed_skills(report, profile):
        result.missing.append(MissingInfo(
            code="unevidenced_claim",
            detail=f"'{skill}' 보유 주장을 뒷받침하는 경험 근거가 없습니다.",
            subject=skill,
            blocking=False,
        ))

    result.sufficient = not result.blocking
    return result


def _unevidenced_claimed_skills(report: MatchReport, profile: dict) -> list[str]:
    """공고가 요구하는 스킬 중 '주장만 있고 근거 없는' 것들.

    공고와 무관한 스킬은 묻지 않는다 — 이 분석에 필요 없는 걸 물으면 사용자 시간만 뺏는다.
    수반 스킬도 묻지 않는다: "MySQL 경험을 알려주세요"와 "SQL 경험을 알려주세요"를 따로
    물으면 같은 걸 두 번 묻는 꼴이다. 가장 구체적인 스킬만 남긴다.

    gap_matcher 가 이제 근거 없는 '기재만 된' 스킬도 met 으로 인정하므로(2026-07-20 결정),
    met 매치도 후보에 포함한다 — 판정은 이미 통과했어도 근거를 보강하면 신뢰도가 오른다.
    """

    skill_evidence: dict[str, list[str]] = profile.get("skillEvidence") or {}
    taxonomy = get_skill_taxonomy()

    candidates: list[str] = []
    for match in report.matches:
        if match.status not in ("met", "partially_met"):
            continue
        for skill in match.matchedSkills:
            if not skill_evidence.get(skill) and skill not in candidates:
                candidates.append(skill)

    # 다른 후보가 수반하는 스킬(MySQL → SQL, RDBMS)은 제외
    implied: set[str] = set()
    for skill in candidates:
        implied.update(taxonomy.implied_by(skill))
    return [s for s in candidates if s not in implied]


def build_questions(result: SufficiencyResult) -> list[dict]:
    """결측 정보 → 사용자에게 던질 질문 목록 (§3.4).

    무엇을 물을지는 룰이 결정하고, 문구는 템플릿에서 온다.
    정보가 충분하면 **아무것도 묻지 않는다** — 분석을 진행할 수 있는데 되묻는 건 방해다.
    반환: [{questionId, text, reason, relatedRequirementIds}]
    """

    if result.sufficient:
        return []

    questions: list[dict] = []
    for missing in result.missing:
        template = _QUESTION_TEMPLATES.get(missing.code)
        if not template:
            continue
        text, reason = template
        questions.append({
            "questionId": f"q-{len(questions) + 1}",
            "text": text.format(subject=missing.subject),
            "reason": reason,
            "relatedRequirementIds": list(missing.relatedRequirementIds),
        })
        if len(questions) >= _MAX_QUESTIONS:
            break
    return questions

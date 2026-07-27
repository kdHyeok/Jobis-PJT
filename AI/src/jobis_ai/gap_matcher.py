"""갭 매칭 엔진 (gap_matcher) — 요구사항 충족 여부를 **결정론으로** 판정한다.

설계 §3.5 의 핵심 툴. 지금까지 "이 사람이 이 요구사항을 충족하나"는 LLM 이 통째로
판단했다. 그건 판단(Decide) 계층이고, 판단이 결정론이어야 신뢰성이 나온다(§0).
이 모듈이 그 판단을 가져온다. **LLM 을 호출하지 않는다.**

판정 절차:
  1차) 정확/동의어 매칭 — requirement 텍스트에서 skill_taxonomy 로 기술명을 뽑고,
       사용자의 skillEvidence(룰로 만든 스킬↔근거 표)와 대조한다. **이력서에 스킬로
       기재만 돼 있어도(근거 문장 없이) met 판정에 넣는다** — 사용자가 직접 적은 스킬은
       "쓸 수 있다"고 인정한다는 결정(2026-07-20). 다만 confidence 는 근거 있는 쪽에
       더 높게 줘서 신뢰도 차이는 남긴다.
  2차) LLM 의미 판정 — 1차로 기술명을 못 뽑은 서술형 요구사항("이벤트 드리븐 아키텍처
       설계 경험")을 evidence 문장들과 의미 비교한다(`semantic_judge.judge_domain_relevance`,
       §0 원칙의 의도적 예외). **원래 임베딩 유사도였으나 2026-07-20 실측으로 교체** —
       `text-embedding-3-small`/`-large` 둘 다 짧은/중간 길이 텍스트 간 주제 관련성을
       신뢰할 수 없게 판정했다(예: "React"가 "Kafka"보다 "이벤트 드리븐 아키텍처"와 더
       유사하다고 나옴). 상세는 `docs/troubleshooting.md` 2026-07-20 항목 참고.
  3차) 도메인 키워드 매칭 — requirement.kind == "domain_keyword"(공고 domainKeywords 유래)일 때,
       ① 포함 매칭(룰, 무료·즉시·결정론)을 먼저 시도 → ② 실패하면 2차와 같은 LLM 의미
       판정으로 폴백(같은 근거로 임베딩 대신 LLM).
  4차) 연차 사다리 비교 — requirement.kind == "seniority"(공고 seniority 유래)일 때,
       experience_estimator 로 관련 직군 경력만 골라 총 개월수를 추정하고 사다리
       (intern~lead) 위치를 비교한다(룰).

'모른다'와 '아니다'의 구분(이 모듈의 가장 중요한 규칙):
  기술명도 못 뽑고 LLM 의미 판정도 못 하면(미설정/호출 실패) `not_met`(미충족)이 아니라
  **`uncertain`(판정 불가)**이다.
  둘은 완전히 다르다 — not_met 은 "이 사람에게 없다"는 주장이고, uncertain 은 "우리가
  판정할 수 없다"는 고백이다. 여기서 not_met 으로 찍으면 근거 없이 사람의 부족을 단정하고,
  그 위에 로드맵까지 쌓여 오류가 증폭된다.

재사용처: analyze_gap(§3.5), check_sufficiency(§3.3 커버리지 게이트),
find_alternatives(§3.7 대체 공고의 reducedGaps 계산).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jobis_ai.experience_estimator import estimate_experience_months
from jobis_ai.role_taxonomy import SENIORITY_KO, SENIORITY_LADDER, get_role_taxonomy
from jobis_ai.semantic_judge import judge_domain_relevance
from jobis_ai.skill_taxonomy import get_skill_taxonomy

# --- 임계값 (판정 기준. 조정 시 여기만 본다) ---

# 요구 기술 중 '근거 있는' 비율이 이 이상이면 met.
# 1.0 이 아닌 이유: 요구사항 한 줄에 기술 4개가 나열되면("Java, Spring, MySQL, Redis")
# 3개를 근거로 증명해도 미충족이 되는데, 그건 과하다.
_MET_EVIDENCE_RATIO = 0.8

# severity 룰 (§3.5): 필수인데 못 갖췄으면 high, 우대는 아무리 못 갖춰도 low.
# uncertain 은 여기 없다 — 판정 못 한 요구사항은 gap(부족 역량)이 아니기 때문이다. 아래 to_gap_payload 참고.
_SEVERITY: dict[tuple[str, str], str] = {
    ("required", "not_met"): "high",
    ("required", "partially_met"): "medium",
    ("preferred", "not_met"): "low",
    ("preferred", "partially_met"): "low",
}

# scoreBasis 집계 시 요구사항 종류별 가중치.
_TYPE_WEIGHT = {"required": 1.0, "preferred": 0.5}

# status → 점수 (scoreBasis 집계용). uncertain 은 분모에서 제외한다(모르는 걸 0점 처리하지 않는다).
_STATUS_SCORE = {"met": 1.0, "partially_met": 0.5, "not_met": 0.0}

# 자격증·어학 요구사항을 식별하는 키워드 (certLanguage 집계용)
_CERT_KEYWORDS = ("자격증", "기사", "토익", "toeic", "opic", "오픽", "어학", "학위", "전공")

# 종합 적합도 점수 집계용 카테고리 가중치 (§3.5 확장). 합이 1.0 일 필요는 없다 —
# 실제로 계산된 카테고리만 골라 그 가중치 합으로 정규화하므로(overall_fit 참고),
# 여기서는 카테고리 간 상대적 중요도만 정하면 된다.
_CATEGORY_WEIGHT = {
    "techSkill": 0.35,
    "projectExperience": 0.25,
    "roleRelevance": 0.15,
    "domainFit": 0.15,
    "certLanguage": 0.10,
}

# 종합 점수 → 등급 경계. 상 ≥ 0.7, 중 0.4~0.7 미만, 하 < 0.4 (사용자 결정 2026-07-21).
_GRADE_HIGH = 0.7
_GRADE_MID = 0.4


@dataclass(frozen=True)
class Match:
    """요구사항 1건의 판정 결과.

    kind: 요구사항 **카테고리** — "text"(기술/서술형) | "domain_keyword" | "seniority".
          요구사항의 kind 를 그대로 보존한다. scoreBasis 집계에서 domainFit/roleRelevance 를
          어떤 매칭으로 계산할지 고를 때 쓴다. method(어떻게 판정했나)와는 다른 축이다.
    method: 어떻게 판정했는지 — "exact"(1차 룰) | "embedding"(2차) | "undecidable"(판정 불가)
            추적성과 디버깅을 위해 남긴다. 나중에 "왜 이렇게 나왔냐"를 답할 수 있어야 한다.
    """

    requirementId: str
    type: str
    text: str
    status: str
    kind: str = "text"
    matchedEvidenceIds: list[str] = field(default_factory=list)
    matchedSkills: list[str] = field(default_factory=list)
    missingSkills: list[str] = field(default_factory=list)
    confidence: float = 0.0
    method: str = "exact"
    reason: str = ""


@dataclass
class MatchReport:
    """전체 매칭 산출물. analyze_gap 이 이걸 그대로 GapAnalysisResult 로 옮긴다."""

    matches: list[Match] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    @property
    def undecidable_count(self) -> int:
        return sum(1 for m in self.matches if m.status == "uncertain")

    def covered_ratio(self, req_type: str = "required") -> float:
        """해당 종류 요구사항 중 met/partially_met 비율. check_sufficiency 게이트가 쓴다.

        uncertain 은 분모에서 뺀다 — 판정 못 한 걸 '미달'로 세면 정보 부족을 사용자 탓으로 돌린다.
        """

        decided = [m for m in self.matches if m.type == req_type and m.status != "uncertain"]
        if not decided:
            return 0.0
        hit = sum(1 for m in decided if m.status in ("met", "partially_met"))
        return hit / len(decided)


def _severity_of(req_type: str, status: str) -> str:
    return _SEVERITY.get((req_type, status), "low")


class GapMatcher:
    """requirement × user profile 매칭기. LLM 없이 판정한다."""

    def __init__(self) -> None:
        self._taxonomy = get_skill_taxonomy()

    # ------------------------------------------------------------------
    # 1차: 정확/동의어 매칭
    # ------------------------------------------------------------------
    def _match_by_skills(
        self,
        required_skills: list[str],
        skill_evidence: dict[str, list[str]],
        claimed_skills: set[str],
    ) -> tuple[str, list[str], list[str], list[str], float, str]:
        """요구 기술 목록 vs 사용자 보유 → (status, evidenceIds, matched, missing, confidence).

        '근거 있는 보유'(skillEvidence 에 등장)와 '주장만 있는 보유'(스킬 목록에만 존재)를
        구분해서 추적하지만(추후 근거로 이어질 신뢰도 표시), **status 판정(met 여부)은
        이력서에 스킬로 기재만 돼 있어도 인정한다** — 사용자가 자기 이력서에 직접 적은
        스킬은 근거 문장이 없어도 '쓸 수 있다'고 본다는 결정(2026-07-20). 다만 confidence
        는 근거 없는 항목에 절반 가중치만 줘서, 판정은 통과시키되 신뢰도 차이는 남긴다.
        """

        evidenced: list[str] = []
        claimed_only: list[str] = []
        missing: list[str] = []
        evidence_ids: list[str] = []

        for skill in required_skills:
            ids = skill_evidence.get(skill, [])
            if ids:
                evidenced.append(skill)
                for eid in ids:
                    if eid not in evidence_ids:
                        evidence_ids.append(eid)
            elif skill.lower() in claimed_skills:
                claimed_only.append(skill)
            else:
                missing.append(skill)

        total = len(required_skills)
        matched = evidenced + claimed_only
        matched_ratio = len(matched) / total

        if matched_ratio >= _MET_EVIDENCE_RATIO:
            status = "met"
        elif matched:
            status = "partially_met"
        else:
            status = "not_met"

        # confidence: 근거 있는 것에 만점, 주장만 있는 것에 절반. status 는 통과했어도
        # '증명 강도' 차이는 이 수치에 남긴다(신뢰도는 낮게, 판정은 인정).
        confidence = (len(evidenced) + 0.5 * len(claimed_only)) / total
        reason = _reason_for_skills(evidenced, claimed_only, missing, status)
        return status, evidence_ids, matched, missing, round(confidence, 2), reason

    # ------------------------------------------------------------------
    # 2차/3차 공용: LLM 의미 판정 (§0 원칙의 의도적 예외)
    # ------------------------------------------------------------------
    def _llm_semantic_match(
        self, topic: str, evidences: list[dict]
    ) -> tuple[str, list[str], float, str]:
        """topic(서술형 요구사항 문장 또는 도메인 키워드) vs evidence 문장들의 의미 관련성.

        원래 임베딩 유사도였으나 2026-07-20 실측으로 LLM 구조화 출력으로 교체했다 —
        짧은/중간 길이 텍스트 간 주제 관련성 판정에 임베딩 신호가 못 미더웠다(근거는
        `docs/troubleshooting.md` 2026-07-20 항목, `semantic_judge.py` 상단 참고).

        LLM은 이진 판정만 한다(met/not_met) — "얼마나 충족하는지" 등급을 안 매긴다.
        재사용처: 2차(서술형 요구사항 전체 매칭), 3차 도메인 키워드(포함 매칭 실패 시 폴백).
        """

        texts = [str(e.get("text", "")) for e in evidences]
        related_idx = judge_domain_relevance(topic, texts)
        if related_idx is None:
            return "uncertain", [], 0.0, "undecidable"

        if related_idx:
            matched_ids = [
                str(evidences[i].get("evidenceId", ""))
                for i in related_idx
                if evidences[i].get("evidenceId")
            ]
            # 룰 매칭(근거 확정)보다는 확신을 낮춰 잡는다(LLM 추론이라 룰만큼 확실하지 않음).
            return "met", matched_ids, 0.6, "llm_semantic"
        return "not_met", [], 1.0, "llm_semantic"

    # ------------------------------------------------------------------
    # 3차: 도메인 키워드 매칭 (룰, 포함 여부)
    # ------------------------------------------------------------------
    def _match_domain_keyword(
        self, keyword: str, evidences: list[dict]
    ) -> tuple[str, list[str], float, str]:
        """도메인 키워드 관련성 판정. 1차 포함 매칭(룰) → 실패 시 2차 LLM 의미 판정.

        2차는 `_llm_semantic_match`(서술형 요구사항 2차 매칭과 공용) 재사용.
        """

        kw = keyword.strip().lower()
        if not kw:
            return "uncertain", [], 0.0, "undecidable"

        # 1차: 포함 매칭 (룰, 무료·즉시·결정론)
        matched_ids = [
            str(e.get("evidenceId", ""))
            for e in evidences
            if kw in str(e.get("text", "")).lower() and e.get("evidenceId")
        ]
        if matched_ids:
            return "met", matched_ids, 1.0, "keyword"

        return self._llm_semantic_match(keyword, evidences)

    # ------------------------------------------------------------------
    # 4차: 연차(seniority) 사다리 비교 (룰)
    # ------------------------------------------------------------------
    def _match_seniority(
        self, posting_seniority: str, profile: dict, role_category: str = ""
    ) -> tuple[str, float, str]:
        """공고 요구 연차 vs 사용자 추정 연차.

        `role_category`가 주어지면 그 직군과 무관한 경력(예: 백엔드 공고에 미술학원
        강사 경력)은 연차 계산에서 제외한다(experience_estimator 참고).

        사용자 연차를 못 정하면(estimate_experience_months 가 None) `not_met` 이 아니라
        `uncertain` 이다 — '모른다'와 '아니다'를 섞지 않는다(모듈 상단 규칙과 동일 원칙).
        """

        posting_key = (posting_seniority or "").strip().lower()
        if posting_key not in SENIORITY_LADDER:
            return "uncertain", 0.0, "공고의 요구 연차를 확인할 수 없습니다."

        estimate = estimate_experience_months(profile, target_role_category=role_category)
        if estimate.totalMonths is None:
            return (
                "uncertain",
                0.0,
                "이력서 경력 항목의 근무 기간을 확인할 수 없어 연차를 판정하지 못했습니다.",
            )

        user_key = get_role_taxonomy().seniority_from_years(estimate.totalMonths // 12)
        posting_idx = SENIORITY_LADDER.index(posting_key)
        user_idx = SENIORITY_LADDER.index(user_key)
        diff = user_idx - posting_idx

        posting_label = SENIORITY_KO.get(posting_key, posting_key)
        user_label = SENIORITY_KO.get(user_key, user_key)
        role_label = get_role_taxonomy().label_of(role_category) if role_category else ""
        scope = f"'{role_label}' 관련 " if role_label else ""
        years_desc = f"{scope}약 {estimate.totalMonths // 12}년 {estimate.totalMonths % 12}개월"

        if diff >= 0:
            status = "met"
            reason = f"요구 연차({posting_label}) 대비 사용자 추정 경력({years_desc}, {user_label})이 충족됩니다."
        elif diff == -1:
            status = "partially_met"
            reason = f"요구 연차({posting_label})에 사용자 추정 경력({years_desc}, {user_label})이 한 단계 못 미칩니다."
        else:
            status = "not_met"
            reason = f"요구 연차({posting_label})에 비해 사용자 추정 경력({years_desc}, {user_label})이 부족합니다."
        return status, 1.0, reason

    # ------------------------------------------------------------------
    # 공개 진입점
    # ------------------------------------------------------------------
    def match(self, requirements: list[dict], profile: dict) -> MatchReport:
        """요구사항 목록 × 프로필 → 판정 목록.

        requirements: [{requirementId, text, type, kind?, seniority?, roleCategory?}]
            kind 가 없거나 "text"면 1·2차(정확/임베딩) 매칭. "domain_keyword"면 3차,
            "seniority"면 4차로 분기한다(seniority 키는 posting 의 사다리 값, roleCategory 는
            연차 계산 시 무관 경력을 걸러내는 기준으로 쓴다).
        profile:      NormalizedUserProfile.model_dump() (skills / skillEvidence / evidenceMap)
        """

        report = MatchReport()
        skill_evidence: dict[str, list[str]] = profile.get("skillEvidence") or {}
        evidences: list[dict] = profile.get("evidenceMap") or []
        claimed_skills = {
            self._taxonomy.normalize(str(s.get("name", ""))).lower()
            for s in (profile.get("skills") or [])
            if s.get("name")
        }

        llm_unavailable = 0

        for req in requirements:
            text = str(req.get("text", ""))
            req_type = str(req.get("type", "required"))
            req_id = str(req.get("requirementId", ""))
            kind = str(req.get("kind", "text"))

            if kind == "domain_keyword":
                status, matched_ids, confidence, dk_method = self._match_domain_keyword(
                    text, evidences
                )
                report.matches.append(Match(
                    requirementId=req_id, type=req_type, text=text, status=status,
                    kind="domain_keyword",
                    matchedEvidenceIds=matched_ids, confidence=confidence, method=dk_method,
                    reason=_reason_for_domain_keyword(text, status, dk_method),
                ))
                continue

            if kind == "seniority":
                status, confidence, reason = self._match_seniority(
                    str(req.get("seniority", "")), profile, str(req.get("roleCategory", ""))
                )
                report.matches.append(Match(
                    requirementId=req_id, type=req_type, text=text, status=status,
                    kind="seniority",
                    confidence=confidence, method="seniority_ladder", reason=reason,
                ))
                continue

            required_skills = self._taxonomy.find_in_text(text)

            if required_skills:
                status, evidence_ids, matched, missing, confidence, reason = self._match_by_skills(
                    required_skills, skill_evidence, claimed_skills
                )
                report.matches.append(Match(
                    requirementId=req_id, type=req_type, text=text, status=status,
                    matchedEvidenceIds=evidence_ids, matchedSkills=matched,
                    missingSkills=missing, confidence=confidence, method="exact",
                    reason=reason,
                ))
                continue

            # 기술명이 안 뽑히는 서술형 요구사항 → 2차 LLM 의미 판정 (§ _llm_semantic_match)
            status, matched_ids, confidence, sem_method = self._llm_semantic_match(text, evidences)
            if sem_method == "undecidable":
                llm_unavailable += 1
            report.matches.append(Match(
                requirementId=req_id, type=req_type, text=text, status=status,
                matchedEvidenceIds=matched_ids, confidence=confidence, method=sem_method,
                reason=_reason_for_llm_semantic(status, sem_method),
            ))

        if llm_unavailable:
            report.warnings.append({
                "code": "undecidable_requirements",
                "message": (
                    f"서술형 요구사항 {llm_unavailable}건을 자동 판정하지 못했습니다"
                    f"(LLM 미설정/호출 실패). 미충족이 아니라 '판정 불가'로 처리했습니다."
                ),
            })
        return report


def _reason_for_skills(
    evidenced: list[str], claimed_only: list[str], missing: list[str], status: str
) -> str:
    """판정 근거 문장(사실 서술). LLM 은 나중에 이 문장을 다듬기만 한다(§3.5).

    **'근거 있음'과 '주장만 있음'을 반드시 구분해 적는다.** status(met 여부)는 기재만
    돼 있어도 인정하지만, 문장에서까지 둘을 뭉개면 "왜 근거는 없는데 확인됐다는 거냐"는
    모순으로 읽힌다. met 이어도 claimed_only/missing 이 섞여 있을 수 있으므로(예: 5개 중
    4개만 충족돼도 met, §_MET_EVIDENCE_RATIO) 항상 세 그룹을 있는 그대로 나열한다.
    """

    if status == "not_met":
        return f"요구 기술({', '.join(missing)})의 보유 근거를 찾지 못했습니다."

    parts: list[str] = []
    if evidenced:
        parts.append(f"{', '.join(evidenced)} 는 프로젝트 근거로 확인됨")
    if claimed_only:
        parts.append(f"{', '.join(claimed_only)} 는 이력서에 기재된 보유 스킬로 인정(뒷받침 경험 근거는 없음)")
    if missing:
        parts.append(f"{', '.join(missing)} 는 언급 자체가 없음")
    return " / ".join(parts)


def _reason_for_llm_semantic(status: str, method: str) -> str:
    if method == "undecidable":
        return "기술명을 식별할 수 없는 서술형 요구사항이라 자동 판정하지 못했습니다(LLM 미설정/호출 실패)."
    if status == "met":
        return "의미상 관련된 경험 근거가 있습니다(LLM 판정)."
    return "관련 경험 근거를 찾지 못했습니다(LLM 판정)."


def _reason_for_domain_keyword(keyword: str, status: str, method: str) -> str:
    if method == "undecidable":
        return f"도메인 키워드 '{keyword}' 관련성을 판정할 수 없습니다(LLM 미설정 또는 호출 실패)."
    if status == "met" and method == "keyword":
        return f"도메인 키워드 '{keyword}'가 근거 문장에서 그대로 발견되었습니다."
    if status == "met" and method == "llm_semantic":
        return f"도메인 키워드 '{keyword}'와 의미상 관련된 근거 문장이 있습니다(LLM 판정)."
    return f"도메인 키워드 '{keyword}'와 관련된 근거를 찾지 못했습니다(포함 매칭·LLM 판정 모두 실패)."


def to_gap_payload(report: MatchReport) -> dict:
    """MatchReport → GapAnalysisResult 에 실을 dict 조각.

    requirementStatus / strengths / gaps / scoreBasis 를 **전부 계산으로** 만든다.
    analyze_gap 노드는 이 결과를 그대로 쓰고, LLM 은 reason 문장만 다듬는다.
    """

    requirement_status = [
        {
            "requirementId": m.requirementId,
            "type": m.type,
            "text": m.text,
            "status": m.status,
            "matchedEvidenceIds": m.matchedEvidenceIds,
            "reason": m.reason,
            "confidence": m.confidence,
        }
        for m in report.matches
    ]

    strengths = [
        {"requirementId": m.requirementId, "text": m.text, "matchedSkills": m.matchedSkills}
        for m in report.matches
        if m.status == "met"
    ]

    # gap = **확인된 부족**. uncertain(판정 불가)은 넣지 않는다.
    # "모르는 것"을 "없는 것"으로 세면 근거 없이 부족을 단정하게 되고, plan_roadmap 이
    # 그 위에 "경력 3년을 쌓으세요" 같은 무의미한 학습 계획을 세운다.
    # uncertain 은 check_sufficiency 가 추가 질문으로 돌려 사용자에게 직접 묻는다(§3.3).
    gaps = [
        {
            "requirementId": m.requirementId,
            "severity": _severity_of(m.type, m.status),
            "reason": m.reason,
            "evidenceMissing": not m.matchedEvidenceIds,
            "missingSkills": m.missingSkills,
        }
        for m in report.matches
        if m.status in ("not_met", "partially_met")
    ]

    return {
        "requirementStatus": requirement_status,
        "strengths": strengths,
        "gaps": gaps,
        "scoreBasis": _score_basis(report),
    }


def _weighted_score(matches: list[Match]) -> float | None:
    """가중 평균 충족 점수 0~1. 판정된 게 없으면 None(0.0 이 아니다)."""

    decided = [m for m in matches if m.status in _STATUS_SCORE]
    if not decided:
        return None
    total = sum(_TYPE_WEIGHT.get(m.type, 1.0) for m in decided)
    got = sum(_STATUS_SCORE[m.status] * _TYPE_WEIGHT.get(m.type, 1.0) for m in decided)
    return round(got / total, 2) if total else None


def _score_basis(report: MatchReport) -> dict:
    """카테고리별 가중 집계 (§3.5).

    계산 근거가 있는 항목만 채우고 나머지는 None 으로 둔다 — 억지로 숫자를 만들면 그게
    지어낸 점수다. roleRelevance/domainFit 은 공고에 seniority/domainKeywords 요구사항이
    있어 해당 매칭이 실제로 생겼을 때만 값을 갖는다(_weighted_score 가 매칭 없으면 None).
    """

    # 카테고리별 분류. domain_keyword/seniority 는 요구사항 kind 로 정확히 가른다.
    # 기술/서술형(kind == "text") 중 자격증·어학 키워드가 있으면 certLanguage 로 뺀다.
    domain_matches = [m for m in report.matches if m.kind == "domain_keyword"]
    seniority_matches = [m for m in report.matches if m.kind == "seniority"]
    cert_matches = [
        m for m in report.matches
        if m.kind == "text" and any(k in m.text.lower() for k in _CERT_KEYWORDS)
    ]
    tech_matches = [
        m for m in report.matches
        if m.kind == "text" and m not in cert_matches
    ]

    return {
        "techSkill": _weighted_score(tech_matches),
        "projectExperience": _evidence_backed_ratio(report.matches),
        "certLanguage": _weighted_score(cert_matches),
        "roleRelevance": _weighted_score(seniority_matches),  # 매칭 없으면 None
        "domainFit": _weighted_score(domain_matches),         # 매칭 없으면 None
    }


def overall_fit(score_basis: dict) -> tuple[float | None, str]:
    """카테고리별 점수(scoreBasis) → (종합 점수, 등급) (§3.5 확장, 2026-07-21).

    **계산된 카테고리만** 골라 가중 평균한다(None 은 '계산 근거 없음'이므로 분모에서 뺀다 —
    _score_basis 가 None 을 남기는 이유와 같은 원칙). 계산된 게 하나도 없으면 등급을
    단정하지 않고 (None, "판정불가") 로 정직하게 남긴다.

    등급: 상 ≥ 0.7 / 중 0.4~0.7 미만 / 하 < 0.4.
    """

    present = {
        k: v for k, v in score_basis.items()
        if v is not None and k in _CATEGORY_WEIGHT
    }
    if not present:
        return None, "판정불가"

    total_w = sum(_CATEGORY_WEIGHT[k] for k in present)
    score = round(sum(v * _CATEGORY_WEIGHT[k] for k, v in present.items()) / total_w, 2)

    if score >= _GRADE_HIGH:
        grade = "상"
    elif score >= _GRADE_MID:
        grade = "중"
    else:
        grade = "하"
    return score, grade


def _evidence_backed_ratio(matches: list[Match]) -> float | None:
    """판정된 요구사항 중 실제 근거(evidence)로 뒷받침된 비율."""

    decided = [m for m in matches if m.status in _STATUS_SCORE]
    if not decided:
        return None
    backed = sum(1 for m in decided if m.matchedEvidenceIds)
    return round(backed / len(decided), 2)


def get_gap_matcher() -> GapMatcher:
    """매처를 생성한다.

    `lru_cache` 를 걸지 않는 이유: 내부에 embedder 를 들고 있어서, 캐시하면 테스트나
    런타임에서 provider 를 바꿔도 낡은 embedder 를 계속 쓰게 된다. 생성 비용은 무시할 수준.
    """

    return GapMatcher()

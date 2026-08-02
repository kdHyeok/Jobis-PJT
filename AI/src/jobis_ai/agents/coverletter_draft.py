"""coverletter_draft — **두 번째 자기 루프 에이전트.** 쓰고, 점검하고, 스스로 고친다.

전에는 LLM 을 한 번 불러 3문단을 받아 그대로 내보냈다. 자소서 작성의 본질은 그게 아니다 —
쓰고 나서 "근거가 붙었나 / 공고 요건을 다뤘나 / 분량이 되나"를 확인해 고치는 일이 반복된다.
한 번 생성으로 끝나는 구조에는 그 반복이 일어날 자리가 없었다(품질을 스스로 올릴 수 없다).

역할 분담은 A단계의 구분을 그대로 따른다:

  · **도구(결정론)** — 근거 조회, 초안 기록, 점검(금지표현·근거 없는 스킬·분량·요건
    커버리지). 세는 일은 전부 여기서 한다. LLM 의 인상이 아니라 **값으로** 판정한다.
  · **에이전트(LLM)** — 무엇을 어떻게 쓸지, 점검 결과에서 무엇을 고칠지.
  · **근거의 출처** — 공고 쪽(요건·부족 역량)은 *과제*라 프롬프트에 싣고, 이력서 쪽은
    *근거*라 도구(`find_evidence`)만 준다. 없는 경험을 쓰는 길을 구조로 막는다.

사용자에게 나가는 초안 본문은 **검증을 통과한 문단으로 결정론 조립**한다(`_render_draft`).
LLM 이 본문을 reply 에 다시 옮겨 적게 하면 검증 전 문장이 그대로 사용자에게 갈 수 있고,
화면에 보이는 것과 저장된 것이 달라진다. LLM 은 마무리 안내 한두 문장만 쓴다.

두 절대 규칙(agent_develop §2.5)은 그대로다: ① 문항 답을 지어내지 않는다 ② 이력서에 없는
성과를 서술하지 않는다 — 이력서에 없는 자소서 성과는 사용자 이름으로 나가는 거짓말이다.
P5 GATE 도 그대로: 산출물은 항상 "초안"이고 사용자 검토 없이 완성본이 되지 않는다.

LLM 미설정(개발 모드)이면 facts 만으로 결정론 템플릿 초안(창작 0%). 호출 실패면 이번 턴에
도구가 이미 기록해 둔 초안을 살려 내보내고, 그것도 없으면 정직하게 실패를 알린다.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import agent_arg, ensure_profile, posting_identity
from jobis_ai.agents.agent_loop import ToolSpec, delegate_tool, run_agent_loop
from jobis_ai.skill_taxonomy import get_skill_taxonomy
from jobis_ai.structured import llm_unconfigured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

# 근거 사실 상한. 프롬프트가 아니라 **도구 응답에만** 실리므로(evidenceCount 만 프롬프트로 간다)
# 넉넉히 둔다 — 여기서 자르면 사용자가 강조해 달라고 한 경험이 애초에 사라진다.
_MAX_FACTS = 60
# 초안 → 점검 → 재작성 → 점검 → 답변. 자기비판을 한 바퀴 돌 수 있는 최소치다
# (기본값 3 이면 쓰고 점검하면 끝나 고칠 기회가 없다). 근거가 빈약해 다른 담당에게
# 물어보는 경우(ask_agent)를 위해 한 칸 더 둔다.
_MAX_STEPS = 7
_MIN_SENTENCES = 3
_MAX_SENTENCES = 5
# 프롬프트에 싣는 과제(공고 쪽) 상한 — 묶음 공고에서 요건이 수십 건 나오는 것을 막는다.
_MAX_REQUIREMENTS = 8
_MAX_GAPS = 5


class _DraftRead(BaseModel):
    """초안 3문단. 검증(`_verify_draft`)과 템플릿 폴백이 함께 쓰는 자료형.

    **각 필드의 description 을 유지한다.** 구조화 출력에서 설명이 없으면 모델이 문단 칸을
    '제목'처럼 취급해 한 줄만 채운다(career_chat 에서 실측: 설명 없음 43자 → 설명 있음 1400자대).
    """

    motivation: str = Field(default="", description=(
        "지원 동기 문단. [requirements] 의 요구 역량과 [facts] 의 접점만으로 3~5문장, 한국어 존댓말. "
        "한 문단의 완성된 글로 쓴다 — 제목이나 한 줄 요약이 아니다."))
    strengthsParagraph: str = Field(default="", description=(
        "강점 문단. [facts] 에 있는 사실만 근거로 3~5문장. 프로젝트·수치는 facts 에 적힌 그대로 인용하고 "
        "없는 경험을 만들지 않는다."))
    improvementParagraph: str = Field(default="", description=(
        "보완 계획 문단. [gaps] 에 명시된 부족 역량만 다뤄 3~5문장. 부족을 숨기지 말고 "
        "무엇을 어떻게 메울지 구체적으로 쓴다."))


# 문단 필드 ↔ 사람이 쓰는 이름. 도구 인자 파싱과 화면 조립이 같은 표를 쓴다.
_FIELD_LABEL: tuple[tuple[str, str], ...] = (
    ("motivation", "지원 동기"),
    ("strengthsParagraph", "강점"),
    ("improvementParagraph", "보완 계획"),
)
_LABEL_FIELD = {
    "동기": "motivation", "지원동기": "motivation",
    "강점": "strengthsParagraph", "강점문단": "strengthsParagraph",
    "보완": "improvementParagraph", "보완계획": "improvementParagraph",
}
# 문단 라벨 줄. 콜론을 **요구**한다 — 없으면 '보완이 필요합니다…' 같은 본문 문장을 라벨로 오인한다.
_LABEL_LINE = re.compile(
    r"^\s*[\[\-\*#>]*\s*(동기|지원\s*동기|강점\s*문단|강점|보완\s*계획|보완)\s*\]?\s*[:：]\s*"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?다])\s+")


# --- P2 MAP [룰] — 근거 사실 목록 조립 -----------------------------------------
def _paren(*parts: Any) -> str:
    """비어 있지 않은 조각만 괄호로 묶는다. 없으면 빈 문자열."""

    inner = ", ".join(str(p).strip() for p in parts if str(p or "").strip())
    return f" ({inner})" if inner else ""


def _collect_facts(profile: dict) -> list[str]:
    """프로필에서 초안 재료가 될 사실 문장을 모은다. 여기 없는 것은 초안에 못 들어간다.

    **넓게 모은다 — 좁히는 것은 LLM 의 일이다.** "트러블슈팅 위주로 다시 써줘" 같은 요청은
    이력서에 그 단어가 없어도 성립한다(장애 대응·성능 개선·디버깅으로 적혀 있다). 어느 문장이
    거기 해당하는지는 문자 대조가 아니라 **읽어야** 안다. 재료를 미리 잘라 두면 LLM 이 아무리
    잘 읽어도 못 찾는다 — 검색을 고쳐도 없는 것은 못 찾기 때문이다.

    그래서 프로필의 모든 섹션을 싣고, 특히 `evidenceMap`(이력서 원문 문장 그대로)을 포함한다 —
    구조화 항목이 요약하며 지운 표현이 거기에 남아 있다.
    """

    facts: list[str] = []
    for p in profile.get("projects", []):
        base = f"프로젝트 '{p.get('title', '')}'"
        base += _paren(p.get("projectType"), p.get("period"), p.get("teamSize"))
        if p.get("role"):
            base += f" — {p['role']} 역할 수행"
        if p.get("techStack"):
            base += f" — 기술: {', '.join(p['techStack'])}"
        if p.get("summary"):
            base += f" — {p['summary']}"
        facts.append(base)
        facts.extend(f"'{p.get('title', '')}' 성과: {a}" for a in p.get("achievements", []))
    for e in profile.get("experiences", []):
        text = f"{e.get('company', '')} {e.get('role', '')} 경력"
        text += _paren(e.get("employmentType"), e.get("period"))
        if e.get("summary"):
            text += f" — {e['summary']}"
        facts.append(text.strip())
    # 이력서 원문 문장. 표현이 살아 있어 의미 매칭의 핵심 재료다(read_nodes 가 "원문 그대로,
    # 요약·윤색 금지"로 뽑는다). 구조화 항목과 내용이 겹치더라도 말이 다르므로 둘 다 싣는다.
    facts.extend(
        str(ev.get("text") or "").strip()
        for ev in profile.get("evidenceMap", []) if str(ev.get("text") or "").strip()
    )
    facts.extend(
        f"부트캠프 {b.get('name', '')}"
        + _paren(b.get("organization"), b.get("track"), b.get("period"))
        + (f" — {b['summary']}" if b.get("summary") else "")
        for b in profile.get("bootcamp", []) if b.get("name")
    )
    facts.extend(
        f"수상: {a.get('title', '')}" + _paren(a.get("organization"), a.get("date"))
        + (f" — {a['description']}" if a.get("description") else "")
        for a in profile.get("awards", []) if a.get("title")
    )
    facts.extend(
        f"자격증: {c.get('name', '')}" + _paren(c.get("status"), c.get("acquiredDate"))
        for c in profile.get("certifications", []) if c.get("name")
    )
    facts.extend(
        f"어학: {lang.get('name', '')}"
        + _paren(lang.get("testName"), lang.get("score"), lang.get("proficiency"))
        for lang in profile.get("languages", []) if lang.get("name")
    )
    facts.extend(
        f"학력: {ed.get('school', '')} {ed.get('major', '')}".strip()
        + _paren(ed.get("degree"), ed.get("status"), ed.get("period"))
        for ed in profile.get("education", []) if ed.get("school") or ed.get("major")
    )
    return list(dict.fromkeys(f.strip() for f in facts if f.strip()))[:_MAX_FACTS]


def _allowed_skills(profile: dict) -> set[str]:
    """초안이 '보유'라고 말해도 되는 스킬 — 프로필에 실재하는 것만."""

    skills = {s.get("name", "").lower() for s in profile.get("skills", [])}
    for p in profile.get("projects", []):
        skills.update(t.lower() for t in p.get("techStack", []))
    skills.update(k.lower() for k in (profile.get("skillEvidence") or {}))
    return {s for s in skills if s}


def _gap_topics(gaps: list[dict]) -> list[str]:
    return [
        ", ".join(g.get("missingSkills") or []) or str(g.get("requirementId") or "")
        for g in gaps
    ]


# ---------------------------------------------------------------------------
# 상태 — 여러 턴에 걸쳐 세션 자산 coverletter 로 보존된다
# ---------------------------------------------------------------------------
def _draft_state(session: dict[str, Any], profile: dict, analysis: dict) -> dict[str, Any]:
    """이전 턴 초안을 이어받는다 — "강점 문단만 다시 써줘" 가 성립하는 지점.

    밑줄 키는 도구가 읽는 이번 턴 재료다(도구는 session 을 모른다). 저장은 하지 않는다.
    """

    prior = dict(session.get("coverletter") or {})
    requirements = [
        str(r.get("text") or "") for r in (analysis.get("requirements") or [])
        if str(r.get("text") or "").strip()
    ][:_MAX_REQUIREMENTS]
    gaps = list(analysis.get("gaps") or [])[:_MAX_GAPS]
    return {
        "motivation": str(prior.get("motivation") or ""),
        "strengthsParagraph": str(prior.get("strengthsParagraph") or ""),
        "improvementParagraph": str(prior.get("improvementParagraph") or ""),
        "revisions": int(prior.get("revisions") or 0),
        "lastCheck": {},
        # 위임 도구(ask_agent)가 다른 담당을 부를 때 쓴다. 도구는 session 을 모르므로 실어 둔다.
        "_session": session,
        "_evidence": _collect_facts(profile),
        "_allowed": _allowed_skills(profile),
        "_requirements": requirements,
        "_gapTopics": [t for t in _gap_topics(gaps) if t],
    }


def _paragraphs(state: dict[str, Any]) -> dict[str, str]:
    return {field: str(state.get(field) or "") for field, _ in _FIELD_LABEL}


def _has_draft(state: dict[str, Any]) -> bool:
    return any(_paragraphs(state).values())


# ---------------------------------------------------------------------------
# 도구 — 전부 결정론. 사실만 돌려주고 판단·권유를 담지 않는다.
# ---------------------------------------------------------------------------
def _tool_find_evidence(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """이력서에서 확인된 사실만 준다. 없는 것을 만들어 주지는 않는다.

    **인자는 정렬 힌트일 뿐 필터가 아니다.** 문자열 일치로 0건이 나와도 "없습니다"로 끝내지
    않고 전체를 함께 돌려준다 — 이력서는 요청과 다른 말로 적혀 있기 때문이다("트러블슈팅"이
    "장애 대응"으로). 어느 문장이 요청에 해당하는지 판단하는 것은 substring 이 아니라 LLM 의
    일이고, 판단하려면 전문을 봐야 한다. 예전에는 "인자를 비우면 전부 볼 수 있습니다"라고
    안내만 했는데, `_MAX_STEPS` 가 7 이라 그 한 스텝이 재작성 기회 하나와 맞바꿔졌다.
    """

    evidence: list[str] = state.get("_evidence") or []
    if not evidence:
        return "이력서에서 확인된 사실이 없습니다.", {}

    everything = f"확인된 사실 전체 {len(evidence)}건: " + " / ".join(evidence)
    terms = [t.strip().lower() for t in (arg or "").split(",") if t.strip()]
    if not terms:
        return everything, {}

    hits = [f for f in evidence if any(t in f.lower() for t in terms)]
    if not hits:
        return (f"'{arg}' 를 문자 그대로 포함하는 사실은 없습니다. 이력서가 다른 표현으로 적었을 수 "
                f"있으니(예: '트러블슈팅' → '장애 대응'·'성능 개선') 아래 전문을 직접 읽고 해당하는 "
                f"것을 고르세요. 정말 없으면 지어내지 말고 없다고 알리세요. " + everything), {}
    if len(hits) < len(evidence):
        return (f"'{arg}' 를 문자 그대로 포함하는 사실 {len(hits)}건: " + " / ".join(hits)
                + f" | 이 목록은 문자 일치일 뿐이라 표현이 다른 관련 경험이 빠져 있을 수 있습니다"
                  f" (전체 {len(evidence)}건 — 인자를 비우면 전부)."), {}
    return everything, {}


def _parse_sections(text: str) -> dict[str, str]:
    """`동기: … / 강점: … / 보완: …` 형식을 문단 dict 로. 라벨 없는 줄은 앞 문단에 이어 붙인다."""

    sections: dict[str, list[str]] = {}
    current = ""
    for line in (text or "").splitlines():
        match = _LABEL_LINE.match(line)
        if match:
            current = _LABEL_FIELD[re.sub(r"\s+", "", match.group(1))]
            sections.setdefault(current, []).append(line[match.end():].strip())
        elif current and line.strip():
            sections[current].append(line.strip())
    return {k: " ".join(v).strip() for k, v in sections.items() if " ".join(v).strip()}


def _tool_save_draft(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """초안 문단을 기록한다. 적어 보낸 문단만 갱신되고 나머지는 유지된다(부분 수정)."""

    sections = _parse_sections(arg)
    if not sections:
        return ("문단 라벨을 찾지 못해 아무것도 저장하지 않았습니다. "
                "'동기:', '강점:', '보완:' 으로 시작하는 줄에 각 문단을 적어 다시 부르세요."), {}

    label_of = dict(_FIELD_LABEL)
    changed = [label_of[f] for f in sections]
    state.update(sections)
    state["revisions"] = int(state.get("revisions") or 0) + 1
    sizes = ", ".join(
        f"{label} {len(str(state.get(field) or ''))}자" for field, label in _FIELD_LABEL
    )
    return (f"초안을 기록했습니다(작성 {state['revisions']}회). "
            f"이번에 바꾼 문단: {', '.join(changed)} / 현재 분량: {sizes}"), {}


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(str(text or "").strip()) if s.strip()]


def _requirement_coverage(state: dict[str, Any], full_text: str) -> tuple[int, int, list[str]]:
    """공고 요건 중 초안이 다룬 비율. (다룬 수, 측정 가능한 수, 미언급 요건들).

    측정 기준은 **기술 용어 대조**다(taxonomy). 기술 용어가 없는 서술형 요건은 기계적으로
    대조할 수 없으므로 분모에서 뺀다 — 셀 수 없는 것을 센 척하지 않는다.
    """

    taxonomy = get_skill_taxonomy()
    lowered = full_text.lower()
    covered, uncovered = 0, []
    for requirement in state.get("_requirements") or []:
        terms = taxonomy.find_in_text(requirement)
        if not terms:
            continue
        if any(t.lower() in lowered for t in terms):
            covered += 1
        else:
            uncovered.append(requirement)
    return covered, covered + len(uncovered), uncovered


def _check_report(state: dict[str, Any],
                  paragraphs: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    """초안을 세어 (측정값, 지적 목록) 을 낸다. **순수 함수** — 루프의 점검 도구와
    최종 산출물 측정이 같은 자를 쓴다(자가 다르면 저장된 값이 화면·로그와 어긋난다).
    """

    label_of = dict(_FIELD_LABEL)
    lines: list[str] = []
    report: dict[str, Any] = {}

    empty = [label_of[f] for f, text in paragraphs.items() if not text.strip()]
    if empty:
        lines.append(f"빈 문단: {', '.join(empty)}")
    report["emptyParagraphs"] = empty

    full_text = " ".join(paragraphs.values())
    forbidden = [e for e in FORBIDDEN_EXPRESSIONS if e in full_text]
    if forbidden:
        lines.append(f"금지표현(단정·과장) 사용: {', '.join(forbidden)} — 빼고 다시 쓸 것")
    report["forbidden"] = forbidden

    # 강점 문단은 '보유 역량 주장'이므로 근거 없는 스킬이 있으면 최종 검증이 그 문장을 지운다.
    # 지워지기 전에 알려 준다 — 고칠 기회를 주는 것이 문장을 잃는 것보다 낫다.
    taxonomy = get_skill_taxonomy()
    allowed: set[str] = state.get("_allowed") or set()
    ungrounded = sorted({
        s for s in taxonomy.find_in_text(paragraphs["strengthsParagraph"])
        if s.lower() not in allowed
    })
    if ungrounded:
        lines.append(f"강점 문단에 이력서 근거가 없는 기술 언급: {', '.join(ungrounded)} "
                     "— 그대로 두면 해당 문장이 제거됨")
    report["ungroundedSkills"] = ungrounded

    counts = {f: len(_sentences(text)) for f, text in paragraphs.items()}
    off_length = [f"{label_of[f]} {n}문장" for f, n in counts.items()
                  if paragraphs[f].strip() and not _MIN_SENTENCES <= n <= _MAX_SENTENCES]
    if off_length:
        lines.append(f"분량 기준({_MIN_SENTENCES}~{_MAX_SENTENCES}문장) 밖: {', '.join(off_length)}")
    report["sentenceCounts"] = counts

    covered, measurable, uncovered = _requirement_coverage(state, full_text)
    if uncovered:
        lines.append(f"초안이 다루지 않은 공고 요건: {'; '.join(u[:40] for u in uncovered[:3])}")
    report["requirementCoverage"] = {"covered": covered, "measurable": measurable,
                                     "uncovered": uncovered}

    improvement = paragraphs["improvementParagraph"].lower()
    missing_gaps = [t for t in (state.get("_gapTopics") or [])
                    if not any(term.strip().lower() in improvement
                               for term in t.split(",") if term.strip())]
    if missing_gaps:
        lines.append(f"보완 계획에서 다루지 않은 부족 역량: {', '.join(missing_gaps[:3])}")
    report["uncoveredGaps"] = missing_gaps

    return report, lines


def _tool_check_draft(state: dict[str, Any], arg: str) -> tuple[str, dict]:
    """기록된 초안을 결정론 점검한다 — **자기비판의 재료.**

    LLM 의 인상이 아니라 세는 것으로 판정한다: 빈 문단, 금지표현, 근거 없는 스킬 언급,
    문단별 문장 수, 공고 요건 커버리지, 부족 역량 언급 여부.
    """

    paragraphs = _paragraphs(state)
    if not any(paragraphs.values()):
        return "점검할 초안이 없습니다. save_draft 로 먼저 기록하세요.", {}

    report, lines = _check_report(state, paragraphs)
    state["lastCheck"] = report
    coverage = report["requirementCoverage"]
    # 커버리지는 지적이 아니라 측정값이므로 항상 앞에 붙인다(고쳤을 때 올라가는 것을 보라고).
    summary = (f"공고 요건 커버리지 {coverage['covered']}/{coverage['measurable']}"
               if coverage["measurable"]
               else "공고 요건 커버리지: 기계적으로 대조할 수 있는 요건 없음")
    if not lines:
        return summary + " | 지적 사항 없음(빈 문단·금지표현·근거 없는 기술·분량 전부 통과).", {}
    return summary + " | " + " | ".join(lines), {}


_TOOLS = {
    t.name: t for t in (
        ToolSpec("find_evidence",
                 "이력서에서 확인된 사실을 가져온다. 초안에 쓸 수 있는 유일한 근거 출처다.",
                 _tool_find_evidence,
                 "찾을 주제·기술 이름(쉼표로 여러 개). 비우면 확인된 사실 전체."),
        ToolSpec("save_draft",
                 "초안 문단을 기록한다. 적어 보낸 문단만 갱신되고 나머지는 그대로 유지된다.",
                 _tool_save_draft,
                 ("줄마다 '동기:', '강점:', '보완:' 으로 시작해 문단 본문을 적는다. "
                  "각 문단은 3~5문장의 완결된 글이다 — 제목·한 줄 요약이 아니다. "
                  "예) 동기: (3~5문장)\\n강점: (3~5문장)\\n보완: (3~5문장)")),
        # 에이전트 간 통신 — 근거가 빈약한 이유는 이력서 진단이 이미 세고 있다.
        # 같은 계산을 여기 다시 구현하는 대신 물어본다(읽기 전용).
        delegate_tool(("resume_diagnosis",)),
        ToolSpec("check_draft",
                 ("기록된 초안을 점검한다(빈 문단·금지표현·근거 없는 기술 언급·문단 분량·"
                  "공고 요건 커버리지·부족 역량 언급)."),
                 _tool_check_draft, "비워 둔다 — 초안 전체를 점검한다."),
    )
}

_GOAL_SYSTEM = """너는 자기소개서 초안 작성기다. 초안을 쓰고, 도구로 점검하고, 지적된 곳을 스스로 고친다.

절대 규칙 — 어기면 지원자 이름으로 나가는 거짓말이 된다:
1. find_evidence 로 확인한 사실만 쓴다. 확인되지 않은 경험·성과·수치·기술을 만들지 않는다. 과장도 금지.
2. 합격 가능성을 단정하지 않는다.

지원 대상: facts.company / facts.role 이 이 자소서를 내는 회사·직무다(비어 있으면 언급하지
않는다 — 회사명을 추측해 쓰지 않는다). 동기 문단은 이 회사·직무를 향해 쓴다.

진행 순서:
- 근거를 모르면 먼저 find_evidence 로 확인한다(인자를 비우면 전체).
- save_draft 로 세 문단을 쓴다. 각 문단은 3~5문장의 완결된 글이다.
  · 동기: 공고 요구 역량과 확인된 사실의 접점만으로
  · 강점: 확인된 사실만 근거로. 프로젝트·수치는 확인된 그대로 인용
  · 보완: 부족 역량만 다룬다. 숨기지 말고 무엇을 어떻게 메울지
- 쓴 뒤에는 check_draft 로 점검한다. 지적이 있으면 **그 문단만 고쳐** save_draft 를 다시 부른다.
- 사용자가 특정 문단 수정을 요청했으면 그 문단만 고치고 나머지는 두 번 쓰지 않는다.
- **사용자가 어떤 주제·기술·경험을 강조해 달라고 하면**(예: "트러블슈팅 위주로", "React 경험
  살려서 다시", "협업 얘기를 더") 그 말을 이력서에서 문자 그대로 찾지 말고, find_evidence 를
  **인자 없이** 불러 확인된 사실 전문을 읽은 뒤 어느 경험이 그 요청에 해당하는지 네가 판단해
  고른다. 이력서는 요청과 다른 말로 적혀 있다 — "트러블슈팅"은 장애 대응·성능 개선·디버깅으로,
  "협업"은 팀 규모·역할·리뷰로 적혀 있을 수 있다. 요청이 모호하면(예: "좀 더 임팩트 있게")
  가장 그럴듯한 뜻으로 해석해 진행하고, 무엇으로 해석했는지 마무리 안내에 적는다.
  요청에 맞는 근거가 **정말** 없으면 지어내지 말고, 그 사실을 마무리 안내에서 알린다
  ("이력서에 해당 경험이 없어 반영하지 못했습니다").
- 쓸 근거가 빈약하면(확인된 사실이 두세 건뿐이면) ask_agent 로 resume_diagnosis 에게
  이력서의 어디가 비었는지 물어본다. 그 답은 참고용이다 — 초안에 사실로 옮겨 쓰지 않고,
  마무리 안내에서 무엇을 보강하면 좋을지 알려 주는 데 쓴다.

마지막 reply 규칙:
- **초안 본문을 옮겨 적지 않는다.** 본문은 화면이 따로 보여 준다.
- 이번 턴에 무엇을 쓰고 점검에서 무엇을 고쳤는지 2~3문장으로 알리고, 제출 전 직접 검토를 요청한다."""


# --- P4 VERIFY [룰] — 사용자에게 나가기 전 마지막 방어선 -------------------------
def _verify_draft(draft: _DraftRead, allowed: set[str]) -> tuple[_DraftRead, list[dict]]:
    """금지표현 경고 + 강점 문단의 근거 없는 스킬 언급 문장 제거.

    루프의 `check_draft` 가 같은 것을 먼저 알려 주지만, 여기서 한 번 더 본다 — 점검을
    건너뛰었거나 고치지 않은 채 끝난 경우에도 **근거 없는 주장은 사용자에게 가지 않는다.**
    """

    warnings: list[dict] = []

    full_text = " ".join([draft.motivation, draft.strengthsParagraph, draft.improvementParagraph])
    for bad in FORBIDDEN_EXPRESSIONS:
        if bad in full_text:
            warnings.append({
                "code": "forbidden_expression",
                "message": f"coverletter_draft: 단정 표현 '{bad}' 발견 — 초안 검토 시 수정이 필요합니다.",
            })

    # 강점 문단은 "보유 역량 주장"이므로 프로필에 없는 스킬이 나오면 그 문장을 제거한다.
    taxonomy = get_skill_taxonomy()
    kept: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(draft.strengthsParagraph):
        mentioned = {s.lower() for s in taxonomy.find_in_text(sentence)}
        ungrounded = mentioned - allowed
        if ungrounded:
            warnings.append({
                "code": "ungrounded_skill_removed",
                "message": (
                    "coverletter_draft: 이력서에 근거가 없는 기술 언급 문장을 제거했습니다 — "
                    f"{', '.join(sorted(ungrounded))}"
                ),
            })
            continue
        kept.append(sentence)

    verified = draft.model_copy(update={"strengthsParagraph": " ".join(kept).strip()})
    return verified, warnings


# --- 표현 계층 — 검증 통과본으로만 조립한다 --------------------------------------
def _render_draft(verified: _DraftRead, note: str) -> str:
    """사용자에게 보이는 초안. **검증을 통과한 문단만** 싣는다.

    LLM 에게 본문을 다시 쓰게 하면 화면에 나가는 글과 저장·검증된 글이 갈라진다
    (제거된 문장이 화면에는 남는 식). 그래서 본문 조립은 결정론이 맡고, LLM 은 이번 턴에
    무엇을 고쳤는지 알리는 note 만 쓴다. **검토 게이트 문장은 note 와 무관하게 항상 붙는다**
    — P5 GATE 는 LLM 이 잊을 수 있는 부탁이 아니라 규칙이다.
    """

    parts: list[str] = []
    for field, label in _FIELD_LABEL:
        text = str(getattr(verified, field) or "").strip()
        if text:
            parts.append(f"[{label}]\n{text}")
    tail = "\n".join(t for t in (note.strip(), _GATE_LINE) if t)
    return ("자소서 초안입니다. 이력서에서 확인된 사실만 사용했습니다.\n\n"
            + "\n\n".join(parts) + "\n\n" + tail)


_GATE_LINE = ("제출 전 직접 검토·수정해 주세요. 수정하고 싶은 문단을 말씀해 주시면 "
              "그 문단만 다시 다듬어 드릴게요.")


def _template_draft(facts: list[str], requirements: list[str], gap_topics: list[str]) -> _DraftRead:
    """LLM 없는 개발 모드 폴백 — facts 문장을 그대로 이어 붙인다(창작 없음)."""

    return _DraftRead(
        motivation=(
            "채용 공고의 요구 역량(" + "; ".join(requirements[:3]) + ")과 맞닿은 경험을 쌓아 왔기에 지원합니다."
            if requirements else "해당 직무와 맞닿은 경험을 쌓아 왔기에 지원합니다."
        ),
        strengthsParagraph=" ".join(f"{f}." if not f.endswith(".") else f for f in facts[:5]),
        improvementParagraph=(
            "다만 " + "; ".join(t for t in gap_topics[:3] if t)
            + " 역량은 아직 부족하여, 학습 계획을 세워 보완하고 있습니다."
            if any(gap_topics) else ""
        ),
    )


def _payload(state: dict[str, Any], verified: _DraftRead,
             check: dict[str, Any]) -> dict[str, Any]:
    """저장·화면용 산출물. `check` 는 **내보내는 초안을 다시 잰 값**이다.

    루프 도중의 마지막 점검값을 그대로 실으면 어긋난다 — 그 점검 뒤에 재작성이 일어나고
    검증이 문장을 지우기 때문이다(실측: 보완 문단을 3문장으로 고쳐 놓고 저장분에는 2문장으로
    남았다). 산출물에 붙는 수치는 산출물을 잰 값이어야 한다.
    """

    return {
        "status": "draft_pending_review",   # P5 GATE — 사용자 검토 전에는 항상 초안
        "motivation": verified.motivation,
        "strengthsParagraph": verified.strengthsParagraph,
        "improvementParagraph": verified.improvementParagraph,
        "factsUsed": list(state.get("_evidence") or []),
        "revisions": int(state.get("revisions") or 0),
        "check": check,
    }


def _finish(state: dict[str, Any], note: str, warnings: list[dict],
            extra_data: dict[str, Any] | None = None) -> AgentResult:
    """상태의 문단 → 검증 → 화면 문장 + 저장 payload. 성공·폴백이 같은 길을 쓴다."""

    draft = _DraftRead(**_paragraphs(state))
    verified, verify_warnings = _verify_draft(draft, state.get("_allowed") or set())
    warnings = warnings + verify_warnings
    if verify_warnings:
        note = (note + " (검증 단계에서 일부 문장이 조정되었습니다 — warnings 참고)").strip()

    check, issues = _check_report(state, _paragraphs(verified.model_dump()))
    if issues:
        # 점검을 건너뛰었거나 지적을 안 고친 채 끝난 경우 — 고칠 기회는 지났지만 **묻히지는
        # 않는다.** 실측에서 2턴째 루프가 check_draft 없이 바로 답을 낸 적이 있다.
        warnings.append({
            "code": "coverletter_check_unresolved",
            "message": "coverletter_draft: 내보낸 초안에 남은 지적 — " + " | ".join(issues),
        })
    payload = _payload(state, verified, check)
    return AgentResult(
        reply=_render_draft(verified, note),
        data={**payload, **(extra_data or {})},
        warnings=warnings,
        # 다음 턴이 이어받아 "강점 문단만 다시" 같은 부분 수정을 할 수 있다.
        sessionUpdates={"coverletter": payload},
    )


# --- 진입점 ----------------------------------------------------------------------
def run(session: dict[str, Any]) -> AgentResult:
    """자기 루프로 초안을 쓰고 스스로 고친다. LLM 불가면 결정론 폴백."""

    analysis: dict = session.get("analysis") or {}
    profile, warnings = ensure_profile(session)
    state = _draft_state(session, profile, analysis)

    if not state["_evidence"]:
        return AgentResult(
            reply=(
                "이력서에서 자소서 재료가 될 경험·프로젝트를 찾지 못했습니다. "
                "지어내서 쓸 수는 없어요 — 이력서에 경험을 보강한 뒤 다시 요청해 주세요."
            ),
            warnings=warnings + [{
                "code": "no_coverletter_facts",
                "message": "coverletter_draft: 근거 사실이 없어 초안을 생성하지 않았습니다(창작 금지).",
            }],
        )

    company, role = posting_identity(session)
    facts = {
        "userMessage": str(session.get("last_message") or ""),
        # **어느 회사·어느 직무에 내는 자소서인가.** 이게 없어서 초안이 지원 대상을 모른
        # 채 쓰였다 — 화이트보드(posting_summary)에 있는 것을 읽지 않았을 뿐이다.
        "company": company,
        "role": role,
        # 공고 쪽은 '과제'라 여기에 싣는다. 이력서 쪽(근거)은 find_evidence 만 준다.
        "requirements": state["_requirements"],
        "gaps": state["_gapTopics"],
        "evidenceCount": len(state["_evidence"]),
        "hasPriorDraft": _has_draft(state),
        "revisions": state["revisions"],
        # 이전 턴 초안 — 부분 수정 요청("강점만 다시")을 처리하려면 지금 글을 알아야 한다.
        "currentDraft": {label: state[field] for field, label in _FIELD_LABEL} if _has_draft(state) else {},
        "focusRequested": agent_arg(session, "coverletter_draft", "focus"),
    }
    outcome = run_agent_loop(
        goal_system=_GOAL_SYSTEM, facts=facts, tools=_TOOLS, state=state,
        node="coverletter_draft", max_steps=_MAX_STEPS,
        session_id=str(session.get("_sessionId") or ""),
    )
    warnings.extend(outcome.warnings)

    if _has_draft(state):
        # 루프가 마무리 문장을 못 만들었어도 **기록된 초안은 살린다.** 본문은 어차피 검증을
        # 통과한 문단으로 조립하고 검토 게이트 문장도 결정론이라, 잃을 것은 안내 한 줄뿐이다.
        if not outcome.reply.strip():
            warnings.append({
                "code": "coverletter_note_missing",
                "message": "coverletter_draft: 마무리 안내 문장 없이 초안만 내보냈습니다.",
            })
        return _finish(state, outcome.reply.strip(), warnings, {"loopSteps": outcome.steps})

    # 초안이 아예 없다 — 개발 모드(LLM 미설정)면 창작 없는 템플릿, 진짜 실패면 정직하게 알린다.
    if llm_unconfigured(outcome.warnings):
        state.update(_template_draft(
            state["_evidence"], state["_requirements"], state["_gapTopics"]).model_dump())
        return _finish(state, "확인된 사실만 이어 붙인 개발 모드 초안입니다.", warnings)

    return AgentResult(
        reply="자소서 초안 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        warnings=warnings + [{
            "code": "coverletter_no_draft",
            "message": "coverletter_draft: 루프가 초안을 기록하지 못했습니다.",
        }],
    )

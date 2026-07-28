"""프로필 결측 필드 보완 (profile_completeness) — **LLM 을 호출하지 않는다.**

`build_user_profile` 직후에 붙는 별도 단계. `sufficiency_rules`(§3.3)와 다른 질문에 답한다:

    ✅ "docx 에서 못 뽑은 항목이 있는가?" (프로필 데이터 완성도)
    ❌ "이 사람을 갭 분석하기에 정보가 충분한가?" (sufficiency_rules 의 몫)

둘을 섞으면 안 된다. 이 모듈이 찾는 결측은 **분석을 막지 않는다(비블로킹)** — degree/
employmentType 같은 값은 gap_matcher 가 실제로 참조하지 않으므로, 이것 때문에 analyze_gap
을 막을 이유가 없다. 결과는 `followUpQuestions` 와 별도로 `profileCompletionQuestions` 에
실려 최종 응답에만 곁들여진다.

대상은 **enum 성격 필드 4개**로 좁힌다: education.degree/status, experiences.employmentType,
projects.projectType. 이 넷은 애초에 "사용자가 목록에서 고르면 되는" 값이라 텍스트 추론에
맡기기보다 되묻는 편이 정확하다. school/company/summary 같은 자유서술 필드는 여기서 다루지
않는다(LLM 추출 대상). skills.level 도 제외한다 — 룰로 찾은 스킬은 의도적으로 level 을
비워 두는 설계(§3.2-③)라서, 매번 물으면 스킬 개수만큼 질문이 쏟아진다.

엔트리 자체가 0건이면 묻지 않는다 — "없다"와 "있는데 못 뽑았다"는 다르다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 항목 종류 → 대상 필드 → (질문 문구, 선택지)
_FIELD_SPECS: dict[str, dict[str, tuple[str, list[str]]]] = {
    "education": {
        "degree": ("최종 학력을 선택해주세요.", ["고졸", "전문학사", "학사", "석사", "박사"]),
        "status": ("재학 상태를 선택해주세요.", ["졸업", "재학", "휴학", "중퇴", "수료"]),
    },
    "experiences": {
        "employmentType": ("고용 형태를 선택해주세요.", ["정규직", "계약직", "인턴", "파견"]),
    },
    "projects": {
        "projectType": (
            "프로젝트 유형을 선택해주세요.",
            ["팀 프로젝트", "개인 프로젝트"],
        ),
    },
}

# 질문 문구에 항목을 특정해 붙일 라벨 (entry.title/company/school 중 있는 것 우선 사용).
_LABEL_FIELDS: dict[str, tuple[str, ...]] = {
    "education": ("school",),
    "experiences": ("company",),
    "projects": ("title",),
}

# 한 번에 던질 질문 수 상한 (sufficiency_rules 와 동일한 취지 — 너무 많이 물으면 이탈한다).
_MAX_QUESTIONS = 10


@dataclass(frozen=True)
class MissingField:
    entryType: str      # "education" | "experiences" | "projects"
    entryId: str        # 해당 엔트리의 id (edu-1 등)
    field: str           # 결측 필드명 (degree/status/employmentType/projectType)
    label: str           # 질문에 끼워 넣을 항목 이름 (학교명/회사명/프로젝트명)


def find_missing_enum_fields(profile: dict) -> list[MissingField]:
    """education/experiences/projects 를 훑어 enum 필드가 빈 엔트리를 찾는다.

    엔트리 리스트 자체가 비어 있으면(해당 경험이 아예 없음) 건드리지 않는다 —
    무엇을 물을지는 '엔트리가 있는데 필드가 빔' 인 경우로 한정한다.
    """

    missing: list[MissingField] = []
    for entry_type, field_specs in _FIELD_SPECS.items():
        entries = profile.get(entry_type) or []
        label_keys = _LABEL_FIELDS.get(entry_type, ())
        for entry in entries:
            label = next((str(entry.get(k, "")) for k in label_keys if entry.get(k)), "")
            for field_name in field_specs:
                if not str(entry.get(field_name, "")).strip():
                    missing.append(MissingField(
                        entryType=entry_type,
                        entryId=str(entry.get("id", "")),
                        field=field_name,
                        label=label,
                    ))
    return missing


def build_completion_questions(missing: list[MissingField]) -> list[dict]:
    """결측 필드 → 선택형 질문 목록.

    반환: [{questionId, text, answerType: "select", options, entryType, entryId, field}]
    """

    questions: list[dict] = []
    for m in missing[:_MAX_QUESTIONS]:
        text, options = _FIELD_SPECS[m.entryType][m.field]
        if m.label:
            text = f"'{m.label}' — {text}"
        questions.append({
            "questionId": f"pc-{len(questions) + 1}",
            "text": text,
            "answerType": "select",
            "options": options,
            "entryType": m.entryType,
            "entryId": m.entryId,
            "field": m.field,
        })
    return questions

from __future__ import annotations

from dataclasses import dataclass

from jobis_ai.career_pipeline.contracts.normalization import CapabilityKind


@dataclass(frozen=True, slots=True)
class ChapterDescriptor:
    key: str
    title: str
    reason: str


_CHAPTERS: dict[CapabilityKind, tuple[str, str]] = {
    CapabilityKind.COMPUTER_SCIENCE: ("foundation", "컴퓨터 과학 기초"),
    CapabilityKind.PROGRAMMING_LANGUAGE: ("language-framework", "언어와 프레임워크"),
    CapabilityKind.FRAMEWORK: ("language-framework", "언어와 프레임워크"),
    CapabilityKind.LIBRARY: ("language-framework", "언어와 프레임워크"),
    CapabilityKind.PROTOCOL: ("interface-data", "HTTP · API · 데이터"),
    CapabilityKind.DATABASE: ("interface-data", "HTTP · API · 데이터"),
    CapabilityKind.SOFTWARE_PRACTICE: ("quality-delivery", "테스트 · 품질 · 전달"),
    CapabilityKind.TOOL: ("quality-delivery", "테스트 · 품질 · 전달"),
    CapabilityKind.MESSAGING: ("operations", "운영 · 확장 · 메시징"),
    CapabilityKind.CLOUD: ("operations", "운영 · 확장 · 메시징"),
    CapabilityKind.INFRASTRUCTURE: ("operations", "운영 · 확장 · 메시징"),
    CapabilityKind.DOMAIN_KNOWLEDGE: ("domain-depth", "도메인 심화"),
    CapabilityKind.TECHNICAL_CAPABILITY: ("engineering-depth", "설계와 문제 해결"),
    CapabilityKind.OTHER: ("engineering-depth", "설계와 문제 해결"),
}


def chapter_for(
    *,
    section_key: str,
    capability_kind: CapabilityKind | None,
    provisional: bool,
) -> ChapterDescriptor:
    """Return a stable display chapter without using company task titles.

    Capability names and individual technologies deliberately do not participate
    in this decision.  The catalog-owned semantic kind is the stable input; a
    company project remains a separate overview node.
    """
    if provisional or capability_kind is None:
        return ChapterDescriptor(
            key="pending-review",
            title="검토 대기 역량",
            reason="공용 역량 사전 승인 전 사용자 범위에서 보존한 역량입니다.",
        )
    suffix, title = _CHAPTERS[capability_kind]
    return ChapterDescriptor(
        key=suffix,
        title=title,
        reason="승인된 원자 역량을 학습 목적에 따라 묶은 챕터입니다.",
    )


def career_stage_ref(*, minimum_months: int | None, maximum_months: int | None) -> str:
    if not minimum_months:
        return "stage.entry"
    maximum = "plus" if maximum_months is None else str(maximum_months)
    return f"stage.experience-{minimum_months}-{maximum}"

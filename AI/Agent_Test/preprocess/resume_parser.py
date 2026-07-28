"""이력서 파서 (docx → profile) — AGENTS §3 · 정본 §3.

agent 밖 **전처리**. docx 문단 텍스트 추출 → LLM structured 강제 추출 → UserProfile.
표 없는 텍스트 이력서 가정(AGENTS §0). 표 파싱은 백로그(design §8.4).
"""
from __future__ import annotations

from docx import Document

from llm import get_structured_llm
from schemas import UserProfile

_SYSTEM = (
    "당신은 이력서에서 구조화 정보를 추출하는 도우미입니다. "
    "주어진 이력서 텍스트에 실제로 있는 내용만 추출하고, 텍스트에 없는 내용을 지어내지 마세요. "
    "없는 섹션은 빈 배열로, 값이 없는 항목은 null로 둡니다.\n"
    "분류 규칙(엄수):\n"
    "- experiences(경력)에는 **실제 재직·근무 경력만** 넣습니다. "
    "팀·개인 프로젝트는 experiences가 아니라 projects에만 넣습니다.\n"
    "- projects에는 프로젝트만 넣습니다.\n"
    "- 어학 시험(TOEIC·OPIc 등)은 languages에만 넣습니다. "
    "certifications에는 자격증만 넣고 어학을 중복 기재하지 마세요."
)


def docx_to_text(path: str) -> str:
    """docx의 문단 텍스트를 추출한다(표 없는 텍스트 이력서 가정)."""
    doc = Document(path)
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paras)


def parse_resume(path: str) -> UserProfile:
    """docx 이력서를 UserProfile로 파싱한다(structured, mid 티어)."""
    resume_text = docx_to_text(path)
    structured = get_structured_llm("mid", UserProfile)
    return structured.invoke(
        [
            ("system", _SYSTEM),
            ("human", f"다음 이력서에서 정보를 추출하세요:\n\n{resume_text}"),
        ]
    )

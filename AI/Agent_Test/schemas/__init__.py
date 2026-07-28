"""schemas 패키지 — 프로토타입 전체가 공유하는 Pydantic 계약층 (AGENTS §2)."""
from schemas.agent_io import Meta, RunAgentResult
from schemas.posting import Posting
from schemas.profile import (
    Award,
    Bootcamp,
    Certification,
    Education,
    Evidence,
    Experience,
    Language,
    Project,
    Skill,
    UserProfile,
)
from schemas.tool_io import (
    GapResult,
    Level,
    MatchReason,
    ScoredPosting,
    SearchResult,
    ToolError,
)

__all__ = [
    "UserProfile", "Skill", "Experience", "Project", "Education",
    "Certification", "Language", "Bootcamp", "Award", "Evidence",
    "Posting",
    "GapResult", "ScoredPosting", "SearchResult", "MatchReason", "ToolError", "Level",
    "RunAgentResult", "Meta",
]

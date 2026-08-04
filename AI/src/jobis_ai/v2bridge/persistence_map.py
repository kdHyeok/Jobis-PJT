"""세션 자산의 **목적지 선언** — 무엇이 어디에 적재되는지 한 곳에 적는다.

왜 이 파일이 있는가: 에이전트의 자산·상태가 SQLite 세션에만 살아 있던 것을 PostgreSQL 로
옮겼고(ⓐ, D152), 그 과정에서 **무엇이든 조용히 빠지면 그게 곧 유실**이다. 세션 키를 새로
만드는 사람이 목적지를 정하지 않고 지나갈 수 없게 선언을 강제하고 테스트가 지킨다
(`tests/test_persistence_map.py`). `ASSET_KEYS` 에 있는 키가 여기 없으면 회귀가 깨진다.

ⓐ 이후의 구조 (0803 인수인계 §0):
  · **진실의 출처는 자산 블롭 하나다** — `agent_session_state.state`(V23). 매 턴 응답
    `collected.outputs.session_state` 로 세션 **전체**가 나가고, 다음 요청
    `career.sessionState` 로 그대로 돌아온다. 번역이 없으므로 키별 유실 여지도 없다.
  · 도메인 테이블(`job_postings`·`career_sources`·`user_goal_profiles`·V23 산출물 테이블)은
    **읽기용 투영**이다 — `collected` 의 나머지 칸(posting·resume·outputs.*)으로 파생되고,
    writer 는 백엔드 하나다. 방향이 한쪽(자산 → 투영)이라 갈리지 않는다.

카테고리는 셋뿐이다:
  · `"backend"` — 블롭으로 영속된다. 값에는 투영 테이블이 있으면 그것을 함께 적는다.
  · `"turn"` — 그 턴 안에서만 의미가 있다. 블롭에 실려도 매 턴 요청·실행이 다시 채운다.
  · `"pending"` — 아직 목적지가 정해지지 않았다. **여기 남아 있는 것이 곧 할 일 목록이다.**
"""

from __future__ import annotations

# (카테고리, 목적지 또는 이유)
ASSET_DESTINATIONS: dict[str, tuple[str, str]] = {
    # --- 진실의 출처: agent_session_state.state 블롭 (투영이 있으면 함께 적는다) ------
    "history": ("backend", "블롭 — conversation_messages 는 백엔드가 따로 쓰는 자기 원천"),
    "resume": ("backend", "블롭 — 투영: career_sources.raw_text (collected.resume)"),
    "resume_library": ("backend", "블롭 — 투영: career_sources 여러 행"),
    "job_posting": ("backend", "블롭 — 투영: job_postings.raw_text (collected.posting)"),
    "posting_summary": ("backend", "블롭 — 투영: job_postings.parsed_data (분석 경로가 쓴다)"),
    "posting_library": ("backend", "블롭 — 투영: job_postings 여러 행"),
    "preferences": ("backend", "블롭 — 투영: user_goal_profiles.chat_preferences (collected.preferences)"),
    "user_facts": ("backend", "블롭 — 투영: user_goal_profiles.chat_facts (collected.facts)"),
    "analysis": ("backend", "블롭 — 투영: analysis_jobs.engine_result (outputs.analysis)"),
    "roadmap": ("backend", "블롭 — 투영: analysis_jobs.engine_result 안 (outputs.roadmap)"),
    "judgment_summary": ("backend", "블롭 — 투영: analysis_jobs.engine_result 안"),
    "profile": ("backend", "블롭 — 투영: ai_user_profiles (outputs.profile)"),
    "recommendations": ("backend", "블롭 — 투영: posting_recommendations"),
    "coverletter": ("backend", "블롭 — 투영: coverletter_drafts"),
    "interview": ("backend", "블롭 — 투영: interview_sessions.state (요청 career.interview 로도 온다)"),
    "application_plan": ("backend", "블롭 — 투영: application_plans"),
    "preparationPeriodWeeks": ("backend", "블롭 — 투영: user_goal_profiles.preparation_period_weeks"),
    "availableHoursPerWeek": ("backend", "블롭 — 투영: user_goal_profiles.available_hours_per_week"),
    "pendingRequest": ("backend", "블롭 — 남은 턴 카운터가 있어 대화 이력으로 복원할 수 없다"),
    "unsupported_requests": ("backend", "블롭 — 계측용 누적 (harvest_sessions 가 읽는다)"),
    "pendingConsent": ("backend", "블롭 — 직전 턴에 물어본 동의가 무상태에서도 다음 턴에 살아야 한다"),
    # 없으면 무상태에서 매 턴 같은 이력서 확인을 되묻는다 — pendingConsent 와 같은 이유다.
    "resumeAskedFor": ("backend", "블롭 — 이 공고로 이력서를 이미 물었다는 사실(D159)"),
    "analysis_key": ("backend", "블롭 — 판정의 출처 지문. 없으면 같은 입력에 판정이 다시 돈다"),

    # --- 턴 안에서만 -------------------------------------------------------------
    "userId": ("turn", "요청 컨텍스트에서 온다"),
    "last_message": ("turn", "이번 턴 발화 — 요청이 곧 원천"),
}


def unmapped(asset_keys: frozenset[str] | set[str]) -> set[str]:
    """목적지가 선언되지 않은 자산 키. 비어 있지 않으면 유실 위험이 그만큼 남아 있다."""

    return set(asset_keys) - set(ASSET_DESTINATIONS)


def pending_destinations() -> dict[str, str]:
    """아직 목적지가 안 정해진 것 — 곧 남은 할 일."""

    return {k: why for k, (kind, why) in ASSET_DESTINATIONS.items() if kind == "pending"}

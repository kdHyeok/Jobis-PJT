"""recent_history 의 role 별 클립 — 어시스턴트 답변이 300자에서 잘리지 않는다."""

from jobis_ai.orchestrator.session import recent_history


def test_assistant_gets_wider_clip_than_user():
    session = {"history": [
        {"role": "user", "content": "가" * 2000},
        {"role": "assistant", "content": "나" * 2000},
    ]}

    user, assistant = recent_history(session)

    assert len(user["content"]) == 300
    assert len(assistant["content"]) == 1200


def test_short_turns_survive_intact():
    session = {"history": [{"role": "assistant", "content": "짧은 답"}]}

    assert recent_history(session)[0]["content"] == "짧은 답"

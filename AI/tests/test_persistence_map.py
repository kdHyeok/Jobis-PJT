"""세션 자산의 목적지가 **하나도 빠지지 않았는지** 지킨다.

에이전트 구현의 핵심 자산이 SQLite 세션에만 살아 있던 것을 PostgreSQL 로 옮기는 중이다
(작업로그/0803-무상태-전환-계획.md). 그 과정에서 **조용히 빠지는 것이 곧 유실**이라,
새 세션 키를 만드는 사람이 목적지를 정하지 않고 지나갈 수 없게 여기서 막는다.

같은 저장소의 `test_produced_assets_are_storable`(에이전트 선언 ⊆ ASSET_KEYS)과 같은 계열의
그물이다 — 그쪽은 "저장할 수 있나", 여기는 "어디에 적재되나"를 묻는다.
"""

from __future__ import annotations

from jobis_ai.orchestrator.session import ASSET_KEYS
from jobis_ai.v2bridge.persistence_map import ASSET_DESTINATIONS, unmapped


def test_every_session_asset_declares_a_destination():
    missing = unmapped(ASSET_KEYS)
    assert not missing, (
        "다음 세션 자산에 목적지 선언이 없다 — 이대로 두면 SQLite 를 지울 때 조용히 사라진다: "
        f"{sorted(missing)}. `v2bridge/persistence_map.ASSET_DESTINATIONS` 에 "
        "backend(테이블·칼럼) 또는 turn(영속 안 하는 이유)으로 적어라."
    )


def test_declarations_do_not_drift_from_the_session_contract():
    """선언에만 있고 세션에는 없는 키 — 자산이 사라졌는데 선언이 남은 경우를 잡는다."""

    stale = set(ASSET_DESTINATIONS) - set(ASSET_KEYS)
    assert not stale, f"세션에 없는 키가 선언에 남아 있다: {sorted(stale)}"


def test_categories_are_only_the_three_we_defined():
    allowed = {"backend", "turn", "pending"}
    bad = {k: kind for k, (kind, _why) in ASSET_DESTINATIONS.items() if kind not in allowed}
    assert not bad, f"알 수 없는 카테고리: {bad}"


def test_every_declaration_carries_its_reason():
    """목적지든 '영속 안 함'이든 **왜**를 적는다 — 근거 없는 규칙은 나중에 알아볼 수 없다(§3-4)."""

    blank = [k for k, (_kind, why) in ASSET_DESTINATIONS.items() if not why.strip()]
    assert not blank, f"이유가 비어 있는 선언: {blank}"


def test_backend_bound_assets_all_ride_the_state_blob(monkeypatch):
    """선언은 있는데 **실어 보내지 않는** 자산이 없어야 한다.

    ⓐ(D152) 이후 진실의 출처는 자산 블롭 하나다: `_collected_outputs` 가 세션 **전체**를
    `session_state` 로 싣는다. 여기서는 그 블롭이 backend 로 선언된 키를 하나도 빠뜨리지
    않는지 실제 코드로 확인한다 — 선언만 보고 안심하게 되는 것이 더 나쁘다.
    """

    from jobis_ai.v2bridge import service

    # CollectedOutputs 의 타입 제약이 있는 칸만 그 형식으로, 나머지는 자리표시 dict 로 채운다
    typed = {
        "preparationPeriodWeeks": 4, "availableHoursPerWeek": 10,
        "roadmap": [{"title": "Kafka 학습"}],
        "recommendations": [{"companyName": "가나테크"}],
        "user_facts": ["9월까지 취업 희망"], "history": [{"role": "user", "content": "안녕"}],
        "unsupported_requests": ["연봉 협상"], "userId": "u-1", "last_message": "안녕",
    }
    session = {k: typed.get(k, {"k": k}) for k in ASSET_KEYS}

    class _Store:
        def get(self, _sid): return dict(session)

    monkeypatch.setattr("jobis_ai.orchestrator.session.get_session_store", lambda: _Store())
    outputs = service._collected_outputs("v2-chat-blob", {})
    declared = {k for k, (kind, _why) in ASSET_DESTINATIONS.items() if kind == "backend"}
    missing = declared - set(outputs.session_state or {})
    assert not missing, (
        "목적지는 선언됐는데 블롭에 실리지 않는다 — 적재되지 않으므로 유실이다: "
        f"{sorted(missing)}"
    )


def test_conversation_survives_without_a_session_file(monkeypatch, tmp_path):
    """**SQLite 없이도** 요청만으로 대화 맥락이 선다 — 무상태 전환의 최종 검증(§2-8, ⓐ).

    저장소를 새로 비우고(파일이 없는 상황과 같다) 요청의 자산 블롭(`career.sessionState`)
    으로만 세운 뒤, 자산이 **보냈던 모습 그대로** 세션에 살아 있는지 본다 — 번역이 없으므로
    라이브러리 표식(`_label`·`_origin`)도 왕복을 그대로 살아남아야 한다(D151 의 근치).
    """

    from uuid import uuid4

    from jobis_ai.orchestrator.session import MemorySessionStore
    from jobis_ai.v2bridge import service
    from jobis_ai.v2bridge.models import ChatRequest

    store = MemorySessionStore()      # 파일 없음 — 프로세스가 죽으면 사라지는 저장소
    monkeypatch.setattr("jobis_ai.orchestrator.session.get_session_store", lambda: store)

    session_id = "v2-chat-stateless"
    request = ChatRequest(
        conversationId=uuid4(), displayName="테스터",
        messages=[{"role": "USER", "content": "이 공고로 준비 계획 세워줘"}],
        career={
            "sessionState": {
                "resume": {"sourceType": "text", "value": "Java Spring 5년. 결제 API 운영.",
                           "origin": "career_source"},
                "resume_library": [{"sourceType": "text", "value": "Java Spring 5년.",
                                    "_label": "백엔드 이력서", "_origin": "career_source"}],
                "job_posting": {"sourceType": "text",
                                "value": "가나테크 백엔드 자격요건 Java 3년"},
                "posting_summary": {"companyName": "가나테크", "jobTitle": "백엔드"},
                "posting_library": [{"companyName": "가나테크", "jobTitle": "백엔드"}],
                "preferences": {"roles": ["백엔드"]},
                "user_facts": ["9월까지 취업 희망"],
                "pendingRequest": {"agent": "fit_analysis",
                                   "missing": ["resume"], "turnsLeft": 2},
                "history": [{"role": "user", "content": "안녕하세요"}],
            },
            "interview": {"asked": ["Kafka 경험"], "answers": [], "usedTopics": ["Kafka"]},
        },
    )

    service._seed_session_state(session_id, request)

    session = store.get(session_id)
    assert session["resume"]["value"].startswith("Java Spring")
    assert session["resume_library"][0]["_label"] == "백엔드 이력서"
    assert session["posting_library"][0]["companyName"] == "가나테크"
    assert session["posting_summary"]["jobTitle"] == "백엔드"
    assert session["preferences"] == {"roles": ["백엔드"]}
    assert session["user_facts"] == ["9월까지 취업 희망"]
    assert session["pendingRequest"]["turnsLeft"] == 2
    assert session["interview"]["usedTopics"] == ["Kafka"]
    assert session["history"][0]["content"] == "안녕하세요"

    # 세션에 이미 있는 키는 덮지 않는다 — 요청 블롭은 직전 턴의 사본이고 세션이 최신이다
    store.update(session_id, {"resume": {"sourceType": "text", "value": "방금 붙여넣은 이력서"}})
    service._seed_session_state(session_id, request)
    assert store.get(session_id)["resume"]["value"] == "방금 붙여넣은 이력서"

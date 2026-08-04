"""서술 관찰 룰 — 실제 이력서(2026-08-04, 조재율 이력서)에서 다른 LLM 이 짚었고 우리는
못 짚던 네 가지가 결정론으로 잡히는지 본다. 프롬프트가 아니라 **이 배관**이 원인이었다.
"""

from jobis_ai.resume_observations import observe
from jobis_ai.v2bridge.mapping import fragments_from_profile

_RESUME_TEXT = """
* Database & Caching: PostgreSQL, MySQL, Redis (Caching / Distributed Lock)
* 유저 데이터 중심의 주도적 문제 해결 & 솔직한 소통:
   * 문제를 'Why/What' 관점에서 구조화하고, 유저 데이터와 기술적 타당성을 근거로 팀원들과
     투명하게 소통하며 솔루션을 끝까지 완수하는 집요함.
* 조직의 요구에 따라 CRM 서버 개발 및 신규 스택 전환에 즉시 뛰어들 수 있는 학습 의지.
"""

_PROFILE = {
    "projects": [
        {
            "id": "prj-1",
            "title": "Django/DRF 기반 RESTful API 및 GPT API/RAG 연동 AI 추천 파이프라인",
            "summary": "유저의 비정형 데이터 및 질의를 기반으로 개인화된 답변을 제공하는 백엔드 API 서비스",
            "techStack": ["Django", "Redis"],
            "achievements": [
                "Frequently Read 데이터를 Redis 캐시 레이어로 분리하고 복합 인덱스를 적용해 API Latency 대폭 단축",
            ],
        },
        {
            "id": "prj-2",
            "title": "OCR 비정형 데이터 분석 및 RDBMS 쿼리 최적화 파이프라인",
            "period": "2024.03 ~ 2024.06",
            "summary": "비정형 이미지에서 핵심 텍스트를 자동 추출하는 서비스",
            "achievements": ["SQL Execution Plan 분석 및 Indexing 재설계로 조회 성능 약 60% 개선"],
        },
    ],
    "experiences": [],
    "skills": [{"name": "Redis", "level": ""}],
}


def _titles(items):
    return [item["text"] for item in items]


def demo() -> None:
    seen = observe(_PROFILE, _RESUME_TEXT)

    # ① 프로젝트 맥락 세 칸의 빈 칸을 **이름으로** 신고한다 — 라벨만 넘기던 배관의 핵심 수정.
    first, second = seen["projects"]
    assert first["missingContext"] == ["기간", "팀 규모", "담당 범위"], first["missingContext"]
    assert "기간" not in second["missingContext"], second["missingContext"]
    assert second["period"] == "2024.03 ~ 2024.06"
    assert first["achievements"], "성과 문장이 루프까지 실려야 한다"

    # ② 숫자 있는 성과 / 없는 성과를 가른다. 실측 이력서에서 측정값은 딱 하나였다.
    assert any("60% 개선" in t for t in _titles(seen["quantifiedClaims"]))
    assert len(seen["quantifiedClaims"]) < len(seen["unquantifiedClaims"])

    # ②-a 실측 오탐(2026-08-04): `\d` 하나로 세면 "ORM N+1"의 1 때문에 이 문장이 정량으로
    #      잡혔다 — 다른 LLM 이 대표적 모호 문장으로 짚은 바로 그 줄이다. 단위가 있어야 측정이다.
    assert any("대폭 단축" in t for t in _titles(seen["unquantifiedClaims"])), \
        "N+1 의 1 을 측정값으로 세면 안 된다"
    assert not any("대폭 단축" in t for t in _titles(seen["quantifiedClaims"]))

    # ②-b 중점(·)으로 문장을 끊으면 "공간·건축 디자인"이 "공간"으로 잘려 나갔다(같은 실측).
    assert all(len(t) >= 8 for t in _titles(seen["unquantifiedClaims"]))

    # ③ 이력서만으로 검증할 수 없는 자기평가 줄.
    lines = " || ".join(seen["selfAssessedLines"])
    assert "집요함" in lines and "학습 의지" in lines, lines

    # ④ 스킬 수식어와 서술의 대조 — "Redis (Caching / Distributed Lock)" 인데 서술에는
    #    캐싱만 나온다. inNarrative=False 가 곧 "확인을 청할 자리"다.
    locks = [q for q in seen["skillQualifiers"] if "Distributed Lock" in q["qualifier"]]
    assert locks and locks[0]["skill"] == "Redis" and locks[0]["inNarrative"] is False, locks

    # ④-a 실측 오탐(2026-08-04): 제목 괄호("(주니어)")와 약어("(DRF)")가 수식어로 잡혔다.
    #      둘 다 "그것까지 해봤다"는 주장이 아니라 표기라서 물을 것이 없다.
    noise = observe(_PROFILE, "지원 직무: Backend Developer (주니어)\n"
                              "* Django REST Framework (DRF), Redis (Caching / Distributed Lock)")
    assert [q["qualifier"] for q in noise["skillQualifiers"]] == ["Caching", "Distributed Lock"], \
        noise["skillQualifiers"]

    # ⑤ 저장소 조각: 서술이 description 으로, 정형 칸이 detail 로 갈라 실린다.
    project = next(f for f in fragments_from_profile(_PROFILE) if f.kind == "PROJECT")
    assert "Redis 캐시 레이어" in project.description, project.description
    assert project.detail["techStack"] == ["Django", "Redis"], project.detail
    assert "period" not in project.detail, "빈 칸은 detail 에 넣지 않는다"

    print("ok")


def test_resume_observations() -> None:
    demo()


if __name__ == "__main__":
    demo()

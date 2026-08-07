# AI CI 소유권과 규칙

루트 [../../AGENTS.md](../../AGENTS.md)의 "CI/CD 소유권"이 상위 규칙이다. 여기는 AI 쪽 상세다.
요약은 `AGENTS.md` §5에 있고, 이 문서는 자동 로드되지 않는다.

## 고칠 파일 / 고치지 않을 파일

| | 파일 | 소유 |
|---|---|---|
| 고친다 | [`../ci/test.sh`](../ci/test.sh) — AI에서 무엇을 검사하는가 | AI 개발자 |
| 고치지 않는다 | 루트 `Jenkinsfile` — 실행 이미지, 스테이지 배치 | Infra |

`Jenkinsfile` 변경이 필요하면 MR을 올리고 Infra 리뷰를 받는다(`.gitlab/CODEOWNERS`).
새 인프라 의존성이 통합 테스트에 필요할 때가 대표적인 사유다. 서비스 스크립트 안에서
`docker run`으로 몰래 띄우지 않는다 — 정리·포트 충돌·동시성 책임이 사라진다.

## `--frozen`을 떼지 않는다

`ci/test.sh`는 `uv run --frozen`으로 돈다. `uv.lock`이 `pyproject.toml`과 어긋나면 실패하는데,
그건 버그가 아니라 설계다. 의존성을 바꿨으면 락파일을 **같은 커밋에서** 갱신한다.
CI에서 새로 풀게 만들면 CI가 검증한 의존성과 배포되는 의존성이 갈라진다.

## CI에는 실 LLM 없이 도는 것만 싣는다

`pytest`와 `python -m jobis_ai.explain`이 그것이다(§4). 평가 하네스
(`planner_harness`, `consistency`, `loop_consistency`)는 크레딧과 시트를 쓰므로 CI에 넣지 않는다.
큰 분기에서 사람이 돌리고 결과를 MR에 적는다.

## 백엔드와의 계약은 양쪽을 같은 MR에서 고친다

`v2bridge/models.py`의 계약 모델을 바꾸면 `backend/`의 대응 record도 함께 맞춘다.
`ContractModel`은 `extra="forbid"`라 **한쪽만 넓히면 상대가 런타임 422로 죽는다.**
타입 검사로는 안 잡히므로 계약 테스트로 잡는다.

실측(2026-08-07): 백엔드가 `ChatRequest`에 `task`·`workspaceState`를 실어 보내기 시작했는데
AI 쪽 모델이 4필드 그대로여서, 모든 대화 턴이 `POST /v1/chat/stream` 422로 실패했다.
`/v1/chat` 폴백도 같은 모델이라 우회로가 없었다.

## 자동 로드 문서 크기

`CLAUDE.md`가 `@`로 임포트하는 문서(`AGENTS.md` + `작업로그/지금상태.md`)의 총 줄 수에
상한이 있다(`tests/test_docs_entrypoint.py`). 규칙을 늘릴 때 그 두 파일을 키우지 말고
이 문서 같은 상세 문서로 밀어내고 요약만 남긴다. 넘기면 CI가 막는다.

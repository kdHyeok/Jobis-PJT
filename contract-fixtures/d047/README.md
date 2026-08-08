# D047 단일 AI 통합 기준선

`multi-role-analysis-baseline.json`은 최신 팀 AI와 AI-v3를 합치기 전에 보존한 제품 경계다.
실제 사람이나 회사의 데이터는 포함하지 않는다.

`career-journey-acceptance.json`은 서로 다른 공고가 독립 로드맵으로 흩어지지 않고 하나의 사용자
커리어 그래프로 연결되는 최종 수용 기준이다. 주니어 백엔드 기회와 경력 2~4년 기회 사이의
취업·경력 게이트, 보안 4년 공고의 독립된 보안 경로를 고정한다.

- `latestTeamBoundary`: Spring이 이미 사용하는 `/v1/analyses` 요청·질문 응답과 NDJSON 진행 이벤트
- `v3Boundary`: 복수 포지션을 손실 없이 보존하는 `StructuredPosting`과 첫 확인 질문
- 고정 대상: 직무 병합 금지, 사용자 선택 전 분석 금지, `runId`·`sequence` 불변식
- 커리어 고정 대상: 최소·최대 경력, 관련 직무 범위, 경력 증거, 병렬 진입 기회, 보안 섹션 분리

검증은 다음 테스트가 각각 자기 계약으로 수행한다.

```powershell
cd C:\JOBIS\AI
uv run --frozen --extra dev --extra prototype pytest -q tests/test_d047_unified_baseline_fixture.py

cd C:\JOBIS\AI-v3
uv run --frozen --group dev pytest -q tests/test_d047_unified_baseline_fixture.py
```

# Contract fixtures

## 회귀 corpus

`regression-corpus.json`은 JOBIS AI v3가 반드시 보호해야 할 실제 실패와 제품 결정을
기계가 읽을 수 있는 형태로 보존한다.

- 총 40건
- P0 22건
- 사용자 제공 공고는 문제를 재현하는 최소 발췌만 포함
- 개인정보 없음
- 이미지·비동기·보안 사례는 합성 최소 재현
- 기대값은 기존 구현 출력이 아니라 `docs/05-regression-scenarios.md`의 제품 결정을 기준으로 함

검증:

```powershell
python C:\jobiss-service-ai-v3-lab\scripts\validate-fixtures.py
```

검증기는 다음을 확인한다.

- JSON 구조와 허용 필드
- 케이스 ID와 category 일치
- 케이스 ID 중복
- 문서에 정의된 40개 케이스와 corpus의 일치
- 출처와 개인정보 표시
- P0 케이스 존재

Phase 1의 Pydantic 계약과 JSON Schema 테스트가 준비되면 같은 corpus를 실제 계약과
각 단계 evaluator에 연결한다.

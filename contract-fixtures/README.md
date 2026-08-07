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

## D047 단일 AI 통합 기준선

`d047/multi-role-analysis-baseline.json`은 최신 팀 AI와 AI-v3 통합 전에 복수 직무 질문과
분석 진행 이벤트 경계를 고정한다. 현재 AI와 AI-v3 테스트가 같은 fixture를 각자의 Pydantic
계약으로 검증한다. 상세 불변식과 실행 명령은 `d047/README.md`를 따른다.

## D048 프로젝트 중심 커리어 여정

`scenarios/d048-estgames-naver-career-journey.json`은 프로젝트 과제를 메인 지도에 펼치지 않고
회사 맞춤 프로젝트 상세로 유지하는 기준과, 이스트게임즈 신입 기회에서 관련 백엔드 취업·경력
2~4년을 거쳐 네이버웹툰 경력 기회로 이어지는 하나의 사용자 커리어 그래프를 고정한다.

이 fixture는 D048 구현의 수용 입력이자 자동 회귀 기준이다. AI 원본 proposal, Spring 저장·합성
결과, API journey projection과 프론트 렌더링 모델이 같은 불변식을 만족하는지 AI·Spring·frontend
테스트에서 검증한다. 실제 LLM 공고 두 건의 라이브 품질 확인은 별도 수용 검사로 남긴다.

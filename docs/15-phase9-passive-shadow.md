# Phase 9 수동적 AI 결과 비교

## 결론

현재 단계에서는 새 공고 원문을 두 AI 공급자에게 동시에 보내는 active shadow를 사용하지 않는다.
동일 사용자가 같은 공고에 대해 이미 완료한 LEGACY와 V3 결과가 모두 있을 때만 두 결과를 짝지어
비교하는 `PASSIVE_PAIRED` 방식을 사용한다.

이 비교는 모델 정확도를 자동 판정하지 않는다. 회사, 직무, 최소 경력, 지원 판정, 필수 요건 수,
역량 집합, 회사 맞춤 프로젝트 존재 여부의 일치도와 처리 시간을 운영자에게 보여 주는 후보
신호다. 어느 결과가 더 정확한지는 공고 원문과 사용자 맥락을 확인한 운영자가 근거를 남겨
`LEGACY_BETTER`, `V3_BETTER`, `EQUIVALENT`, `INCONCLUSIVE` 중 하나로 판정한다.

## 활성화 조건

기본값은 결과 저장 비활성화다.

```powershell
$env:AI_PROVIDER="shadow"
$env:AI_SHADOW_STORE_RESULTS="true"
$env:AI_SHADOW_PRIMARY="v3"
$env:AI_SHADOW_BATCH_SIZE="10"
```

두 조건이 모두 참일 때만 완료 결과를 찾는다.

- `AI_PROVIDER=shadow`
- `AI_SHADOW_STORE_RESULTS=true`

`AI_SHADOW_DUPLICATE_TRANSMISSION_APPROVED`는 향후 정책 결정을 기록하기 위한 값일 뿐이다.
현재 코드에는 active duplicate dispatch가 없으며 값을 true로 바꿔도 AI를 추가 호출하지 않는다.
기본 provider와 사용자 응답 경로도 이 단계에서 바꾸지 않는다.

## 저장 경계

`ai_provider_comparisons`에는 다음 정보만 저장한다.

- 사용자 소유 ID와 두 분석 작업 ID
- 공고 내용 fingerprint
- 정규화된 필드별 차이
- 일치율, 역량 집합 Jaccard, 경고 수, 두 작업의 처리 시간
- 운영자 판정과 판정 근거

공고 원문, 이력서 원문, 프롬프트, 모델 내부 reasoning은 비교 테이블에 복사하지 않는다.
비교 후보 함수도 ID와 fingerprint만 반환한다. 테이블에는 사용자 RLS와 운영자 정책을 적용했다.

## 운영자 흐름

운영 검토함의 `AI 결과 비교` 탭에서 다음을 수행한다.

1. 현재 모드가 `shadow`이고 결과 저장이 켜졌는지 확인한다.
2. `완료 결과 찾아 비교`를 눌러 이미 완료된 결과만 스캔한다.
3. 핵심 불일치 수, 필드 일치율, 역량 집합 유사도와 처리 시간을 확인한다.
4. 상세 창에서 필드별 LEGACY·V3 값을 대조한다.
5. 공고 원문과 사용자 맥락을 별도로 확인하고 근거를 입력해 판정한다.

자동 일치율이 100%여도 두 모델이 같이 틀릴 수 있다. 따라서 자동 점수만으로 `EQUIVALENT`를
확정하거나 기본 provider를 전환하지 않는다.

## 검증 결과

2026-08-04 격리 PostgreSQL `localhost:58432/jobiss_v3_integration_lab`과 백엔드 8381에서
다음을 확인했다.

- Flyway V43 실제 적용 성공
- 공개 합성 결과 쌍 1건의 passive comparison 생성 성공
- LEGACY 8,000ms, V3 4,000ms의 기존 작업 시간을 비교 레코드에 보존
- 동일 쌍 재스캔 결과 0건으로 멱등성 확인
- 운영자 `EQUIVALENT` 판정과 근거 저장 성공
- 일반 사용자 운영 API 접근 403 확인
- 공고 원문 없이 5개 공개 합성 결과 쌍의 결정론적 비교 회귀 통과
- 프론트 프로덕션 빌드와 comparator 테스트 통과

위 처리 시간은 비교 저장 기능을 확인하기 위해 넣은 합성 값이다. 실제 모델의 p50/p95나 비용
측정값으로 사용해서는 안 된다.

## 전환 전 남은 게이트

- 같은 공개 공고 fixture를 실제 LEGACY와 V3에 반복 실행
- 정답표 또는 운영자 판정으로 필드별 정확성·근거 완전성 측정
- 기존이 맞고 V3가 틀린 사례와 그 반대 사례를 각각 기록
- 실제 모델 처리 시간 p50/p95와 비용 측정
- 제한된 내부 사용자에서 오류율·질문율·사용자 수정률 관찰
- 롤백 리허설 후 별도 승인으로 기본 provider 결정

이 게이트를 통과하기 전에는 `AI_PROVIDER` 기본값을 바꾸지 않는다.

## 중단과 롤백

비교 저장만 즉시 중단하려면 다음처럼 설정하고 백엔드를 재시작한다.

```powershell
$env:AI_SHADOW_STORE_RESULTS="false"
```

provider 실험 자체를 중단하려면 다음처럼 기존 경로로 되돌린다.

```powershell
$env:AI_PROVIDER="legacy"
$env:AI_SHADOW_STORE_RESULTS="false"
```

V43 테이블과 기존 비교 기록은 삭제하지 않는다. worker는 조건이 꺼지면 새 비교를 만들지 않으며,
기존 LEGACY·V3 분석 결과와 공개 로드맵을 변경하지 않는다.

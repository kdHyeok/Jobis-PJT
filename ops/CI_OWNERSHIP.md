# CI 소유권 — 뼈대는 공용, 검사는 각 영역

이 저장소는 파이프라인을 **두 층**으로 나눈다. 기능을 개발할 때 어느 쪽을 고쳐야
하는지 헷갈리지 않게 하려는 것이다.

```
Jenkinsfile  ← 뼈대. 공용 정책.          (Infra 담당 리뷰 필수)
  │  언제 도는가 (브랜치·변경 경로)
  │  무엇이 머지를 막는가 (required / advisory)
  │  어떤 순서로 배포되는가 (build once → promote → deploy → verify)
  │
  └─ 각 영역의 ci-checks 를 호출만 한다
        backend/ci-checks        ← 백엔드 개발자가 고친다
        frontend/ci-checks       ← 프론트 개발자가 고친다
        AI/ci-checks             ← AI 담당자가 고친다
        RAG/ci-checks            ← RAG 담당자가 고친다
```

## 기능을 하나 추가했다면

**대부분의 경우 CI 파일은 건드리지 않는다.** 테스트를 추가하면 기존 파이프라인이
알아서 그 테스트까지 돌린다.

| 상황 | 고칠 곳 |
|---|---|
| 기능 추가 + 테스트 작성 | 코드와 테스트만. CI 무수정 |
| DB 스키마 변경 | 마이그레이션 파일 추가. CI 무수정 |
| 검사 명령이 늘어남 (예: 새 린터, 새 테스트 스위트) | 해당 영역의 `ci-checks` |
| 테스트에 새 서비스가 필요 (예: Redis 컨테이너) | `Jenkinsfile` — **MR 로 제안하고 Infra 리뷰** |
| 머지 차단 기준 변경 (advisory → required) | `Jenkinsfile` — **MR 로 제안하고 Infra 리뷰** |
| 배포 순서·대상 변경 | `Jenkinsfile`, `ops/` — **Infra 담당** |

## required / advisory

머지를 막는 검사(required)와 경고만 남기는 검사(advisory)를 구분한다. 처음부터 모든
검사를 차단으로 두면 개발이 멈춘다.

| 검사 | 상태 | 올리는 조건 |
|---|---|---|
| 컴파일·빌드 | required | — |
| 단위·통합 테스트 | required | — |
| DB 마이그레이션 적용 | required | — |
| 인프라 스크립트 문법·릴리스 설정 | required | — |
| SpotBugs (backend) | **advisory** | 기존 지적사항 정리 후 `build.gradle` 의 `ignoreFailures=false` |
| ESLint (frontend) | **advisory** (기존 지적 허용) | 지적 0건을 유지하게 되면 Jenkinsfile 의 `catchError` 제거 |
| ruff (AI·RAG) | **required** | 지적 0건 달성해 2026-08-08 승격 |

advisory 는 빌드를 `UNSTABLE` 로 표시한다. 머지는 되지만 파이프라인이 노란색으로
남으므로, 방치하면 눈에 띈다.

## 변경 경로에 따른 실행 범위

기능 브랜치는 **바뀐 영역만** 돈다(`Detect changes` 단계가 `origin/develop...HEAD` 를
비교한다). 프론트 CSS 한 줄을 고쳤다고 Testcontainers 백엔드 테스트까지 돌지 않는다.

- `backend/**` → 백엔드 테스트
- `frontend/**` → 프론트 빌드
- `AI/**` → AI 테스트
- `RAG/**`, `DATA/**` → RAG 테스트
- `ops/**`, `infra/**` → 인프라 검증
- 루트 파일(`Jenkinsfile`, `compose.yaml`, …) → **전부**
- 판단 불가(첫 빌드 등) → **전부** (건너뛰는 쪽이 더 위험하다)

`develop` 은 통합 게이트라 항상 전부 돈다.

## 게이트 3단

```
기능 브랜치 ──▶ Fast CI          : 영역별 테스트 + advisory 정적분석
develop    ──▶ Integration CI    : 전 영역 + compose 스모크 + 이미지 빌드/push
master     ──▶ Release Gate      : 검증된 develop 트리와 동일한지 + 이미지 승격
              ──▶ Production CD  : 배포 후 verify-jobis-release
```

`master` 는 테스트를 다시 돌리지 않는다. `Master release: verify` 가 **master 트리 ==
검증된 develop 트리** 를 강제하므로, develop 에서 통과한 결과가 그대로 유효하기
때문이다. 대신 이미지를 **재빌드하지 않고 승격**한다(build once, deploy many).

## CI 가 실패했을 때

원인을 만든 사람이 고친다. 한 단계가 실패해도 나머지 단계는 계속 돌도록 해 뒀으므로,
한 번의 파이프라인 결과로 모든 실패를 한꺼번에 볼 수 있다.

## 아직 없는 것 — 스테이징

지금 구조에서 컨테이너가 **실제 서버에서 처음 도는 곳은 운영**이다. `Compose smoke`
단계가 develop 에서 같은 이미지를 띄워 접합부를 확인하므로 위험은 크게 줄었지만,
운영과 같은 호스트·네트워크·nginx·인증서 조합에서 도는 것은 아니다.

스테이징을 붙인다면 이 순서를 권한다. 새 호스트 하나가 필요하다.

1. 호스트 준비 — `ops/prepare-jobis-server` 를 그대로 쓴다(운영과 같은 절차).
2. Jenkins 에 `STAGING_HOST` 전역 환경변수와 `jobis-staging-ssh` 자격증명 추가.
3. `Jenkinsfile` 에 `Deploy staging` 단계 추가:
   - `when { allOf { branch 'develop'; expression { env.STAGING_HOST } } }`
   - `Deploy production` 과 같은 스크립트(`sync-jobis-release-assets` →
     `audit-jobis-server` → `deploy-jobis`)를 `STAGING_HOST` 로 실행
   - 이어서 `ops/verify-jobis-release` 로 스모크
4. 그 뒤 `Master release: verify` 에 "스테이징 배포가 성공한 SHA 인가" 검사를 더한다.

**지금 스텁 단계를 미리 넣지 않은 이유**: 호스트가 없는 상태에서 `when` 으로 항상
건너뛰는 단계는 파이프라인만 복잡하게 만들고 아무것도 검증하지 않는다. 호스트가
준비되는 시점에 위 4단계를 한 번에 넣는 편이 낫다.

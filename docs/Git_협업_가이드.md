# Git 협업 가이드

브랜치 전략, 기능 개발 절차, MR 템플릿 사용 방법을 정리한 팀 공통 가이드입니다.
저장소에서 작업하는 모든 팀원(및 AI 에이전트)은 이 문서를 기준으로 작업합니다.

---

## 1. 브랜치 전략

### 1.1 브랜치 구조

```text
master
├── hotfix/*
└── develop
    ├── feat/ai/*      ├── feat/be/*
    ├── feat/fe/*      ├── feat/infra/*
    ├── fix/*          ├── refactor/*
    ├── docs/*         ├── test/*
    └── chore/*
```

코드 반영 흐름:

```text
feat/* → develop → master
fix/*  → develop
hotfix/* → master + develop (양쪽 모두)
```

### 1.2 브랜치별 역할

| 브랜치 | 역할 | 규칙 |
|---|---|---|
| `master` | 배포·시연 가능한 안정 버전 | 직접 Push 시스템 차단. **병합은 팀장(Maintainer)만** — 배포 MR 전용. 배포 시 태그 생성 (`v0.1.0`) |
| `develop` | 통합 개발 기준 브랜치 (**기본 브랜치**) | 직접 Push 시스템 차단. 모든 작업 브랜치의 시작점. 실행 안 되는 코드 병합 금지 |
| `feat/<영역>/<기능명>` | 새 기능 개발 | 영역: `ai` `rag` `data` `be` `fe` `infra`. 최신 `develop`에서 분기 |
| `fix/<영역>/<수정명>` | 개발 버전 오류 수정 | `develop`에서 분기 → `develop`으로 MR |
| `hotfix/<수정명>` | **배포된** `master`의 긴급 오류 | `master`에서 분기 → `master`와 `develop` 양쪽 MR |
| `refactor/` `docs/` `test/` `chore/` | 구조 개선·문서·테스트·설정 | `develop` 기준, `feat/*`와 동일한 흐름 |

### 1.3 명명 규칙

- 영문 소문자, 단어 사이 하이픈(`-`)
- 작업자 이름이 아니라 **기능 기준**으로 작성
- 하나의 브랜치는 하나의 기능/수정만 담당

```text
좋은 예: feat/ai/resume-analysis, fix/be/token-expiration, feat/rag/vector-store
나쁜 예: donghyeok, backend, final, develop2, feature/rag, jobis-final-final
```

> `feat/ai` 같은 중간 브랜치는 만들지 않습니다. `feat/ai/`는 이름의 분류 표현일 뿐입니다.
> ⚠️ `feature/xxx`, 작업자 이름 브랜치 등 규칙에 안 맞는 브랜치는 정리 대상입니다.

### 1.4 GitLab 저장소 설정 (시스템으로 강제되는 것)

아래는 GitLab 프로젝트 설정으로 적용되어 있어 실수해도 시스템이 막아줍니다.

| 설정 | 내용 |
|---|---|
| 기본 브랜치 = `develop` | 새로 clone 하면 develop이 체크아웃되고, MR의 Target branch도 기본으로 develop을 가리킴 (배포 MR 외에는 그대로 두면 됨) |
| `master`·`develop` 직접 Push 차단 | push가 거부됨. 코드 반영은 MR로만 가능 |
| `master` 병합 권한 | 팀장(Maintainer)만 — 배포 MR 전용 |
| `develop` 병합 권한 | 팀원 누구나. 단, 수정한 코드의 관계자에게 MM·Jira 등으로 공유 후 병합 (팀장 승인 시 바로 병합 가능) |
| Squash 기본 체크 | 병합 시 작업 커밋들이 하나로 정리됨. 그대로 두면 됨 |
| Delete source branch 기본 체크 | 병합되면 작업 브랜치가 자동 삭제됨 |
| 리뷰 스레드 resolve 필수 | 스레드가 모두 resolve 되어야 병합 버튼 활성화. 받은 코멘트는 처리 후 Resolve |

---

## 2. 기능 개발 방법

### 2.1 전체 흐름

```text
이슈 확인/생성 → develop 최신화 → 브랜치 생성 → 개발·커밋
→ Push → MR 생성 → 리뷰 → Squash 병합 → 브랜치 삭제
```

### 2.2 단계별 명령

**1) 이슈 확인** — Jira(또는 GitLab Issue)에서 담당자·작업 범위·중복 여부를 확인합니다.

**2) 최신 develop 반영 후 브랜치 생성**

```bash
git switch develop
git pull origin develop
git switch -c feat/be/analysis-api
```

**3) 개발 및 커밋** — 커밋은 하나의 논리적 변경 단위로, 아래 형식을 사용합니다.

```text
<타입>(<영역>): <작업 내용>

예: feat(be): 분석 결과 조회 API 추가
    fix(fe): 로그인 입력값 검증 오류 수정
    docs: API 명세서 업데이트
```

| 타입 | 의미 | | 타입 | 의미 |
|---|---|---|---|---|
| `feat` | 기능 추가 | | `test` | 테스트 |
| `fix` | 버그 수정 | | `chore` | 설정·패키지·빌드 |
| `refactor` | 구조 개선 | | `style` | 포맷·스타일 |
| `docs` | 문서 | | `perf` / `ci` | 성능 / CI 설정 |

`수정`, `최종`, `진짜 최종` 같은 메시지는 사용하지 않습니다.

**4) Push 및 MR 생성**

```bash
git push -u origin feat/be/analysis-api
```

GitLab에서 `develop`을 Target으로 MR을 생성하고, 템플릿을 채웁니다. (→ 3장)

**5) 리뷰 및 병합**

- 최소 1명의 리뷰(승인) 후 병합 (본인 MR 셀프 승인·병합 금지)
- 병합 전 수정한 코드의 관계자에게 MM·Jira 등으로 공유 (팀장 승인 시 바로 병합 가능)
- 받은 리뷰 코멘트는 처리 후 스레드 Resolve — 전부 resolve 되어야 병합 버튼이 활성화됩니다
- 병합 옵션 **Squash commits** + **Delete source branch**는 기본 체크되어 있으니 그대로 둡니다
- 장기 작업 브랜치는 병합 전 최신 develop을 merge로 반영:

```bash
git fetch origin
git merge origin/develop   # 충돌 해결 후
git commit -m "chore: develop 병합 충돌 해결"
```

**6) 병합 후 로컬 정리**

```bash
git switch develop
git pull origin develop
git branch -d feat/be/analysis-api
```

### 2.3 주의사항

- `application.yml`, `build.gradle`, `package.json`, DB 스키마 등 **충돌 잦은 공통 파일은 수정 전에 팀에 공유**합니다.
- API·WebSocket 메시지·환경 변수 등 **공통 규격 변경은 관련 담당자에게 먼저 공유**하고 MR에 명시합니다.
- 미완성 기능은 develop에 병합하지 않습니다. 부분 병합이 필요하면 Feature Flag, Mock, 모듈 분리 등을 사용하고 MR에 제한 사항을 적습니다.
- 공유된 원격 브랜치에서 rebase·force push 하지 않습니다.

---

## 3. MR 템플릿 사용 방법

### 3.1 템플릿 선택

MR 작성 화면 상단의 **"Choose a template"** 드롭다운에서 선택합니다.

| 템플릿 | 언제 사용 | Target |
|---|---|---|
| **Default** | 기능 개발, 리팩터링, 문서, 설정 등 일반 작업 전부 | `develop` |
| **Fix** | 아직 배포되지 않은 개발 버전의 오류 수정 | `develop` |
| **Hotfix** | 이미 배포된 `master` 버전의 긴급 오류 | `master` (+ 이후 `develop`) |

고민되면 **Default**를 쓰면 됩니다. 각 섹션에 작성 예시가 HTML 주석(`<!-- -->`)으로
들어 있어 편집 화면에서 참고할 수 있고, 주석은 제출된 MR 본문에는 표시되지 않습니다.

### 3.2 MR 제목 형식

```text
[JIRA-이슈키] <타입>(<영역>): <작업 내용>

예: [JOBIS-123] feat(ai): 이력서 분석 기능 구현
    [JOBIS-177] fix(be): 토큰 만료 오류 수정
```

Jira 이슈가 없으면 이슈 키 없이 `<타입>(<영역>): <작업 내용>`만 적습니다.

### 3.3 작성 원칙

템플릿은 **체크리스트가 맨 위**에 있습니다. MR을 열자마자 확인할 것부터 점검하고 본문을 채웁니다.
**필수는 "작업 내용"과 "확인 방법" 두 섹션뿐입니다.** 나머지는 해당 없으면 섹션째 삭제하세요.

| 섹션 | 필수 | 작성 요령 |
|---|---|---|
| 체크리스트 | ✅ | 실제로 확인한 것만 체크 (허위 체크 금지). 병합 전 확인 항목은 병합하는 사람이 체크 |
| 작업 내용 | ✅ | 핵심 변경만 1~3개 |
| 확인 방법 | ✅ | 리뷰어가 그대로 따라 할 최소 단계 |
| 관련 이슈 및 참고 사항 | 선택 | Jira 이슈 URL 첨부 (`https://ssafy.atlassian.net/browse/S15P11C202-88`), 제한 사항·후속 작업. 없으면 삭제 |
| 변경 영향 | 선택 | API/DB/환경변수/화면/의존성 중 해당 항목만 체크하고 상세를 한 줄씩. 영향 없으면 삭제 |

- 화면 변경이 있으면 스크린샷이나 GIF를 첨부합니다.
- API/DB 변경 상세는 명세 문서에 기록하고 MR에는 링크만 적어도 됩니다.
- 체크리스트에는 팀 규칙 준수 항목이 포함되어 있습니다: 최신 develop 분기·브랜치 명명, 제목 형식,
  **MM에 관계자·팀장 태그하여 MR 공유**, **Jira 이슈 반영(상태 변경 + 결과물 링크)**.

### 3.4 작성 예시 (Default 템플릿)

```markdown
## 체크리스트
- [x] 최신 `develop`에서 분기했고, 브랜치명이 `<타입>/<영역>/<작업명>` 규칙을 따릅니다.
- [x] MR 제목이 `[JOBIS-이슈키] <타입>(<영역>): <작업 내용>` 형식입니다.
- [x] Target Branch가 `develop`입니다.
- [x] 로컬에서 직접 실행해 확인했습니다.
- [x] 민감 정보와 디버깅 로그가 없습니다.
- [x] Squash / Delete source branch 체크가 켜져 있습니다. (기본값 유지)
- [x] MR 링크를 Mattermost에 관계자·팀장을 태그하여 공유했습니다.
- [x] Jira 이슈에 작업 내용이 반영되어 있습니다. (상태 변경 + MR 등 결과물 링크 첨부)

**병합 전 확인** (병합하는 사람이 체크)
- [ ] 작성자 외 1명 이상의 승인(Approve)을 받았습니다.
- [ ] 리뷰 스레드를 모두 resolve 했습니다.

## 작업 내용
- 분석 결과 조회 API(GET /api/v1/analyses/{id}) 추가
- 조회 권한 검증 로직 추가

## 확인 방법
1. 백엔드 실행 후 로그인해서 토큰을 발급받는다.
2. GET /api/v1/analyses/1 호출 → 본인 분석이면 200, 타인 것이면 403 확인.

## 관련 이슈 및 참고 사항
- https://ssafy.atlassian.net/browse/S15P11C202-145

## 변경 영향
- [x] API 변경
  - GET /api/v1/analyses/{id} 신규 추가 (응답 형식은 API 명세서 참고)
```

### 3.5 Hotfix 흐름 요약

```bash
git switch master && git pull origin master
git switch -c hotfix/login-error
# 수정 → 커밋 → push
```

1. `master` 대상 MR 생성 (Hotfix 템플릿) — Target을 `master`로 직접 변경, **Delete source branch 체크 해제**
2. 병합·배포 후 수정 버전 태그 (`v1.0.0` → `v1.0.1`)
3. **같은 브랜치로 `develop` 대상 MR을 한 번 더 생성** — 양쪽 반영 전까지 브랜치 삭제 금지

---

## 4. 핵심 규칙 요약

1. `master`·`develop`에 직접 Push하지 않는다. (시스템 차단)
2. 기본 브랜치는 `develop` — MR의 기본 Target도 develop이다.
3. 모든 작업 브랜치는 최신 `develop`에서 생성한다. (hotfix만 `master`)
4. `master` 병합은 팀장만 한다. (배포 MR 전용)
5. MR은 작성자 외 1명 이상의 승인 후 병합하고, 리뷰 스레드는 모두 resolve 한다.
6. 병합 시 Squash + Delete source branch 기본값을 유지한다. (Hotfix만 소스 삭제 해제)
7. 병합 전 작성자가 직접 실행·테스트한다. 실행 안 되는 코드는 병합하지 않는다.
8. MR은 MM에 관계자·팀장을 태그해 공유하고, Jira 이슈에 반영한다.
9. 공통 규격(API·DB·환경 변수) 변경은 담당자에게 공유하고 MR에 명시한다.
10. Hotfix는 `master`와 `develop` 양쪽에 반영한다.

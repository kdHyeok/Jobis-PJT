# frontend 작업 지침

루트 [AGENTS.md](../AGENTS.md)를 먼저 읽는다. 이 파일은 프론트엔드에만 해당하는 규칙이다.

## CI에서 이 디렉토리가 책임지는 것

- **고칠 파일**: [ci/test.sh](ci/test.sh) — 프론트엔드에서 무엇을 검사하는가.
- **고치지 않을 파일**: 루트 `Jenkinsfile` — Node 이미지와 스테이지 배치는 뼈대가 책임진다.

현재 `ci/test.sh`는 `npm ci --ignore-scripts` 뒤 `npm run build`(= `vue-tsc -b && vite build`)만
실행한다.

## 알려진 공백 (빚으로 취급한다)

`package.json`에 다음이 정의돼 있으나 **CI가 아직 실행하지 않는다.**

- `npm run test` — `node --test tests/*.test.ts && vitest run`
- `npm run test:e2e` — `playwright test` (`tests/e2e/` 에 시나리오 존재)

작성된 테스트가 아무것도 지키지 못하는 상태다. 붙일 때는 게이트 구분을 지킨다 —
빠른 unit/vitest는 `ci/test.sh`에, 느린 Playwright E2E는 develop 전용 스테이지에 둔다.
E2E를 기능 브랜치 게이트에 넣으면 MR 피드백이 느려지고 flaky 실패가 merge를 막는다.

## 타입 규칙

`tsconfig.app.json`은 `@vue/tsconfig/tsconfig.dom.json`을 extends하고, 거기서
`lib`이 **`["ES2020", "DOM", "DOM.Iterable"]`로 고정**돼 있다. Vite 빌드 타깃에 맞춘
의도적 설정이다.

- **ES2021 이상 빌트인을 그냥 쓰면 빌드가 깨진다.** `String.prototype.replaceAll`,
  `Object.hasOwn`, `Array.prototype.at` 등이 여기 해당한다.
  - `replaceAll(a, b)` → `split(a).join(b)` 또는 `replace(/a/g, b)`
- `lib`을 올리는 것은 프로젝트 전체의 브라우저 지원 경계를 넓히는 결정이다.
  파일 하나 때문에 올리지 말고, 필요하면 별도 MR로 근거와 함께 제안한다.
- 로컬에서 `npm run typecheck`로 확인하고 올린다. CI가 이걸로 실패한 전례가 있다.

## 기능을 추가·수정할 때

1. 백엔드 API 계약이 바뀌었으면 타입도 같은 MR에서 맞춘다.
2. 화면을 추가하면 최소한 타입체크가 통과하는지 확인한다.
3. CI가 깨지면 원인을 만든 사람이 고친다.

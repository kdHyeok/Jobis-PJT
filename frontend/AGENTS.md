# frontend 작업 지침

루트 [AGENTS.md](../AGENTS.md) 를 먼저 읽는다. 여기서는 이 디렉토리에만 해당하는 것을 적는다.

## CI — 무엇이 돌고, 무엇을 고쳐야 하는가

이 영역의 검사는 **[frontend/ci-checks](ci-checks)** 가 정한다. `Jenkinsfile` 은 언제
돌릴지만 정한다. 검사를 추가·변경할 때 `Jenkinsfile` 을 고치지 않는다.

```
./frontend/ci-checks test   # required — npm ci && build + Node/Vitest tests
./frontend/ci-checks lint   # advisory — eslint src
```

`frontend/**` 가 바뀐 MR 에서만 이 단계가 돈다.

## 기능을 추가할 때

- 타입 오류는 `vue-tsc` 가 잡는다. `npm run build` 가 곧 타입체크다.
- ESLint 는 기존 지적을 보이는 advisory 다. 지적 0건을 유지하게 되면 `catchError` 를 걷어내고
  required 로 올릴 수 있다.
- 의존성을 추가하면 `package-lock.json` 을 함께 커밋한다. CI 는 `npm ci` 라 lock 이
  package.json 과 어긋나면 실패한다.

## 스타일 규약

- 색은 `src/styles/base.css` 의 팔레트를 쓴다. 새 색을 직접 박지 말고 기존 토큰이나
  `color-mix(in srgb, var(--토큰) N%, #fff)` 로 파생시킨다.
- 움직이는 배경 위에 글자를 올릴 때는 최악 프레임 기준 대비를 확인한다. 정적 배경
  기준으로만 맞추면 프레임에 따라 AA 미달이 된다(랜딩·로그인이 그 사례다).
- 로고·마스코트는 `src/assets/` 의 이미지를 쓴다. CSS 도형으로 다시 그리지 않는다.

# frontend 작업자 진입점

@AGENTS.md

루트 [../AGENTS.md](../AGENTS.md)가 상위 규약이다.

CI에서 고칠 파일은 [ci/test.sh](ci/test.sh)다. 루트 `Jenkinsfile`은 Infra 소유다.

타입 주의: `lib`이 ES2020으로 고정돼 있어 `replaceAll` 같은 ES2021 빌트인은 빌드를 깨뜨린다.
올리기 전에 `npm run typecheck`.

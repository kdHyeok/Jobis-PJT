#!/usr/bin/env bash
# Frontend CI — 프론트엔드 개발자 소유.
#
# 호출: Jenkinsfile 'Frontend: typecheck & build' 스테이지가 workspace 루트에서
#       `bash frontend/ci/test.sh` 로 실행한다. Node 이미지는 Jenkinsfile이 고른다.
#
# `npm ci` 는 package-lock.json 이 package.json 과 어긋나면 실패한다. 의존성을
# 바꿨다면 락파일을 같은 커밋에 포함한다.
#
# 알려진 공백(의도된 현재 상태가 아니라 빚이다):
#   `npm run test`(node --test + vitest)와 `npm run test:e2e`(playwright)가
#   작성돼 있으나 아직 여기서 실행하지 않는다. 추가할 때는 Gate 구분을 지킨다 —
#   unit/vitest 는 이 파일에, 느린 E2E 는 develop 전용 스테이지에 둔다.
set -euo pipefail

cd "$(dirname "$0")/.."

npm ci --ignore-scripts

# vue-tsc 타입체크 + vite 프로덕션 빌드
npm run build

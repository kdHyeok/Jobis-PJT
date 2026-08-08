#!/usr/bin/env sh
# Backend CI — 백엔드 개발자 소유.
#
# 호출: Jenkinsfile 'Backend: test & package' 스테이지가 workspace 루트에서
#       `sh backend/ci/test.sh` 로 실행한다.
#
# 실행 환경(컨테이너 이미지, PostgreSQL 컨테이너, DB_* 환경변수)은 Jenkinsfile이
# 준비한다. 여기서는 "무엇을 검사하는가"만 정한다. 새 인프라 의존성(Redis 등)이
# 필요하면 이 파일이 아니라 Jenkinsfile을 바꾸는 MR을 올리고 Infra 리뷰를 받는다.
#
# 산출물 계약: 이 스크립트는 backend/backend.jar 를 남겨야 한다.
# Jenkinsfile이 그 파일을 stash 하고, JUnit XML을 build/test-results/test 에서 읽는다.
set -eu

cd "$(dirname "$0")/.."

chmod +x gradlew
./gradlew clean test bootJar --no-daemon

jar="$(find build/libs -maxdepth 1 -type f -name '*.jar' ! -name '*-plain.jar' -print -quit)"
test -n "$jar" || { echo "실행 가능한 JAR 없음" >&2; exit 1; }
cp "$jar" backend.jar

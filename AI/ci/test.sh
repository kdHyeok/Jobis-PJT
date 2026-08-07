#!/usr/bin/env bash
# JOBIS AI CI — AI 개발자 소유.
#
# 호출: Jenkinsfile 'AI: test' 스테이지가 workspace 루트에서
#       `bash AI/ci/test.sh` 로 실행한다. 컨테이너 이미지는 Jenkinsfile이 고른다.
#
# `--frozen` 은 uv.lock 이 pyproject.toml 과 어긋나면 실패한다. 의존성을 바꿨다면
# 락파일을 같은 커밋에서 갱신한다 — CI에서 새로 풀라고 `--frozen` 을 떼지 않는다.
# 그러면 CI가 검증한 의존성과 배포되는 의존성이 달라진다.
set -euo pipefail

export PYTHONUTF8=1
export UV_CACHE_DIR=/tmp/jobis-uv-cache
export UV_PROJECT_ENVIRONMENT=/tmp/jobis-ai-venv

python -m venv /tmp/jobis-uv-bootstrap
/tmp/jobis-uv-bootstrap/bin/python -m pip install \
  --disable-pip-version-check --no-cache-dir uv==0.11.32

cd "$(dirname "$0")/.."

# 회귀 테스트 — 실 LLM 없이 돈다(비용 0). 새 기능은 여기 붙는다.
/tmp/jobis-uv-bootstrap/bin/uv run \
  --frozen --extra dev --extra prototype pytest -q

# 선언 표·관문 순서가 import 단계에서 깨지지 않는지 확인한다.
/tmp/jobis-uv-bootstrap/bin/uv run \
  --frozen --extra prototype python -m jobis_ai.explain \
  > /tmp/jobis-ai-explain.txt

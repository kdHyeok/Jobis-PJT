# syntax=docker/dockerfile:1
# JOBIS fake-ai — node 서버 + codex sidecar(파이썬, uv)용 이미지
#
# LLM 폴백 관련:
#   - LLM_DISABLED=1 이면 외부 LLM 호출 없음 (로컬/CI 기본)
#   - LLM_PROVIDER=codex 는 이미지에 내장된 uv sidecar 사용
#   - LLM_PROVIDER=claude 는 claude CLI 필요 → --build-arg WITH_CLAUDE=1 로 빌드

FROM node:24-slim

# uv (codex sidecar의 파이썬 런타임/의존성 관리자)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
# 관리형 파이썬을 모든 사용자가 읽을 수 있는 경로에 설치
ENV UV_PYTHON_INSTALL_DIR=/usr/local/share/uv-python

WORKDIR /app

# node 의존성 레이어 (package.json이 안 바뀌면 캐시)
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

# 파이썬 sidecar 의존성을 빌드 시 미리 준비 (첫 요청 때 다운로드 지연 방지)
COPY pyproject.toml uv.lock ./
COPY codex_oauth_adapter ./codex_oauth_adapter
RUN uv python install 3.11 && uv sync --frozen --extra server --no-dev

# claude CLI (선택 — 프로덕션에서 LLM_PROVIDER=claude일 때만 필요)
ARG WITH_CLAUDE=0
RUN if [ "$WITH_CLAUDE" = "1" ]; then npm install -g @anthropic-ai/claude-code; fi

COPY . .
RUN chown -R node:node /app
USER node

ENV NODE_ENV=production
EXPOSE 8000
CMD ["node", "server.js"]

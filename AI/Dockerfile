FROM python:3.11-slim AS dependencies

ARG UV_VERSION=0.11.32

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_PROJECT_ENVIRONMENT=/opt/jobis-ai/.venv

WORKDIR /build

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra prototype --no-install-project


FROM python:3.11-slim AS runtime

ENV PATH=/opt/jobis-ai/.venv/bin:${PATH} \
    PYTHONPATH=/opt/jobis-ai/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SESSION_STORE=sqlite \
    SESSION_DB_PATH=/var/lib/jobis-ai/sessions.sqlite3 \
    JOBIS_AUDIT_LOG=/var/lib/jobis-ai/logs/audit.jsonl \
    POSTINGS_DB_DIR="/opt/jobis-ai/sample_data/db내 공고파일"

RUN groupadd --gid 1000 jobiss \
    && useradd --uid 1000 --gid jobiss --create-home --shell /usr/sbin/nologin jobiss \
    && mkdir -p /opt/jobis-ai /var/lib/jobis-ai/logs /var/lib/jobis-ai/codex \
    && chown -R jobiss:jobiss /opt/jobis-ai /var/lib/jobis-ai

WORKDIR /opt/jobis-ai

COPY --from=dependencies /opt/jobis-ai/.venv /opt/jobis-ai/.venv
COPY --chown=jobiss:jobiss src ./src
COPY --chown=jobiss:jobiss sample_data ./sample_data
COPY --chown=jobiss:jobiss NOTICE ./NOTICE

USER jobiss

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=10 \
    CMD python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)); assert d['status']=='ok' and d['service']=='jobis-ai-v2bridge'"

ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["jobis_ai.v2bridge.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

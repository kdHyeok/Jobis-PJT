FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir ".[prototype]"

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "jobis_ai.v2bridge.app:app", "--host", "0.0.0.0", "--port", "8000"]

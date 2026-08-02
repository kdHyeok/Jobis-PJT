FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
RUN addgroup --system jobiss && adduser --system --ingroup jobiss jobiss
WORKDIR /app
COPY pyproject.toml ./
RUN python -m pip install .
COPY app ./app
USER jobiss
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

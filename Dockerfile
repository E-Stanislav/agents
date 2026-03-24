FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY src/ src/
COPY scripts/ scripts/
COPY llm_config.yaml .

RUN mkdir -p /app/tasks /app/output /app/templates

# По умолчанию 8000; переопределяется через APP_PORT при запуске контейнера
ENV APP_PORT=8000
EXPOSE 8000

CMD ["/bin/sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${APP_PORT:-8000} --reload"]

FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./

RUN python3 -m venv /app/.venv
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.cache/pip \
    uv sync --frozen --active

FROM base AS runtime
RUN useradd -m -u 10001 app

COPY --from=builder /app/.venv /app/.venv

COPY recommendations_service.py /app/recommendations_service.py
COPY config.py /app/config.py
COPY settings.py /app/settings.py

USER app
EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "recommendations_service:app", "--host", "0.0.0.0", "--port", "8000"]

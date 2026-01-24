FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

FROM base AS builder
ADD https://astral.sh/uv/install.sh /tmp/uv-install.sh
RUN sh /tmp/uv-install.sh && rm /tmp/uv-install.sh
COPY pyproject.toml uv.lock /app/
RUN /root/.local/bin/uv sync --frozen

FROM base AS runtime
RUN useradd -m -u 10001 app
COPY --from=builder /app/.venv /app/.venv
COPY . /app
USER app
EXPOSE 8000
CMD ["uvicorn", "recommendations_service:app", "--host", "0.0.0.0", "--port", "8000"]

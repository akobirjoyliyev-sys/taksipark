# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv
RUN useradd --create-home --uid 10001 kassa

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .

COPY alembic.ini ./
COPY migrations ./migrations

USER kassa
EXPOSE 8000
CMD ["uvicorn", "app.webhooks.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]


FROM base AS test
USER root
RUN pip install ".[dev]"
COPY tests ./tests
USER kassa
CMD ["pytest", "-q"]

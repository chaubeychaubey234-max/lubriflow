FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.12.19 && useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend ./backend
COPY alembic.ini ./
RUN mkdir -p /app/var/documents && chown -R app:app /app
ENV PYTHONPATH=/app/backend PYTHONUNBUFFERED=1
USER app
EXPOSE 8000

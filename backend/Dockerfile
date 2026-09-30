FROM python:3.13-slim

WORKDIR /app

# uv is the only installer used in this image (faster resolution, no pip).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# No gcc/libpq-dev needed: every dependency ships a prebuilt wheel for
# python 3.13 (psycopg2 was removed — the app uses asyncpg exclusively).
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql postgresql-contrib redis-server curl procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini .

RUN chmod +x ./scripts/start.sh

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["./scripts/start.sh"]

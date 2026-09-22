FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev postgresql postgresql-contrib redis-server curl procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini .

RUN chmod +x ./scripts/start.sh

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["./scripts/start.sh"]

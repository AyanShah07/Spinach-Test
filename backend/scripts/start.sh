#!/usr/bin/env bash
set -e

echo "=================================================="
echo " Starting MarTech Intelligence All-In-One Container "
echo "=================================================="

# 1. Start Local Redis if REDIS_URL is not set or points to localhost
if [ -z "$REDIS_URL" ] || [[ "$REDIS_URL" == *"localhost"* ]] || [[ "$REDIS_URL" == *"127.0.0.1"* ]]; then
    echo "==> Starting embedded Redis server..."
    mkdir -p /var/lib/redis
    redis-server --daemonize yes --dir /var/lib/redis
    export REDIS_URL="redis://127.0.0.1:6379/0"
    
    # Wait for Redis
    for i in {1..15}; do
        if redis-cli ping >/dev/null 2>&1; then
            echo "==> Redis is ready."
            break
        fi
        sleep 1
    done
else
    echo "==> Using external Redis: $REDIS_URL"
fi

# 2. Start Local PostgreSQL if DATABASE_URL is not set or points to localhost
if [ -z "$DATABASE_URL" ] || [[ "$DATABASE_URL" == *"localhost"* ]] || [[ "$DATABASE_URL" == *"127.0.0.1"* ]]; then
    echo "==> Setting up embedded PostgreSQL server..."
    PG_VERSION=$(ls -1 /usr/lib/postgresql/ | head -n 1)
    PG_BIN="/usr/lib/postgresql/${PG_VERSION}/bin"
    PG_DATA="/var/lib/postgresql/data"

    if [ ! -f "$PG_DATA/PG_VERSION" ]; then
        echo "==> Initializing PostgreSQL data directory at $PG_DATA..."
        mkdir -p "$PG_DATA"
        chown -R postgres:postgres "$PG_DATA"
        su - postgres -c "$PG_BIN/initdb -D $PG_DATA --auth-local=trust --auth-host=md5"
        
        # Configure postgres to listen on localhost
        echo "listen_addresses = '127.0.0.1'" >> "$PG_DATA/postgresql.conf"
        echo "host all all 127.0.0.1/32 md5" >> "$PG_DATA/pg_hba.conf"
    fi

    echo "==> Starting PostgreSQL daemon..."
    su - postgres -c "$PG_BIN/pg_ctl -D $PG_DATA -o '-c shared_buffers=32MB -c max_connections=30' -l /var/log/postgresql.log start"

    # Wait for PostgreSQL
    for i in {1..30}; do
        if su - postgres -c "$PG_BIN/pg_isready -h 127.0.0.1 -p 5432" >/dev/null 2>&1; then
            echo "==> PostgreSQL is ready."
            break
        fi
        sleep 1
    done

    # Ensure postgres role has password 'postgres' and 'martech' database exists
    su - postgres -c "$PG_BIN/psql -h 127.0.0.1 -c \"ALTER USER postgres WITH PASSWORD 'postgres';\"" || true
    su - postgres -c "$PG_BIN/psql -h 127.0.0.1 -tc \"SELECT 1 FROM pg_database WHERE datname = 'martech'\"" | grep -q 1 || \
        su - postgres -c "$PG_BIN/psql -h 127.0.0.1 -c \"CREATE DATABASE martech OWNER postgres;\""

    export DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/martech"
    export DATABASE_URL_SYNC="postgresql://postgres:postgres@127.0.0.1:5432/martech"
else
    echo "==> Using external DATABASE_URL."
fi

# 3. Apply Alembic migrations
echo "==> Applying database migrations..."
alembic upgrade head

# 4. Auto-seed demo data if not already present
echo "==> Seeding initial demo data (campaigns, customers, events)..."
python -m scripts.generate_synthetic_data --customers 200 --events 500 --campaigns 10 || echo "Initial seed completed or skipped."

# 5. Start FastAPI application
PORT="${PORT:-8000}"
echo "=================================================="
echo " Starting FastAPI application on port $PORT"
echo "=================================================="
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

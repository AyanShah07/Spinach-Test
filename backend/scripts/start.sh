#!/usr/bin/env bash
set -e

# Support direct command execution if arguments are passed (e.g. docker run ... python -m app.workers)
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

SERVICE_ROLE="${SERVICE_ROLE:-all-in-one}"

echo "=================================================="
echo " Starting MarTech Platform (Role: ${SERVICE_ROLE}) "
echo "=================================================="

# 1. Start Local Redis if REDIS_URL is not set or points to localhost
if [ -z "$REDIS_URL" ] || [[ "$REDIS_URL" == *"localhost"* ]] || [[ "$REDIS_URL" == *"127.0.0.1"* ]]; then
    if [ "$SERVICE_ROLE" = "all-in-one" ]; then
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
    fi
else
    echo "==> Using external Redis: $REDIS_URL"
fi

# 2. Start Local PostgreSQL if DATABASE_URL is not set or points to localhost
if [ -z "$DATABASE_URL" ] || [[ "$DATABASE_URL" == *"localhost"* ]] || [[ "$DATABASE_URL" == *"127.0.0.1"* ]]; then
    if [ "$SERVICE_ROLE" = "all-in-one" ]; then
        echo "==> Setting up embedded PostgreSQL server..."
        PG_VERSION=$(ls -1 /usr/lib/postgresql/ | head -n 1)
        PG_BIN="/usr/lib/postgresql/${PG_VERSION}/bin"
        PG_DATA="/var/lib/postgresql/data"

        mkdir -p /var/run/postgresql "$PG_DATA"
        chown -R postgres:postgres /var/run/postgresql "$PG_DATA"

        if [ ! -f "$PG_DATA/PG_VERSION" ]; then
            echo "==> Initializing PostgreSQL data directory at $PG_DATA..."
            su - postgres -c "$PG_BIN/initdb -D $PG_DATA"
            
            # Configure postgres to listen on localhost with trust auth inside container
            echo "listen_addresses = '127.0.0.1'" >> "$PG_DATA/postgresql.conf"
            cat <<EOF > "$PG_DATA/pg_hba.conf"
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
EOF
        fi

        echo "==> Starting PostgreSQL daemon..."
        # Log inside $PG_DATA to avoid permission issues in /var/log
        su - postgres -c "$PG_BIN/pg_ctl -D $PG_DATA -o '-c shared_buffers=32MB -c max_connections=30' -l $PG_DATA/postgresql.log start"

        # Wait for PostgreSQL
        PG_READY=0
        for i in {1..30}; do
            if su - postgres -c "$PG_BIN/pg_isready -h 127.0.0.1 -p 5432" >/dev/null 2>&1; then
                echo "==> PostgreSQL is ready."
                PG_READY=1
                break
            fi
            sleep 1
        done

        if [ "$PG_READY" -ne 1 ]; then
            echo "==> ERROR: PostgreSQL failed to start. Displaying log output:"
            cat "$PG_DATA/postgresql.log" || true
            exit 1
        fi

        # Ensure postgres role and 'martech' database exist
        su - postgres -c "$PG_BIN/psql -c \"ALTER ROLE postgres WITH PASSWORD 'postgres';\"" || true
        su - postgres -c "$PG_BIN/psql -tc \"SELECT 1 FROM pg_database WHERE datname = 'martech'\"" | grep -q 1 || \
            su - postgres -c "$PG_BIN/psql -c \"CREATE DATABASE martech OWNER postgres;\""

        export DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/martech"
        export DATABASE_URL_SYNC="postgresql://postgres:postgres@127.0.0.1:5432/martech"
        echo "==> Embedded PostgreSQL configured and ready."
    fi
else
    echo "==> Using external DATABASE_URL."
fi

# Execute according to role
if [ "$SERVICE_ROLE" = "worker" ]; then
    echo "=================================================="
    echo " Starting Standalone Event Worker Fleet Instance"
    echo "=================================================="
    exec python -m app.workers
elif [ "$SERVICE_ROLE" = "api" ]; then
    echo "==> Applying database migrations..."
    alembic upgrade head
    PORT="${PORT:-8000}"
    echo "=================================================="
    echo " Starting Dedicated FastAPI Server on port $PORT"
    echo "=================================================="
    export RUN_EMBEDDED_WORKER=false
    exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
else
    # Default: all-in-one mode (Render free tier / quick demo)
    echo "==> Applying database migrations..."
    alembic upgrade head

    echo "==> Seeding initial demo data (campaigns, customers, events)..."
    python -m scripts.generate_synthetic_data --customers 200 --events 500 --campaigns 10 || echo "Initial seed completed or skipped."

    PORT="${PORT:-8000}"
    echo "=================================================="
    echo " Starting All-In-One FastAPI on port $PORT"
    echo "=================================================="
    exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
fi

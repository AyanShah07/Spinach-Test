# MarTech Intelligence & Campaign Decision Engine

A working demo for durable event ingestion, customer engagement scoring, audience previews, and grounded campaign analysis. FastAPI + PostgreSQL + Redis Streams power a Next.js console; the backend also includes a lightweight HTML console.

## Run with Docker

```bash
cd backend
cp .env.example .env
docker compose up --build
```

The API image runs Alembic migrations before startup. PostgreSQL and Redis data use named volumes. The embedded worker is enabled by default; the demo uses rule-based AI fallback unless a provider is explicitly configured.

- Backend console: http://localhost:8000/
- API documentation: http://localhost:8000/docs
- Readiness: http://localhost:8000/api/v1/system/health
- Liveness: http://localhost:8000/api/v1/system/live

Start the richer frontend in another terminal (Node 24 recommended):

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. The browser calls a same-origin `/api/backend` proxy, so backend hostnames and CORS settings do not need to be embedded in the client. Set `BACKEND_URL` in `frontend/.env.local` if the API uses another address.

## Run without Docker

Install Python 3.11+ and make PostgreSQL 16+ and Redis 6.2+ available locally.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
cp .env.example .env
# Adjust DATABASE_URL and REDIS_URL in .env for your services.
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For runtime-only installation use `requirements.lock`. Dependency inputs are `requirements.txt` and `requirements-dev.txt`; their lockfiles pin transitive dependencies. Regenerate with:

```bash
uv pip compile --universal --python-version 3.11 requirements.txt -o requirements.lock
uv pip compile --universal --python-version 3.11 -c requirements.lock requirements-dev.txt -o requirements-dev.lock
```

Schema changes use migrations. `AUTO_CREATE_TABLES=true` is an explicit development-only escape hatch, never required for normal startup. The initial migration adopts the original unversioned demo tables without deleting their data; the next revision records stream message IDs for recovery. Back up existing data before migrations. Historical attributes already erased by old code and previously clamped scores cannot be recovered automatically.

## Seed and explore

```bash
# From backend, with migrations applied:
python -m scripts.generate_synthetic_data
# In Docker:
docker compose exec api python -m scripts.generate_synthetic_data
# Full assessment scale, with reproducible timestamps:
python -m scripts.generate_synthetic_data --customers 50000 --events 100000 --campaigns 20 --as-of 2026-09-22T00:00:00+00:00
```

Defaults create 500 customers, 1,000 events and 10 campaigns. Repeating the same seed, dimensions and reference timestamp skips existing customers/campaigns/events. Seeded events enter the durable outbox; the worker updates profiles asynchronously. Without `--as-of`, timestamps are anchored to today's UTC midnight. IDs and payloads are reproducible for the same parameters. Use a current reference date when testing the 30-day recency filter.

In the console:

1. Check service health and backlog.
2. Load `cust_000001` to inspect its current score and timeline.
3. Send an event; the console polls its processing status.
4. Preview an audience. Repeating a preview does not consume send limits.
5. Analyze `camp_000`; the source badge distinguishes AI from fallback.
6. Inspect failed events and replay them after fixing the underlying cause.

## Behavior and operational guarantees

- **Ingestion:** single and batch requests return 202 only after committing events and outbox rows. Event IDs are unique. Batch persistence failures use per-item savepoints; invalid request schemas return 422 for the request. The rate limiter counts events, including every item in a batch.
- **Delivery:** the worker is the only stream publisher. It retries failures, reclaims idle pending messages, and acknowledges/deletes only terminal work. Published pending events are periodically checked against their stream IDs and republished if Redis lost them. This is an at-least-once design, with idempotent application in PostgreSQL.
- **Concurrency:** event and customer row locks serialize updates to each customer. Profile attributes survive event processing.
- **Scoring:** late events decay into a monotonic reference time. Raw accumulators are not clamped; displayed/ranked scores are decayed to the present and bounded to [-50, 200]. This preserves order independence of accumulated contributions.
- **Consent:** new customers default to not opted in. Synthetic profiles explicitly set demo consent. Unsubscribe and complaint events clear channel eligibility. Event ingestion never grants consent.
- **Audiences:** streamed SQL eligibility filtering, confirmed-send exclusion for 24 hours, and a bounded min-heap. There is no arbitrary 50,000-candidate cutoff and no per-customer Redis network call. All objectives currently rank by engagement; objective-specific strategies remain a product extension. Recommendations are previews, not send reservations.
- **AI:** facts are rendered from stored aggregates; generated recommendations are advisory. Timeouts/errors use a rule-based fallback. The circuit breaker has a cooldown and a single recovery probe.
- **Health:** readiness returns 503 when DB, Redis or worker availability is degraded. Unread messages, pending acknowledgements, unpublished outbox rows and unresolved failures are separate counts. Heartbeats report worker availability, not a guarantee of throughput.
- **Retention:** acknowledged stream entries are removed. Terminal outbox entries are cleaned after seven days; pending durable work is retained. Monitor database capacity and queue lag; the demo has no automatic overload admission control or archival policy for customer/event history.

To run workers separately, set `RUN_EMBEDDED_WORKER=false` for the API and run `python -m app.workers`, or use `docker compose --profile workers up` after adjusting the API setting. Consumer IDs are unique by default. A stream belongs to one consumer group; use separate streams for additional independent consumers.

## Security settings

Local development works without a key. For a protected single-workspace deployment:

- Set `APP_ENV=production`, an `API_KEY` with at least 32 random characters, and an explicit JSON `CORS_ORIGINS` allowlist.
- Send `X-API-Key` for event/customer/campaign/audience/DLQ endpoints. Both consoles have a connection-settings field; the Next.js console keeps the key only in memory.
- `/system/live` and `/system/health` remain unauthenticated for monitoring and expose no event payloads.
- Terminate HTTPS at your host/proxy, use private database/Redis connections, and store secrets in the hosting provider's secret manager.

This is single-workspace API-key protection. User login, tenant isolation, role-based permissions, automated backups, and production load/availability targets require deployment-specific work.

## Deploy on Render (Single Free Web Service)

The backend includes an embedded HTML console at `/` and runs migrations + embedded worker on startup, allowing a complete working demo on Render's free tier.

1. Create managed data stores:
   - **PostgreSQL**: Render PostgreSQL or Neon (`postgresql+asyncpg://...`)
   - **Redis**: Render Redis or Upstash (`rediss://...`)
2. Connect this repository to [Render](https://render.com) as a Web Service:
   - **Runtime**: Docker
   - **Dockerfile path**: `backend/Dockerfile`
   - **Docker build context**: `backend`
   - **Health check path**: `/api/v1/system/live`
3. Configure Environment Variables:
   - `DATABASE_URL`: `postgresql+asyncpg://USER:PASS@HOST/DB?ssl=require`
   - `REDIS_URL`: `rediss://default:PASS@HOST:6379`
   - `LLM_PROVIDER`: `none` (or `openrouter` with `OPENROUTER_API_KEY`)
   - `RUN_EMBEDDED_WORKER`: `true`
   - `APP_ENV`: `development`
4. Access:
   - Web Console: `https://YOUR-SERVICE.onrender.com/`
   - API Docs: `https://YOUR-SERVICE.onrender.com/docs`
   - Health: `https://YOUR-SERVICE.onrender.com/api/v1/system/health`

## Verify

```bash
cd backend
pip install -r requirements-dev.lock
pytest app/tests -q
# Optional real service tests: each test creates its own PostgreSQL schema.
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/martech_test \
TEST_REDIS_URL=redis://localhost:6379/15 pytest app/tests -q
alembic check
```

Without `TEST_*` URLs, tests use SQLite/fakeredis and explicitly skip PostgreSQL row-lock cases. Use an isolated test database; tests need permission to create/drop temporary schemas. They do not truncate your application tables.

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
npm start
```

GitHub Actions runs real PostgreSQL/Redis tests, migration drift checks, and frontend checks.


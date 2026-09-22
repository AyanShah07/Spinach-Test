# MarTech Intelligence & Campaign Decision Engine

> An enterprise-grade, event-driven platform for durable customer event ingestion, real-time engagement scoring, audience segmentation, and grounded AI campaign decision analysis.

---

## 4W & 1H Framework Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  WHAT:   Event-driven MarTech platform with AI-assisted campaign decisions  │
│  WHY:    Durable ingestion, zero event loss, and real-time engagement score │
│  WHO:    Growth Marketers, Campaign Managers, and Platform/Data Engineers   │
│  WHERE:  All-in-one container (Render/Docker) or cloud microservices (AWS)  │
│  HOW:    FastAPI + Transactional Outbox + Redis Streams + Worker + AI LLMs  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. WHAT: Platform Overview & Capabilities

### What is the MarTech Intelligence Platform?
The MarTech Intelligence Platform is a high-throughput backend service designed to process customer engagement events (email opens, link clicks, push notifications, purchases, unsubscribes), compute real-time customer engagement scores using mathematical decay, and deliver grounded, hallucination-free AI campaign recommendations.

### What are its core capabilities?
- **Durable Event Ingestion**: Single (`POST /events`) and batch (`POST /events/batch`) ingestion returning `202 Accepted` backed by an atomic PostgreSQL transactional outbox.
- **Continuous Engagement Scoring**: Real-time scoring using continuous exponential half-life decay ($\lambda = 0.05$). Order-independent, idempotent, and resilient to late or out-of-order events.
- **Audience Segmentation & Preview**: Streamed SQL qualification filtering, 24-hour frequency capping, and min-heap ranking without arbitrary cutoffs.
- **Grounded AI Decision Engine**: Campaign analysis combining deterministic SQL aggregates with LLM intelligence (**Google Gemini**, **Groq**, **OpenRouter**, or local **Ollama**). Protected by a **Number-Containment Grounding Guard**, automatic circuit breaker, and deterministic rule-based fallback.
- **Live Cloud Testing Console**: Web console with a dedicated **Live Config** interface. Enter your own API keys for AI (Gemini, Groq, OpenRouter), Supabase PostgreSQL, and Upstash Redis for live cloud testing with zero persistence.
- **Audit & Dead-Letter Queue (DLQ)**: Automatic retry with exponential backoff (3 attempts), dead-letter queue persistence (`dlq_events`), and audited, race-free replay capabilities.
- **Decoupled Worker Architecture**: Multi-role process support (`SERVICE_ROLE=api`, `worker`, or `all-in-one`) allowing horizontal worker scaling (`docker compose --scale worker=3`).
- **Self-Contained AI Console**: A responsive, dark-mode single-page console served directly at `/` from the backend.

---

## 2. WHY: Architectural Rationale & Guarantees

### Why the Transactional Outbox Pattern?
Writing events directly to an external message broker can cause split-brain failures if the database write succeeds but the queue publish fails. The Transactional Outbox pattern guarantees **zero event loss** by committing incoming events and their outbox entries in a single atomic database transaction.

### Why Redis Streams?
Redis Streams provides low-latency, ordered message delivery with consumer group semantics, message acknowledgment (`XACK`), pending message reclamation (`XAUTOCLAIM`), and consumer group lag monitoring—all with minimal infrastructure overhead.

### Why Continuous Half-Life Decay Scoring?
Batch-computed customer scores go stale quickly. Our algorithm evaluates decay continuously as a function of elapsed time:
$$\text{Score}(t) = \text{Score}_0 \cdot e^{-\lambda \Delta t} + \text{EventWeight}$$
This ensures:
1. Scores reflect current customer engagement without requiring nightly batch re-scoring jobs.
2. Ingesting out-of-order or late events yields consistent, mathematically correct results.

### Why Grounded Facts + Number-Containment Guards for AI?
LLMs are prone to hallucinations when generating quantitative performance assessments. Our architecture enforces a strict separation:
- **Facts**: Computed directly from deterministic database aggregates (open rates, click rates, conversion rates).
- **Number-Containment Guard**: An automated post-generation guard (`app.ai.grounding_guard`) verifies all quantitative claims (percentages, counts) against SQL metrics, rejecting hallucinated figures.
- **Circuit Breaker**: If the LLM provider fails, times out, or rate limits, the circuit trips into cooldown and returns a deterministic, rule-based summary without user-facing downtime.

---

## 3. WHO: Target Users & Stakeholders

| Stakeholder | How They Interact With the System | Key Benefit |
| :--- | :--- | :--- |
| **Growth & Lifecycle Marketers** | Uses the `/` console or audience APIs to preview segment sizes and run campaign analysis. | Immediate feedback on campaign health and grounded suggestions for improvement. |
| **Campaign Operations Teams** | Queries engagement scores and frequency caps to schedule multi-channel messaging. | Prevents customer fatigue; honors opt-outs and channel preferences in real-time. |
| **Platform & Data Engineers** | Integrates event producers (web/mobile SDKs, webhooks) via `POST /api/v1/events`. | Reliable at-least-once delivery, automatic deduplication, and zero dropped events. |
| **DevOps / SRE Teams** | Monitors `/api/v1/system/health`, queue depth, worker pools, and DLQ replayer. | Clear operational visibility, health probes, and self-healing worker processes. |

---

## 4. WHERE: Deployment Environments & Endpoints

### Where does the platform run?
1. **Render (Cloud Demo)**: Packaged as a single, self-contained Docker container running embedded PostgreSQL and Redis—operating within Render's free tier (512 MB RAM limit).
2. **Local Workstation**: Runs via `docker compose` (with scalable workers) or directly with Python virtualenv and native PostgreSQL/Redis services.
3. **Enterprise Production**: Decoupled across AWS ECS/EKS, Aurora PostgreSQL, and ElastiCache Redis (see [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md)).

### Where are the key endpoints located?
- **AI Web Console**: `http://localhost:8000/` (or `https://<render-app>.onrender.com/`)
- **Interactive OpenAPI Documentation**: `/docs`
- **Readiness Probe**: `GET /api/v1/system/health`
- **Liveness Probe**: `GET /api/v1/system/live`
- **Live Credential Validation**: `POST /api/v1/system/configure`
- **Live Data Seeding**: `POST /api/v1/system/seed-live`
- **Local Demo Seeding**: `POST /api/v1/system/seed`
- **AI Campaign Analysis**: `POST /api/v1/campaigns/{id}/analyze`
- **AI Campaign Recommendations**: `POST /api/v1/campaigns/{id}/recommend`
- **Dead-Letter Queue (DLQ)**: `GET /api/v1/system/dlq` & `POST /api/v1/system/dlq/{id}/replay`

---

## 5. HOW: Operations, Setup & Execution

### How to Use the Live Config Tab (Interactive Live Cloud Testing)
The `/` web console includes a dedicated **🔑 Live Config** tab allowing real-time evaluation with live external cloud services:
1. Open the web console at `/` and click **🔑 Live Config**.
2. **AI Provider**: Select Groq, Gemini, or OpenRouter and enter your API key (`gsk_...`, `AIza...`, or `sk-or-...`).
3. **Supabase (PostgreSQL)**: Enter your Project URL (`https://xxxx.supabase.co`) and database password.
4. **Upstash Redis**: Enter your Upstash Redis connection URL (`rediss://default:...@...upstash.io:6379`).
5. Click **🔍 Validate Connections** to verify connectivity without saving keys to disk.
6. Click **⚡ Generate Live Data** to automatically create database tables (`Base.metadata.create_all`) and seed 100 customers, 10 campaigns, and 500 events directly into Supabase, plus 10 demo stream events into Upstash.
7. *Zero Persistence Guarantee*: Credentials reside in browser memory and are transmitted to the backend only for validation and request execution. They are never written to disk or logged.

### How to Run with Makefile (Recommended)
```bash
make help          # View all available automation commands
make run-api       # Run FastAPI web server locally with hot-reload
make run-worker    # Run standalone background event worker
make seed          # Seed synthetic demo data (10 campaigns, 500 customers)
make demo-dedup    # Run concurrent batch deduplication demonstration
make test          # Run full pytest test suite
make docker-up     # Start PostgreSQL, Redis, API, and Worker via Docker
make docker-scale  # Start Docker services and scale workers to 3 parallel processes
make docker-down   # Stop and tear down Docker containers
```

### How to Run Locally with Docker
```bash
cd backend
cp .env.example .env
docker compose up --build
```
To run multi-worker horizontal scaling:
```bash
docker compose up --build --scale worker=3
```
- Web Console: `http://localhost:8000/`
- API Docs: `http://localhost:8000/docs`

### How to Run without Docker
Ensure Python 3.11+, PostgreSQL 16+, and Redis 6.2+ are available:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
cp .env.example .env
# Set DATABASE_URL and REDIS_URL in .env
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### How to Seed and Explore Demo Data
```bash
# Seed 500 customers, 1,000 events, 10 campaigns:
python -m scripts.generate_synthetic_data

# Full assessment scale (50,000 customers, 100,000 events):
python -m scripts.generate_synthetic_data --customers 50000 --events 100000 --campaigns 20
```

### How to Test and Verify
```bash
cd backend
pytest app/tests -q
# Optional real service tests:
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/martech_test \
TEST_REDIS_URL=redis://localhost:6379/15 pytest app/tests -q
alembic check
```

---

## 6. High-Load & Concurrency: Can 50,000 Concurrent Users Run on Render Free Tier?

A common systems engineering question: **Can 50,000 concurrent requests be handled on Render Free Tier (0.1 shared vCPU, 512 MB RAM)?**

### The Physical Reality
**No, 50,000 simultaneous open TCP/HTTP connections cannot run on a 512 MB, 0.1 vCPU container.**
Here is the systems breakdown:
1. **Memory Ceiling**: Each active TCP socket with TLS handshake and HTTP receive buffers requires ~30 KB–50 KB of RAM. Maintaining 50,000 open connections consumes **1.5 GB to 2.5 GB of RAM alone**, triggering an instant kernel OOM-killer (Out Of Memory) crash on a 512 MB container.
2. **File Descriptor Limits**: Render free tier containers default to `1024` or `4096` max open file descriptors (`ulimit -n`). Attempting 50k connections immediately yields `OSError: [Errno 24] Too many open files`.
3. **CPU Contention**: 0.1 vCPU provides only 10% of a single physical core time-slice. Context-switching among tens of thousands of coroutines causes catastrophic event-loop thrashing and connection timeouts.

### What Render Free Tier *Can* Sustain
- **Sustainable Throughput**: 50–150 HTTP requests/second.
- **Concurrent Connections**: 20–50 simultaneous in-flight connections.
- **Data Volume**: 50,000 to 100,000 total events ingested in batches (e.g. `POST /api/v1/events/batch` with 500 events per payload) without dropping a single event.

### How 50,000 Concurrent Users are Handled in Production
Handling 50,000 true concurrent users requires decoupling the infrastructure as detailed in [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) and [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md):
1. **Edge Multiplexing**: Cloudflare / AWS ALB terminates 50,000 client connections at the edge and proxies them over persistent HTTP/2 keep-alive pools.
2. **Horizontal API Fleet**: 8–16 FastAPI pods (2 vCPU, 4 GB RAM each) scaled across Kubernetes or AWS ECS.
3. **Connection Pooling**: **PgBouncer** in `pool_mode = transaction` multiplexes 50,000 client queries into 50–100 PostgreSQL backend connections.
4. **Asynchronous Ingestion**: Ingestion returns `202 Accepted` immediately upon writing to PostgreSQL's transactional outbox. Heavy scoring and decay computations are offloaded to autoscaled background workers reading from partitioned Redis Streams or Apache Kafka.

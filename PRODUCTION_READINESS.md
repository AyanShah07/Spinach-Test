# Production Readiness & Architecture Roadmap

> An enterprise architectural evaluation and transition roadmap for the **MarTech Intelligence & Campaign Decision Engine**, structured using the **4W & 1H (What, Why, Who, Where, How)** engineering framework.

---

## 4W & 1H Framework Executive Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  WHAT:   Enterprise migration plan from all-in-one demo to scalable cloud   │
│  WHY:    Fault isolation, 50,000+ concurrent throughput, zero data loss SLA │
│  WHO:    Platform Engineers, DevOps/SREs, Lifecycle Marketers, SecOps       │
│  WHERE:  AWS / GCP Multi-AZ, VPC private subnets, Kubernetes, Edge WAF      │
│  HOW:    5-phase Pull Request (PR) roadmap, OTel metrics, Kafka/PgBouncer   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. WHAT: Capabilities & Production Gap Analysis

### What It Is Today vs. What It Actually Does

| Dimension | Current Prototype / Demo | What It Actually Does Today | Production Target |
| :--- | :--- | :--- | :--- |
| **Deployment Model** | Single Docker container on Render Free Tier. | Runs FastAPI, embedded Postgres, embedded Redis, and background worker in 1 container; supports `SERVICE_ROLE` splitting. | Decoupled microservices on Kubernetes (EKS/GKE) or AWS ECS. |
| **Database** | Embedded PostgreSQL daemon inside container + Supabase Live connector. | Stores events, outbox, customers, and campaigns on container filesystem; seeds external Supabase over SSL pooler. | Managed Multi-AZ PostgreSQL 16+ (AWS Aurora / Cloud SQL) with automated failover and PITR. |
| **Message Broker** | Embedded local Redis server + Upstash Redis connector. | Powers Redis Streams (`events:stream`) for worker consumption; writes live events to Upstash over TLS. | Managed Redis Cluster (AWS ElastiCache) or Apache Kafka for multi-partition streaming. |
| **Worker Engine** | In-process `asyncio.create_task` or standalone process (`SERVICE_ROLE=worker`). | Asynchronously claims outbox rows via `SKIP LOCKED`, calculates decayed scores, updates customer records with row locks. | Autoscaled worker fleet scaled via KEDA based on stream consumer lag (`xlen` - `ack_count`). |
| **Throughput & Concurrency** | ~50–150 events/sec; 20–50 concurrent sockets. | Sufficient for interactive demo and batch seeding up to 50k events. | 10,000–50,000+ concurrent requests across edge WAF, ALB, and API replicas. |
| **Fault Isolation** | Single-container boundary. | If Postgres or Redis runs out of memory (512MB RAM limit), the API restarts. | Independent failure domains: API, workers, databases, and caches fail and scale independently. |
| **Authentication & Keys** | Static `API_KEY` header + ephemeral browser key injection. | Header check for DLQ; UI supports dynamic in-memory injection for Gemini, Groq, OpenRouter, Supabase, Upstash. | Multi-tenant RBAC, JWT / OAuth2 bearer tokens, hashed API keys (`argon2id`), KMS secrets. |
| **AI Evaluation** | Multi-model gateway (Gemini, Groq, OpenRouter, Ollama). | Protected by **Number-Containment Grounding Guard**, in-process circuit breaker, and deterministic rule fallback. | Distributed circuit breaker (Redis), semantic prompt cache (Redis Vector), token budgeting, and fallback chain. |
| **Observability** | Stdout logs + `/system/health` + `/system/live`. | Detailed health JSON (queue depth, outbox pending, worker heartbeat, DLQ count). | OpenTelemetry distributed tracing, Prometheus metrics exporter, structured JSON logs, and PagerDuty. |

### What Needs to Be Changed (The Production Gaps)
1. **Decouple the Compute Tier**: The background worker fleet must not share process space or container lifecycles with the public HTTP API.
2. **Externalize State**: Eliminate embedded database and Redis daemons in favor of managed, persistent, multi-AZ cloud services.
3. **Partition Message Streaming**: Partition message streams by `hash(customer_id)` across Kafka topics or multiple Redis streams to enable horizontal worker scaling without row lock contention.
4. **Harden Security & Secrets**: Move away from plaintext `.env` variables to KMS/Vault secret injection; replace single API keys with scoped, multi-tenant tokens.
5. **Implement Data Lifecycle Policies**: Add PostgreSQL range partitioning to `events` and automate outbox pruning and cold-storage S3 Parquet archiving.

---

## 2. WHY: Architectural Rationale & Motivations

### Why Decouple API and Worker Fleets?
In the current prototype, a sudden spike in event ingestion or worker scoring can consume all CPU/RAM, causing the web API to fail health checks and restart. Decoupling ensures:
- Ingestion APIs remain responsive even during heavy background processing.
- Workers can be scaled independently using KEDA based strictly on queue backlog (`xlen` / `pending`).
- Deployments to the web API do not terminate in-flight event processing tasks.

### Why Managed Multi-AZ PostgreSQL with PgBouncer?
- **Zero Data Loss**: Automated point-in-time recovery (PITR) and synchronous multi-AZ replication protect against hardware failure.
- **Connection Saturation**: Tens of thousands of client requests can exhaust PostgreSQL's `max_connections` (typically capped at 100–300). Deploying **PgBouncer** in `pool_mode = transaction` allows 50,000 concurrent clients to share a lean database pool of 50–100 connections.
- **Read Scaling**: Heavy analytics queries (`/campaigns/{id}/analytics`) can be offloaded to read replicas without contending with transactional ingestion writes.

### Why Stream Partitioning by Customer ID?
To calculate engagement scores accurately, all events for a given customer must be processed in chronological order. 
- By partitioning streams (or Kafka topics) with `hash(customer_id) % num_partitions`, events for the same customer always route to the same partition/worker.
- This eliminates the need for cross-worker distributed locking while allowing dozens of workers to process different customers in parallel.

### Why Distributed Circuit Breakers & Semantic Caching for AI?
- **Cost Protection**: Semantic caching in Redis prevents paying LLM token costs for identical campaign metric profiles.
- **Resilience**: An in-memory circuit breaker only protects a single container. A distributed Redis-backed circuit breaker immediately shields the entire API cluster when an upstream AI provider experiences outages or elevated latencies.

---

## 3. WHO: Roles, Ownership & Stakeholders

| Stakeholder / Team | Responsibilities in Production | Key Deliverables & KPIs |
| :--- | :--- | :--- |
| **Platform & Data Engineers** | Owns event ingestion pipelines, database schemas, Alembic migrations, and queue partitioning. | Pipeline latency < 100ms; zero data loss; 99.99% ingestion uptime. |
| **DevOps & Site Reliability (SRE)** | Manages Kubernetes/ECS infrastructure, PgBouncer, Redis clusters, CI/CD pipelines, and alerting. | Mean time to detect (MTTD) < 5 min; automated multi-AZ failover; disaster recovery drills. |
| **Security & SecOps** | Manages KMS/Vault secret rotation, RBAC policies, network segmentation, and penetration testing. | SOC2 / GDPR compliance; zero plaintext secrets; rate-limiting enforcement. |
| **Growth & Lifecycle Marketers** | Consumes campaign analytics, triggers AI decision evaluations, and schedules audiences. | Grounded campaign insights; accurate audience reach estimates; frequency cap protection. |

---

## 4. WHERE: High-Scale Infrastructure & 50,000 Concurrency Architecture

### Concurrency Sizing: Handling 50,000 Concurrent Requests

When scaling to 50,000 concurrent requests, the system transitions from the single-container demo to a tiered cloud deployment:

```mermaid
flowchart TD
    subgraph Clients["Clients Tier"]
        C50K["50,000 Concurrent HTTP/TLS Clients"]
    end

    subgraph Edge["Edge & Ingress Tier"]
        CF["Cloudflare Enterprise WAF / CDN<br/>(TLS Offload, DDoS Filtering, HTTP/2 & HTTP/3)"]
        ALB["AWS Application Load Balancer<br/>(Cross-AZ Target Group Health Routing)"]
    end

    subgraph AppCluster["Private Compute Tier (EKS / ECS)"]
        subgraph APITier["FastAPI Stateless Fleet (12-16 Replicas)"]
            API1["FastAPI Pod 1 (2 vCPU, 4GB)"]
            API2["FastAPI Pod 2 (2 vCPU, 4GB)"]
            APIN["FastAPI Pod N (2 vCPU, 4GB)"]
        end
        subgraph WorkerTier["Event Worker Fleet (Autoscaled via KEDA)"]
            W1["Worker Pod 1"]
            W2["Worker Pod 2"]
            WN["Worker Pod N"]
        end
    end

    subgraph IngestionBuffer["Buffer & Streaming Tier"]
        Outbox["Postgres Transactional Outbox (Indexed)"]
        Kafka["Apache Kafka / Partitioned Redis Streams<br/>(Keyed by customer_id)"]
    end

    subgraph DataTier["Data Tier"]
        PgB["PgBouncer Connection Pooler (Transaction Mode)"]
        PGPrimary[("AWS Aurora PostgreSQL 16 Multi-AZ (Write)")]
        PGReplica[("AWS Aurora PostgreSQL Read Replica")]
        RedisCache[("AWS ElastiCache Redis Cluster (Frequency Capping)")]
    end

    %% Ingress Flow
    C50K --> CF
    CF -->|Multiplexed Keep-Alive| ALB
    ALB --> API1 & API2 & APIN

    %% Ingestion Execution
    API1 & API2 & APIN -->|1. Write Event & Outbox (202 Accepted)| PgB
    PgB -->|50-100 Shared Connections| PGPrimary
    API1 & API2 & APIN -.->|Outbox Publisher| Kafka
    Kafka --> W1 & W2 & WN
    W1 & W2 & WN -->|Compute Decayed Score| PgB

    %% Analytics Read Offload
    API1 & API2 & APIN -->|Analytics Queries| PGReplica
```

### Resource Sizing & Capacity Matrix

| Component | Prototype (Render Free) | Staging (Serverless) | Production (50k Concurrent Users) |
| :--- | :--- | :--- | :--- |
| **vCPU** | 0.1 vCPU (Shared) | 2–4 vCPU | 24–32 vCPU total (across 12–16 API replicas) |
| **RAM** | 512 MB | 2–4 GB | 48–64 GB total |
| **Concurrent Sockets** | 20–50 | 500–1,000 | 50,000 (terminated at Edge WAF / ALB) |
| **Database Pool** | 5 direct connections | 15–30 connections | PgBouncer: 50,000 client sockets → 100 Postgres connections |
| **Ingestion SLA** | Best-effort (~50–150 req/s) | ~500 req/s | > 10,000 req/s ingestion; < 25ms p99 response time |
| **Failure Domain** | Single container | Decoupled serverless | Multi-AZ with automated failover and zero data loss |

---

## 5. HOW: Transition Roadmap & Pull Request (PR) Plan

To systematically take the repository from the current prototype to high-scale production without downtime, follow this 5-stage Pull Request plan:

### PR 1: Service Decoupling & Managed Infrastructure Config
- **What**: Split the codebase into standalone API and Worker container images. Decouple embedded databases.
- **Why**: Eliminates single-point-of-failure; allows independent autoscaling via `SERVICE_ROLE`.
- **Files Modified**:
  - `backend/Dockerfile.api` and `backend/Dockerfile.worker`
  - `docker-compose.yml` (configure independent API and scalable worker services)
  - `backend/app/main.py`
- **Key Changes**:
  - Remove embedded postgres and redis setup from container startup scripts.
  - Set `RUN_EMBEDDED_WORKER=false` by default in production.
  - Add container health probes: HTTP `/live` for API, Redis heartbeat key check for workers.

### PR 2: Partitioned Event Ingestion & Kafka/Redis Cluster Adapter
- **What**: Partition message streams by `customer_id` and complete the Kafka swap contract.
- **Why**: Scales event processing beyond the throughput limit of a single stream while preserving per-customer ordering.
- **Files Modified**:
  - `backend/app/queue/redis_streams.py`
  - `backend/app/queue/kafka_adapter.py`
  - `backend/app/workers/event_worker.py`
- **Key Changes**:
  - Implement consistent hashing on `customer_id` across $N$ stream partitions.
  - Wire `aiokafka` into `KafkaQueue` for enterprise deployments handling > 10,000 events/sec.

### PR 3: Production Security, RBAC & Secret Management
- **What**: Multi-tenant authorization, hashed API tokens, and cloud secret injection.
- **Why**: Protects sensitive customer data, enables multi-tenant SaaS billing, and meets security standards.
- **Files Modified**:
  - `backend/app/core/security.py`
  - `backend/app/core/config.py`
  - `backend/app/db/models.py`
  - `backend/migrations/versions/`
- **Key Changes**:
  - Add `Tenant` and `ApiKey` models with `argon2id` token hashing.
  - Introduce permission scopes (`events:ingest`, `campaigns:read`, `ai:analyze`).
  - Integrate AWS Secrets Manager / HashiCorp Vault dynamic secret fetching.

### PR 4: Full Observability (OpenTelemetry & Prometheus)
- **What**: Distributed tracing, metrics exporter, and structured JSON logs.
- **Why**: Enables instant root-cause analysis during incidents and automated alerting.
- **Files Modified**:
  - `backend/app/core/telemetry.py` (New)
  - `backend/app/main.py`
  - `backend/requirements.txt`
- **Key Changes**:
  - Instrument FastAPI and async SQLAlchemy with OpenTelemetry OTLP exporters.
  - Expose `/metrics` for Prometheus (stream lag, processing latency histograms, DLQ count).
  - Propagate W3C trace context across HTTP headers, outbox payloads, and worker tasks.

### PR 5: Data Retention, Partitioning & Disaster Recovery
- **What**: Table partitioning on `events`, automated outbox cleanup, and S3 cold storage archival.
- **Why**: Keeps database queries fast as event volume grows to millions of rows; enforces GDPR/CCPA data retention.
- **Files Modified**:
  - `backend/migrations/versions/` (Postgres table range partitioning)
  - `backend/scripts/prune_outbox.py`
  - `backend/scripts/archive_to_s3.py`
- **Key Changes**:
  - Convert `events` table to native PostgreSQL range partitioning by month.
  - Cron job pruning processed outbox entries older than 7 days.
  - Nightly export of cold historical events to Amazon S3 in Parquet format.

---

## 6. How Much It Costs: Production Budget Breakdown

| Environment Tier | Monthly Cost (Est.) | Target Workload & Capacity | Infrastructure Components |
| :--- | :--- | :--- | :--- |
| **Current Prototype** | **$0 / mo** | Testing, proof of concept, demos (< 1,000 events/day). | 1x Render Free Web Service (512MB RAM, shared CPU) with embedded Postgres & Redis. |
| **Serverless Staging Tier** | **~$35–$60 / mo** | Development, staging, live validation with team. | - Supabase Pro (Postgres + Connection Pooler): $25<br/>- Upstash Redis (Pay-per-request): $5–$10<br/>- 1x Render / Fly.io Starter Web Service: $7 |
| **Entry Production** | **~$120–$250 / mo** | Early production, up to 5,000,000 events/month, 500 concurrent connections. | - AWS Aurora PostgreSQL (db.t4g.medium): $75<br/>- AWS ElastiCache Redis (cache.t4g.small): $35<br/>- 2x API Replicas + 2x Worker Replicas: $40<br/>- PgBouncer on t4g.micro: $10 |
| **High-Scale Enterprise (50k Concurrency)** | **~$1,200–$2,800 / mo** | 50,000 concurrent users, 100M+ events/month, 99.95% SLA. | - AWS Aurora PostgreSQL Multi-AZ (db.r6g.xlarge): $450<br/>- AWS ElastiCache Cluster (cache.m6g.large): $220<br/>- EKS / ECS Cluster (12-16 API + 8 Worker Pods): $650<br/>- Cloudflare Enterprise WAF + ALB: $300<br/>- LLM Token Usage (Groq / Gemini / OpenRouter): Usage-based |

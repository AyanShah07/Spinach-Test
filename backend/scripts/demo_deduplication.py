#!/usr/bin/env python3
"""
Demonstration of PostgreSQL Deduplication Authority under Concurrent Batch Ingestion.

Shows how PostgreSQL's atomic ON CONFLICT DO NOTHING guarantees exact once-only
durable insertion even when identical event IDs are concurrently submitted.
"""
import asyncio
import time
from datetime import datetime, timezone
import httpx


async def run_deduplication_demo(base_url: str = "http://127.0.0.1:8000/api/v1"):
    print("=" * 65)
    print(" PostgreSQL Deduplication Authority & Idempotency Demo")
    print("=" * 65)

    client = httpx.AsyncClient(timeout=10.0)

    # 1. Check if backend is alive
    try:
        resp = await client.get(f"{base_url}/system/live")
        resp.raise_for_status()
        print("✓ Connected to MarTech API backend.")
    except Exception as exc:
        print(f"✗ Backend unreachable at {base_url}. Make sure API is running.")
        return

    # 2. Prepare 5 unique event IDs, each repeated 3 times (15 items total)
    batch_ts = datetime.now(timezone.utc).isoformat()
    unique_ids = [f"evt_demo_dedup_{int(time.time())}_{i}" for i in range(1, 6)]
    raw_events = []
    for eid in unique_ids:
        for attempt in range(1, 4):
            raw_events.append({
                "event_id": eid,
                "customer_id": "cust_000001",
                "channel": "email",
                "event_type": "open",
                "timestamp": batch_ts,
                "metadata": {"attempt": attempt, "demo": True}
            })

    print(f"\nSending batch of {len(raw_events)} events containing {len(unique_ids)} unique IDs (each repeated 3x)...")

    # 3. Post batch to /events/batch
    t0 = time.perf_counter()
    post_resp = await client.post(f"{base_url}/events/batch", json={"events": raw_events})
    elapsed = (time.perf_counter() - t0) * 1000

    if post_resp.status_code == 202:
        data = post_resp.json()
        print(f"✓ Response received in {elapsed:.1f}ms:")
        print(f"   - Status:      202 Accepted")
        print(f"   - Accepted:    {data.get('accepted')} (New events stored in DB & Outbox)")
        print(f"   - Duplicates:  {data.get('duplicates')} (Safely skipped by ON CONFLICT)")
        print(f"   - Rejected:    {len(data.get('rejected', []))}")
        
        assert data.get("accepted") == 5, f"Expected 5 accepted, got {data.get('accepted')}"
        assert data.get("duplicates") == 10, f"Expected 10 duplicates, got {data.get('duplicates')}"
        print("\n✓ SUCCESS: PostgreSQL successfully deduplicated 10 duplicate events!")
        print("  Database is authoritative; Redis queue will only process the 5 unique events.")
    else:
        print(f"✗ Error: HTTP {post_resp.status_code} - {post_resp.text}")

    await client.aclose()


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api/v1"
    asyncio.run(run_deduplication_demo(url))

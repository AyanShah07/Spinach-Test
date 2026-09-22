import asyncio
import itertools
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
from app.core.config import get_settings
from app.core.exceptions import RateLimitError
from app.core.rate_limit import rate_limit_events
from app.db.models import Customer, Event, EngagementScore, DLQEvent, EventOutbox
from app.workers.event_worker import process_one_event, reconcile_outbox, fail_event, run_worker
from app.domain.audience.topk import select_top_k
from app.domain.scoring.engagement_score import compute_new_score, score_at
from app.ai.service import AnalysisService
from app.ai.provider import AIResponse

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)

def event(eid="e1", cid="c1", kind="open", ts=None):
    return dict(event_id=eid, customer_id=cid, event_type=kind, channel="email",
                timestamp=(ts or datetime.now(timezone.utc)).isoformat(), metadata={})

async def ingest(stack, payload):
    response = await stack.client.post('/api/v1/events', json=payload)
    assert response.status_code == 202, response.text

async def process(stack, payload):
    async with stack.sessions() as session:
        await process_one_event(session, payload)

@pytest.mark.parametrize("seed", range(5))
def test_topk_matches_sort(seed):
    rng = random.Random(seed)
    values = [(f"c{i}", rng.randint(-10, 100), {}) for i in range(200)]
    rng.shuffle(values)
    actual = select_top_k(iter(values), 20)
    assert [(e.score, e.customer_id) for e in actual] == sorted([(s, c) for c, s, _ in values], reverse=True)[:20]

def test_score_independent_of_arrival_order_even_at_clamp():
    events = [(NOW, "purchase"), (NOW + timedelta(days=30), "open"), (NOW + timedelta(days=2), "complaint")]
    scores = []
    for ordering in itertools.permutations(events):
        score, clock = 250.0, NOW - timedelta(days=1)
        for ts, kind in ordering:
            score, _ = compute_new_score(score, clock, kind, "email", ts)
            clock = max(clock, ts)
        scores.append(score)
    assert max(scores) - min(scores) < 1e-9
    assert score_at(100, NOW, NOW + timedelta(days=30)) < 25

async def test_profile_preserved_and_activity_monotonic(stack):
    async with stack.sessions() as session:
        session.add(Customer(id="c1", attributes={"vip": True}, email_opt_in=True))
        await session.commit()
    latest, older = event(), event('older', ts=datetime.now(timezone.utc) - timedelta(days=30))
    for payload in (latest, older):
        await ingest(stack, payload)
        await process(stack, payload)
    response = await stack.client.get('/api/v1/customers/c1')
    assert response.json()['attributes'] == {'vip': True}
    assert datetime.fromisoformat(response.json()['last_active']).replace(tzinfo=timezone.utc) >= datetime.fromisoformat(latest['timestamp'])

async def test_unsubscribe_and_new_customer_defaults(stack):
    await ingest(stack, event())
    await process(stack, event())
    customer = (await stack.client.get('/api/v1/customers/c1')).json()
    assert not customer['email_opt_in']
    async with stack.sessions() as session:
        customer = await session.get(Customer, 'c1')
        customer.email_opt_in = True
        await session.commit()
    payload = event('unsubscribe', kind='unsubscribe')
    await ingest(stack, payload)
    await process(stack, payload)
    assert not (await stack.client.get('/api/v1/customers/c1')).json()['email_opt_in']

async def test_duplicate_is_applied_once_and_outbox_only_publishes_once(stack):
    payload = event()
    await ingest(stack, payload)
    response = await stack.client.post('/api/v1/events', json=payload)
    assert response.json()['status'] == 'duplicate'
    assert await stack.redis.xlen(stack.queue.stream) == 0
    assert await reconcile_outbox(stack.queue, stack.sessions) == 1
    assert await reconcile_outbox(stack.queue, stack.sessions) == 0
    await process(stack, payload)
    await process(stack, payload)
    async with stack.sessions() as session:
        score = await session.get(EngagementScore, 'c1')
        assert score.score == 1.0
        assert score.channel_breakdown['email']['count'] == 1

async def test_dlq_replay_is_atomic_and_idempotent(stack):
    payload = event()
    await ingest(stack, payload)
    async with stack.sessions() as session:
        await fail_event(session, payload, RuntimeError('transient'), 3)
        dlq_id = (await session.execute(select(DLQEvent.id))).scalar_one()
    response = await stack.client.post(f'/api/v1/system/dlq/{dlq_id}/replay')
    assert response.json()['status'] == 'requeued'
    assert (await stack.client.post(f'/api/v1/system/dlq/{dlq_id}/replay')).json()['status'] == 'already_requeued'
    await process(stack, payload)
    async with stack.sessions() as session:
        evt = (await session.execute(select(Event))).scalar_one()
        assert evt.status == 'processed'
        assert (await session.get(DLQEvent, dlq_id)).replayed_at

async def test_frequency_cap_preview_is_read_only_and_send_expiry_is_individual(stack):
    async with stack.sessions() as session:
        session.add_all([Customer(id='c1', attributes={}, email_opt_in=True),
                         Customer(id='c2', attributes={}, email_opt_in=True)])
        await session.commit()
    body = {'objective':'conversion', 'channel':'email', 'audience_size':5}
    for _ in range(2):
        assert (await stack.client.post('/api/v1/audience/recommend', json=body)).json()['returned_size'] == 2
    for payload in [event('send1', kind='send'), event('send2', cid='c2', kind='send', ts=datetime.now(timezone.utc)-timedelta(hours=25))]:
        await ingest(stack, payload)
        await process(stack, payload)
    data = (await stack.client.post('/api/v1/audience/recommend', json=body)).json()
    assert [r['customer_id'] for r in data['customers']] == ['c2']

@pytest.mark.parametrize('body', [
    {'conditions': {'min_score': 'bad'}}, {'channel':'unknown'},
    {'conditions': {'max_days_inactive':-1}}, {'conditions':{'unknown':1}}])
async def test_bad_filters_are_422(stack, body):
    response = await stack.client.post('/api/v1/audience/recommend', json={'objective':'conversion','channel':'email',**body})
    assert response.status_code == 422, response.text
    assert response.json()['code'] == 'validation_error'

async def test_same_second_requests_count_and_batch_cost():
    redis = FakeRedis(decode_responses=True)
    request = SimpleNamespace(client=SimpleNamespace(host='rate-test'))
    with patch('app.core.rate_limit.time.time', return_value=1000):
        await rate_limit_events(request, redis, cost=500)
        await rate_limit_events(request, redis, cost=100)
        with pytest.raises(RateLimitError):
            await rate_limit_events(request, redis)
    await redis.aclose()

async def test_rate_limiter_fails_open_on_redis_outage():
    await rate_limit_events(SimpleNamespace(client=None), SimpleNamespace(eval=AsyncMock(side_effect=ConnectionError())))

async def test_ai_recovers_and_grounded_facts(monkeypatch):
    service = AnalysisService()
    provider = SimpleNamespace(generate=AsyncMock(side_effect=RuntimeError('temporary')))
    ctx = {'audience_size':10,'metrics':{'open_rate':0.1}}
    for _ in range(4):
        assert (await service.analyze(provider,'prompt',ctx)).source == 'fallback'
    assert provider.generate.call_count == 3
    provider.generate.side_effect = None
    provider.generate.return_value = AIResponse(facts=['Invented revenue: 999'], recommendations=['Test subject lines'], confidence=.7)
    service.opened_at -= get_settings().LLM_CIRCUIT_BREAKER_COOLDOWN_SEC + 1
    result = await service.analyze(provider,'prompt',ctx)
    assert result.source == 'llm'
    assert not any('999' in fact for fact in result.facts)
    assert service.opened_at is None

async def test_pending_messages_are_recovered_and_ack_deleted(stack):
    group = get_settings().REDIS_CONSUMER_GROUP
    await stack.queue.ensure_group(group)
    mid = await stack.queue.enqueue('c1',event())
    delivered = await stack.queue.consume(group,'old',count=1,block_ms=1)
    assert delivered[0][0] == mid
    await stack.redis.xclaim(stack.queue.stream,group,'old',0,[mid],idle=120000)
    recovered = await stack.queue.consume(group,'new',count=1,block_ms=1)
    assert recovered[0][0] == mid
    await stack.queue.ack(group,mid)
    assert (await stack.redis.xpending(stack.queue.stream,group))['pending'] == 0
    assert await stack.redis.xlen(stack.queue.stream) == 0

async def test_malformed_stream_payload_goes_through_failure_path(stack):
    await stack.queue.ensure_group(get_settings().REDIS_CONSUMER_GROUP)
    await stack.redis.xadd(stack.queue.stream,{'payload':'not-json'})
    messages = await stack.queue.consume(get_settings().REDIS_CONSUMER_GROUP,'worker',block_ms=1)
    assert messages[0][1]['raw'] == 'not-json'

async def test_worker_processes_and_readiness_reports_health(stack):
    payload = event()
    await ingest(stack,payload)
    stop = asyncio.Event()
    task = asyncio.create_task(run_worker(stack.queue,stack.redis,stack.sessions,stop))
    try:
        for _ in range(100):
            async with stack.sessions() as session:
                evt = (await session.execute(select(Event))).scalar_one()
                if evt.status == 'processed':
                    break
            await asyncio.sleep(.02)
        else:
            pytest.fail('Worker did not process event')
        response = await stack.client.get('/api/v1/system/health')
        assert response.status_code == 200, response.text
        assert response.json()['worker'] == 'ok'
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    assert (await stack.client.get('/api/v1/system/health')).status_code == 503

async def test_protected_routes_require_key(stack,monkeypatch):
    monkeypatch.setattr(get_settings(),'API_KEY','local-test-key')
    assert (await stack.client.get('/api/v1/customers')).status_code == 401
    assert (await stack.client.get('/api/v1/customers',headers={'X-API-Key':'local-test-key'})).status_code == 200
    assert (await stack.client.get('/api/v1/system/live')).status_code == 200

async def test_batch_uses_savepoints_for_partial_failure(stack):
    from app.api.events import _persist_one
    async def fail_one(session, body):
        if body.event_id == 'bad':
            await session.execute(__import__('sqlalchemy').text('SELECT * FROM definitely_missing_table'))
        return await _persist_one(session,body)
    with patch('app.api.events._persist_one',side_effect=fail_one):
        response = await stack.client.post('/api/v1/events/batch',json={'events':[event('good1'),event('bad'),event('good2')]})
    assert response.status_code == 202, response.text
    assert response.json()['accepted'] == 2
    assert len(response.json()['rejected']) == 1
    async with stack.sessions() as session:
        assert len((await session.execute(select(Event))).scalars().all()) == 2

async def test_postgres_concurrent_events_do_not_lose_updates(stack):
    if not stack.postgres:
        pytest.skip('Requires TEST_DATABASE_URL; SQLite cannot validate row locks')
    payloads = [event(f'concurrent{i}',ts=NOW) for i in range(20)]
    for payload in payloads:
        await ingest(stack,payload)
    await asyncio.gather(*(process(stack,payload) for payload in payloads))
    async with stack.sessions() as session:
        score = await session.get(EngagementScore,'c1')
        assert score.score == 20
        assert score.channel_breakdown['email']['count'] == 20

async def test_published_pending_event_republished_after_redis_loss(stack):
    payload=event()
    await ingest(stack,payload)
    assert await reconcile_outbox(stack.queue,stack.sessions) == 1
    await stack.redis.delete(stack.queue.stream)
    async with stack.sessions() as session:
        row=(await session.execute(select(EventOutbox))).scalar_one()
        row.published_at=datetime.now(timezone.utc)-timedelta(minutes=3)
        await session.commit()
    assert await reconcile_outbox(stack.queue,stack.sessions) == 1
    assert await stack.redis.xlen(stack.queue.stream) == 1

async def test_outbox_cleanup_preserves_pending_work(stack):
    from app.queue.outbox import cleanup_outbox
    for eid in ('processed','pending'):
        await ingest(stack,event(eid))
    await process(stack,event('processed'))
    async with stack.sessions() as session:
        rows=(await session.execute(select(EventOutbox))).scalars().all()
        for row in rows:
            row.created_at=datetime.now(timezone.utc)-timedelta(days=10)
        await session.commit()
        await cleanup_outbox(session)
        await session.commit()
        assert (await session.execute(select(EventOutbox.event_id))).scalars().all() == ['pending']

async def test_ack_failure_does_not_kill_worker_or_double_apply(stack,monkeypatch):
    original=stack.queue.ack
    calls=0
    async def fail_first(group,msg):
        nonlocal calls
        calls+=1
        if calls==1:
            await stack.redis.xclaim(stack.queue.stream,group,'failed-worker',0,[msg],idle=120000)
            raise ConnectionError('ACK connection dropped')
        await original(group,msg)
    monkeypatch.setattr(stack.queue,'ack',fail_first)
    await ingest(stack,event())
    stop=asyncio.Event()
    task=asyncio.create_task(run_worker(stack.queue,stack.redis,stack.sessions,stop))
    try:
        for _ in range(150):
            if calls>=2 and await stack.redis.xlen(stack.queue.stream)==0:
                break
            await asyncio.sleep(.02)
        else:
            pytest.fail('Worker did not recover ACK failure')
        assert not task.done()
        async with stack.sessions() as session:
            assert (await session.get(EngagementScore,'c1')).score == 1.0
    finally:
        stop.set();task.cancel();await asyncio.gather(task,return_exceptions=True)

async def test_same_event_concurrent_delivery_is_idempotent(stack):
    if not stack.postgres:
        pytest.skip('Requires PostgreSQL row locks')
    payload=event()
    await ingest(stack,payload)
    await asyncio.gather(*(process(stack,payload) for _ in range(10)))
    async with stack.sessions() as session:
        assert (await session.get(EngagementScore,'c1')).score == 1

async def test_concurrent_replay_creates_one_new_outbox_row(stack):
    if not stack.postgres:
        pytest.skip('Requires PostgreSQL row locks')
    payload=event()
    await ingest(stack,payload)
    async with stack.sessions() as session:
        await fail_event(session,payload,RuntimeError('transient'),3)
        dlq_id=(await session.execute(select(DLQEvent.id))).scalar_one()
    responses=await asyncio.gather(*(stack.client.post(f'/api/v1/system/dlq/{dlq_id}/replay') for _ in range(5)))
    assert sum(r.json()['status']=='requeued' for r in responses)==1
    async with stack.sessions() as session:
        assert len((await session.execute(select(EventOutbox))).scalars().all())==2

async def test_per_event_idempotency_expiry_does_not_extend_other_events():
    from app.domain.events.idempotency import mark_seen
    redis=FakeRedis(decode_responses=True)
    with patch('time.time',return_value=1000):
        await mark_seen(redis,'older',100)
    with patch('time.time',return_value=1050):
        await mark_seen(redis,'newer',100)
        assert await redis.ttl(f'{get_settings().REDIS_IDEMPOTENCY_SET}:older')==50
    await redis.aclose()

def test_production_requires_auth_and_explicit_origins():
    from app.core.config import Settings
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(APP_ENV='production',API_KEY='')
    with pytest.raises(ValidationError):
        Settings(APP_ENV='production',API_KEY='x'*32,CORS_ORIGINS=['*'])

async def test_api_does_not_start_worker_when_disabled(stack,monkeypatch):
    from contextlib import asynccontextmanager
    from app.main import lifespan
    @asynccontextmanager
    async def fake_connection():
        yield SimpleNamespace(execute=AsyncMock())
    engine=SimpleNamespace(connect=fake_connection,dispose=AsyncMock())
    with patch('app.main.create_async_engine',return_value=engine), \
         patch('app.main.async_sessionmaker',return_value=stack.sessions), \
         patch('app.main.Redis.from_url',return_value=stack.redis), \
         patch('app.main.run_worker',new_callable=AsyncMock) as worker:
        async with lifespan(stack.app):
            assert stack.app.state.worker_task is None
            worker.assert_not_called()

async def test_slow_consumer_does_not_cause_republication(stack):
    await ingest(stack,event())
    assert await reconcile_outbox(stack.queue,stack.sessions)==1
    async with stack.sessions() as session:
        row=(await session.execute(select(EventOutbox))).scalar_one()
        row.published_at=datetime.now(timezone.utc)-timedelta(minutes=3)
        await session.commit()
    assert await reconcile_outbox(stack.queue,stack.sessions)==0
    assert await stack.redis.xlen(stack.queue.stream)==1

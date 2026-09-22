#!/usr/bin/env python3
"""Repeatable synthetic data: python -m scripts.generate_synthetic_data.

Customers/campaigns are inserted only if absent. Deterministic event IDs make
re-runs safe. Events enter the same durable outbox as API ingestion and are
processed by workers. --as-of makes timestamps reproducible across days.
"""
import argparse
import asyncio
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import get_settings
from app.db.models import Customer, Campaign, CampaignMetric, Event, EventOutbox

CHANNELS = ["email", "sms", "whatsapp", "push", "web"]
TYPES = ["open", "click", "purchase", "unsubscribe", "complaint", "send", "delivered", "view"]
OBJECTIVES = ["conversion", "retention", "winback", "awareness", "upsell"]

async def generate(customers, events, campaigns, seed, as_of):
    rng = random.Random(seed)
    engine = create_async_engine(get_settings().DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            for start in range(0, customers, 500):
                rows = []
                for i in range(start, min(start+500, customers)):
                    rows.append(dict(id=f"cust_{i:06d}",
                        attributes={"vip":rng.random()<.05,"segment":rng.choice(list("ABCD"))},
                        email_opt_in=rng.random()<.9, sms_opt_in=rng.random()<.7,
                        whatsapp_opt_in=rng.random()<.6, push_opt_in=rng.random()<.8,
                        last_active=as_of-timedelta(days=rng.randint(0,60)), has_converted=rng.random()<.2))
                await session.execute(insert(Customer).values(rows).on_conflict_do_nothing(index_elements=["id"]))
                await session.commit()
            for i in range(campaigns):
                cid=f"camp_{i:03d}"
                ch,obj=rng.choice(CHANNELS),rng.choice(OBJECTIVES)
                stmt=insert(Campaign).values(id=cid,name=f"{obj.title()} · {ch}",channel=ch,
                    objective=obj,status="active",audience_size=rng.randint(500,20000))
                created=(await session.execute(stmt.on_conflict_do_nothing(index_elements=["id"]).returning(Campaign.id))).scalar_one_or_none()
                metrics=[(name,round(rng.uniform(low,high),4)) for name,low,high in
                    [("open_rate",.08,.45),("click_rate",.005,.08),("conversion_rate",.001,.03),("unsubscribe_rate",.0005,.01)]]
                if created:
                    session.add_all([CampaignMetric(campaign_id=cid,metric_name=name,value=value) for name,value in metrics])
            await session.commit()
            accepted=0
            for start in range(0,events,500):
                rows=[]; payloads={}
                for i in range(start,min(start+500,events)):
                    ts=as_of-timedelta(minutes=rng.randint(0,60*24*45))
                    eid=f"seed_{seed}_{as_of.strftime('%Y%m%dT%H%M%S')}_{i:08d}"
                    row=dict(event_id=eid,customer_id=f"cust_{rng.randrange(customers):06d}",
                             channel=rng.choice(CHANNELS),event_type=rng.choice(TYPES),timestamp=ts,
                             metadata_={"source":"synthetic","index":i},status="pending")
                    rows.append(row)
                    payloads[eid]={**{k:v for k,v in row.items() if k not in ('metadata_','status')},
                                   "timestamp":ts.isoformat(),"metadata":row['metadata_']}
                inserted=(await session.execute(insert(Event).values(rows).on_conflict_do_nothing(
                    index_elements=["event_id"]).returning(Event.event_id))).scalars().all()
                session.add_all([EventOutbox(event_id=eid,payload=payloads[eid]) for eid in inserted])
                await session.commit()
                accepted+=len(inserted)
            print(f"Seed complete: {customers} customer IDs, {campaigns} campaign IDs, {accepted} new events, {events-accepted} duplicate events skipped.")
            print("Workers process the durable outbox. Check /api/v1/system/health for progress.")
    finally:
        await engine.dispose()

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--customers',type=int,default=500)
    parser.add_argument('--events',type=int,default=1000)
    parser.add_argument('--campaigns',type=int,default=10)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--as-of',default=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).isoformat())
    args=parser.parse_args()
    if args.customers < 1 or args.events < 0 or args.campaigns < 0:
        parser.error('customers must be positive; events and campaigns must be nonnegative')
    as_of=datetime.fromisoformat(args.as_of.replace('Z','+00:00'))
    if as_of.tzinfo is None:
        parser.error('--as-of must include a timezone')
    asyncio.run(generate(args.customers,args.events,args.campaigns,args.seed,as_of))

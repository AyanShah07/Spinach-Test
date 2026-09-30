#!/usr/bin/env python3
"""Repeatable synthetic data: python -m scripts.generate_synthetic_data.

Customers and events are insert-if-absent (deterministic event IDs make
re-runs safe, and the duplicates exercise the dedup path). Campaigns and
their metrics are REFRESHED on every seed so changes to the generator take
effect on existing databases. Events enter the same durable outbox as API
ingestion and are processed by workers. --as-of makes timestamps
reproducible across days.

Campaigns are shaped to resemble real tracking data:
  - Audiences follow a power law (many small tests, a few large blasts).
  - Metric availability reflects tracking maturity: conversion tracking
    depends on the objective (awareness campaigns rarely have it) and
    unsubscribe tracking is only present on ~70% of campaigns.
  - Rates are channel-appropriate (WhatsApp read rates dwarf push opens).
  - Weak engagement correlates with higher unsubscribe rates.
Without that variety every campaign looks fully evidenced and the computed
confidence score saturates at 100%.
"""
import argparse
import asyncio
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import get_settings
from app.db.models import Customer, Campaign, CampaignMetric, Event, EventOutbox

CHANNELS = ["email", "sms", "whatsapp", "push", "web"]
TYPES = ["open", "click", "purchase", "unsubscribe", "complaint", "send", "delivered", "view"]
OBJECTIVES = ["conversion", "retention", "winback", "awareness", "upsell"]

# (open, click, conversion, unsubscribe) rate ranges per channel, from
# typical ESP/platform benchmarks.
CHANNEL_METRIC_PROFILE = {
    "email":    ((.18, .42), (.010, .060), (.002, .035), (.0005, .008)),
    "sms":      ((.05, .15), (.020, .080), (.001, .030), (.001, .012)),
    "whatsapp": ((.45, .75), (.030, .120), (.002, .040), (.0005, .006)),
    "push":     ((.03, .15), (.005, .040), (.001, .025), (.002, .015)),
    "web":      ((.02, .10), (.010, .090), (.001, .030), (.0002, .002)),
}

# How often conversion tracking exists, by what the campaign is for.
CONVERSION_TRACKING_P = {
    "conversion": .95, "upsell": .85, "winback": .6, "retention": .35, "awareness": .1,
}
# Unsubscribe tracking is a maturity signal, not universal.
UNSUBSCRIBE_TRACKING_P = .7

async def generate(customers, events, campaigns, seed, as_of, override_db_url: str | None = None):
    rng = random.Random(seed)
    db_url = override_db_url or get_settings().DATABASE_URL
    engine = create_async_engine(db_url)
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
                audience=int(10 ** rng.uniform(2, 4.7))  # power law: ~100 to ~50k, median ~700
                status=rng.choices(["active","completed","paused"],weights=[.7,.2,.1])[0]
                stmt=insert(Campaign).values(id=cid,name=f"{obj.title()} · {ch}",channel=ch,
                    objective=obj,status=status,audience_size=audience)
                stmt=stmt.on_conflict_do_update(index_elements=["id"], set_={
                    "name":stmt.excluded.name,"channel":stmt.excluded.channel,
                    "objective":stmt.excluded.objective,"status":stmt.excluded.status,
                    "audience_size":stmt.excluded.audience_size})
                await session.execute(stmt)
                (o_lo,o_hi),(c_lo,c_hi),(v_lo,v_hi),(u_lo,u_hi)=CHANNEL_METRIC_PROFILE[ch]
                open_rate=round(rng.uniform(o_lo,o_hi),4)
                metrics=[("open_rate",open_rate),
                         ("click_rate",round(rng.uniform(c_lo,c_hi),4))]
                if rng.random() < CONVERSION_TRACKING_P[obj]:
                    conv_hi=v_hi if obj in ("conversion","upsell") else round(v_hi*.6,4)
                    metrics.append(("conversion_rate",round(rng.uniform(v_lo,conv_hi),4)))
                if rng.random() < UNSUBSCRIBE_TRACKING_P:
                    # Churny campaigns: below-median open rates skew the
                    # unsubscribe draw to the upper half of its range.
                    if open_rate < (o_lo+o_hi)/2:
                        u_lo=round((u_lo+u_hi)/2,4)
                    metrics.append(("unsubscribe_rate",round(rng.uniform(u_lo,u_hi),4)))
                await session.execute(delete(CampaignMetric).where(CampaignMetric.campaign_id==cid))
                session.add_all([CampaignMetric(campaign_id=cid,metric_name=name,value=value)
                                 for name,value in metrics])
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

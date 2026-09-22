"use client";

import { useEffect, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import * as api from "@/lib/api";

type Tab = "health" | "ingest" | "customer" | "audience" | "analyze" | "dlq";
type Result = { data?: unknown; error?: string };
const channels = ["email", "sms", "whatsapp", "push", "web"];
const eventTypes = ["open", "click", "purchase", "unsubscribe", "complaint", "send", "delivered", "bounce", "view"];
const selectClass = "h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const tabs: {id:Tab; label:string}[] = [{id:"health",label:"Overview"},{id:"ingest",label:"Ingest event"},{id:"customer",label:"Customers"},{id:"audience",label:"Audience"},{id:"analyze",label:"Campaign analysis"},{id:"dlq",label:"Failed events"}];

function Select({id, label, value, values, onChange}: {id:string;label:string;value:string;values:string[];onChange:(s:string)=>void}) {
  return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><select id={id} className={selectClass} value={value} onChange={e=>onChange(e.target.value)}>{values.map(v=><option key={v} value={v}>{v}</option>)}</select></div>;
}
function Metric({label,value}: {label:string;value:React.ReactNode}) {
  return <div className="rounded-lg border bg-muted/20 p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 text-xl font-semibold">{value ?? "—"}</p></div>;
}
function Results({tab,data,onReplay,busy}: {tab:Tab;data:unknown;onReplay:(id:number)=>void;busy:boolean}) {
  if (tab === "health") {
    const h = data as api.Health;
    return <div className="grid gap-3 sm:grid-cols-3"><Metric label="Database" value={h.database}/><Metric label="Redis" value={h.redis}/><Metric label="Worker" value={h.worker}/><Metric label="Unread events" value={h.queue_depth}/><Metric label="Pending acknowledgements" value={h.queue_pending}/><Metric label="Unpublished / failed" value={`${h.outbox_pending ?? "—"} / ${h.dlq_size ?? "—"}`}/></div>;
  }
  if (tab === "customer") {
    const {customer:c,timeline} = data as {customer:api.Customer;timeline:api.TimelineEvent[]};
    const breakdown = Object.entries(c.channel_breakdown || {});
    const max = Math.max(1,...breakdown.map(([,v])=>v.count));
    return <div className="space-y-6"><div className="grid gap-3 sm:grid-cols-3"><Metric label="Current engagement" value={c.engagement_score?.toFixed(2)}/><Metric label="Last active" value={c.last_active ? new Date(c.last_active).toLocaleDateString() : "No events"}/><Metric label="Converted" value={c.has_converted ? "Yes" : "No"}/></div>
      <div><h3 className="mb-3 font-medium">Channel activity</h3>{breakdown.length === 0 && <p className="text-sm text-muted-foreground">No processed activity yet.</p>}{breakdown.map(([channel,v])=><div key={channel} className="mb-3"><div className="mb-1 flex justify-between text-sm"><span>{channel}</span><span>{v.count} events</span></div><div role="meter" aria-label={`${channel} events`} aria-valuenow={v.count} aria-valuemin={0} aria-valuemax={max} className="h-2 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{width:`${v.count/max*100}%`}}/></div></div>)}</div>
      <div className="flex flex-wrap gap-2">{(["email","sms","whatsapp","push"] as const).map(ch=><Badge key={ch} variant="secondary">{ch}: {c[`${ch}_opt_in`] ? "opted in" : "not opted in"}</Badge>)}</div>
      <div><h3 className="mb-3 font-medium">Recent events</h3>{timeline.length ? <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">Event</th><th className="p-2">Channel</th><th className="p-2">When</th></tr></thead><tbody>{timeline.map(e=><tr className="border-t" key={e.event_id}><td className="p-2">{e.event_type}</td><td className="p-2">{e.channel}</td><td className="p-2">{new Date(e.timestamp).toLocaleString()}</td></tr>)}</tbody></table></div> : <p className="text-sm text-muted-foreground">No events recorded.</p>}</div>
    </div>;
  }
  if (tab === "audience") {
    const a=data as api.Audience;
    return <div className="space-y-4"><p className="text-sm">{a.returned_size} of {a.requested_size} requested customers eligible. Previewing does not consume sending limits.</p>{a.customers.length ? <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">Customer</th><th className="p-2">Score now</th><th className="p-2">Reason</th></tr></thead><tbody>{a.customers.map(c=><tr key={c.customer_id} className="border-t"><td className="p-2 font-mono">{c.customer_id}</td><td className="p-2">{c.score.toFixed(2)}</td><td className="p-2">{c.reason}</td></tr>)}</tbody></table></div> : <p className="text-muted-foreground">No eligible customers. Check opt-in, recent activity, and sends in the last 24 hours.</p>}</div>;
  }
  if (tab === "analyze") {
    const {analysis:a}=data as api.Analysis;
    return <div className="space-y-5"><div className="flex gap-2"><Badge>{a.source === "llm" ? "AI assisted" : "Rule-based fallback"}</Badge><Badge variant="secondary">Confidence: {Math.round(a.confidence*100)}%</Badge></div><div><h3 className="font-medium">Measured facts</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{a.facts.map((s,i)=><li key={i}>{s}</li>)}</ul></div><div><h3 className="font-medium">Suggested next actions</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{a.recommendations.map((s,i)=><li key={i}>{s}</li>)}</ul></div></div>;
  }
  if (tab === "dlq") {
    const rows=data as api.DeadLetter[];
    return rows.length ? <div className="space-y-3">{rows.map(row=><div key={row.id} className="rounded-lg border p-4"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono text-sm">{row.event_id}</span><Button size="sm" disabled={busy || !!row.replayed_at} onClick={()=>onReplay(row.id)}>{row.replayed_at ? "Replayed" : "Replay event"}</Button></div><p className="mt-2 break-words text-sm text-muted-foreground">{row.failure_reason}</p><p className="mt-1 text-xs">Retries: {row.retry_count}</p></div>)}</div> : <p>No failed events. Your queue is clear.</p>;
  }
  const e=data as {event_id:string;status:string;message?:string};
  return <div className="space-y-2"><Badge>{e.status}</Badge><p className="break-all font-mono text-sm">{e.event_id}</p><p className="text-sm text-muted-foreground">{e.message || (e.status === "processed" ? "Event processed. The customer score is updated." : "Event saved. Processing continues in the background.")}</p></div>;
}

export default function HomePage() {
  const [tab,setTab]=useState<Tab>("health");
  const [busy,setBusy]=useState(false);
  const [results,setResults]=useState<Partial<Record<Tab,Result>>>({});
  const [customerId,setCustomerId]=useState("cust_000001");
  const [channel,setChannel]=useState("email");
  const [kind,setKind]=useState("open");
  const [size,setSize]=useState("20");
  const [objective,setObjective]=useState("conversion");
  const [campaignId,setCampaignId]=useState("camp_000");
  const [customers,setCustomers]=useState<{id:string}[]>([]);
  const [campaigns,setCampaigns]=useState<api.Campaign[]>([]);
  const [key,setKey]=useState("");
  const [catalogError,setCatalogError]=useState("");
  const [refresh,setRefresh]=useState(0);
  const active=useRef<AbortController | null>(null);

  useEffect(()=>{
    const controller=new AbortController();
    Promise.all([api.listCustomers(controller.signal),api.listCampaigns(controller.signal)]).then(([c, p])=>{
      setCustomers(c);setCampaigns(p);setCatalogError("");
    }).catch(e=>{if(!controller.signal.aborted)setCatalogError(e.message);});
    return ()=>controller.abort();
  },[refresh]);
  useEffect(()=>()=>active.current?.abort(),[]);

  async function run(fn:(signal:AbortSignal)=>Promise<unknown>, target:Tab=tab) {
    active.current?.abort();
    const controller=new AbortController();active.current=controller;
    setBusy(true);setResults(prev=>({...prev,[target]:undefined}));
    try {const data=await fn(controller.signal);if(!controller.signal.aborted)setResults(prev=>({...prev,[target]:{data}}));}
    catch(e){if(!controller.signal.aborted)setResults(prev=>({...prev,[target]:{error:e instanceof Error ? e.message : "Something went wrong"}}));}
    finally {if(active.current===controller)setBusy(false);}
  }
  const result=results[tab];
  const customerField=(id:string)=><div className="space-y-2"><Label htmlFor={id}>Customer ID</Label><Input id={id} list="customer-options" value={customerId} required onChange={e=>setCustomerId(e.target.value)}/></div>;
  return <div className="space-y-6">
    <div><h1 className="text-3xl font-bold tracking-tight">Campaign intelligence</h1><p className="mt-2 text-muted-foreground">Explore customer engagement, preview audiences, and turn campaign results into next actions.</p></div>
    <details className="rounded-lg border p-3 text-sm"><summary className="cursor-pointer">Connection settings</summary><div className="mt-3 flex flex-wrap items-end gap-3"><div className="min-w-56 flex-1 space-y-2"><Label htmlFor="api-key">API key (if configured)</Label><Input id="api-key" type="password" autoComplete="off" value={key} onChange={e=>setKey(e.target.value)}/></div><Button variant="outline" onClick={()=>{api.setApiKey(key);setRefresh(n=>n+1);}}>Apply and reconnect</Button></div><p className="mt-2 text-xs text-muted-foreground">The key is kept only in this browser tab&apos;s memory.</p></details>
    {catalogError && <div role="status" className="rounded-lg border border-amber-500/40 p-3 text-sm">Customer and campaign lists are unavailable. {catalogError} <Button variant="ghost" size="sm" onClick={()=>setRefresh(n=>n+1)}>Retry</Button></div>}
    <datalist id="customer-options">{customers.map(c=><option key={c.id} value={c.id}/>)}</datalist>
    <Tabs.Root value={tab} onValueChange={value=>{active.current?.abort();setBusy(false);setTab(value as Tab);}}>
      <Tabs.List aria-label="Console sections" className="mb-6 flex flex-wrap gap-2">{tabs.map(t=><Tabs.Trigger key={t.id} value={t.id} className="rounded-md border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:border-primary data-[state=active]:bg-primary data-[state=active]:text-primary-foreground">{t.label}</Tabs.Trigger>)}</Tabs.List>
      <Tabs.Content value="health"><Card><CardHeader><CardTitle>Service overview</CardTitle><CardDescription>Database, processing worker, and event backlog.</CardDescription></CardHeader><CardContent><Button disabled={busy} onClick={()=>run(api.health)}>{busy ? "Checking…" : "Check health"}</Button></CardContent></Card></Tabs.Content>
      <Tabs.Content value="ingest"><Card><CardHeader><CardTitle>Record an event</CardTitle><CardDescription>Events are saved durably, then processed in the background. New customers start without channel opt-in.</CardDescription></CardHeader><CardContent><form className="space-y-4" onSubmit={e=>{e.preventDefault();run(async signal=>{
        const accepted=await api.postEvent({event_id:`evt_${crypto.randomUUID()}`,customer_id:customerId.trim(),channel,event_type:kind,timestamp:new Date().toISOString(),metadata:{source:"console"}},signal);
        for(let i=0;i<10;i++){await new Promise<void>((resolve,reject)=>{const onAbort=()=>{clearTimeout(timer);reject(new DOMException("Aborted","AbortError"));};const timer=setTimeout(()=>{signal.removeEventListener("abort",onAbort);resolve();},500);signal.addEventListener("abort",onAbort,{once:true});});const state=await api.eventStatus(accepted.event_id,signal);if(state.status!=="pending")return state;}
        return {...accepted,message:"Saved successfully. Processing is still pending; check service health or the customer timeline."};
      });}}><div className="grid gap-4 sm:grid-cols-3">{customerField("event-customer")}<Select id="event-channel" label="Channel" value={channel} values={channels} onChange={setChannel}/><Select id="event-type" label="Event type" value={kind} values={eventTypes} onChange={setKind}/></div><Button disabled={busy}>{busy ? "Processing…" : "Send event"}</Button></form></CardContent></Card></Tabs.Content>
      <Tabs.Content value="customer"><Card><CardHeader><CardTitle>Customer profile</CardTitle><CardDescription>Current score, channel eligibility, and the latest 50 events.</CardDescription></CardHeader><CardContent><form className="max-w-md space-y-4" onSubmit={e=>{e.preventDefault();run(async signal=>{const [customer,timeline]=await Promise.all([api.getCustomer(customerId,signal),api.getTimeline(customerId,signal)]);return {customer,timeline};});}}>{customerField("profile-customer")}<Button disabled={busy}>{busy ? "Loading…" : "Load customer"}</Button></form></CardContent></Card></Tabs.Content>
      <Tabs.Content value="audience"><Card><CardHeader><CardTitle>Preview an audience</CardTitle><CardDescription>Opted-in customers active within 30 days, excluding those already sent a message on this channel in the last 24 hours.</CardDescription></CardHeader><CardContent><form className="space-y-4" onSubmit={e=>{e.preventDefault();run(signal=>api.recommendAudience({objective,channel,conditions:{max_days_inactive:30},audience_size:Number(size)},signal));}}><div className="grid gap-4 sm:grid-cols-3"><Select id="audience-channel" label="Channel" value={channel} values={channels} onChange={setChannel}/><Select id="objective" label="Objective" value={objective} values={["conversion","retention","winback","awareness","upsell"]} onChange={setObjective}/><div className="space-y-2"><Label htmlFor="audience-size">Audience size</Label><Input id="audience-size" type="number" min={1} max={10000} step={1} required value={size} onChange={e=>setSize(e.target.value)}/></div></div><Button disabled={busy}>{busy ? "Finding customers…" : "Preview audience"}</Button></form></CardContent></Card></Tabs.Content>
      <Tabs.Content value="analyze"><Card><CardHeader><CardTitle>Campaign analysis</CardTitle><CardDescription>Measured facts and suggestions, with a fallback when an AI provider is unavailable.</CardDescription></CardHeader><CardContent><form className="max-w-lg space-y-4" onSubmit={e=>{e.preventDefault();run(signal=>api.analyzeCampaign(campaignId,signal));}}><div className="space-y-2"><Label htmlFor="campaign">Campaign</Label><Input id="campaign" list="campaign-options" required value={campaignId} onChange={e=>setCampaignId(e.target.value)}/><datalist id="campaign-options">{campaigns.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</datalist></div><Button disabled={busy}>{busy ? "Analyzing…" : "Analyze campaign"}</Button></form></CardContent></Card></Tabs.Content>
      <Tabs.Content value="dlq"><Card><CardHeader><CardTitle>Failed events</CardTitle><CardDescription>Inspect failures and replay events after resolving their cause. Replay history is retained.</CardDescription></CardHeader><CardContent><Button disabled={busy} onClick={()=>run(api.listDlq)}>{busy ? "Loading…" : "Refresh failed events"}</Button></CardContent></Card></Tabs.Content>
    </Tabs.Root>
    <div aria-live="polite" aria-busy={busy}>{result && <Card><CardHeader><CardTitle>{result.error ? "Request failed" : "Results"}</CardTitle></CardHeader><CardContent>{result.error ? <p role="alert" className="text-sm text-red-300">{result.error}</p> : <><Results tab={tab} data={result.data} busy={busy} onReplay={id=>run(async signal=>{await api.replayDlq(id,signal);return api.listDlq(signal);})}/><details className="mt-6 text-sm"><summary className="cursor-pointer text-muted-foreground">View response JSON</summary><pre className="mt-3 max-h-96 overflow-auto rounded bg-muted/40 p-3 text-xs">{JSON.stringify(result.data,null,2)}</pre></details></>}</CardContent></Card>}</div>
  </div>;
}

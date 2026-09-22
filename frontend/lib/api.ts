const BASE = process.env.NEXT_PUBLIC_API_URL || "/api/backend";
let apiKey = "";
export function setApiKey(value: string) { apiKey = value; }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      signal: init.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(35000)]) : AbortSignal.timeout(35000),
      headers: { "Content-Type": "application/json", ...(apiKey ? { "X-API-Key": apiKey } : {}), ...init.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Cannot reach the service. Check that the backend is running, then try again.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const details = body?.details?.map?.((item: { loc: string[]; msg: string }) => `${item.loc.join(".")}: ${item.msg}`).join("; ");
    throw new Error(details || body?.error || body?.detail || (body?.status === "degraded" ? "Service is degraded. Check the database, Redis, and worker." : `Request failed (${response.status})`));
  }
  return body as T;
}
export type Customer = { id: string; attributes: Record<string, unknown>; engagement_score: number | null; channel_breakdown: Record<string, { count: number; total_weight: number }>; email_opt_in: boolean; sms_opt_in: boolean; whatsapp_opt_in: boolean; push_opt_in: boolean; last_active: string | null; has_converted: boolean };
export type TimelineEvent = { event_id: string; channel: string; event_type: string; timestamp: string };
export type Campaign = { id: string; name: string; objective: string; channel: string };
export type Audience = { preview: boolean; returned_size: number; requested_size: number; customers: { customer_id: string; score: number; reason: string }[] };
export type Analysis = { campaign_id: string; analysis: { facts: string[]; recommendations: string[]; source: string; confidence: number } };
export type Health = { status: string; database: string; redis: string; worker: string; queue_depth: number | null; queue_pending: number | null; outbox_pending: number | null; dlq_size: number | null };
export type DeadLetter = { id: number; event_id: string; failure_reason: string; retry_count: number; replayed_at: string | null };
export const postEvent = (payload: Record<string, unknown>, signal?: AbortSignal) => request<{event_id: string; status: string; message: string}>("/events", { method: "POST", body: JSON.stringify(payload), signal });
export const eventStatus = (id: string, signal?: AbortSignal) => request<{event_id: string; status: string}>(`/events/${encodeURIComponent(id)}`, {signal});
export const getCustomer = (id: string, signal?: AbortSignal) => request<Customer>(`/customers/${encodeURIComponent(id)}`, {signal});
export const getTimeline = (id: string, signal?: AbortSignal) => request<TimelineEvent[]>(`/customers/${encodeURIComponent(id)}/timeline`, {signal});
export const listCustomers = (signal?: AbortSignal) => request<{id:string}[]>("/customers?limit=100", {signal});
export const recommendAudience = (body: Record<string, unknown>, signal?: AbortSignal) => request<Audience>("/audience/recommend", {method:"POST", body:JSON.stringify(body),signal});
export const listCampaigns = (signal?: AbortSignal) => request<Campaign[]>("/campaigns?limit=200", {signal});
export const analyzeCampaign = (id: string, signal?: AbortSignal) => request<Analysis>(`/campaigns/${encodeURIComponent(id)}/analyze`, {method:"POST",signal});
export const health = (signal?: AbortSignal) => request<Health>("/system/health", {signal});
export const listDlq = (signal?: AbortSignal) => request<DeadLetter[]>("/system/dlq", {signal});
export const replayDlq = (id: number, signal?: AbortSignal) => request(`/system/dlq/${id}/replay`, {method:"POST",signal});

export type LiveZone = {
  id: number;
  name: string;
  watts: number | null;
  pin_x: number;
  pin_y: number;
  flagged: boolean;
};

export type RatePeriod = "on_peak" | "off_peak" | "super_off_peak";

export type Live = {
  as_of: string | null;
  stale: boolean;
  whole_house_w: number | null;
  unmetered_w: number | null;
  charger_estimate_w: number | null;
  cost_per_hour_estimate: number | null;
  rate_period: RatePeriod;
  zones: LiveZone[];
  month_kwh: number;
  month_coverage: number;
};

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} answered ${response.status}`);
  return response.json();
}

export type MaintenanceItem = { id: number; name: string; last_done: string | null };

export type MaintenanceTask = {
  id: number;
  name: string;
  category: string;
  notes: string;
  interval_months: number | null;
  items: MaintenanceItem[];
  last_done: string | null;
  next_due: string | null;
  overdue: boolean;
};

export async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-Control-Action": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} answered ${response.status}`);
  return (response.status === 204 ? null : await response.json()) as T;
}

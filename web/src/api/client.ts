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

export class ApiError extends Error {
  constructor(
    path: string,
    readonly status: number,
    readonly retryAfter: string | null = null,
  ) {
    super(`${path} answered ${status}`);
  }
}

export async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-Control-Action": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(path, response.status, response.headers.get("Retry-After"));
  return (response.status === 204 ? null : await response.json()) as T;
}

export type CameraInfo = {
  id: number;
  name: string;
  kind: string;
  last_event: string | null;
  last_event_at: string | null;
};

export type CameraEvent = { camera_id: number; camera: string; type: string; occurred_at: string };

export type NetworkArc = {
  lat: number;
  lon: number;
  country_code: string;
  country: string;
  queries: number;
  blocked: number;
  state: string;
};

export type Network = {
  top_devices: { id: string; name: string; device_type: string; queries: number; blocked: number }[];
  arcs: NetworkArc[];
  home: { lat: number; lon: number } | null;
};

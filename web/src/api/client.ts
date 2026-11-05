export type LiveZone = {
  id: number;
  name: string;
  watts: number | null;
  pin_x: number;
  pin_y: number;
  room: string | null;
  floor: string | null;
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
  outdoor_f: number | null;
  outdoor_code: number | null;
  outdoor_is_day: boolean | null;
  today_kwh: number;
  today_cost: number;
  today_coverage: number;
  whole_house_pin: { x: number; y: number } | null;
  recent_w: { time: string; watts: number }[];
};

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} answered ${response.status}`);
  return response.json();
}

export type MaintenanceItem = { id: number; name: string; last_done: string | null };

export type RepeatUnit = "day" | "week" | "month";

export type CurrentBill = {
  period_start: string;
  period_end: string;
  day: number;
  days: number;
  kwh_so_far: number;
  cost_so_far: number;
  projected_kwh: number;
  projected_cost: number;
  last_charge: number;
  change_pct: number;
  verdict: "less" | "more" | "about the same";
  manual_days: number;
};

export type MaintenanceTask = {
  id: number;
  name: string;
  category: string;
  notes: string;
  repeat_every: number | null;
  repeat_unit: RepeatUnit;
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
  lanthorn_url: string;
};

export type TrafficCamera = { nickname: string; name: string; view: number; image_url: string; home: boolean };

import type { Feature } from "geojson";
import iso from "iso-3166-1";

// Copied from Lanthorn, recoloured to this app's palette.
export const COLORS = { allowed: "#d3b877", blocked: "#d79971", land: "#354331", landFill: "#192119" };
const RAMP = { from: "#6f7d5c", to: "#d3b877" };

/** The map uses ISO numeric codes; Lanthorn reports alpha-2. */
export function alpha2For(country: Feature): string | null {
  if (country.id === undefined || country.id === null) return null;
  return iso.whereNumeric(String(country.id).padStart(3, "0"))?.alpha2 ?? null;
}

function channels(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function mix(from: string, to: string, t: number): string {
  const [ar, ag, ab] = channels(from);
  const [br, bg, bb] = channels(to);
  const at = Math.max(0, Math.min(1, t));
  const to255 = (a: number, b: number) => Math.round(a + (b - a) * at);
  return `#${[to255(ar, br), to255(ag, bg), to255(ab, bb)].map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

/** Log scale: volumes span orders of magnitude. Countries with no traffic stay unlit. */
export function trafficColor(queries: number, busiest: number): string {
  if (queries <= 0 || busiest <= 0) return COLORS.land;
  const share = Math.log10(1 + queries) / Math.log10(1 + busiest);
  return mix(RAMP.from, RAMP.to, 0.25 + 0.75 * Math.min(1, share));
}

export function trafficFromArcs(arcs: { country_code: string; queries: number }[]): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const arc of arcs) totals[arc.country_code] = (totals[arc.country_code] ?? 0) + arc.queries;
  return totals;
}

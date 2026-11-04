import type { RatePeriod } from "../api/client";

export function formatWatts(watts: number | null): string {
  if (watts === null) return "—";
  return watts >= 1000 ? `${(watts / 1000).toFixed(1)} kW` : `${Math.round(watts)} W`;
}

export const formatKwh = (value: number) => `${value < 10 ? value.toFixed(1) : Math.round(value)} kWh`;

export function dueText(nextDue: string | null, overdue: boolean): string | null {
  if (!nextDue) return null;
  const [year, month, day] = nextDue.split("-").map(Number);
  const when = new Date(year, month - 1, day).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
  return overdue ? `Overdue since ${when}` : `Due ${when}`;
}

export const PERIOD_LABEL: Record<RatePeriod, string> = {
  on_peak: "On-peak",
  off_peak: "Off-peak",
  super_off_peak: "Super off-peak",
};

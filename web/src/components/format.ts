import type { CurrentBill, RatePeriod, RepeatUnit } from "../api/client";

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

export function repeatText(every: number | null, unit: RepeatUnit): string {
  if (every === null) return "Doesn't repeat";
  return every === 1 ? `Every ${unit}` : `Every ${every} ${unit}s`;
}

export const PERIOD_LABEL: Record<RatePeriod, string> = {
  on_peak: "On-peak",
  off_peak: "Off-peak",
  super_off_peak: "Super off-peak",
};


function shortDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** The words for the current bill, shared by the home card and the Bills page. */
export function thisBillText(bill: CurrentBill) {
  const pct = Math.round(Math.abs(bill.change_pct) * 100);
  return {
    projected: `≈ $${Math.round(bill.projected_cost)}`,
    period: `${shortDate(bill.period_start)} – ${shortDate(bill.period_end)} · day ${bill.day} of ${bill.days}`,
    compare: `Last bill $${bill.last_charge.toFixed(2)} · on track for ${
      bill.verdict === "about the same" ? "about the same" : `${pct}% ${bill.verdict}`
    }`,
    soFar: `$${Math.round(bill.cost_so_far)} so far · ${Math.round(bill.kwh_so_far)} kWh`,
    higher: bill.verdict === "more",
  };
}

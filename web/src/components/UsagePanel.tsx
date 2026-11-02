import type { Live, RatePeriod } from "../api/client";
import { formatWatts } from "./format";

const PERIOD_LABEL: Record<RatePeriod, string> = {
  on_peak: "On-peak",
  off_peak: "Off-peak",
  super_off_peak: "Super off-peak",
};

export function UsagePanel({ live }: { live: Live }) {
  return (
    <div className="panel usage">
      <div className="label">USING NOW</div>
      <div className="big">{formatWatts(live.whole_house_w)}</div>
      {live.stale ? <p className="warn">No live reading from the monitor</p> : null}
      <p className="sub">{PERIOD_LABEL[live.rate_period]}</p>
      {live.cost_per_hour_estimate !== null ? (
        <p className="sub">About ${live.cost_per_hour_estimate.toFixed(2)}/hr (estimate)</p>
      ) : null}
      {live.unmetered_w !== null ? (
        <p className="sub">{formatWatts(live.unmetered_w)} not on any zone</p>
      ) : null}
      <p className="sub">
        {Math.round(live.month_kwh)} kWh this month, {Math.round(live.month_coverage * 100)}%
        recorded
      </p>
    </div>
  );
}

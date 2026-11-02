import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getJson, type MaintenanceTask } from "../api/client";
import { dueText } from "./format";

type ThermostatSummary = {
  name: string;
  stale: boolean;
  ambient_f: number | null;
  setpoint_f: number | null;
};

function climateText(thermostats: ThermostatSummary[] | undefined): string {
  if (!thermostats?.length) return "Thermostats: no readings yet";
  return thermostats
    .map((t) => {
      if (t.stale || t.ambient_f === null) return `${t.name}: no recent reading`;
      const target = t.setpoint_f === null ? "" : ` → ${Math.round(t.setpoint_f)}°`;
      return `${t.name} ${Math.round(t.ambient_f)}°${target}`;
    })
    .join(" · ");
}

export function StatusStrip() {
  const next = useQuery({
    queryKey: ["maintenance-next"],
    queryFn: () => getJson<MaintenanceTask | null>("/api/maintenance/next"),
    refetchInterval: 60_000,
  });
  const bill = useQuery({
    queryKey: ["bill-latest"],
    queryFn: () => getJson<{ actual_charge: number } | null>("/api/bills/latest"),
    refetchInterval: 3_600_000,
  });

  const climate = useQuery({
    queryKey: ["climate-summary"],
    queryFn: () => getJson<{ thermostats: ThermostatSummary[] }>("/api/climate/summary"),
    refetchInterval: 60_000,
  });

  return (
    <div className="strip">
      <Link to="/climate">{climateText(climate.data?.thermostats)}</Link>
      <Link to="/maintenance">
        {next.data
          ? `${next.data.name}: ${dueText(next.data.next_due, next.data.overdue)}`
          : "Maintenance: nothing scheduled"}
      </Link>
      <Link to="/bills">
        {bill.data ? `Last bill: $${bill.data.actual_charge.toFixed(2)} actual` : "Last bill: none yet"}
      </Link>
    </div>
  );
}

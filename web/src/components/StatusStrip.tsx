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

function climateLines(thermostats: ThermostatSummary[] | undefined): string[] {
  if (!thermostats?.length) return ["No readings yet"];
  return thermostats.map((t) => {
    if (t.stale || t.ambient_f === null) return `${t.name}: no recent reading`;
    const target = t.setpoint_f === null ? "" : ` → ${Math.round(t.setpoint_f)}°`;
    return `${t.name} ${Math.round(t.ambient_f)}°${target}`;
  });
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
      <Link className="panel tile" to="/climate">
        <span className="eyebrow">A/C</span>
        {climateLines(climate.data?.thermostats).map((line) => (
          <span key={line} className="tile-line">
            {line}
          </span>
        ))}
      </Link>
      <Link className="panel tile" to="/maintenance">
        <span className="eyebrow">Maintenance</span>
        {next.data ? (
          <>
            <span className="tile-value">{next.data.name}</span>
            <span className="sub">{dueText(next.data.next_due, next.data.overdue)}</span>
          </>
        ) : (
          <span className="tile-value">Nothing scheduled</span>
        )}
      </Link>
      <Link className="panel tile" to="/bills">
        <span className="eyebrow">Last bill</span>
        {bill.data ? (
          <>
            <span className="tile-value">${bill.data.actual_charge.toFixed(2)}</span>
            <span className="sub">actual charge</span>
          </>
        ) : (
          <span className="tile-value">None yet</span>
        )}
      </Link>
    </div>
  );
}

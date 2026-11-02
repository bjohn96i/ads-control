import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getJson, type MaintenanceTask } from "../api/client";
import { dueText } from "./format";

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

  return (
    <div className="strip">
      <span>Thermostats: not connected yet</span>
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

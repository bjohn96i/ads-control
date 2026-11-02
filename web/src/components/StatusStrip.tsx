import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getJson, type MaintenanceTask } from "../api/client";
import { dueText } from "./format";

export function StatusStrip() {
  const { data } = useQuery({
    queryKey: ["maintenance-next"],
    queryFn: () => getJson<MaintenanceTask | null>("/api/maintenance/next"),
    refetchInterval: 60_000,
  });

  return (
    <div className="strip">
      <span>Thermostats: not connected yet</span>
      <Link to="/maintenance">
        {data
          ? `${data.name}: ${dueText(data.next_due, data.overdue)}`
          : "Maintenance: nothing scheduled"}
      </Link>
      <span>Last bill: not connected yet</span>
    </div>
  );
}

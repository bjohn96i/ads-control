import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { getJson, type Live, type MaintenanceTask } from "../api/client";
import { dueText, formatWatts } from "./format";
import { PinGate } from "./PinGate";
import { blocked, type ThermostatState, ThermostatControls } from "./ThermostatControls";

function statusText(t: ThermostatState): string {
  if (t.stale) return "no recent reading";
  if (t.hvac_status === "HEATING") return "heating";
  if (t.hvac_status === "COOLING") return "cooling";
  return "idle";
}

/** Not a link: it holds the real controls, behind one PIN form for both thermostats. Its arrow opens Climate. */
export function AcCard() {
  const [error, setError] = useState<string | null>(null);
  const auth = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => getJson<{ pin_set: boolean; unlocked: boolean }>("/api/auth/status"),
  });
  const unlocked = auth.data?.unlocked ?? false;
  const { data } = useQuery({
    queryKey: ["climate-summary"],
    queryFn: () => getJson<{ thermostats: ThermostatState[] }>("/api/climate/summary"),
    refetchInterval: 60_000,
  });
  return (
    <section className="card">
      <div className="eyebrow">
        <span>A/C</span>
        <Link className="go" to="/climate" aria-label="Open Climate">
          →
        </Link>
      </div>
      {data && data.thermostats.length === 0 ? <p className="sub">No thermostats paired</p> : null}
      {data?.thermostats.map((t) => (
        <div key={t.id} className="therm">
          <div>
            <div className="name">
              {t.name} · {statusText(t)}
            </div>
            <div className="t">
              <span>{t.ambient_f === null ? "—" : `${Math.round(t.ambient_f)}°`}</span>
              {t.setpoint_f !== null ? <em>→ {Math.round(t.setpoint_f)}°</em> : null}
            </div>
          </div>
          {unlocked ? (
            <ThermostatControls t={t} onError={setError} gated={false} />
          ) : blocked(t) ? (
            <p className="sub">{blocked(t)}</p>
          ) : null}
        </div>
      ))}
      {auth.data && !unlocked && data?.thermostats.some((t) => !t.stale && !blocked(t)) ? (
        <PinGate>{null}</PinGate>
      ) : null}
      {error ? (
        <p className="warn" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

export function MaintenanceCard() {
  const { data } = useQuery({
    queryKey: ["maintenance"],
    queryFn: () => getJson<{ tasks: MaintenanceTask[] }>("/api/maintenance"),
    refetchInterval: 60_000,
  });
  // The API already sorts by when each is due.
  const next = (data?.tasks ?? []).filter((t) => t.next_due !== null).slice(0, 3);
  return (
    <Link className="card" to="/maintenance">
      <div className="eyebrow">
        <span>Maintenance</span>
        <span className="go">→</span>
      </div>
      {data && next.length === 0 ? <p className="sub">Nothing scheduled</p> : null}
      {next.map((t) => (
        <div key={t.id} className="row">
          <span>{t.name}</span>
          <span className={t.overdue ? "d warn" : "d"}>{dueText(t.next_due, t.overdue)}</span>
        </div>
      ))}
    </Link>
  );
}

function monthOf(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", { month: "long" });
}

export function BillCard() {
  const { data, isSuccess } = useQuery({
    queryKey: ["bill-latest"],
    queryFn: () => getJson<{ actual_charge: number; period_end: string } | null>("/api/bills/latest"),
    refetchInterval: 3_600_000,
  });
  const [dollars, cents] = data ? data.actual_charge.toFixed(2).split(".") : [];
  return (
    <Link className="card" to="/bills">
      <div className="eyebrow">
        <span>Last bill</span>
        <span className="go">→</span>
      </div>
      {data ? (
        <>
          <div className="big">
            ${dollars}
            <small>.{cents}</small>
          </div>
          <p className="sub">{monthOf(data.period_end)} · actual charge</p>
        </>
      ) : isSuccess ? (
        <p className="sub">No bills yet</p>
      ) : null}
    </Link>
  );
}

function sparkPoints(line: Live["recent_w"]): string {
  if (line.length === 0) return "";
  const values = line.map((p) => p.watts);
  const low = Math.min(...values);
  const span = Math.max(...values) - low || 1;
  const step = line.length > 1 ? 240 / (line.length - 1) : 0;
  return line.map((p, i) => `${(i * step).toFixed(1)},${(40 - ((p.watts - low) / span) * 36).toFixed(1)}`).join(" ");
}

export function PowerCard({ live }: { live: Live }) {
  return (
    <Link className="card" to="/energy">
      <div className="eyebrow">
        <span>Power now</span>
        <span className="go">→</span>
      </div>
      <div className="big">{formatWatts(live.whole_house_w)}</div>
      {live.stale ? <p className="warn">No live reading from the monitor</p> : null}
      <svg className="spark" viewBox="0 0 240 44" preserveAspectRatio="none" aria-hidden="true">
        <polyline fill="none" stroke="var(--amber)" strokeWidth="1.5" points={sparkPoints(live.recent_w)} />
      </svg>
      <div className="row">
        <span className="d">Today {Math.round(live.today_kwh)} kWh</span>
        <span className="d">≈ ${live.today_cost.toFixed(2)}</span>
      </div>
    </Link>
  );
}

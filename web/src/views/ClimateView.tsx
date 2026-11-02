import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError, getJson, send } from "../api/client";
import { PinGate } from "../components/PinGate";

type Point = {
  time: string;
  ambient_f: number | null;
  setpoint_f: number | null;
  running: boolean | null;
  ac_watts: number | null;
  outdoor_f: number | null;
};
type Estimate = { kwh_per_degree_day: number; dollars_per_f_degree_month: number; days: number; full_season: boolean };
type ThermostatView = {
  id: number;
  name: string;
  zone_name: string | null;
  stale: boolean;
  ambient_f: number | null;
  humidity: number | null;
  setpoint_f: number | null;
  heat_f: number | null;
  cool_f: number | null;
  mode: string | null;
  hvac_status: string | null;
  eco: boolean;
  online: boolean;
  timeline: Point[];
  on_peak_flag: boolean;
  estimate: Estimate | null;
};

const RANGES = [
  { value: "1d", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];
const degrees = (f: number) => `${Math.round(f)}°`;

function statusText(t: ThermostatView): string {
  if (t.hvac_status === "HEATING") return "Heating now";
  if (t.hvac_status === "COOLING") return "Cooling now";
  return "Idle";
}

function blocked(t: ThermostatView): string | null {
  if (t.stale) return null;
  if (!t.online) return "This thermostat is offline.";
  if (t.eco) return "This thermostat is in Eco mode. Turn Eco off in the Google Home app to change it here.";
  if (t.mode === "OFF") return "This thermostat is off.";
  return null;
}

function Controls({ t, onError }: { t: ThermostatView; onError: (text: string | null) => void }) {
  const client = useQueryClient();
  const range = t.mode === "HEATCOOL";
  const [target, setTarget] = useState<"heat" | "cool">("heat");
  const current = range ? (target === "heat" ? t.heat_f : t.cool_f) : t.setpoint_f;
  const [choice, setChoice] = useState<number | null>(null);
  const shown = choice ?? (current === null ? null : Math.round(current));
  if (shown === null) return null;

  const save = async () => {
    try {
      await send("POST", `/api/climate/${t.id}/setpoint`, {
        temp_f: shown,
        ...(range ? { target } : {}),
      });
      onError(null);
      setChoice(null);
      client.invalidateQueries({ queryKey: ["climate"] });
    } catch (failure) {
      onError(
        failure instanceof ApiError && failure.status === 401
          ? "Not changed. Enter the PIN again."
          : "Not changed. Check the thermostat's state and try again.",
      );
    }
  };

  return (
    <div className="task-actions">
      {range ? (
        <>
          <button type="button" aria-pressed={target === "heat"} onClick={() => { setTarget("heat"); setChoice(null); }}>
            Heat
          </button>
          <button type="button" aria-pressed={target === "cool"} onClick={() => { setTarget("cool"); setChoice(null); }}>
            Cool
          </button>
        </>
      ) : null}
      <button type="button" aria-label="Cooler" disabled={shown <= 50} onClick={() => setChoice(shown - 1)}>
        −
      </button>
      <button type="button" aria-label="Warmer" disabled={shown >= 90} onClick={() => setChoice(shown + 1)}>
        +
      </button>
      {choice !== null && choice !== Math.round(current ?? choice) ? (
        <button type="button" onClick={save}>
          Set to {shown}°
        </button>
      ) : null}
    </div>
  );
}

function Chart({ points }: { points: Point[] }) {
  return (
    <div className="chart" data-testid="climate-chart">
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={points}>
          <CartesianGrid stroke="#354331" vertical={false} />
          <XAxis
            dataKey="time"
            tick={{ fill: "#9fac93", fontSize: 10 }}
            tickFormatter={(value: string) =>
              new Date(value).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric" })
            }
            minTickGap={50}
          />
          <YAxis yAxisId="temp" tick={{ fill: "#9fac93", fontSize: 10 }} width={36} unit="°" domain={["auto", "auto"]} />
          <YAxis yAxisId="watts" orientation="right" tick={{ fill: "#9fac93", fontSize: 10 }} width={46} unit=" W" />
          <Tooltip
            contentStyle={{ background: "#192119", border: "1px solid #354331" }}
            labelFormatter={(value) => new Date(String(value)).toLocaleString("en-US")}
          />
          <Bar yAxisId="watts" dataKey="ac_watts" name="A/C circuit" fill="#d7997155" isAnimationActive={false} />
          <Line yAxisId="temp" dataKey="ambient_f" name="Inside" stroke="#e5e8d9" dot={false} connectNulls={false} isAnimationActive={false} />
          <Line yAxisId="temp" dataKey="setpoint_f" name="Set to" stroke="#d3b877" strokeDasharray="4 3" dot={false} connectNulls={false} isAnimationActive={false} />
          <Line yAxisId="temp" dataKey="outdoor_f" name="Outside" stroke="#8aaeb0" dot={false} connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function ThermostatCard({ t, onError }: { t: ThermostatView; onError: (text: string | null) => void }) {
  const reason = blocked(t);
  return (
    <article className="panel task">
      <h2>{t.name}</h2>
      {t.stale ? (
        <p className="warn">No recent reading from this thermostat</p>
      ) : (
        <>
          <div className="big">{t.ambient_f === null ? "—" : degrees(t.ambient_f)}</div>
          <p className="sub">
            {t.setpoint_f !== null ? `Set to ${degrees(t.setpoint_f)}` : null}
            {t.mode === "HEATCOOL" && t.heat_f !== null && t.cool_f !== null
              ? `Keeps between ${degrees(t.heat_f)} and ${degrees(t.cool_f)}`
              : null}
            {" · "}
            {statusText(t)}
            {t.humidity !== null ? ` · ${Math.round(t.humidity)}% humidity` : ""}
          </p>
        </>
      )}
      {t.on_peak_flag ? (
        <p className="warn">The A/C is running hard during on-peak hours, your most expensive power.</p>
      ) : null}
      {reason ? <p className="sub">{reason}</p> : null}
      {!t.stale && !reason ? (
        <PinGate>
          <Controls t={t} onError={onError} />
        </PinGate>
      ) : null}
      <Chart points={t.timeline} />
      {t.estimate ? (
        <p className="sub">
          One degree cooler costs about ${t.estimate.dollars_per_f_degree_month.toFixed(2)} a month
          (estimate from {t.estimate.days} days).
          {t.estimate.full_season ? "" : " It needs a full season before it means much."}
        </p>
      ) : (
        <p className="sub">The cost of a degree needs about 3 weeks of cooling data.</p>
      )}
    </article>
  );
}

export function ClimateView() {
  const [params, setParams] = useSearchParams();
  const range = params.get("range") ?? "1d";
  const [error, setError] = useState<string | null>(null);
  const { data, isError } = useQuery({
    queryKey: ["climate", range],
    queryFn: () => getJson<{ thermostats: ThermostatView[] }>(`/api/climate?range=${range}`),
    refetchInterval: 60_000,
  });

  return (
    <main className="home">
      <header>
        <div className="eyebrow">HOUSE / CLIMATE</div>
        <h1>Temperature and what it costs</h1>
        <p className="sub">
          <Link to="/">Back to the house</Link>
        </p>
      </header>
      <div className="task-actions range">
        {RANGES.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={range === option.value}
            onClick={() => setParams({ range: option.value })}
          >
            {option.label}
          </button>
        ))}
      </div>
      <p className="sub">A change here lasts like one made on the thermostat. The Nest schedule isn't changed.</p>
      <p className="sub">Gas heat isn't measured here, so winter shows only what runs on electricity.</p>
      {error ? (
        <p className="warn" role="alert">
          {error}
        </p>
      ) : null}
      {isError ? (
        <p className="warn" role="alert">
          Can't reach the house server
        </p>
      ) : null}
      <div className="tasks climate">
        {data?.thermostats.map((t) => (
          <ThermostatCard key={t.id} t={t} onError={setError} />
        ))}
      </div>
    </main>
  );
}

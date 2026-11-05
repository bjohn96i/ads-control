import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
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
import { FeedStopped, type Stopped } from "../components/FeedStopped";
import { getJson } from "../api/client";
import { ThermostatControls } from "../components/ThermostatControls";

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

function Chart({ points }: { points: Point[] }) {
  return (
    <div className="chart" data-testid="climate-chart">
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={points}>
          <CartesianGrid stroke="#233026" vertical={false} />
          <XAxis
            dataKey="time"
            tick={{ fill: "#8f988f", fontSize: 10 }}
            tickFormatter={(value: string) =>
              new Date(value).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric" })
            }
            minTickGap={50}
          />
          <YAxis yAxisId="temp" tick={{ fill: "#8f988f", fontSize: 10 }} width={36} unit="°" domain={["auto", "auto"]} />
          <YAxis yAxisId="watts" orientation="right" tick={{ fill: "#8f988f", fontSize: 10 }} width={46} unit=" W" />
          <Tooltip
            contentStyle={{ background: "#121a14", border: "1px solid #233026" }}
            labelFormatter={(value) => new Date(String(value)).toLocaleString("en-US")}
          />
          <Bar yAxisId="watts" dataKey="ac_watts" name="A/C circuit" fill="#f2b45a33" isAnimationActive={false} />
          <Line yAxisId="temp" dataKey="ambient_f" name="Inside" stroke="#ece6da" dot={false} connectNulls={false} isAnimationActive={false} />
          <Line yAxisId="temp" dataKey="setpoint_f" name="Set to" stroke="#f2b45a" strokeDasharray="4 3" dot={false} connectNulls={false} isAnimationActive={false} />
          <Line yAxisId="temp" dataKey="outdoor_f" name="Outside" stroke="#8f988f" dot={false} connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function ThermostatCard({ t, onError }: { t: ThermostatView; onError: (text: string | null) => void }) {
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
      <ThermostatControls t={t} onError={onError} />
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
    queryFn: () => getJson<{ thermostats: ThermostatView[]; feed_stopped: Stopped }>(`/api/climate?range=${range}`),
    refetchInterval: 60_000,
  });

  return (
    <main className="page">
      <header className="top">
        <h1>Climate</h1>
        <div className="seg">
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
      </header>
      <p className="sub">A change here lasts like one made on the thermostat. The Nest schedule isn't changed.</p>
      <p className="sub">Gas heat isn't measured here, so winter shows only what runs on electricity.</p>
      <FeedStopped stopped={data?.feed_stopped} text="Not hearing from the thermostats" />
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

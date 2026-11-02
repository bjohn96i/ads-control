import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getJson } from "../api/client";
import { formatWatts } from "../components/format";

type EnergyLine = { kwh: number; est_cost: number; share: number; coverage: number };
type Ranking = {
  zones: (EnergyLine & { id: number; name: string })[];
  charger_estimate: EnergyLine;
  unmetered: EnergyLine;
  whole_house: EnergyLine;
};
type ZoneFlag = { kind: string; opened_at: string; summary: string };
type ZoneDetail = {
  id: number;
  name: string;
  series: { time: string; watts: number | null }[];
  overnight_min_w: number | null;
  flags: ZoneFlag[];
};

const RANGES = [
  { value: "bill", label: "This bill" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];
const COVERAGE_WARN = 0.9;

const kwh = (value: number) => `${Math.round(value)} kWh`;
const dollars = (value: number) => `$${value.toFixed(2)}`;

function Row({ name, line, onOpen }: { name: string; line: EnergyLine; onOpen?: () => void }) {
  return (
    <tr>
      <td>
        {onOpen ? (
          <button type="button" className="link" onClick={onOpen}>
            {name}
          </button>
        ) : (
          name
        )}
      </td>
      <td>{kwh(line.kwh)}</td>
      <td>{dollars(line.est_cost)}</td>
      <td>
        <span className="share" aria-hidden="true">
          <i style={{ width: `${Math.min(100, line.share * 100)}%` }} />
        </span>
        {Math.round(line.share * 100)}%
      </td>
    </tr>
  );
}

function ZonePanel({ zoneId, range }: { zoneId: string; range: string }) {
  const { data } = useQuery({
    queryKey: ["energy-zone", zoneId, range],
    queryFn: () => getJson<ZoneDetail>(`/api/energy/zones/${zoneId}?range=${range}`),
  });
  if (!data) return null;
  return (
    <section className="panel task zone-panel">
      <h2>{data.name}</h2>
      <p className="sub">
        {data.overnight_min_w === null
          ? "Not enough overnight data yet"
          : `Always-on load: ${formatWatts(data.overnight_min_w)} overnight`}
      </p>
      {data.flags.map((flag) => (
        <p key={flag.kind} className="warn">
          {flag.summary}
        </p>
      ))}
      <div className="chart">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data.series}>
            <CartesianGrid stroke="#354331" vertical={false} />
            <XAxis
              dataKey="time"
              tick={{ fill: "#9fac93", fontSize: 10 }}
              tickFormatter={(t: string) =>
                new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" })
              }
              minTickGap={40}
            />
            <YAxis tick={{ fill: "#9fac93", fontSize: 10 }} width={44} unit=" W" />
            <Tooltip
              contentStyle={{ background: "#192119", border: "1px solid #354331" }}
              labelFormatter={(t) => new Date(String(t)).toLocaleString("en-US")}
            />
            {/* Gaps stay gaps: a line across missing readings would invent data. */}
            <Line dataKey="watts" stroke="#d79971" dot={false} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

export function EnergyView() {
  const [params, setParams] = useSearchParams();
  const range = params.get("range") ?? "bill";
  const zone = params.get("zone");

  const change = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };

  const { data, isError } = useQuery({
    queryKey: ["energy-ranking", range],
    queryFn: () => getJson<Ranking>(`/api/energy/ranking?range=${range}`),
  });

  return (
    <main className="home">
      <header>
        <div className="eyebrow">HOUSE / ENERGY</div>
        <h1>Where the power goes</h1>
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
            onClick={() => change("range", option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {isError ? (
        <p className="warn" role="alert">
          Can't reach the house server
        </p>
      ) : null}
      {data ? (
        <>
          <p className="big">{kwh(data.whole_house.kwh)}</p>
          <p className="sub">{dollars(data.whole_house.est_cost)} estimated, before fixed monthly charges</p>
          {data.whole_house.coverage < COVERAGE_WARN ? (
            <p className="warn" role="status">
              Only {Math.round(data.whole_house.coverage * 100)}% of this period was recorded, so real
              usage is higher than this.
            </p>
          ) : null}
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Zone</th>
                  <th>Energy</th>
                  <th>Estimated cost</th>
                  <th>Share</th>
                </tr>
              </thead>
              <tbody>
                {data.zones.map((row) => (
                  <Row
                    key={row.id}
                    name={row.name}
                    line={row}
                    onOpen={() => change("zone", String(row.id))}
                  />
                ))}
                <Row name="Car charger (estimate)" line={data.charger_estimate} />
                <Row name="Not on any zone" line={data.unmetered} />
              </tbody>
            </table>
          </div>
        </>
      ) : null}
      {zone ? <ZonePanel zoneId={zone} range={range} /> : null}
    </main>
  );
}

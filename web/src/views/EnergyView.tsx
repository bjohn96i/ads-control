import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getJson, type Live, type LiveZone } from "../api/client";
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

const kwh = (value: number) => `${value < 10 ? value.toFixed(1) : Math.round(value)} kWh`;
const dollars = (value: number) => `$${value.toFixed(2)}`;

function Row({
  name,
  line,
  onOpen,
  selected = false,
  flagged = false,
  quiet = false,
}: {
  name: string;
  line: EnergyLine;
  onOpen?: () => void;
  selected?: boolean;
  flagged?: boolean;
  quiet?: boolean;
}) {
  return (
    <tr className={selected ? "sel" : quiet ? "quiet" : undefined}>
      <td>
        {onOpen ? (
          <button type="button" className="link" onClick={onOpen}>
            {name}
          </button>
        ) : (
          name
        )}
        {flagged ? <span className="flagdot" aria-label="Unusual" /> : null}
      </td>
      <td className="n">{kwh(line.kwh)}</td>
      <td className="n">{dollars(line.est_cost)}</td>
      <td>
        <span className="share" aria-hidden="true">
          <i style={{ width: `${Math.min(100, line.share * 100)}%` }} />
        </span>
        {Math.round(line.share * 100)}%
      </td>
    </tr>
  );
}

function where(zone: LiveZone | undefined): string {
  if (!zone?.floor) return "";
  return zone.room && zone.room !== zone.name ? `${zone.floor} · ${zone.room}` : zone.floor;
}

function ZonePanel({ zoneId, range, place }: { zoneId: string; range: string; place: LiveZone | undefined }) {
  const { data } = useQuery({
    queryKey: ["energy-zone", zoneId, range],
    queryFn: () => getJson<ZoneDetail>(`/api/energy/zones/${zoneId}?range=${range}`),
  });
  if (!data) return null;
  return (
    <section className="card zone-panel">
      <div
        className="photo"
        data-testid="zone-photo"
        style={place ? { backgroundPosition: `${place.pin_x}% ${place.pin_y}%` } : undefined}
      />
      <div className="body">
        <div className="eyebrow" data-testid="zone-where">
          {where(place)}
        </div>
        <h2>{data.name}</h2>
        <p className="sub">
          {data.overnight_min_w === null
            ? "Not enough overnight data yet"
            : `Always-on load: ${formatWatts(data.overnight_min_w)} overnight`}
        </p>
        {data.flags.map((flag) => (
          <p key={flag.kind} className="warn box">
            {flag.summary}
          </p>
        ))}
        <div className="chart">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data.series}>
              <CartesianGrid stroke="#233026" vertical={false} />
              <XAxis
                dataKey="time"
                tick={{ fill: "#8f988f", fontSize: 10, fontFamily: "JetBrains Mono, monospace" }}
                tickFormatter={(t: string) =>
                  new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                }
                minTickGap={40}
              />
              <YAxis tick={{ fill: "#8f988f", fontSize: 10, fontFamily: "JetBrains Mono, monospace" }} width={52} unit=" W" />
              <Tooltip
                contentStyle={{ background: "#121a14", border: "1px solid #233026" }}
                labelFormatter={(t) => new Date(String(t)).toLocaleString("en-US")}
              />
              {/* Gaps stay gaps: a line across missing readings would invent data. */}
              <Line dataKey="watts" stroke="#f2b45a" dot={false} connectNulls={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
}

export function EnergyView() {
  const [params, setParams] = useSearchParams();
  const range = params.get("range") ?? "bill";

  const change = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };

  const { data, isError } = useQuery({
    queryKey: ["energy-ranking", range],
    queryFn: () => getJson<Ranking>(`/api/energy/ranking?range=${range}`),
  });
  const live = useQuery({
    queryKey: ["live"],
    queryFn: () => getJson<Live>("/api/live"),
    refetchInterval: 5000,
  });
  // No zone picked: show the biggest one (the ranking comes biggest first), without touching the URL.
  const zone = params.get("zone") ?? (data?.zones[0] ? String(data.zones[0].id) : null);
  const placeOf = (id: number) => live.data?.zones.find((z) => z.id === id);
  const [costWhole, costCents] = (data?.whole_house.est_cost ?? 0).toFixed(2).split(".");
  const label = RANGES.find((r) => r.value === range)?.label ?? "";

  return (
    <main className="page">
      <header className="top">
        <h1>Energy</h1>
        <div className="seg">
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
      </header>
      {isError ? (
        <p className="warn" role="alert">
          Can't reach the house server
        </p>
      ) : null}
      {data ? (
        <>
          <div className="stats">
            <div className="card">
              <div className="eyebrow">Used · {label}</div>
              <div className="big">{kwh(data.whole_house.kwh)}</div>
            </div>
            <div className="card">
              <div className="eyebrow">Estimated cost</div>
              <div className="big">
                ${costWhole}
                <small>.{costCents}</small>
              </div>
              <p className="sub">before fixed monthly charges</p>
            </div>
            <div className="card">
              <div className="eyebrow">Recorded</div>
              <div className="big">
                {Math.round(data.whole_house.coverage * 100)}
                <small>%</small>
              </div>
              <p className="sub">of this period has readings</p>
            </div>
          </div>
          {data.whole_house.coverage < COVERAGE_WARN ? (
            <p className="warn box" role="status">
              Only {Math.round(data.whole_house.coverage * 100)}% of this period was recorded, so real
              usage is higher than this.
            </p>
          ) : null}
          <div className="split">
            <div className="card">
              <div className="eyebrow">Where the power goes</div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Zone</th>
                      <th className="n">Energy</th>
                      <th className="n">Estimated cost</th>
                      <th>Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.zones.map((row) => (
                      <Row
                        key={row.id}
                        name={row.name}
                        line={row}
                        selected={String(row.id) === zone}
                        flagged={placeOf(row.id)?.flagged ?? false}
                        onOpen={() => change("zone", String(row.id))}
                      />
                    ))}
                    <Row name="Car charger (estimate)" line={data.charger_estimate} quiet />
                    <Row name="Not on any zone" line={data.unmetered} quiet />
                  </tbody>
                </table>
              </div>
            </div>
            {zone ? <ZonePanel zoneId={zone} range={range} place={placeOf(Number(zone))} /> : null}
          </div>
        </>
      ) : null}
    </main>
  );
}

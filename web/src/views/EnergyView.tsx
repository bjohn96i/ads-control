import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getJson, type Live, type LiveZone } from "../api/client";
import { formatKwh, formatWatts } from "../components/format";

type EnergyLine = { kwh: number; est_cost: number; share: number; coverage: number };
type RankedZone = EnergyLine & { id: number; name: string; room: string | null };
type Ranking = {
  start: string;
  end: string;
  since_bill: boolean;
  manual_kwh?: number;
  manual_days?: number;
  zones: RankedZone[];
  charger_estimate: EnergyLine;
  unmetered: EnergyLine;
  whole_house: EnergyLine & { id: number };
};
type ZoneFlag = { kind: string; opened_at: string; summary: string };
type ZoneDetail = {
  id: number | null;
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

const kwh = formatKwh;
const dollars = (value: number) => `$${value.toFixed(2)}`;

function Row({
  name,
  line,
  onOpen,
  selected = false,
  flagged = false,
  quiet = false,
  sub = false,
}: {
  name: string;
  line: EnergyLine;
  onOpen?: () => void;
  selected?: boolean;
  flagged?: boolean;
  quiet?: boolean;
  sub?: boolean;
}) {
  const classes = [selected ? "sel" : quiet ? "quiet" : "", sub ? "sub" : ""].join(" ").trim();
  return (
    <tr className={classes || undefined}>
      <td>
        {onOpen ? (
          <button type="button" className="link" onClick={onOpen}>
            {name}
          </button>
        ) : (
          name
        )}
        {flagged ? <span className="flagdot" role="img" aria-label="Unusual" /> : null}
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

/** Circuits in the same room, biggest room first; a room's numbers are its circuits added up. */
function byRoom(zones: RankedZone[]) {
  const rooms = new Map<string, RankedZone[]>();
  for (const zone of zones) {
    const key = zone.room ?? zone.name;
    rooms.set(key, [...(rooms.get(key) ?? []), zone]);
  }
  const total = (members: RankedZone[], key: "kwh" | "est_cost" | "share") => members.reduce((sum, z) => sum + z[key], 0);
  return [...rooms]
    .map(([name, members]) => ({
      name,
      members,
      line: {
        kwh: total(members, "kwh"),
        est_cost: total(members, "est_cost"),
        share: total(members, "share"),
        coverage: Math.min(...members.map((z) => z.coverage)),
      },
    }))
    .sort((a, b) => b.line.kwh - a.line.kwh);
}

/** The picture is cropped to the place's label, or shown whole for the whole house. */
function ZonePanel({ path, range, place, eyebrow }: { path: string; range: string; place: LiveZone | "whole" | undefined; eyebrow: string }) {
  const { data, isError } = useQuery({
    queryKey: ["energy-detail", path, range],
    queryFn: () => getJson<ZoneDetail>(`${path}?range=${range}`),
  });
  if (isError) {
    return (
      <section className="card zone-panel">
        <p className="warn">Can't load this detail right now. Reload to try again.</p>
      </section>
    );
  }
  if (!data) return null;
  return (
    <section className="card zone-panel">
      <div className={place === "whole" ? "photo whole" : "photo"} data-testid="zone-photo">
        {place === "whole" ? (
          <img src="/house.jpg" alt="" />
        ) : place ? (
          <img src="/house.jpg" alt="" style={{ transform: `translate(-${place.pin_x}%, -${place.pin_y}%)` }} />
        ) : null}
      </div>
      <div className="body">
        <div className="eyebrow" data-testid="zone-where">
          {eyebrow}
        </div>
        <h2>{data.name}</h2>
        <p className="sub">
          {data.overnight_min_w === null
            ? "Not enough overnight data yet"
            : `Always-on load: ${formatWatts(data.overnight_min_w)} overnight`}
        </p>
        {data.flags.map((flag, i) => (
          <p key={i} className="warn box">
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
    // A room and a zone are two ways to pick what the panel shows; only one stands.
    if (key === "zone" || key === "room") ["zone", "room"].forEach((k) => next.delete(k));
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
  const room = params.get("room");
  // Nothing picked: show the whole house, without touching the URL.
  const zone = room ? null : (params.get("zone") ?? (data ? String(data.whole_house.id) : null));
  const whole = data !== undefined && zone === String(data.whole_house.id);
  const placeOf = (id: number) => live.data?.zones.find((z) => z.id === id);
  const roomPlace = live.data?.zones.find((z) => z.room === room);
  const [costWhole, costCents] = (data?.whole_house.est_cost ?? 0).toFixed(2).split(".");
  // With no bill saved, "This bill" falls back to the last 30 days; say so rather than mislabel it.
  const label =
    range === "bill"
      ? data?.since_bill
        ? "Since the last bill"
        : "Last 30 days, no bill yet"
      : (RANGES.find((r) => r.value === range)?.label ?? "");
  const day = (iso: string) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

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
              <p className="sub">
                {day(data.start)} – {day(data.end)}
              </p>
              {data.manual_days ? (
                <p className="sub">
                  Includes {data.manual_days} days from the Refoss app, not split by circuit
                </p>
              ) : null}
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
                    {byRoom(data.zones).map((group) => {
                      const circuit = (row: RankedZone, sub: boolean) => (
                        <Row
                          key={row.id}
                          name={row.name}
                          line={row}
                          sub={sub}
                          selected={String(row.id) === zone}
                          flagged={placeOf(row.id)?.flagged ?? false}
                          onOpen={() => change("zone", String(row.id))}
                        />
                      );
                      if (group.members.length === 1) return circuit(group.members[0], false);
                      return [
                        <Row
                          key={`room-${group.name}`}
                          name={group.name}
                          line={group.line}
                          selected={group.name === room}
                          flagged={group.members.some((z) => placeOf(z.id)?.flagged)}
                          onOpen={() => change("room", group.name)}
                        />,
                        ...group.members.map((row) => circuit(row, true)),
                      ];
                    })}
                    <Row name="Car charger (estimate)" line={data.charger_estimate} quiet />
                    <Row name="Not on any zone" line={data.unmetered} quiet />
                    <Row
                      name="Whole House"
                      line={data.whole_house}
                      selected={whole}
                      onOpen={() => change("zone", String(data.whole_house.id))}
                    />
                  </tbody>
                </table>
              </div>
            </div>
            {room ? (
              <ZonePanel
                path={`/api/energy/rooms/${encodeURIComponent(room)}`}
                range={range}
                place={roomPlace}
                eyebrow={roomPlace?.floor ?? ""}
              />
            ) : zone ? (
              <ZonePanel
                path={`/api/energy/zones/${zone}`}
                range={range}
                place={whole ? "whole" : placeOf(Number(zone))}
                eyebrow={whole ? "All floors" : where(placeOf(Number(zone)))}
              />
            ) : null}
          </div>
        </>
      ) : null}
    </main>
  );
}

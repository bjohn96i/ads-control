import { Link } from "react-router-dom";
import type { Live, LiveZone } from "../api/client";
import { formatWatts } from "./format";

export type Room = { name: string; watts: number | null; flagged: boolean; pin_x: number; pin_y: number; zoneId: number };

// The charger has no zone of its own, so its place on the render lives here.
const CHARGER_PIN = { x: 82, y: 50 };

/** One label per room: circuits in the same room add up; one stopped circuit makes the room unknown. */
export function groupRooms(zones: LiveZone[]): Room[] {
  const rooms = new Map<string, LiveZone[]>();
  for (const zone of zones) {
    const key = zone.room ?? zone.name;
    rooms.set(key, [...(rooms.get(key) ?? []), zone]);
  }
  return [...rooms].map(([name, members]) => {
    const biggest = members.reduce((a, b) => ((b.watts ?? -1) > (a.watts ?? -1) ? b : a));
    return {
      name,
      watts: members.some((z) => z.watts === null) ? null : members.reduce((sum, z) => sum + z.watts!, 0),
      flagged: members.some((z) => z.flagged),
      pin_x: members[0].pin_x,
      pin_y: members[0].pin_y,
      zoneId: biggest.id,
    };
  });
}

function chargerText(watts: number | null): string {
  if (watts === null) return "—";
  return watts > 0 ? formatWatts(watts) : "Not charging";
}

function Label({ name, value, x, y, to, flagged = false }: { name: string; value: string; x: number; y: number; to: string; flagged?: boolean }) {
  return (
    <Link className={flagged ? "pin flag" : "pin"} style={{ left: `${x}%`, top: `${y}%` }} to={to}>
      <b>{name}</b>
      <span>{value}</span>
      {flagged ? <em>Unusual</em> : null}
    </Link>
  );
}

export function HouseScene({ live }: { live: Live }) {
  return (
    <div className="scene">
      <Link className="picture" to="/energy" aria-label="Open Energy">
        <img src="/house.jpg" alt="Cutaway picture of the house: two floors and a basement" />
      </Link>
      {groupRooms(live.zones).map((room) => (
        <Label
          key={room.name}
          name={room.name}
          value={formatWatts(room.watts)}
          x={room.pin_x}
          y={room.pin_y}
          to={`/energy?zone=${room.zoneId}`}
          flagged={room.flagged}
        />
      ))}
      {live.whole_house_pin ? (
        <Label name="Whole House" value={formatWatts(live.whole_house_w)} x={live.whole_house_pin.x} y={live.whole_house_pin.y} to="/energy" />
      ) : null}
      <Label name="Car charger (estimate)" value={chargerText(live.charger_estimate_w)} x={CHARGER_PIN.x} y={CHARGER_PIN.y} to="/energy" />
    </div>
  );
}

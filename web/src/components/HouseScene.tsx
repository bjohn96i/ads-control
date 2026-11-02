import { Link } from "react-router-dom";
import type { LiveZone } from "../api/client";
import { formatWatts } from "./format";

function chargerText(watts: number | null): string {
  if (watts === null) return "—";
  return watts > 0 ? formatWatts(watts) : "Not charging";
}

export function HouseScene({
  zones,
  chargerWatts,
}: {
  zones: LiveZone[];
  chargerWatts: number | null;
}) {
  return (
    <div className="panel scene">
      <img src="/house.svg" alt="Drawing of the house: two floors and a basement" />
      {zones.map((zone) => (
        <Link
          key={zone.id}
          className={zone.flagged ? "pin flagged" : "pin"}
          style={{ left: `${zone.pin_x}%`, top: `${zone.pin_y}%` }}
          to={`/energy?zone=${zone.id}`}
        >
          <span className="pin-name">{zone.name}</span>
          <b>{formatWatts(zone.watts)}</b>
        </Link>
      ))}
      <Link className="pin" style={{ left: "88%", top: "66%" }} to="/energy">
        <span className="pin-name">Car charger (estimate)</span>
        <b>{chargerText(chargerWatts)}</b>
      </Link>
    </div>
  );
}

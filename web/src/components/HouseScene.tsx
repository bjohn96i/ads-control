import { Link } from "react-router-dom";
import type { LiveZone } from "../api/client";
import { formatWatts } from "./format";

export function HouseScene({ zones }: { zones: LiveZone[] }) {
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
    </div>
  );
}

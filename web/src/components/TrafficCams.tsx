import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { TrafficCamera } from "../api/client";

// 511GA refreshes each picture about once a minute, so asking more often gains nothing.
const REFRESH_MS = 60_000;

function useMinute(): number {
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setTick(Date.now()), REFRESH_MS);
    return () => clearInterval(timer);
  }, []);
  return tick;
}

export function TrafficCams({ cameras, linkTo }: { cameras: TrafficCamera[]; linkTo?: string }) {
  const tick = useMinute();
  return (
    <div className="traffic">
      {cameras.map((camera) => {
        const body = (
          <>
            <img src={`${camera.image_url}?t=${tick}`} alt={`Traffic at ${camera.nickname}`} loading="lazy" />
            <span className="label">{camera.nickname}</span>
            <span className="sub">{camera.name}</span>
          </>
        );
        return linkTo ? (
          <Link key={camera.image_url} className="panel traffic-cam" to={linkTo}>
            {body}
          </Link>
        ) : (
          <figure key={camera.image_url} className="panel traffic-cam">
            {body}
          </figure>
        );
      })}
    </div>
  );
}

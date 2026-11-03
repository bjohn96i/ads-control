import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { type CameraEvent, getJson, type Live } from "../api/client";
import { CameraEventTable } from "../components/CameraEvents";
import { HouseScene } from "../components/HouseScene";
import { NetworkPanel } from "../components/network/NetworkPanel";
import { StatusStrip } from "../components/StatusStrip";
import { UsagePanel } from "../components/UsagePanel";

export function HomeView() {
  const { data, isError } = useQuery({
    queryKey: ["live"],
    queryFn: () => getJson<Live>("/api/live"),
    refetchInterval: 5000,
  });

  const events = useQuery({
    queryKey: ["camera-events", 5],
    queryFn: () => getJson<{ events: CameraEvent[] }>("/api/cameras/events?limit=5"),
    refetchInterval: 30_000,
  });

  return (
    <main className="home">
      <header>
        <div className="eyebrow">HOUSE / LIVE</div>
        <h1>What's happening at home?</h1>
      </header>
      {isError ? <p className="warn" role="alert">Can't reach the house server</p> : null}
      {data ? (
        <div className="overview">
          <HouseScene zones={data.zones} chargerWatts={data.charger_estimate_w} />
          <div className="side">
            <UsagePanel live={data} />
            {events.data ? (
              <Link className="panel camera-events" to="/cameras">
                <div className="eyebrow">RECENT CAMERA EVENTS</div>
                <CameraEventTable events={events.data.events} />
              </Link>
            ) : null}
            <NetworkPanel />
          </div>
        </div>
      ) : null}
      <StatusStrip />
    </main>
  );
}

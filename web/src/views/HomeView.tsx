import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { type CameraEvent, getJson, type Live, type TrafficCamera } from "../api/client";
import { CameraEventTable } from "../components/CameraEvents";
import { HouseScene } from "../components/HouseScene";
import { NetworkPanel } from "../components/network/NetworkPanel";
import { StatusStrip } from "../components/StatusStrip";
import { TrafficCams } from "../components/TrafficCams";
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
  const traffic = useQuery({
    queryKey: ["traffic"],
    queryFn: () => getJson<{ cameras: TrafficCamera[] }>("/api/traffic"),
  });

  return (
    <main className="page">
      <header className="top">
        <h1>Home</h1>
      </header>
      {isError ? <p className="warn" role="alert">Can't reach the house server</p> : null}
      {data ? (
        <div className="overview">
          <div className="main">
            <HouseScene live={data} />
            {traffic.data ? (
              <TrafficCams
                className="traffic-row"
                cameras={traffic.data.cameras.filter((c) => c.home)}
                linkTo="/cameras"
              />
            ) : null}
          </div>
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

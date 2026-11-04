import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { type CameraEvent, getJson, type Live, type TrafficCamera } from "../api/client";
import { CameraEventList } from "../components/CameraEvents";
import { AcCard, BillCard, MaintenanceCard, PowerCard } from "../components/HomeCards";
import { HouseScene } from "../components/HouseScene";
import { NetworkPanel } from "../components/network/NetworkPanel";
import { TrafficCams } from "../components/TrafficCams";

function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

export function HomeView() {
  const now = useNow();
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
        <span className="meta">
          {now.toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
        </span>
      </header>
      {isError ? <p className="warn" role="alert">Can't reach the house server</p> : null}
      {data ? (
        <div className="stage">
          <div className="col">
            <AcCard />
            <MaintenanceCard />
            <BillCard />
          </div>
          <HouseScene live={data} />
          <div className="col">
            <PowerCard live={data} />
            <Link className="card camera-events" to="/cameras">
              <div className="eyebrow">
                <span>Camera events</span>
                <span className="go">→</span>
              </div>
              {events.data ? <CameraEventList events={events.data.events} /> : null}
            </Link>
            <NetworkPanel />
          </div>
        </div>
      ) : null}
      {traffic.data ? (
        <TrafficCams cameras={traffic.data.cameras.filter((c) => c.home)} linkTo="/cameras" />
      ) : null}
    </main>
  );
}

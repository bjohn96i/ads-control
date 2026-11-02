import { useQuery } from "@tanstack/react-query";
import { type CameraInfo, getJson, type Live } from "../api/client";
import { CameraTile } from "../components/CameraTile";
import { HouseScene } from "../components/HouseScene";
import { StatusStrip } from "../components/StatusStrip";
import { UsagePanel } from "../components/UsagePanel";

export function HomeView() {
  const { data, isError } = useQuery({
    queryKey: ["live"],
    queryFn: () => getJson<Live>("/api/live"),
    refetchInterval: 5000,
  });

  const cameras = useQuery({
    queryKey: ["cameras"],
    queryFn: () => getJson<{ cameras: CameraInfo[] }>("/api/cameras"),
    refetchInterval: 30_000,
  });
  const auth = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => getJson<{ unlocked: boolean }>("/api/auth/status"),
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
            <div className="cameras">
              {cameras.data?.cameras.map((camera) => (
                <CameraTile key={camera.id} camera={camera} unlocked={auth.data?.unlocked ?? false} />
              ))}
            </div>
          </div>
        </div>
      ) : null}
      <StatusStrip />
    </main>
  );
}

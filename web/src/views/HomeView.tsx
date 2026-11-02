import { useQuery } from "@tanstack/react-query";
import { getJson, type Live } from "../api/client";
import { CameraTile } from "../components/CameraTile";
import { HouseScene } from "../components/HouseScene";
import { StatusStrip } from "../components/StatusStrip";
import { UsagePanel } from "../components/UsagePanel";

const CAMERAS = ["Nest Cam 1", "Nest Cam 2", "Doorbell", "Hub Max"];

export function HomeView() {
  const { data, isError } = useQuery({
    queryKey: ["live"],
    queryFn: () => getJson<Live>("/api/live"),
    refetchInterval: 5000,
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
          <HouseScene zones={data.zones} />
          <div className="side">
            <UsagePanel live={data} />
            <div className="cameras">
              {CAMERAS.map((name) => (
                <CameraTile key={name} name={name} />
              ))}
            </div>
          </div>
        </div>
      ) : null}
      <StatusStrip />
    </main>
  );
}

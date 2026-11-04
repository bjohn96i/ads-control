import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";

import { getJson, type Network } from "../../api/client";

const Globe = lazy(() => import("./Globe"));

function lanthornLink(base: string, params: Record<string, string> = {}): string {
  return `${base}/?${new URLSearchParams({ ...params, range: "24h" })}`;
}

const open = (href: string) => window.open(href, "_blank", "noopener");

/** Measures the globe's box once it exists, which is only after the data arrives. */
function useWidth() {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!box) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(box);
    return () => observer.disconnect();
  }, [box]);
  return [setBox, width] as const;
}

export function NetworkPanel() {
  const { data, isError } = useQuery({
    queryKey: ["network"],
    queryFn: () => getJson<Network>("/api/network"),
    refetchInterval: 60_000,
  });
  const [box, width] = useWidth();
  const lanthorn = (params?: Record<string, string>) => lanthornLink(data?.lanthorn_url ?? "", params);

  return (
    <section className="panel network">
      {data ? (
        <a className="eyebrow" href={lanthorn()} target="_blank" rel="noopener">
          NETWORK / LAST 24 HOURS
        </a>
      ) : (
        <span className="eyebrow">NETWORK / LAST 24 HOURS</span>
      )}
      {isError ? (
        <p className="warn" role="alert">
          Lanthorn isn't reachable
        </p>
      ) : null}
      {data ? (
        <div className="network-body">
          <div ref={box} className="network-globe">
            {data.home && width > 0 ? (
              <Suspense fallback={<p className="sub">Loading the globe…</p>}>
                <Globe
                  arcs={data.arcs}
                  home={data.home}
                  width={width}
                  height={200}
                  onCountryClick={(code) => open(lanthorn({ panel: `country:${code}` }))}
                  onGlobeClick={() => open(lanthorn())}
                />
              </Suspense>
            ) : null}
          </div>
          <ol className="noisiest">
            {data.top_devices.map((device) => (
              <li key={device.id}>
                <a
                  href={lanthorn({ panel: `device:${encodeURIComponent(device.id)}` })}
                  target="_blank"
                  rel="noopener"
                >
                  {device.name}
                </a>
                <span>{device.queries.toLocaleString("en-US")}</span>
                <span className="sub">
                  {device.queries ? Math.round((100 * device.blocked) / device.queries) : 0}% blocked
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}

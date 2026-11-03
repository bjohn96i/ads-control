import type { Feature } from "geojson";
import { useEffect, useMemo, useRef } from "react";
import ReactGlobe, { type GlobeMethods } from "react-globe.gl";

import type { NetworkArc } from "../../api/client";
import { alpha2For, COLORS, trafficColor, trafficFromArcs } from "./countryTraffic";
import { countryFeatures } from "./landmass";

/** Lanthorn's globe, reduced to its 24-hour picture: no live arcs. Checked by eye. */
const LAND = countryFeatures();

export default function Globe({
  arcs,
  home,
  width,
  height,
  onCountryClick,
  onGlobeClick,
}: {
  arcs: NetworkArc[];
  home: { lat: number; lon: number };
  width: number;
  height: number;
  onCountryClick: (code: string) => void;
  onGlobeClick: () => void;
}) {
  const globe = useRef<GlobeMethods | undefined>(undefined);
  const traffic = useMemo(() => trafficFromArcs(arcs), [arcs]);
  const busiest = useMemo(() => Math.max(0, ...Object.values(traffic)), [traffic]);
  const lines = useMemo(
    () =>
      arcs.map((arc) => ({
        startLat: home.lat,
        startLng: home.lon,
        endLat: arc.lat,
        endLng: arc.lon,
        color: `${arc.state === "blocked" ? COLORS.blocked : COLORS.allowed}8c`,
        stroke: 0.25 + Math.min(1, Math.log10(Math.max(1, arc.queries)) / 6) * 1.25,
        code: arc.country_code,
      })),
    [arcs, home],
  );

  useEffect(() => {
    const controls = globe.current?.controls();
    if (!controls) return;
    controls.autoRotate = !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    controls.autoRotateSpeed = 0.25;
    controls.enableZoom = false; // a scroll over the home page should scroll the page
    globe.current?.pointOfView({ lat: home.lat, lng: home.lon, altitude: 2.2 }, 0);
  }, [home]);

  return (
    <ReactGlobe
      ref={globe}
      width={width}
      height={height}
      backgroundColor="rgba(0,0,0,0)"
      globeImageUrl={null}
      showGlobe
      showGraticules
      polygonsData={LAND}
      polygonCapColor={() => COLORS.landFill}
      polygonSideColor={() => "rgba(0,0,0,0)"}
      polygonStrokeColor={() => COLORS.land}
      polygonAltitude={0.004}
      hexPolygonsData={LAND}
      hexPolygonResolution={3}
      hexPolygonUseDots
      hexPolygonMargin={0.1}
      hexPolygonAltitude={0.006}
      hexPolygonColor={(d) => {
        const code = alpha2For(d as Feature);
        return trafficColor(code ? (traffic[code] ?? 0) : 0, busiest);
      }}
      showAtmosphere
      atmosphereColor={COLORS.allowed}
      atmosphereAltitude={0.12}
      arcsData={lines}
      arcColor={(a: object) => (a as (typeof lines)[number]).color}
      arcStroke={(a) => (a as (typeof lines)[number]).stroke}
      arcsTransitionDuration={0}
      onArcClick={(a) => onCountryClick((a as (typeof lines)[number]).code)}
      onGlobeClick={onGlobeClick}
    />
  );
}

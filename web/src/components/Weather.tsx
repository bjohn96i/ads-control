import type { Live } from "../api/client";
import { PERIOD_LABEL } from "./format";

type Icon = "sun" | "moon" | "partly-day" | "partly-night" | "cloud" | "fog" | "rain" | "snow" | "thunder";

/** Open-Meteo's WMO weather codes, grouped the way a person would say them. */
export function weatherOf(code: number, isDay: boolean): { label: string; icon: Icon } | null {
  if (code === 0) return { label: "Clear", icon: isDay ? "sun" : "moon" };
  if (code === 1 || code === 2)
    return { label: code === 1 ? "Mostly clear" : "Partly cloudy", icon: isDay ? "partly-day" : "partly-night" };
  if (code === 3) return { label: "Cloudy", icon: "cloud" };
  if (code === 45 || code === 48) return { label: "Fog", icon: "fog" };
  if (code >= 51 && code <= 57) return { label: "Drizzle", icon: "rain" };
  if (code === 66 || code === 67) return { label: "Freezing rain", icon: "rain" };
  if (code >= 61 && code <= 65) return { label: "Rain", icon: "rain" };
  if (code >= 80 && code <= 82) return { label: "Showers", icon: "rain" };
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return { label: "Snow", icon: "snow" };
  if (code >= 95 && code <= 99) return { label: "Thunderstorms", icon: "thunder" };
  return null;
}

const CLOUD = "M7 17h10a4 4 0 0 0 .4-7.98A6 6 0 0 0 5.9 10.2 3.5 3.5 0 0 0 7 17z";
const RAYS = "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4";
const MOON = "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z";

function Glyph({ icon }: { icon: Icon }) {
  const high = <path d={CLOUD} transform="translate(0 -3)" />;
  const shapes = {
    sun: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d={RAYS} />
      </>
    ),
    moon: <path d={MOON} />,
    "partly-day": (
      <>
        <circle cx="8" cy="8" r="3" />
        <path d="M8 2.5v1.2M2.5 8h1.2M4.1 4.1l.9.9M11.9 4.1l-.9.9" />
        <path d={CLOUD} transform="translate(2 3)" className="solid" />
      </>
    ),
    "partly-night": (
      <>
        <path d={MOON} transform="translate(1 1) scale(.6)" />
        <path d={CLOUD} transform="translate(2 3)" className="solid" />
      </>
    ),
    cloud: <path d={CLOUD} />,
    fog: <path d="M4 9h16M4 13h16M6 17h12" />,
    rain: (
      <>
        {high}
        <path d="M9 18l-1 3M13 18l-1 3M17 18l-1 3" />
      </>
    ),
    snow: (
      <>
        {high}
        <path d="M8 19.5h.01M12 21h.01M16 19.5h.01M10 22.5h.01M14 22.5h.01" />
      </>
    ),
    thunder: (
      <>
        {high}
        <path d="M13 14.5l-2.5 4h3l-2 4" />
      </>
    ),
  };
  return (
    <svg data-icon={icon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {shapes[icon]}
    </svg>
  );
}

/** Outside now, and the electricity rate, for the corner of the house picture. */
export function Weather({ live }: { live: Live }) {
  const now = live.outdoor_code === null ? null : weatherOf(live.outdoor_code, live.outdoor_is_day ?? true);
  return (
    <div className="weather">
      {now ? <Glyph icon={now.icon} /> : null}
      <div>
        {live.outdoor_f !== null ? <b>{Math.round(live.outdoor_f)}°F</b> : null}
        {now ? <span>{now.label}</span> : null}
        <span>{PERIOD_LABEL[live.rate_period]}</span>
      </div>
    </div>
  );
}

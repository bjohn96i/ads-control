import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Live } from "../api/client";
import { Weather, weatherOf } from "./Weather";

const live = (over: Partial<Live>) =>
  ({ outdoor_f: 68.4, outdoor_code: 61, outdoor_is_day: true, rate_period: "off_peak", ...over }) as Live;

describe("Weather", () => {
  it("shows the temperature, the conditions and the rate", () => {
    render(<Weather live={live({})} />);
    expect(screen.getByText("68°F")).toBeInTheDocument();
    expect(screen.getByText("Rain")).toBeInTheDocument();
    expect(screen.getByText("Off-peak")).toBeInTheDocument();
  });

  it("a clear night gets the moon", () => {
    const { container } = render(<Weather live={live({ outdoor_code: 0, outdoor_is_day: false })} />);
    expect(screen.getByText("Clear")).toBeInTheDocument();
    expect(container.querySelector("svg")).toHaveAttribute("data-icon", "moon");
  });

  it("without a reading it shows only the rate", () => {
    const { container } = render(<Weather live={live({ outdoor_f: null, outdoor_code: null, outdoor_is_day: null })} />);
    expect(screen.getByText("Off-peak")).toBeInTheDocument();
    expect(screen.queryByText(/°F/)).not.toBeInTheDocument();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("names the WMO code groups", () => {
    expect(weatherOf(2, true)).toEqual({ label: "Partly cloudy", icon: "partly-day" });
    expect(weatherOf(3, true)).toEqual({ label: "Cloudy", icon: "cloud" });
    expect(weatherOf(45, true)).toEqual({ label: "Fog", icon: "fog" });
    expect(weatherOf(53, true)).toEqual({ label: "Drizzle", icon: "rain" });
    expect(weatherOf(81, true)).toEqual({ label: "Showers", icon: "rain" });
    expect(weatherOf(75, true)).toEqual({ label: "Snow", icon: "snow" });
    expect(weatherOf(95, true)).toEqual({ label: "Thunderstorms", icon: "thunder" });
    expect(weatherOf(42, true)).toBeNull();
  });
});

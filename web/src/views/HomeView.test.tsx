import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HomeView } from "./HomeView";

const LIVE = {
  as_of: "2026-11-02T05:00:00Z",
  stale: false,
  whole_house_w: 1712,
  unmetered_w: 94,
  cost_per_hour_estimate: 0.115,
  rate_period: "super_off_peak",
  month_kwh: 26.2,
  month_coverage: 0.05,
  zones: [
    { id: 3, name: "Dishwasher", watts: 942.4, pin_x: 60, pin_y: 60, flagged: false },
    { id: 4, name: "Dryer", watts: 4200, pin_x: 40, pin_y: 80, flagged: false },
  ],
};

function renderHome(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status: ok ? 200 : 500 })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HomeView />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("HomeView", () => {
  it("renders_each_zone_pin_with_watts", async () => {
    renderHome(LIVE);
    const pin = await screen.findByRole("link", { name: /Dishwasher/ });
    expect(within(pin).getByText("942 W")).toBeInTheDocument();
  });

  it("shows_kw_above_1000_w", async () => {
    renderHome(LIVE);
    const pin = await screen.findByRole("link", { name: /Dryer/ });
    expect(within(pin).getByText("4.2 kW")).toBeInTheDocument();
  });

  it("stale_response_shows_stale_label_and_no_zero_watts", async () => {
    renderHome({
      ...LIVE,
      stale: true,
      whole_house_w: null,
      unmetered_w: null,
      cost_per_hour_estimate: null,
      zones: LIVE.zones.map((z) => ({ ...z, watts: null })),
    });
    expect(await screen.findByText(/no live reading/i)).toBeInTheDocument();
    expect(screen.queryByText(/^0 W$/)).not.toBeInTheDocument();
  });

  it("zero_watts_on_fresh_data_is_shown_as_zero", async () => {
    renderHome({ ...LIVE, zones: [{ ...LIVE.zones[0], watts: 0 }] });
    expect(await screen.findByText("0 W")).toBeInTheDocument();
  });

  it("shows_rate_period_and_estimate_label", async () => {
    renderHome(LIVE);
    expect(await screen.findByText(/super off-peak/i)).toBeInTheDocument();
    expect(screen.getByText(/\$0\.12\/hr.*estimate/i)).toBeInTheDocument();
  });

  it("shows_how_much_of_the_month_was_recorded", async () => {
    renderHome(LIVE);
    expect(await screen.findByText(/26 kWh this month.*5% recorded/i)).toBeInTheDocument();
  });

  it("pin_links_to_energy_page_for_that_zone", async () => {
    renderHome(LIVE);
    const pin = await screen.findByRole("link", { name: /Dishwasher/ });
    expect(pin).toHaveAttribute("href", "/energy?zone=3");
  });

  it("api_failure_shows_unreachable_state", async () => {
    renderHome({}, false);
    expect(await screen.findByText(/can.t reach the house server/i)).toBeInTheDocument();
  });

  it("camera_tiles_and_strip_say_not_connected_yet", async () => {
    renderHome(LIVE);
    await screen.findByRole("link", { name: /Dishwasher/ });
    expect(screen.getAllByText(/not connected yet/i).length).toBeGreaterThanOrEqual(4);
  });
});

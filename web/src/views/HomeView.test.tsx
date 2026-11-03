import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HomeView } from "./HomeView";

const LIVE = {
  as_of: "2026-11-02T05:00:00Z",
  stale: false,
  charger_estimate_w: 7200,
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

function renderHome(
  body: unknown,
  ok = true,
  next: unknown = null,
  bill: unknown = null,
  climate: unknown[] = [],
  events: unknown[] = [],
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url === "/api/auth/status"
        ? new Response(JSON.stringify({ pin_set: true, unlocked: false }))
        : url === "/api/traffic"
          ? new Response(JSON.stringify({ cameras: [
              { nickname: "Pool Turtle", name: "SR 154 at SR 12", view: 24030, image_url: "https://511ga.org/map/Cctv/24030", home: true },
              { nickname: "QT Exit 2", name: "I-285 CCW", view: 21551, image_url: "https://511ga.org/map/Cctv/21551", home: false },
            ] }))
        : url === "/api/network"
          ? new Response(JSON.stringify({ top_devices: [{ id: "tv", name: "Living Room TV", device_type: "iot", queries: 10, blocked: 1 }], arcs: [], home: null }))
        : url === "/api/cameras/events?limit=5"
          ? new Response(JSON.stringify({ events }))
          : url === "/api/climate/summary"
        ? new Response(JSON.stringify({ thermostats: climate }))
        : url === "/api/maintenance/next"
        ? new Response(JSON.stringify(next))
        : url === "/api/bills/latest"
          ? new Response(JSON.stringify(bill))
          : new Response(JSON.stringify(body), { status: ok ? 200 : 500 }),
    ),
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

  it("charging_car_shows_a_pin_labelled_as_an_estimate", async () => {
    renderHome(LIVE);
    const pin = await screen.findByRole("link", { name: /Car charger \(estimate\)/ });
    expect(within(pin).getByText("7.2 kW")).toBeInTheDocument();
  });

  it("idle_charger_says_not_charging_rather_than_0_w", async () => {
    renderHome({ ...LIVE, charger_estimate_w: 0 });
    const pin = await screen.findByRole("link", { name: /Car charger/ });
    expect(within(pin).getByText("Not charging")).toBeInTheDocument();
  });

  it("stale_charger_shows_no_claim", async () => {
    renderHome({ ...LIVE, stale: true, charger_estimate_w: null });
    const pin = await screen.findByRole("link", { name: /Car charger/ });
    expect(within(pin).getByText("—")).toBeInTheDocument();
  });

  it("maintenance_tile_shows_the_next_item_and_links_to_it", async () => {
    renderHome(LIVE, true, { name: "HVAC Filters", next_due: "2026-08-23", overdue: true });
    const link = await screen.findByRole("link", { name: /HVAC Filters/ });
    expect(link).toHaveAttribute("href", "/maintenance");
    expect(within(link).getByText("Maintenance")).toBeInTheDocument();
    expect(within(link).getByText(/overdue since Aug 23/i)).toBeInTheDocument();
  });

  it("maintenance_tile_with_nothing_due_still_links_to_maintenance", async () => {
    renderHome(LIVE);
    const link = await screen.findByRole("link", { name: /Maintenance.*Nothing scheduled/i });
    expect(link).toHaveAttribute("href", "/maintenance");
  });

  it("bill_tile_shows_the_actual_charge", async () => {
    renderHome(LIVE, true, null, { actual_charge: 150.26, budget_payment: 248 });
    const link = await screen.findByRole("link", { name: /Last bill/ });
    expect(await within(link).findByText("$150.26")).toBeInTheDocument();
    expect(within(link).getByText("actual charge")).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/bills");
  });

  it("ac_tile_shows_both_thermostats_and_links_to_climate", async () => {
    renderHome(LIVE, true, null, null, [
      { name: "Upstairs", stale: false, ambient_f: 67.4, setpoint_f: 67 },
      { name: "Downstairs", stale: true, ambient_f: null, setpoint_f: null },
    ]);
    const link = await screen.findByRole("link", { name: /A\/C/ });
    expect(await within(link).findByText("Upstairs 67° → 67°")).toBeInTheDocument();
    expect(within(link).getByText("Downstairs: no recent reading")).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/climate");
  });

  it("flagged_zone_says_so_in_words", async () => {
    renderHome({ ...LIVE, zones: [{ ...LIVE.zones[0], flagged: true }] });
    const pin = await screen.findByRole("link", { name: /Dishwasher/ });
    expect(within(pin).getByText("Unusual")).toBeInTheDocument();
  });

  it("shows_recent_camera_events_linking_to_the_camera_page", async () => {
    renderHome(LIVE, true, null, null, [], [
      { camera_id: 2, camera: "Entryway doorbell", type: "chime", occurred_at: "2026-11-02T19:14:00Z" },
      { camera_id: 1, camera: "Backyard camera", type: "motion", occurred_at: "2026-11-02T19:10:00Z" },
    ]);
    expect(await screen.findByText("Entryway doorbell")).toBeInTheDocument();
    expect(screen.getByText("Doorbell rang")).toBeInTheDocument();
    const panel = screen.getByText("Backyard camera").closest("a")!;
    expect(panel).toHaveAttribute("href", "/cameras");
    expect(within(panel).queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows_lanthorns_noisiest_devices", async () => {
    renderHome(LIVE);
    expect(await screen.findByRole("link", { name: "Living Room TV" })).toBeInTheDocument();
  });

  it("shows_only_the_home_traffic_cameras", async () => {
    renderHome(LIVE);
    expect(await screen.findByRole("img", { name: /Pool Turtle/ })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /QT Exit 2/ })).not.toBeInTheDocument();
  });
});

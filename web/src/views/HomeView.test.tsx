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
  outdoor_f: 68,
  today_kwh: 31.4,
  today_cost: 4.12,
  today_coverage: 0.98,
  whole_house_pin: { x: 65, y: 79 },
  recent_w: [
    { time: "2026-11-02T04:58:00Z", watts: 1500 },
    { time: "2026-11-02T04:59:00Z", watts: 1600 },
    { time: "2026-11-02T05:00:00Z", watts: 1712 },
  ],
  zones: [
    { id: 3, name: "Dishwasher", watts: 942.4, pin_x: 60, pin_y: 60, room: null, floor: null, flagged: false },
    { id: 4, name: "Dryer", watts: 4200, pin_x: 40, pin_y: 80, room: null, floor: null, flagged: false },
  ],
};

const ESTIMATE = {
  period_start: "2026-10-24",
  period_end: "2026-11-22",
  day: 12,
  days: 30,
  kwh_so_far: 405.2,
  cost_so_far: 55.1,
  projected_kwh: 1013,
  projected_cost: 137.2,
  last_charge: 150.26,
  change_pct: -0.087,
  verdict: "less",
  manual_days: 9,
};

function renderHome(
  body: unknown,
  ok = true,
  tasks: unknown[] = [],
  bill: unknown = null,
  climate: unknown[] = [],
  events: unknown[] = [],
  { unlocked = false, network = true, failing = [] as string[], current = null as unknown } = {},
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      failing.includes(url)
        ? new Response("{}", { status: 500 })
        : url === "/api/auth/status"
        ? new Response(JSON.stringify({ pin_set: true, unlocked }))
        : url === "/api/traffic"
          ? new Response(JSON.stringify({ cameras: [
              { nickname: "Pool Turtle", name: "SR 154 at SR 12", view: 24030, image_url: "https://511ga.org/map/Cctv/24030", home: true },
              { nickname: "QT Exit 2", name: "I-285 CCW", view: 21551, image_url: "https://511ga.org/map/Cctv/21551", home: false },
            ] }))
        : url === "/api/network" && !network
          ? new Response(JSON.stringify({ detail: "Lanthorn isn't reachable" }), { status: 503 })
        : url === "/api/network"
          ? new Response(JSON.stringify({ top_devices: [{ id: "tv", name: "Living Room TV", device_type: "iot", queries: 10, blocked: 1 }], arcs: [], home: null }))
        : url === "/api/cameras/events?limit=5"
          ? new Response(JSON.stringify({ events }))
          : url === "/api/climate/summary"
        ? new Response(JSON.stringify({ thermostats: climate }))
        : url === "/api/maintenance"
        ? new Response(JSON.stringify({ tasks }))
        : url === "/api/bills/latest"
          ? new Response(JSON.stringify(bill))
        : url === "/api/bills/current"
          ? new Response(JSON.stringify(current))
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

  it("power_card_shows_today_and_draws_the_recent_line", async () => {
    renderHome(LIVE);
    const card = (await screen.findByText("Power now")).closest("a")!;
    expect(card).toHaveAttribute("href", "/energy");
    expect(within(card).getByText(/Today 31 kWh/)).toBeInTheDocument();
    expect(within(card).getByText("≈ $4.12")).toBeInTheDocument();
    const line = card.querySelector("polyline")!;
    expect(line.getAttribute("points")!.trim().split(/\s+/)).toHaveLength(3);
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

  it("power_card_warns_when_today_is_only_partly_recorded", async () => {
    renderHome({ ...LIVE, today_coverage: 0.5 });
    const card = (await screen.findByText("Power now")).closest("a")!;
    expect(within(card).getByText(/50% recorded/)).toBeInTheDocument();
  });

  it("power_card_shows_a_dash_when_nothing_was_recorded_today", async () => {
    renderHome({ ...LIVE, today_kwh: 0, today_cost: 0, today_coverage: 0 });
    const card = (await screen.findByText("Power now")).closest("a")!;
    expect(within(card).getByText("Today —")).toBeInTheDocument();
    expect(within(card).queryByText(/\$0\.00/)).not.toBeInTheDocument();
  });

  it("older_camera_events_show_their_day", async () => {
    renderHome(LIVE, true, [], null, [], [
      { camera_id: 2, camera: "Entryway doorbell", type: "chime", occurred_at: "2026-01-02T19:14:00Z" },
    ]);
    expect(await screen.findByText(/Jan 2/)).toBeInTheDocument();
  });

  it("small_amounts_today_keep_a_decimal", async () => {
    renderHome({ ...LIVE, today_kwh: 0.4 });
    const card = (await screen.findByText("Power now")).closest("a")!;
    expect(within(card).getByText(/Today 0\.4 kWh/)).toBeInTheDocument();
  });

  it("ac_card_says_offline_rather_than_idle", async () => {
    renderHome(LIVE, true, [], null, [{ ...{ id: 1, name: "Upstairs", stale: false, ambient_f: 74, setpoint_f: 72, heat_f: null, cool_f: 72, mode: "COOL", hvac_status: "OFF", eco: false, online: true }, online: false }]);
    expect(await screen.findByText("Upstairs · offline")).toBeInTheDocument();
  });

  it("ac_card_says_off_when_the_thermostat_is_off", async () => {
    renderHome(LIVE, true, [], null, [{ id: 1, name: "Upstairs", stale: false, ambient_f: 74, setpoint_f: null, heat_f: null, cool_f: null, mode: "OFF", hvac_status: "OFF", eco: false, online: true }]);
    expect(await screen.findByText("Upstairs · off")).toBeInTheDocument();
  });

  it("bill_and_maintenance_cards_say_when_they_cant_load", async () => {
    renderHome(LIVE, true, [], null, [], [], { failing: ["/api/bills/latest", "/api/maintenance"] });
    expect(await screen.findByText("Can't load the bills")).toBeInTheDocument();
    expect(await screen.findByText("Can't load maintenance")).toBeInTheDocument();
  });

  it("maintenance_shows_the_next_three", async () => {
    const task = (id: number, name: string, next_due: string | null) => ({ id, name, next_due, overdue: false });
    renderHome(LIVE, true, [
      task(1, "HVAC Filters", "2026-11-07"),
      task(2, "Dryer vent", "2026-11-20"),
      task(3, "Undated", null),
      task(4, "Water heater flush", "2027-01-10"),
      task(5, "Gutters", "2027-03-01"),
    ]);
    const card = (await screen.findByText("HVAC Filters")).closest("a")!;
    expect(card).toHaveAttribute("href", "/maintenance");
    expect(within(card).getAllByText(/^(HVAC Filters|Dryer vent|Water heater flush|Gutters|Undated)$/).map((e) => e.textContent)).toEqual([
      "HVAC Filters",
      "Dryer vent",
      "Water heater flush",
    ]);
  });

  it("empty_bills_and_maintenance_say_so", async () => {
    renderHome(LIVE);
    expect(await screen.findByText("Nothing scheduled")).toBeInTheDocument();
    expect(await screen.findByText("No bills yet")).toBeInTheDocument();
  });

  it("bill_card_shows_the_actual_charge", async () => {
    renderHome(LIVE, true, [], { actual_charge: 150.26, period_end: "2026-10-21" });
    const link = (await screen.findByText("Last bill")).closest("a")!;
    expect(link).toHaveAttribute("href", "/bills");
    expect(await within(link).findByText("$150")).toBeInTheDocument();
    expect(within(link).getByText(".26")).toBeInTheDocument();
    expect(within(link).getByText("October · actual charge")).toBeInTheDocument();
  });

  it("this_bill_card_projects_against_the_last_bill", async () => {
    renderHome(LIVE, true, [], { actual_charge: 150.26, period_end: "2026-10-23" }, [], [], { current: ESTIMATE });
    const link = (await screen.findByText(/^This bill/)).closest("a")!;
    expect(link).toHaveAttribute("href", "/bills");
    expect(link).toHaveTextContent("estimate");
    expect(await within(link).findByText("≈ $137")).toBeInTheDocument();
    expect(within(link).getByText("Oct 24 – Nov 22 · day 12 of 30")).toBeInTheDocument();
    expect(within(link).getByText("Last bill $150.26 · on track for 9% less")).toBeInTheDocument();
    expect(within(link).getByText("$55 so far · 405 kWh")).toBeInTheDocument();
  });

  it("this_bill_card_warns_when_heading_higher", async () => {
    renderHome(LIVE, true, [], { actual_charge: 150.26, period_end: "2026-10-23" }, [], [], {
      current: { ...ESTIMATE, projected_cost: 171.4, change_pct: 0.141, verdict: "more" },
    });
    const line = await screen.findByText("Last bill $150.26 · on track for 14% more");
    expect(line).toHaveClass("warn");
  });

  it("this_bill_card_says_about_the_same", async () => {
    renderHome(LIVE, true, [], { actual_charge: 150.26, period_end: "2026-10-23" }, [], [], {
      current: { ...ESTIMATE, projected_cost: 151, change_pct: 0.005, verdict: "about the same" },
    });
    expect(await screen.findByText("Last bill $150.26 · on track for about the same")).toBeInTheDocument();
  });

  it("ac_card_has_real_controls_behind_the_pin", async () => {
    renderHome(LIVE, true, [], null, [{ id: 1, name: "Upstairs", stale: false, ambient_f: 74, setpoint_f: 72, heat_f: null, cool_f: 72, mode: "COOL", hvac_status: "COOLING", eco: false, online: true }], [], { unlocked: false });
    const card = (await screen.findByText(/^Upstairs ·/)).closest("section")!;
    expect(await within(card).findByLabelText("Household PIN")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Warmer" })).not.toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /Climate/ })).toHaveAttribute("href", "/climate");
  });

  it("ac_card_unlocked_shows_the_buttons", async () => {
    renderHome(LIVE, true, [], null, [{ id: 1, name: "Upstairs", stale: false, ambient_f: 74, setpoint_f: 72, heat_f: null, cool_f: 72, mode: "COOL", hvac_status: "COOLING", eco: false, online: true }], [], { unlocked: true });
    const card = (await screen.findByText(/^Upstairs ·/)).closest("section")!;
    expect(await within(card).findByRole("button", { name: "Warmer" })).toBeInTheDocument();
    expect(within(card).getByText("74°")).toBeInTheDocument();
  });

  it("ac_card_shows_why_a_thermostat_cant_be_changed", async () => {
    renderHome(LIVE, true, [], null, [{ ...{ id: 1, name: "Upstairs", stale: false, ambient_f: 74, setpoint_f: 72, heat_f: null, cool_f: 72, mode: "COOL", hvac_status: "COOLING", eco: false, online: true }, mode: "OFF" }], [], { unlocked: true });
    const card = (await screen.findByText(/^Upstairs ·/)).closest("section")!;
    expect(await within(card).findByText("This thermostat is off.")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Warmer" })).not.toBeInTheDocument();
  });

  it("the_page_still_lays_out_when_lanthorn_is_down", async () => {
    renderHome(LIVE, true, [], null, [], [], { network: false });
    expect(await screen.findByText("Lanthorn isn't reachable")).toBeInTheDocument();
    for (const name of ["A/C", "Maintenance", "Last bill", "Power now", "Camera events"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("flagged_zone_says_so_in_words", async () => {
    renderHome({ ...LIVE, zones: [{ ...LIVE.zones[0], flagged: true }] });
    const pin = await screen.findByRole("link", { name: /Dishwasher/ });
    expect(within(pin).getByText("Unusual")).toBeInTheDocument();
  });

  it("shows_recent_camera_events_linking_to_the_camera_page", async () => {
    renderHome(LIVE, true, [], null, [], [
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

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ClimateView } from "./ClimateView";

const thermostat = (over: object = {}) => ({
  id: 1,
  name: "Upstairs",
  zone_name: "Upstairs A/C",
  stale: false,
  ambient_f: 67.4,
  humidity: 70,
  setpoint_f: 67,
  heat_f: 67,
  cool_f: null,
  mode: "HEAT",
  hvac_status: "OFF",
  eco: false,
  online: true,
  timeline: [{ time: "2026-11-02T14:00:00Z", ambient_f: 67, setpoint_f: 67, running: false, ac_watts: 20, outdoor_f: 50 }],
  on_peak_flag: false,
  estimate: null,
  ...over,
});

let calls: { url: string; body: any }[];

function show(thermostats: object[], { unlocked = true, setStatus = 200, detail = "" } = {}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") !== "GET") {
        calls.push({ url, body: JSON.parse(init!.body as string) });
        return new Response(JSON.stringify({ ok: true, detail }), { status: setStatus });
      }
      if (url === "/api/auth/status") return new Response(JSON.stringify({ pin_set: true, unlocked }));
      return new Response(JSON.stringify({ thermostats, rate_period: "off_peak" }));
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <ClimateView />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

async function card(name: string) {
  const heading = await screen.findByRole("heading", { name });
  // The PIN check answers just after the card appears.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  return within(heading.closest("article")!);
}

describe("ClimateView", () => {
  it("controls_and_timeline_per_thermostat", async () => {
    show([thermostat(), thermostat({ id: 2, name: "Downstairs" })]);
    for (const name of ["Upstairs", "Downstairs"]) {
      const c = await card(name);
      expect(c.getByRole("button", { name: /warmer/i })).toBeInTheDocument();
      expect(c.getByTestId("climate-chart")).toBeInTheDocument();
    }
  });

  it("shows_temperature_setpoint_and_what_it_is_doing", async () => {
    show([thermostat({ hvac_status: "HEATING" })]);
    const c = await card("Upstairs");
    expect(c.getByText("67°")).toBeInTheDocument();
    expect(c.getByText(/set to 67°/i)).toBeInTheDocument();
    expect(c.getByText(/heating/i)).toBeInTheDocument();
  });

  it("pin_prompt_before_change", async () => {
    show([thermostat()], { unlocked: false });
    const c = await card("Upstairs");
    expect(c.getByLabelText(/household pin/i)).toBeInTheDocument();
    expect(c.queryByRole("button", { name: /warmer/i })).not.toBeInTheDocument();
    expect(c.getByText("67°")).toBeInTheDocument();
  });

  it("stepping_alone_changes_nothing_until_confirmed", async () => {
    show([thermostat()]);
    const c = await card("Upstairs");
    fireEvent.click(c.getByRole("button", { name: /warmer/i }));
    fireEvent.click(c.getByRole("button", { name: /warmer/i }));
    expect(calls).toHaveLength(0);
    fireEvent.click(c.getByRole("button", { name: "Set to 69°" }));
    await waitFor(() => expect(calls[0]?.url).toBe("/api/climate/1/setpoint"));
    expect(calls[0].body).toEqual({ temp_f: 69 });
  });

  it("failed_change_says_so", async () => {
    show([thermostat()], { setStatus: 409 });
    const c = await card("Upstairs");
    fireEvent.click(c.getByRole("button", { name: /cooler/i }));
    fireEvent.click(c.getByRole("button", { name: "Set to 66°" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not changed/i);
  });

  it("the_schedule_is_described_as_untouched", async () => {
    show([thermostat()]);
    await card("Upstairs");
    expect(screen.getByText(/schedule isn.t changed/i)).toBeInTheDocument();
  });

  it("off_or_eco_or_offline_shows_why_with_no_controls", async () => {
    for (const [over, text] of [
      [{ mode: "OFF" }, /is off/i],
      [{ eco: true }, /eco/i],
      [{ online: false }, /offline/i],
    ] as const) {
      show([thermostat(over)]);
      const c = await card("Upstairs");
      expect(c.getByText(text)).toBeInTheDocument();
      expect(c.queryByRole("button", { name: /warmer/i })).not.toBeInTheDocument();
      document.body.innerHTML = "";
    }
  });

  it("range_mode_offers_both_ends", async () => {
    show([thermostat({ mode: "HEATCOOL", heat_f: 66, cool_f: 76, setpoint_f: null })]);
    const c = await card("Upstairs");
    fireEvent.click(c.getByRole("button", { name: "Cool" }));
    fireEvent.click(c.getByRole("button", { name: /cooler/i }));
    fireEvent.click(c.getByRole("button", { name: "Set to 75°" }));
    await waitFor(() => expect(calls[0]?.body).toEqual({ temp_f: 75, target: "cool" }));
  });

  it("stale_says_no_recent_reading", async () => {
    show([thermostat({ stale: true, ambient_f: null, setpoint_f: null, mode: null, online: false })]);
    const c = await card("Upstairs");
    expect(c.getByText(/no recent reading/i)).toBeInTheDocument();
  });

  it("winter_says_gas_not_measured", async () => {
    show([thermostat({ mode: "HEAT" })]);
    await card("Upstairs");
    expect(screen.getByText(/gas.*isn.t measured/i)).toBeInTheDocument();
  });

  it("estimate_labelled_and_mentions_season", async () => {
    show([thermostat({ estimate: { kwh_per_degree_day: 2, dollars_per_f_degree_month: 6.7, days: 25, full_season: false } })]);
    const c = await card("Upstairs");
    expect(c.getByText(/about \$6\.70 a month.*estimate/i)).toBeInTheDocument();
    expect(c.getByText(/full season/i)).toBeInTheDocument();
  });

  it("no_estimate_explains_itself", async () => {
    show([thermostat()]);
    const c = await card("Upstairs");
    expect(c.getByText(/needs about 3 weeks of cooling/i)).toBeInTheDocument();
  });

  it("on_peak_flag_is_shown", async () => {
    show([thermostat({ on_peak_flag: true })]);
    const c = await card("Upstairs");
    expect(c.getByText(/on-peak/i)).toBeInTheDocument();
  });
});

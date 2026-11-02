import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EnergyView } from "./EnergyView";

const line = (kwh: number, est_cost: number, share: number, coverage = 0.98) => ({
  kwh,
  est_cost,
  share,
  coverage,
});

const RANKING = {
  start: "2026-10-01T00:00:00Z",
  end: "2026-10-31T00:00:00Z",
  zones: [
    { id: 3, name: "Dishwasher", ...line(120.4, 21.5, 0.2) },
    { id: 6, name: "Basement", ...line(90, 12.25, 0.15) },
  ],
  charger_estimate: line(300, 20, 0.5),
  unmetered: line(30, 4, 0.05),
  whole_house: line(600, 90, 1),
};

const ZONE = {
  id: 3,
  name: "Dishwasher",
  series: [
    { time: "2026-10-30T00:00:00Z", watts: 10 },
    { time: "2026-10-30T01:00:00Z", watts: null },
  ],
  overnight_min_w: 42,
  flags: [],
};

function Where() {
  return <div data-testid="where">{useLocation().search}</div>;
}

function show(ranking: unknown = RANKING, entry = "/energy") {
  const fetchMock = vi.fn(async (url: string) =>
    url.startsWith("/api/energy/zones/")
      ? new Response(JSON.stringify(ZONE))
      : new Response(JSON.stringify(ranking)),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <EnergyView />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("EnergyView", () => {
  it("lists_zones_in_order_with_kwh_and_cost", async () => {
    show();
    const rows = await screen.findAllByRole("row");
    expect(within(rows[1]).getByText("Dishwasher")).toBeInTheDocument();
    expect(within(rows[1]).getByText("120 kWh")).toBeInTheDocument();
    expect(within(rows[1]).getByText("$21.50")).toBeInTheDocument();
  });

  it("small_amounts_keep_a_decimal_rather_than_rounding_to_nothing", async () => {
    show({ ...RANKING, zones: [{ id: 3, name: "Dishwasher", ...line(0.43, 0.03, 0.15) }] });
    expect(await screen.findByText("0.4 kWh")).toBeInTheDocument();
  });

  it("labels_costs_as_estimates", async () => {
    show();
    expect(await screen.findByRole("columnheader", { name: /estimated cost/i })).toBeInTheDocument();
    expect(screen.getByText(/\$90\.00 estimated/i)).toBeInTheDocument();
  });

  it("shows_charger_and_unmetered_lines_with_the_charger_marked_estimate", async () => {
    show();
    expect(await screen.findByText("Car charger (estimate)")).toBeInTheDocument();
    expect(screen.getByText("Not on any zone")).toBeInTheDocument();
  });

  it("shows_coverage_warning_below_90_percent", async () => {
    show({ ...RANKING, whole_house: line(600, 90, 1, 0.42) });
    expect(await screen.findByRole("status")).toHaveTextContent(/42%/);
  });

  it("no_coverage_warning_at_90_percent", async () => {
    show({ ...RANKING, whole_house: line(600, 90, 1, 0.9) });
    await screen.findByText("Dishwasher");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("range_is_in_url", async () => {
    const fetchMock = show();
    fireEvent.click(await screen.findByRole("button", { name: "7 days" }));
    expect(screen.getByTestId("where")).toHaveTextContent("range=7d");
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/energy/ranking?range=7d"),
    );
  });

  it("url_range_is_used_on_load", async () => {
    const fetchMock = show(RANKING, "/energy?range=30d");
    await screen.findByText("Dishwasher");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/energy/ranking?range=30d");
  });

  it("zone_from_the_home_page_opens_its_detail", async () => {
    show(RANKING, "/energy?zone=3");
    expect(await screen.findByText(/42 W overnight/i)).toBeInTheDocument();
  });

  it("clicking_a_zone_opens_its_detail", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Dishwasher" }));
    expect(screen.getByTestId("where")).toHaveTextContent("zone=3");
    expect(await screen.findByText(/42 W overnight/i)).toBeInTheDocument();
  });

  it("zone_flags_explain_what_is_unusual", async () => {
    ZONE.flags = [{ kind: "creep", summary: "Typical use has risen from 1.0 to 2.0 kWh a day" }] as never;
    show(RANKING, "/energy?zone=3");
    expect(await screen.findByText(/risen from 1\.0 to 2\.0/)).toBeInTheDocument();
    ZONE.flags = [];
  });

  it("failed_load_says_so", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <EnergyView />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/can.t reach/i);
  });
});

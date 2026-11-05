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
  start: "2026-10-24T00:00:00-04:00",
  end: "2026-11-04T12:00:00-05:00",
  since_bill: true,
  zones: [
    { id: 3, name: "Dishwasher", room: "Kitchen", ...line(120.4, 21.5, 0.2) },
    { id: 6, name: "Basement", room: "John's Office", ...line(90, 12.25, 0.15) },
    { id: 2, name: "Fridge/Stove", room: "Kitchen", ...line(30, 5, 0.05) },
  ],
  charger_estimate: line(300, 20, 0.5),
  unmetered: line(30, 4, 0.05),
  whole_house: { id: 1, ...line(600, 90, 1) },
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

const LIVE = {
  zones: [
    { id: 3, name: "Dishwasher", watts: 5, pin_x: 33, pin_y: 35, room: "Kitchen", floor: "1st floor", flagged: false },
    { id: 4, name: "Dryer", watts: 0, pin_x: 25, pin_y: 80, room: "Laundry", floor: "Basement", flagged: false },
    { id: 12, name: "Water Heater", watts: 0, pin_x: 56, pin_y: 92, room: "Water Heater", floor: "Basement", flagged: false },
  ],
};

function Where() {
  return <div data-testid="where">{useLocation().search}</div>;
}

const zoneName = (url: string) =>
  ({ 1: "Whole House", 3: "Dishwasher", 4: "Dryer", 12: "Water Heater" })[Number(url.split("/").pop()!.split("?")[0])] ?? "Zone";

function show(ranking: unknown = RANKING, entry = "/energy") {
  const fetchMock = vi.fn(async (url: string) =>
    url === "/api/live"
      ? new Response(JSON.stringify(LIVE))
      : url.startsWith("/api/energy/rooms/")
        ? new Response(JSON.stringify({ ...ZONE, id: null, name: decodeURIComponent(url.split("/").pop()!.split("?")[0]) }))
        : url.startsWith("/api/energy/zones/")
        ? new Response(JSON.stringify({ ...ZONE, id: Number(url.split("/").pop()!.split("?")[0]), name: zoneName(url) }))
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
    expect(within(rows[2]).getByText("Dishwasher")).toBeInTheDocument();
    expect(within(rows[2]).getByText("120 kWh")).toBeInTheDocument();
    expect(within(rows[2]).getByText("$21.50")).toBeInTheDocument();
  });

  it("small_amounts_keep_a_decimal_rather_than_rounding_to_nothing", async () => {
    show({ ...RANKING, zones: [{ id: 3, name: "Dishwasher", ...line(0.43, 0.03, 0.15) }] });
    expect(await screen.findByText("0.4 kWh")).toBeInTheDocument();
  });

  it("labels_costs_as_estimates", async () => {
    show();
    expect(await screen.findByRole("columnheader", { name: /estimated cost/i })).toBeInTheDocument();
    const cost = screen.getByText("Estimated cost", { selector: ".eyebrow" }).closest<HTMLElement>(".card")!;
    expect(within(cost).getByText("$90")).toBeInTheDocument();
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

  it("shows_the_whole_house_uncropped_when_nothing_is_picked", async () => {
    show();
    expect(await screen.findByRole("heading", { name: "Whole House" })).toBeInTheDocument();
    expect(screen.getByTestId("where")).not.toHaveTextContent("zone=");
    expect(screen.getByTestId("zone-photo")).toHaveClass("whole");
    expect(screen.getByTestId("zone-photo").querySelector("img")!.style.transform).toBe("");
  });

  it("groups_circuits_under_their_room_with_the_room_total", async () => {
    show();
    const rows = await screen.findAllByRole("row");
    expect(within(rows[1]).getByRole("button", { name: "Kitchen" })).toBeInTheDocument();
    expect(within(rows[1]).getByText("150 kWh")).toBeInTheDocument();
    expect(within(rows[1]).getByText("$26.50")).toBeInTheDocument();
    expect(within(rows[3]).getByText("Fridge/Stove")).toBeInTheDocument();
    // A room with one circuit is just that circuit's row.
    expect(screen.queryByRole("button", { name: "John's Office" })).not.toBeInTheDocument();
  });

  it("clicking_a_room_shows_the_room", async () => {
    const fetchMock = show(RANKING, "/energy?zone=3");
    fireEvent.click(await screen.findByRole("button", { name: "Kitchen" }));
    expect(screen.getByTestId("where")).toHaveTextContent("room=Kitchen");
    expect(screen.getByTestId("where")).not.toHaveTextContent("zone=");
    expect(await screen.findByRole("heading", { name: "Kitchen" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/energy/rooms/Kitchen?range=bill");
    await vi.waitFor(() => expect(screen.getByTestId("zone-where")).toHaveTextContent(/^1st floor$/));
  });

  it("whole_house_row_opens_the_whole_house", async () => {
    show(RANKING, "/energy?zone=3");
    fireEvent.click(await screen.findByRole("button", { name: "Whole House" }));
    expect(screen.getByTestId("where")).toHaveTextContent("zone=1");
    expect(await screen.findByRole("heading", { name: "Whole House" })).toBeInTheDocument();
  });

  it("the_crop_is_centred_on_the_zones_label", async () => {
    show(RANKING, "/energy?zone=12");
    await screen.findByRole("heading", { name: "Water Heater" });
    // The picture is moved so the zone's spot sits at the box's focal point, not its edge.
    await vi.waitFor(() =>
      expect(screen.getByTestId("zone-photo").querySelector("img")!.style.transform).toBe("translate(-56%, -92%)"),
    );
  });

  it("a_flagged_zone_is_announced_not_just_coloured", async () => {
    LIVE.zones[0].flagged = true;
    show();
    const row = (await screen.findByRole("button", { name: "Dishwasher" })).closest("tr")!;
    await vi.waitFor(() => expect(within(row).getByRole("img", { name: "Unusual" })).toBeInTheDocument());
    LIVE.zones[0].flagged = false;
  });

  it("eyebrow_names_floor_and_room", async () => {
    show(RANKING, "/energy?zone=4");
    await vi.waitFor(() => expect(screen.getByTestId("zone-where")).toHaveTextContent(/^Basement · Laundry$/));
  });

  it("eyebrow_is_just_the_floor_when_the_room_is_the_zone", async () => {
    show(RANKING, "/energy?zone=12");
    await vi.waitFor(() => expect(screen.getByTestId("zone-where")).toHaveTextContent(/^Basement$/));
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

  it("shows_the_dates_the_figures_cover", async () => {
    show();
    const used = (await screen.findByText(/^Used ·/)).closest<HTMLElement>(".card")!;
    expect(used).toHaveTextContent("Since the last bill");
    expect(used).toHaveTextContent("Oct 24 – Nov 4");
  });

  it("says_when_this_bill_is_really_the_last_30_days", async () => {
    show({ ...RANKING, since_bill: false });
    const used = (await screen.findByText(/^Used ·/)).closest<HTMLElement>(".card")!;
    expect(used).toHaveTextContent("Last 30 days, no bill yet");
  });

  it("a_failed_detail_load_says_so_instead_of_vanishing", async () => {
    const ok = show();
    ok.mockImplementation(async (url: string) =>
      url.startsWith("/api/energy/zones/")
        ? new Response("{}", { status: 500 })
        : url === "/api/live"
          ? new Response(JSON.stringify(LIVE))
          : new Response(JSON.stringify(RANKING)),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Dishwasher" }));
    expect(await screen.findByText(/can.t load this detail/i)).toBeInTheDocument();
  });
});

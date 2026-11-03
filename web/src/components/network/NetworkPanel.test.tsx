import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NetworkPanel } from "./NetworkPanel";

// WebGL isn't available in tests; the globe is checked by eye, as in Lanthorn.
vi.mock("./Globe", () => ({ default: () => <div data-testid="globe" /> }));

const NETWORK = {
  top_devices: [
    { id: "tv 1", name: "Living Room TV", device_type: "iot", queries: 5442, blocked: 3480 },
    { id: "mac", name: "MacBook Air (2)", device_type: "laptop", queries: 5383, blocked: 155 },
  ],
  arcs: [{ lat: 37.8, lon: -97.8, country_code: "US", country: "United States", queries: 900, blocked: 4, state: "normal" }],
  home: { lat: 33.75, lon: -84.39 },
};

class SizedObserver {
  constructor(private report: ResizeObserverCallback) {}
  observe() {
    this.report([{ contentRect: { width: 320 } } as ResizeObserverEntry], this as never);
  }
  disconnect() {}
}

function show(response: Response) {
  vi.stubGlobal("fetch", vi.fn(async () => response));
  vi.stubGlobal("ResizeObserver", SizedObserver);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NetworkPanel />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("NetworkPanel", () => {
  it("lists_noisiest_devices_opening_each_in_lanthorn", async () => {
    show(new Response(JSON.stringify(NETWORK)));
    const tv = await screen.findByRole("link", { name: /Living Room TV/ });
    expect(tv).toHaveAttribute("href", `http://${window.location.hostname}:8000/?panel=device%3Atv%25201&range=24h`);
    expect(tv).toHaveAttribute("target", "_blank");
    expect(screen.getByText("5,442")).toBeInTheDocument();
    expect(screen.getByText("64% blocked")).toBeInTheDocument();
    expect(await screen.findByTestId("globe")).toBeInTheDocument();
  });

  it("heading_opens_lanthorn_overview", async () => {
    show(new Response(JSON.stringify(NETWORK)));
    const heading = await screen.findByRole("link", { name: /network/i });
    expect(heading).toHaveAttribute("href", `http://${window.location.hostname}:8000/?range=24h`);
  });

  it("lanthorn_down_says_so", async () => {
    show(new Response(JSON.stringify({ detail: "Lanthorn isn't reachable" }), { status: 503 }));
    expect(await screen.findByText(/lanthorn isn't reachable/i)).toBeInTheDocument();
    expect(screen.queryByTestId("globe")).not.toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type ThermostatState, ThermostatControls } from "./ThermostatControls";

const state = (over: Partial<ThermostatState> = {}): ThermostatState => ({
  id: 1,
  name: "Upstairs",
  stale: false,
  ambient_f: 71,
  setpoint_f: 72,
  heat_f: null,
  cool_f: 72,
  mode: "COOL",
  hvac_status: "COOLING",
  eco: false,
  online: true,
  ...over,
});

let posts: { url: string; body: unknown }[];

function show(t: ThermostatState, unlocked = true, setStatus = 200) {
  posts = [];
  let locked = !unlocked;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") !== "GET") {
        posts.push({ url, body: JSON.parse(init!.body as string) });
        // The session ran out: the server refuses, and asks for the PIN from now on.
        if (setStatus === 401) locked = true;
        return new Response(JSON.stringify({ ok: setStatus === 200 }), { status: setStatus });
      }
      return new Response(JSON.stringify({ pin_set: true, unlocked: !locked }));
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ThermostatControls t={t} onError={() => {}} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ThermostatControls", () => {
  it("shows the Eco reason and no buttons", async () => {
    show(state({ eco: true }));
    expect(await screen.findByText(/This thermostat is in Eco mode/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Warmer" })).not.toBeInTheDocument();
  });

  it("nothing changes until Set is pressed", async () => {
    show(state());
    fireEvent.click(await screen.findByRole("button", { name: "Warmer" }));
    expect(posts).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Set to 73°" }));
    await vi.waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ url: "/api/climate/1/setpoint", body: { temp_f: 73 } });
  });

  it("asks for the PIN again when the session has run out", async () => {
    show(state(), true, 401);
    fireEvent.click(await screen.findByRole("button", { name: "Warmer" }));
    fireEvent.click(screen.getByRole("button", { name: "Set to 73°" }));
    expect(await screen.findByLabelText("Household PIN")).toBeInTheDocument();
  });

  it("asks for the PIN when locked", async () => {
    show(state(), false);
    expect(await screen.findByLabelText("Household PIN")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Warmer" })).not.toBeInTheDocument();
  });
});

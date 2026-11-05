import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PinGate } from "./PinGate";

function show(status: unknown, pinResponse?: () => Response) {
  const state = { status };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/auth/status") return new Response(JSON.stringify(state.status));
    const response = pinResponse ? pinResponse() : new Response("{}");
    if (response.ok) state.status = { pin_set: true, unlocked: true };
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PinGate>
        <p>secret content</p>
      </PinGate>
    </QueryClientProvider>,
  );
  return fetchMock;
}

const enter = async (pin = "482915") => {
  fireEvent.change(await screen.findByLabelText(/pin/i), { target: { value: pin } });
  fireEvent.click(screen.getByRole("button", { name: /unlock/i }));
};

afterEach(() => vi.unstubAllGlobals());

describe("PinGate", () => {
  it("shows_children_when_unlocked", async () => {
    show({ pin_set: true, unlocked: true });
    expect(await screen.findByText("secret content")).toBeInTheDocument();
  });

  it("hides_children_while_locked", async () => {
    show({ pin_set: true, unlocked: false });
    await screen.findByLabelText(/pin/i);
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
  });

  it("the_field_hides_digits_and_offers_a_number_pad", async () => {
    show({ pin_set: true, unlocked: false });
    const field = await screen.findByLabelText(/pin/i);
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("inputmode", "numeric");
  });

  it("right_pin_unlocks", async () => {
    const fetchMock = show({ pin_set: true, unlocked: false });
    await enter();
    expect(await screen.findByText("secret content")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find((c) => c[0] === "/api/auth/pin")!;
    expect((call[1]!.headers as Record<string, string>)["X-Control-Action"]).toBe("1");
  });

  it("wrong_pin_says_so_and_clears", async () => {
    show({ pin_set: true, unlocked: false }, () => new Response("{}", { status: 401 }));
    await enter();
    expect(await screen.findByRole("alert")).toHaveTextContent(/wrong pin/i);
    expect(screen.getByLabelText(/pin/i)).toHaveValue("");
  });

  it("lockout_says_how_long", async () => {
    show(
      { pin_set: true, unlocked: false },
      () => new Response("{}", { status: 429, headers: { "Retry-After": "120" } }),
    );
    await enter();
    expect(await screen.findByRole("alert")).toHaveTextContent(/120 seconds/);
  });

  it("plain_http_points_to_the_secure_address", async () => {
    show({ pin_set: true, unlocked: false }, () => new Response("{}", { status: 400 }));
    await enter();
    expect(await screen.findByRole("alert")).toHaveTextContent(/https/i);
  });

  it("no_pin_set_explains_the_next_step", async () => {
    show({ pin_set: false, unlocked: false });
    expect(await screen.findByText(/adscontrol pin set/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("secret content")).not.toBeInTheDocument());
  });

  it("a_failed_status_check_says_so_instead_of_vanishing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <PinGate>
          <p>secret content</p>
        </PinGate>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/can.t check the pin/i);
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
  });
});

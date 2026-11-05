import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Layout } from "./Layout";

let posts: string[] = [];

function show(path: string, live: object, unlocked = false) {
  posts = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") !== "GET") {
        posts.push(url);
        unlocked = false;
        return new Response(null, { status: 204 });
      }
      if (url === "/api/auth/status") return new Response(JSON.stringify({ pin_set: true, unlocked }));
      return new Response(JSON.stringify(live));
    }),
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="*" element={<p>page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Layout", () => {
  it("marks the current page", () => {
    show("/energy", { rate_period: "off_peak", outdoor_f: null });
    expect(screen.getByRole("link", { name: "Energy" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("page")).toBeInTheDocument();
  });

  it("the weather is on the house picture, not the sidebar", async () => {
    show("/", { rate_period: "on_peak", outdoor_f: 68.4 });
    await screen.findByText("page");
    await new Promise((resolve) => setTimeout(resolve, 50)); // let any live fetch land
    expect(screen.queryByText(/°F/)).not.toBeInTheDocument();
  });

  it("an unlocked device can lock itself again", async () => {
    show("/", {}, true);
    fireEvent.click(await screen.findByRole("button", { name: "Lock" }));
    await waitFor(() => expect(posts).toEqual(["/api/auth/lock"]));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Lock" })).not.toBeInTheDocument());
  });

  it("a locked device shows no Lock button", async () => {
    show("/", {});
    await screen.findByText("page");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("button", { name: "Lock" })).not.toBeInTheDocument();
  });
});

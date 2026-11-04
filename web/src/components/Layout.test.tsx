import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Layout } from "./Layout";

function show(path: string, live: object) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(live))));
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

  it("shows outside temperature and rate", async () => {
    show("/", { rate_period: "on_peak", outdoor_f: 68.4 });
    expect(await screen.findByText("68°F outside")).toBeInTheDocument();
    expect(screen.getByText("On-peak")).toBeInTheDocument();
  });

  it("leaves out a missing outside temperature", async () => {
    show("/", { rate_period: "on_peak", outdoor_f: null });
    await screen.findByText("On-peak");
    expect(screen.queryByText(/outside/)).not.toBeInTheDocument();
  });
});

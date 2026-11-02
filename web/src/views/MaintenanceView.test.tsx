import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MaintenanceView } from "./MaintenanceView";

const TASKS = [
  {
    id: 1,
    name: "HVAC Filters",
    category: "House",
    notes: "14 x 25 x 1",
    interval_months: 3,
    items: [
      { id: 11, name: "Gym", last_done: "Aug 29, 2026" },
      { id: 12, name: "Living Room", last_done: "May 23, 2026" },
    ],
    last_done: "Aug 29, 2026",
    next_due: "2026-08-23",
    overdue: true,
  },
  {
    id: 2,
    name: "Fridge Filter",
    category: "House",
    notes: "",
    interval_months: null,
    items: [],
    last_done: "May 2026",
    next_due: null,
    overdue: false,
  },
];

type Call = { url: string; method: string; body: any; headers: any };
let calls: Call[];

function stub() {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "GET") return new Response(JSON.stringify({ tasks: TASKS }));
      calls.push({
        url,
        method,
        body: init?.body ? JSON.parse(init.body as string) : null,
        headers: init?.headers,
      });
      if (method === "DELETE") return new Response(null, { status: 204 });
      return new Response(JSON.stringify({ completion_ids: [501, 502] }));
    }),
  );
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MaintenanceView />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Node's own partial localStorage shadows jsdom's, so tests use a plain in-memory one.
function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    clear: () => values.clear(),
  };
}

beforeEach(() => {
  stub();
  vi.stubGlobal("localStorage", memoryStorage());
  localStorage.setItem("who", "Sam");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function row(name: string) {
  const heading = await screen.findByRole("heading", { name });
  return within(heading.closest("article")!);
}

describe("MaintenanceView", () => {
  it("one_tap_marks_done_and_shows_undo", async () => {
    show();
    fireEvent.click((await row("Fridge Filter")).getByRole("button", { name: /done today/i }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].url).toBe("/api/maintenance/2/complete");
    expect(calls[0].body.who).toBe("Sam");
    expect(calls[0].headers["X-Control-Action"]).toBe("1");
    fireEvent.click(await screen.findByRole("button", { name: /undo/i }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(2));
    expect(calls[1].url).toBe("/api/maintenance/completions/501");
  });

  it("undo_goes_away_after_10_seconds", async () => {
    show();
    fireEvent.click((await row("Fridge Filter")).getByRole("button", { name: /done today/i }));
    await screen.findByRole("button", { name: /undo/i });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10_100));
    });
    expect(screen.queryByRole("button", { name: /undo/i })).not.toBeInTheDocument();
  }, 15_000);

  it("undo_is_still_there_before_10_seconds", async () => {
    show();
    fireEvent.click((await row("Fridge Filter")).getByRole("button", { name: /done today/i }));
    await screen.findByRole("button", { name: /undo/i });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 500));
    });
    expect(screen.getByRole("button", { name: /undo/i })).toBeInTheDocument();
  });

  it("repeat_tap_says_already_recorded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_u: string, init?: RequestInit) =>
        (init?.method ?? "GET") === "GET"
          ? new Response(JSON.stringify({ tasks: TASKS }))
          : new Response(JSON.stringify({ completion_ids: [] })),
      ),
    );
    show();
    fireEvent.click((await row("Fridge Filter")).getByRole("button", { name: /done today/i }));
    expect(await screen.findByText(/already recorded/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /undo/i })).not.toBeInTheDocument();
  });

  it("rooms_can_be_partly_ticked", async () => {
    show();
    const hvac = await row("HVAC Filters");
    fireEvent.click(hvac.getByRole("checkbox", { name: /Gym/ }));
    fireEvent.click(hvac.getByRole("button", { name: /mark 1 room done/i }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body.item_ids).toEqual([11]);
  });

  it("room_task_cannot_be_saved_with_no_rooms_ticked", async () => {
    show();
    expect((await row("HVAC Filters")).getByRole("button", { name: /tick the rooms/i })).toBeDisabled();
  });

  it("asks_who_once_then_remembers", async () => {
    localStorage.clear();
    show();
    fireEvent.click(await screen.findByRole("button", { name: "John" }));
    expect(localStorage.getItem("who")).toBe("John");
    expect(screen.queryByRole("button", { name: "Sam" })).not.toBeInTheDocument();
    fireEvent.click((await row("Fridge Filter")).getByRole("button", { name: /done today/i }));
    await waitFor(() => expect(calls[0]?.body.who).toBe("John"));
  });

  it("works_when_localstorage_throws", async () => {
    const blocked = () => {
      throw new Error("blocked");
    };
    vi.stubGlobal("localStorage", { getItem: blocked, setItem: blocked });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "John" }));
    fireEvent.click((await row("Fridge Filter")).getByRole("button", { name: /done today/i }));
    await waitFor(() => expect(calls[0]?.body.who).toBe("John"));
  });

  it("overdue_sorts_first", async () => {
    show();
    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings[0]).toHaveTextContent("HVAC Filters");
    expect(screen.getByText(/overdue since Aug 23/i)).toBeInTheDocument();
  });

  it("date_can_be_changed_before_saving", async () => {
    show();
    const fridge = await row("Fridge Filter");
    fireEvent.change(fridge.getByLabelText(/date/i), { target: { value: "2026-10-31" } });
    fireEvent.click(fridge.getByRole("button", { name: /mark done/i }));
    await waitFor(() => expect(calls[0]?.body.done_on).toBe("2026-10-31"));
  });

  it("repeat_interval_can_be_set", async () => {
    show();
    const repeat = (await row("Fridge Filter")).getByLabelText(/repeat every/i);
    fireEvent.change(repeat, { target: { value: "6" } });
    fireEvent.blur(repeat);
    await waitFor(() => expect(calls[0]?.body).toEqual({ interval_months: 6 }));
    expect(calls[0].url).toBe("/api/maintenance/2");
  });

  it("repeat_interval_can_be_cleared", async () => {
    show();
    const repeat = (await row("HVAC Filters")).getByLabelText(/repeat every/i);
    fireEvent.change(repeat, { target: { value: "" } });
    fireEvent.blur(repeat);
    await waitFor(() => expect(calls[0]?.body).toEqual({ interval_months: null }));
  });

  it("unchanged_or_invalid_repeat_saves_nothing", async () => {
    show();
    const repeat = (await row("HVAC Filters")).getByLabelText(/repeat every/i);
    fireEvent.blur(repeat);
    fireEvent.change(repeat, { target: { value: "0" } });
    fireEvent.blur(repeat);
    expect(calls).toHaveLength(0);
  });

  it("failed_save_says_so", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_u: string, init?: RequestInit) =>
        (init?.method ?? "GET") === "GET"
          ? new Response(JSON.stringify({ tasks: TASKS }))
          : new Response("{}", { status: 500 }),
      ),
    );
    show();
    fireEvent.click((await row("Fridge Filter")).getByRole("button", { name: /done today/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not saved/i);
  });

  it("notes_are_shown", async () => {
    show();
    expect(await screen.findByText("14 x 25 x 1")).toBeInTheDocument();
  });
});

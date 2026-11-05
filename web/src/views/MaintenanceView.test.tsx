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
    repeat_every: 3,
    repeat_unit: "month",
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
    repeat_every: null,
    repeat_unit: "month",
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

  async function editor(name: string) {
    const card = await row(name);
    fireEvent.click(card.getByRole("button", { name: /^edit$/i }));
    return card;
  }

  it("repeat_interval_can_be_set", async () => {
    show();
    const card = await editor("Fridge Filter");
    fireEvent.change(card.getByLabelText(/repeat every/i), { target: { value: "6" } });
    fireEvent.click(card.getByRole("button", { name: /save changes/i }));
    await waitFor(() => expect(calls[0]?.body).toEqual({ repeat_every: 6 }));
    expect(calls[0].url).toBe("/api/maintenance/2");
    expect(calls[0].method).toBe("PATCH");
  });

  it("repeat_interval_can_be_cleared", async () => {
    show();
    const card = await editor("HVAC Filters");
    fireEvent.change(card.getByLabelText(/repeat every/i), { target: { value: "" } });
    fireEvent.click(card.getByRole("button", { name: /save changes/i }));
    await waitFor(() => expect(calls[0]?.body).toEqual({ repeat_every: null }));
  });

  it("the_repeat_can_be_in_weeks", async () => {
    show();
    const card = await editor("Fridge Filter");
    fireEvent.change(card.getByLabelText(/repeat unit/i), { target: { value: "week" } });
    fireEvent.click(card.getByRole("button", { name: /save changes/i }));
    await waitFor(() => expect(calls[0]?.body).toEqual({ repeat_unit: "week" }));
  });

  it("a_new_task_can_repeat_in_days", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: /add a task/i }));
    fireEvent.change(screen.getByLabelText(/task name/i), { target: { value: "Water plants" } });
    fireEvent.change(screen.getByLabelText(/new task category/i), { target: { value: "House" } });
    fireEvent.change(screen.getByLabelText(/^new task repeat$/i), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText(/new task repeat unit/i), { target: { value: "day" } });
    fireEvent.click(screen.getByRole("button", { name: /save task/i }));
    await waitFor(() => expect(calls[0]?.body).toMatchObject({ repeat_every: 3, repeat_unit: "day" }));
  });

  it("invalid_repeat_explains_and_saves_nothing", async () => {
    show();
    const card = await editor("HVAC Filters");
    fireEvent.change(card.getByLabelText(/repeat every/i), { target: { value: "0" } });
    fireEvent.click(card.getByRole("button", { name: /save changes/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/whole number/i);
    expect(calls).toHaveLength(0);
  });

  it("task_can_be_renamed_with_notes_and_category", async () => {
    show();
    const card = await editor("Fridge Filter");
    fireEvent.change(card.getByLabelText(/^name$/i), { target: { value: "Water Filter" } });
    fireEvent.change(card.getByLabelText(/category/i), { target: { value: "Kitchen" } });
    fireEvent.change(card.getByLabelText(/notes/i), { target: { value: "Part 123" } });
    fireEvent.click(card.getByRole("button", { name: /save changes/i }));
    await waitFor(() =>
      expect(calls[0]?.body).toEqual({ name: "Water Filter", category: "Kitchen", notes: "Part 123" }),
    );
  });

  it("blank_task_name_is_not_saved", async () => {
    show();
    const card = await editor("Fridge Filter");
    fireEvent.change(card.getByLabelText(/^name$/i), { target: { value: "  " } });
    fireEvent.click(card.getByRole("button", { name: /save changes/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/name/i);
    expect(calls).toHaveLength(0);
  });

  it("deleting_a_task_asks_first_and_keep_cancels", async () => {
    show();
    const card = await editor("Fridge Filter");
    fireEvent.click(card.getByRole("button", { name: /delete task/i }));
    expect(calls).toHaveLength(0);
    expect(card.getByText(/can.t be undone/i)).toBeInTheDocument();
    fireEvent.click(card.getByRole("button", { name: /keep it/i }));
    expect(calls).toHaveLength(0);
    fireEvent.click(card.getByRole("button", { name: /delete task/i }));
    fireEvent.click(card.getByRole("button", { name: /yes, delete/i }));
    await waitFor(() => expect(calls[0]?.method).toBe("DELETE"));
    expect(calls[0].url).toBe("/api/maintenance/2");
  });

  it("room_can_be_added", async () => {
    show();
    const card = await editor("HVAC Filters");
    fireEvent.change(card.getByLabelText(/new room/i), { target: { value: "Attic" } });
    fireEvent.click(card.getByRole("button", { name: /add room/i }));
    await waitFor(() => expect(calls[0]?.body).toEqual({ name: "Attic" }));
    expect(calls[0].url).toBe("/api/maintenance/1/items");
  });

  it("room_can_be_renamed", async () => {
    show();
    const card = await editor("HVAC Filters");
    const gym = card.getByLabelText("Room name: Gym");
    fireEvent.change(gym, { target: { value: "Home Gym" } });
    fireEvent.blur(gym);
    await waitFor(() => expect(calls[0]?.body).toEqual({ name: "Home Gym" }));
    expect(calls[0].url).toBe("/api/maintenance/items/11");
  });

  it("unchanged_or_blank_room_name_saves_nothing", async () => {
    show();
    const card = await editor("HVAC Filters");
    const gym = card.getByLabelText("Room name: Gym");
    fireEvent.blur(gym);
    fireEvent.change(gym, { target: { value: " " } });
    fireEvent.blur(gym);
    expect(calls).toHaveLength(0);
    expect(gym).toHaveValue("Gym");
  });

  it("removing_a_room_asks_first", async () => {
    show();
    const card = await editor("HVAC Filters");
    fireEvent.click(card.getByRole("button", { name: "Remove Gym" }));
    expect(calls).toHaveLength(0);
    fireEvent.click(card.getByRole("button", { name: /yes, remove/i }));
    await waitFor(() => expect(calls[0]?.method).toBe("DELETE"));
    expect(calls[0].url).toBe("/api/maintenance/items/11");
  });

  it("new_task_can_be_added_with_rooms", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: /add a task/i }));
    fireEvent.change(screen.getByLabelText(/task name/i), { target: { value: "Dryer Vent" } });
    fireEvent.change(screen.getByLabelText(/new task category/i), { target: { value: "House" } });
    fireEvent.change(screen.getByLabelText(/^new task repeat$/i), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText(/rooms, one per line/i), {
      target: { value: "Laundry\n\n  Roof  \n" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save task/i }));
    await waitFor(() => expect(calls[0]?.url).toBe("/api/maintenance"));
    expect(calls[0].body).toEqual({
      name: "Dryer Vent",
      category: "House",
      notes: "",
      repeat_every: 12,
      repeat_unit: "month",
      items: ["Laundry", "Roof"],
    });
  });

  it("duplicate_name_gets_a_clear_message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_u: string, init?: RequestInit) =>
        (init?.method ?? "GET") === "GET"
          ? new Response(JSON.stringify({ tasks: TASKS }))
          : new Response("{}", { status: 409 }),
      ),
    );
    show();
    fireEvent.click(await screen.findByRole("button", { name: /add a task/i }));
    fireEvent.change(screen.getByLabelText(/task name/i), { target: { value: "Fridge Filter" } });
    fireEvent.click(screen.getByRole("button", { name: /save task/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already used/i);
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

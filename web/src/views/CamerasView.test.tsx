import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CamerasView, LIVE_LIMIT_MS } from "./CamerasView";

const CAMERAS = [
  { id: 7, name: "Backyard camera", kind: "camera", last_event: "motion", last_event_at: "2026-11-02T19:14:00Z" },
  { id: 8, name: "Living Room Display", kind: "display", last_event: null, last_event_at: null },
];

const EVENTS = [
  { camera_id: 7, camera: "Backyard camera", type: "motion", occurred_at: "2026-11-02T19:14:00Z" },
];

class FakePeer {
  static made: FakePeer[] = [];
  closed = false;
  ontrack: ((e: unknown) => void) | null = null;
  constructor() {
    FakePeer.made.push(this);
  }
  addTransceiver = vi.fn();
  createDataChannel = vi.fn();
  createOffer = vi.fn(async () => ({ type: "offer", sdp: "offer-sdp" }));
  setLocalDescription = vi.fn(async () => {});
  setRemoteDescription = vi.fn(async () => {});
  close = vi.fn(() => {
    this.closed = true;
  });
}

let posts: { url: string; method: string; body: any }[];

function show({ unlocked = true, liveStatus = 200, feedStopped = null as object | null } = {}) {
  posts = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "GET") {
        if (url === "/api/auth/status") return new Response(JSON.stringify({ pin_set: true, unlocked }));
        if (url === "/api/traffic")
          return new Response(JSON.stringify({ cameras: [
            { nickname: "Pool Turtle", name: "SR 154 at SR 12", view: 24030, image_url: "https://511ga.org/map/Cctv/24030", home: true },
            { nickname: "QT Exit 2", name: "I-285 CCW", view: 21551, image_url: "https://511ga.org/map/Cctv/21551", home: false },
          ] }));
        if (url === "/api/cameras/events?limit=25") return new Response(JSON.stringify({ events: EVENTS, feed_stopped: feedStopped }));
        return new Response(JSON.stringify({ cameras: CAMERAS }));
      }
      posts.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : null });
      if (method === "DELETE") return new Response(null, { status: 204 });
      return new Response(
        JSON.stringify({ answer_sdp: "answer-sdp", expires_at: "t", media_session_id: "s1" }),
        { status: liveStatus },
      );
    }),
  );
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <CamerasView />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  FakePeer.made = [];
  vi.stubGlobal("RTCPeerConnection", FakePeer);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function card(name: string) {
  const heading = await screen.findByRole("heading", { name });
  return within(heading.closest("article")!);
}

describe("CamerasView", () => {
  it("shows_the_lock_state_in_the_title_line", async () => {
    show({ unlocked: false });
    const top = screen.getByRole("heading", { name: "Cameras" }).closest("header")!;
    expect(await within(top).findByText("Locked")).toBeInTheDocument();
  });

  it("shows_unlocked_in_the_title_line", async () => {
    show({ unlocked: true });
    const top = screen.getByRole("heading", { name: "Cameras" }).closest("header")!;
    expect(await within(top).findByText("Unlocked")).toBeInTheDocument();
  });

  it("locked_tile_prompts_for_pin", async () => {
    show({ unlocked: false });
    const backyard = await card("Backyard camera");
    expect(await screen.findByLabelText(/household pin/i)).toBeInTheDocument();
    expect(backyard.queryByRole("button", { name: /watch live/i })).not.toBeInTheDocument();
    expect(backyard.queryByRole("img")).not.toBeInTheDocument();
  });

  it("click_starts_live_only_on_click", async () => {
    show();
    const c = await card("Backyard camera");
    await c.findByRole("button", { name: /watch live/i });
    expect(FakePeer.made).toHaveLength(0);
    expect(posts).toHaveLength(0);
    fireEvent.click(c.getByRole("button", { name: /watch live/i }));
    await waitFor(() => expect(posts[0]?.url).toBe("/api/cameras/7/live"));
    expect(posts[0].body).toEqual({ offer_sdp: "offer-sdp" });
    const peer = FakePeer.made[0];
    await waitFor(() =>
      expect(peer.setRemoteDescription).toHaveBeenCalledWith({ type: "answer", sdp: "answer-sdp" }),
    );
    expect(peer.addTransceiver).toHaveBeenCalledWith("audio", { direction: "recvonly" });
    expect(peer.addTransceiver).toHaveBeenCalledWith("video", { direction: "recvonly" });
    expect(peer.createDataChannel).toHaveBeenCalled();
  });

  it("battery_stream_stops_at_5_minutes_and_offers_watch_again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    show();
    const c = await card("Backyard camera");
    fireEvent.click(await c.findByRole("button", { name: /watch live/i }));
    await waitFor(() => expect(FakePeer.made[0]?.setRemoteDescription).toHaveBeenCalled());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(LIVE_LIMIT_MS + 10);
    });
    expect(LIVE_LIMIT_MS).toBe(5 * 60 * 1000);
    expect(FakePeer.made[0].closed).toBe(true);
    await waitFor(() => expect(posts.some((p) => p.method === "DELETE" && p.url === "/api/cameras/7/live/s1")).toBe(true));
    expect(await c.findByRole("button", { name: /watch again/i })).toBeInTheDocument();
  });

  it("stop_ends_the_stream_early", async () => {
    show();
    const c = await card("Backyard camera");
    fireEvent.click(await c.findByRole("button", { name: /watch live/i }));
    fireEvent.click(await c.findByRole("button", { name: /^stop$/i }));
    await waitFor(() => expect(FakePeer.made[0].closed).toBe(true));
    await waitFor(() => expect(posts.some((p) => p.method === "DELETE")).toBe(true));
  });

  it("leaving_page_stops_stream", async () => {
    const view = show();
    const c = await card("Backyard camera");
    fireEvent.click(await c.findByRole("button", { name: /watch live/i }));
    await c.findByRole("button", { name: /^stop$/i });
    await waitFor(() => expect(FakePeer.made[0].setRemoteDescription).toHaveBeenCalled());
    view.unmount();
    expect(FakePeer.made[0].closed).toBe(true);
    await waitFor(() => expect(posts.some((p) => p.method === "DELETE")).toBe(true));
  });

  it("unavailable_camera_explains_and_closes", async () => {
    show({ liveStatus: 409 });
    const c = await card("Living Room Display");
    fireEvent.click(await c.findByRole("button", { name: /watch live/i }));
    expect(await c.findByRole("alert")).toHaveTextContent(/isn.t available/i);
    expect(FakePeer.made[0].closed).toBe(true);
    expect(c.getByRole("button", { name: /watch live/i })).toBeInTheDocument();
  });

  it("video_is_muted_with_controls_so_it_can_autoplay", async () => {
    show();
    const c = await card("Backyard camera");
    fireEvent.click(await c.findByRole("button", { name: /watch live/i }));
    const video = await c.findByTestId("live-video");
    expect((video as HTMLVideoElement).muted).toBe(true);
    expect(video).toHaveAttribute("controls");
  });

  it("lists_the_last_25_camera_events", async () => {
    show();
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).getByText("Motion")).toBeInTheDocument();
  });

  it("shows_every_traffic_camera_above_the_house_cameras", async () => {
    show({ unlocked: false });
    const turtle = await screen.findByRole("img", { name: /Pool Turtle/ });
    // traffic video is public, so it needs no PIN
    expect(within(turtle.closest("figure")!).getByRole("button", { name: /watch live/i })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /QT Exit 2/ })).toBeInTheDocument();
    const house = await screen.findByRole("heading", { name: "Backyard camera" });
    expect(turtle.compareDocumentPosition(house) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says when camera events have stopped arriving", async () => {
    show({ feedStopped: { since: "2026-11-02T19:14:00Z" } });
    expect(await screen.findByRole("status")).toHaveTextContent(/Not receiving camera events since .*:14/);
  });

  it("says nothing about the feed while it works", async () => {
    show();
    await screen.findByText("Last 25 camera events");
    expect(screen.queryByText(/Not receiving/)).not.toBeInTheDocument();
  });
});

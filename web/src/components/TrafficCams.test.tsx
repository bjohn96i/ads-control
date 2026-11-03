import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TrafficCams, withToken } from "./TrafficCams";

const players: FakeHls[] = [];
class FakeHls {
  static isSupported = () => true;
  loaded: string[] = [];
  destroyed = false;
  constructor(public config: { xhrSetup: (xhr: { open: (...a: unknown[]) => void }, url: string) => void }) {
    players.push(this);
  }
  loadSource(url: string) {
    this.loaded.push(url);
  }
  attachMedia() {}
  on() {}
  destroy() {
    this.destroyed = true;
  }
}
vi.mock("hls.js", () => ({ default: FakeHls }));

const STREAM = "https://sfs-msc-pub-lq-02.navigator.dot.ga.gov:443/rtplive/DEK-CCTV-0668/playlist.m3u8?token=";

const CAMS = [
  { nickname: "Pool Turtle", name: "SR 154 at SR 12", view: 24030, image_url: "https://511ga.org/map/Cctv/24030", home: true },
  { nickname: "QT Exit 2", name: "I-285 CCW at US278", view: 21551, image_url: "https://511ga.org/map/Cctv/21551", home: false },
];

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  players.length = 0;
});

function show(props: { linkTo?: string; live?: boolean } = {}) {
  render(
    <MemoryRouter>
      <TrafficCams cameras={CAMS} {...props} />
    </MemoryRouter>,
  );
}

describe("TrafficCams", () => {
  it("shows_each_picture_with_its_nickname", () => {
    show();
    const turtle = screen.getByRole("img", { name: /Pool Turtle/ });
    expect(turtle.getAttribute("src")).toMatch(/^https:\/\/511ga\.org\/map\/Cctv\/24030\?t=\d+$/);
    expect(screen.getByText("SR 154 at SR 12")).toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(2);
  });

  it("refreshes_the_pictures_every_minute", () => {
    vi.useFakeTimers();
    show();
    const before = screen.getByRole("img", { name: /Pool Turtle/ }).getAttribute("src");
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByRole("img", { name: /Pool Turtle/ }).getAttribute("src")).not.toBe(before);
  });

  it("can_link_each_tile_to_a_page", () => {
    show({ linkTo: "/cameras" });
    expect(screen.getAllByRole("link")[0]).toHaveAttribute("href", "/cameras");
  });

  it("token_is_swapped_into_every_stream_request", () => {
    expect(withToken("https://x.navigator.dot.ga.gov/a/chunk.m3u8?token=old", "new")).toBe(
      "https://x.navigator.dot.ga.gov/a/chunk.m3u8?token=new",
    );
    expect(withToken("https://x.navigator.dot.ga.gov/a/media_1.ts", "new")).toBe(
      "https://x.navigator.dot.ga.gov/a/media_1.ts?token=new",
    );
  });

  it("watch_live_plays_the_stream_and_keeps_its_token_fresh", async () => {
    let issued = 0;
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ url: `${STREAM}t${++issued}` })));
    vi.stubGlobal("fetch", fetcher);
    show({ live: true });
    expect(fetcher).not.toHaveBeenCalled(); // nothing streams until someone asks
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(screen.getAllByRole("button", { name: /watch live/i })[0]);
    await waitFor(() => expect(players).toHaveLength(1));
    expect(fetcher).toHaveBeenCalledWith("/api/traffic/24030/video");
    expect(players[0].loaded).toEqual([`${STREAM}t1`]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    const opened: unknown[][] = [];
    players[0].config.xhrSetup({ open: (...a) => opened.push(a) }, `${STREAM}t1`);
    expect(new URL(opened[0][1] as string).searchParams.get("token")).toBe("t2");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60_000);
    });
    expect(players[0].destroyed).toBe(true);
    expect(screen.getByRole("button", { name: /watch again/i })).toBeInTheDocument();
  });

  it("video_failure_says_so", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
    show({ live: true });
    fireEvent.click(screen.getAllByRole("button", { name: /watch live/i })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent(/video isn't available/i);
  });

  it("no_watch_button_unless_asked", () => {
    show();
    expect(screen.queryByRole("button", { name: /watch live/i })).not.toBeInTheDocument();
  });
});

import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TrafficCams } from "./TrafficCams";

const CAMS = [
  { nickname: "Pool Turtle", name: "SR 154 at SR 12", image_url: "https://511ga.org/map/Cctv/24030", home: true },
  { nickname: "QT Exit 2", name: "I-285 CCW at US278", image_url: "https://511ga.org/map/Cctv/21551", home: false },
];

afterEach(() => vi.useRealTimers());

function show(props: { linkTo?: string } = {}) {
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
});

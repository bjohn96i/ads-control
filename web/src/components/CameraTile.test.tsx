import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { CameraTile } from "./CameraTile";

const CAMERA = {
  id: 7,
  name: "Backyard camera",
  kind: "camera",
  last_event: "person",
  last_event_at: "2026-11-02T19:14:00Z",
  has_image: true,
  image_age_s: 3 * 3600,
};

function show(camera: object, unlocked: boolean) {
  render(
    <MemoryRouter>
      <CameraTile camera={{ ...CAMERA, ...camera }} unlocked={unlocked} />
    </MemoryRouter>,
  );
}

describe("CameraTile", () => {
  it("tile_shows_name_event_and_image_age", () => {
    show({}, true);
    expect(screen.getByText("Backyard camera")).toBeInTheDocument();
    expect(screen.getByText(/person/i)).toBeInTheDocument();
    expect(screen.getByText(/3 hrs ago/)).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("src", expect.stringContaining("/api/cameras/7/image"));
  });

  it("tile_without_image_shows_text_only", () => {
    show({ has_image: false, image_age_s: null }, true);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(/person/i)).toBeInTheDocument();
  });

  it("no_events_yet_says_so", () => {
    show({ has_image: false, image_age_s: null, last_event: null, last_event_at: null }, true);
    expect(screen.getByText(/no events yet/i)).toBeInTheDocument();
  });

  it("locked_tile_never_requests_the_image", () => {
    show({}, false);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(/person/i)).toBeInTheDocument();
  });

  it("doorbell_press_reads_naturally", () => {
    show({ last_event: "chime", kind: "doorbell" }, true);
    expect(screen.getByText(/doorbell rang/i)).toBeInTheDocument();
  });

  it("links_to_the_cameras_page", () => {
    show({}, true);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/cameras");
  });
});

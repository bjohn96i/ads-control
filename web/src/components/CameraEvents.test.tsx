import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CameraEventTable, eventText } from "./CameraEvents";

const CAMERA = {
  id: 7,
  name: "Backyard camera",
  kind: "camera",
  last_event: "person",
  last_event_at: "2026-11-02T19:14:00Z",
};

describe("eventText", () => {
  it("doorbell_press_reads_naturally", () => {
    expect(eventText({ ...CAMERA, last_event: "chime" })).toMatch(/^Doorbell rang, Nov 2/);
  });

  it("no_events_yet_says_so", () => {
    expect(eventText({ ...CAMERA, last_event: null, last_event_at: null })).toBe("No events yet");
  });
});

describe("CameraEventTable", () => {
  it("lists_time_camera_and_event_per_row", () => {
    render(
      <CameraEventTable
        events={[
          { camera_id: 2, camera: "Entryway doorbell", type: "chime", occurred_at: "2026-11-02T19:14:00Z" },
          { camera_id: 7, camera: "Backyard camera", type: "person", occurred_at: "2026-11-02T18:01:00Z" },
        ]}
      />,
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Entryway doorbell")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Doorbell rang")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/Nov 2.*2:14/)).toBeInTheDocument();
    expect(within(rows[1]).getByText("Person")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("empty_list_says_so", () => {
    render(<CameraEventTable events={[]} />);
    expect(screen.getByText(/no camera events yet/i)).toBeInTheDocument();
  });
});

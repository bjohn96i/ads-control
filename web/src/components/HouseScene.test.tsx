import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Live, LiveZone } from "../api/client";
import { groupRooms, HouseScene } from "./HouseScene";

const zone = (over: Partial<LiveZone>): LiveZone => ({
  id: 1,
  name: "Fridge/Stove",
  watts: 100,
  pin_x: 33,
  pin_y: 35,
  room: "Kitchen",
  floor: "1st floor",
  flagged: false,
  ...over,
});

const KITCHEN = [
  zone({ id: 2, name: "Fridge/Stove", watts: 100 }),
  zone({ id: 3, name: "Dishwasher", watts: 50 }),
];

function show(zones: LiveZone[]) {
  const live = { zones, whole_house_w: 1000, charger_estimate_w: 0 } as unknown as Live;
  render(
    <MemoryRouter>
      <HouseScene live={live} />
    </MemoryRouter>,
  );
}

describe("HouseScene", () => {
  it("groups kitchen circuits into one label", () => {
    const rooms = groupRooms(KITCHEN);
    expect(rooms).toHaveLength(1);
    expect(rooms[0]).toMatchObject({ name: "Kitchen", watts: 150, zoneId: 2 });
  });

  it("a room with a stopped circuit shows a dash", () => {
    show([KITCHEN[0], { ...KITCHEN[1], watts: null }]);
    const label = screen.getByRole("link", { name: /Kitchen/ });
    expect(label).toHaveTextContent(/^Kitchen—$/);
    expect(label).not.toHaveTextContent("0 W");
  });

  it("a flagged circuit flags its room", () => {
    show([
      zone({ id: 7, name: "Washer", room: "Laundry", flagged: true }),
      zone({ id: 4, name: "Dryer", room: "Laundry" }),
    ]);
    expect(screen.getByRole("link", { name: /Laundry/ })).toHaveClass("flag");
  });

  it("labels open energy for the biggest circuit", () => {
    show(KITCHEN);
    expect(screen.getByRole("link", { name: /Kitchen/ })).toHaveAttribute("href", "/energy?zone=2");
  });
});

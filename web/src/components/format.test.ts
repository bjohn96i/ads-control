import { describe, expect, it } from "vitest";
import { repeatText } from "./format";

describe("repeatText", () => {
  it("names the unit, singular for one", () => {
    expect(repeatText(1, "week")).toBe("Every week");
    expect(repeatText(1, "day")).toBe("Every day");
    expect(repeatText(10, "day")).toBe("Every 10 days");
    expect(repeatText(6, "month")).toBe("Every 6 months");
  });

  it("a one-off task doesn't repeat", () => {
    expect(repeatText(null, "month")).toBe("Doesn't repeat");
  });
});

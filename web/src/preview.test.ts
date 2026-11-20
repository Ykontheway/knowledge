import { describe, expect, it } from "vitest";
import { parseHashRoute } from "./management/route";
import { initialHash, isReplayPreview, previewRouteAllowed } from "./preview";

describe("explicit static replay preview build", () => {
  it("only activates for the replay build mode and preserves normal defaults", () => {
    expect(isReplayPreview("replay")).toBe(true);
    for (const mode of ["test", "development", "production"]) expect(isReplayPreview(mode)).toBe(false);
    expect(initialHash("", false)).toBe("#overview");
    expect(initialHash("", true)).toBe("#replay/guide");
    expect(initialHash("#trace", true)).toBe("#trace");
  });

  it.each(["#lifecycle", "#evaluation", "#guide", "#changes"])("blocks live and mutation route %s in the preview build", (hash) => {
    const route = parseHashRoute(hash);
    expect(previewRouteAllowed(route, true)).toBe(false);
    expect(previewRouteAllowed(route, false)).toBe(true);
  });

  it.each(["#replay", "#replay/guide", "#replay/evaluation", "#replay/lifecycle", "#overview", "#trace", "#diff"])("keeps explicit static route %s", (hash) => {
    expect(previewRouteAllowed(parseHashRoute(hash), true)).toBe(true);
  });
});

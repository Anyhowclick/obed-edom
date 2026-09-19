import { describe, expect, it } from "vitest";
import { MAPS_SAVE_STATUS_KEY, loadMapsSaveStatus, writeMapsSaveStatus } from "../src/maps/saveStatusStore";

describe("maps save-status sessionStorage", () => {
  it("round-trips a status for the same job", () => {
    writeMapsSaveStatus("job-1", "unsaved");
    expect(loadMapsSaveStatus("job-1")).toBe("unsaved");
    expect(JSON.parse(sessionStorage.getItem(MAPS_SAVE_STATUS_KEY) || "")).toEqual({
      jobId: "job-1",
      status: "unsaved",
    });
  });

  it("returns saved for a different job or bad payload", () => {
    writeMapsSaveStatus("job-1", "paused");
    expect(loadMapsSaveStatus("job-2")).toBe("saved");
    sessionStorage.setItem(MAPS_SAVE_STATUS_KEY, "{");
    expect(loadMapsSaveStatus("job-1")).toBe("saved");
  });
});

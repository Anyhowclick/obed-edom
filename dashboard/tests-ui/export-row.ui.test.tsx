import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderMapsTab } from "./renderMapsTab";
import { ExportDestinationRow } from "../src/components/ExportDestinationRow";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("MapsTab export row sits in the Export button's row", () => {
  it("shares an .actions ancestor with the Export button and renders Export to… as a collab button", async () => {
    await renderMapsTab();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });

    const exportTo = screen.getByRole("button", { name: "Export to…" });
    const exportBtn = screen.getByRole("button", { name: "Export" });

    expect(exportTo).toHaveClass("collab");
    expect(exportTo.closest(".actions")).not.toBeNull();
    expect(exportTo.closest(".actions")).toBe(exportBtn.closest(".actions"));
  });
});

describe("ExportDestinationRow default (non-inline) rendering", () => {
  it("still shows the Export to heading when inline is not passed", () => {
    render(<ExportDestinationRow value="" onChange={() => undefined} />);
    expect(screen.getByText("Export to")).toBeInTheDocument();
  });
});

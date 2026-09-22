import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoadingOverlay } from "../src/components/PreviewGrid";

describe("LoadingOverlay progress + elapsed + details", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the stage label, a ticking elapsed time, and collapsed technical details", () => {
    const startedAt = Math.floor(Date.now() / 1000) - 5;
    render(
      <LoadingOverlay
        title="Building the DSK deck…"
        logs={["Assembling Alpha_Wall_DSK.key…"]}
        progress={{ label: "Step 2 of 3 — Assembling the DSK deck", value: 1, max: 3 }}
        details={["opened archive", "wrote iwa"]}
        startedAt={startedAt}
      />
    );

    expect(screen.getByText("Step 2 of 3 — Assembling the DSK deck")).toBeInTheDocument();
    expect(screen.getByText(/^Elapsed 0:0[45]$/)).toBeInTheDocument();

    const details = screen.getByText("Technical details").closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText(/^Elapsed 0:0[56]$/)).toBeInTheDocument();
  });

  it("keeps prior behaviour when progress/details/startedAt are absent", () => {
    render(<LoadingOverlay title="Working…" logs={["a log line"]} />);

    expect(screen.queryByText(/Elapsed/)).toBeNull();
    expect(screen.queryByText("Technical details")).toBeNull();
    expect(screen.getByText("a log line")).toBeInTheDocument();
  });
});

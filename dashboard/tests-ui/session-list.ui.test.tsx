import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SessionList } from "../src/components/SessionList";
import { makeJob } from "./fakes/doc";

describe("SessionList status badge and delete button", () => {
  it("shows the feature-specific done label instead of the raw status, and keeps an icon-only delete button", () => {
    const job = makeJob({ id: "job-1", feature: "maps", status: "done" });
    render(<SessionList jobs={[job]} activeId={null} onSelect={() => undefined} onDelete={() => undefined} />);

    expect(screen.getByText("Exported")).toBeInTheDocument();
    expect(screen.queryByText("done")).not.toBeInTheDocument();

    const del = screen.getByRole("button", { name: `Delete ${job.name || job.id}` });
    expect(del.textContent).toBe("");
  });
});

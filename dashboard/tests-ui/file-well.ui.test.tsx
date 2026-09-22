import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FileWell } from "../src/components/FileWell";

describe("FileWell required + error", () => {
  it("has no aria-required on the choose button, and describes it by a required note and the error", () => {
    render(
      <FileWell
        label="DSK template (.key)"
        tone="dsk"
        hint="Required."
        required
        error="DSK template not found at /tmp/missing.key."
        onChoose={vi.fn()}
      />
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("DSK template not found at /tmp/missing.key.");

    const chooseButton = screen.getByRole("button", { name: "Choose on this Mac" });
    expect(chooseButton).not.toHaveAttribute("aria-required");
    const describedBy = chooseButton.getAttribute("aria-describedby")?.split(" ") || [];
    expect(describedBy).toContain(alert.id);
    expect(describedBy.some((id) => document.getElementById(id)?.textContent === "Required")).toBe(true);
  });

  it("renders no error or required semantics when the props are absent", () => {
    render(<FileWell label="Reference deck (optional)" tone="dsk" hint="Optional." onChoose={vi.fn()} />);

    expect(screen.queryByRole("alert")).toBeNull();
    const chooseButton = screen.getByRole("button", { name: "Choose on this Mac" });
    expect(chooseButton).not.toHaveAttribute("aria-required");
    expect(chooseButton).not.toHaveAttribute("aria-describedby");
  });
});

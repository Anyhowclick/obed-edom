import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { SlidingSeg } from "../src/maps/SlidingSeg";

const BOX: Record<string, { left: number; width: number }> = {
  a: { left: 3, width: 34 },
  b: { left: 40, width: 28 },
};

const leftDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetLeft");
const widthDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth");

function Harness({ initial = "a" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <SlidingSeg
      value={value}
      onChange={setValue}
      ariaLabel="Demo"
      options={[
        { id: "a", label: "Plan" },
        { id: "b", label: "Debug" },
      ]}
    />
  );
}

describe("SlidingSeg", () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "offsetLeft", {
      configurable: true,
      get() {
        const box = BOX[(this as HTMLElement).dataset.segOpt || ""];
        return box?.left ?? 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
      configurable: true,
      get() {
        const box = BOX[(this as HTMLElement).dataset.segOpt || ""];
        return box?.width ?? 0;
      },
    });
  });

  afterEach(() => {
    if (leftDesc) Object.defineProperty(HTMLElement.prototype, "offsetLeft", leftDesc);
    if (widthDesc) Object.defineProperty(HTMLElement.prototype, "offsetWidth", widthDesc);
  });

  it("snaps the pill to the active tab on first paint", () => {
    render(<Harness />);
    const pill = document.querySelector(".seg-slide-ind") as HTMLElement;
    expect(pill.style.transform).toBe("translateX(3px)");
    expect(pill.style.width).toBe("34px");
    expect(pill.style.visibility).toBe("visible");
    expect(pill.style.transition).toBe("");
  });

  it("writes the clicked tab's box so the CSS transition can tween", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("tab", { name: "Debug" }));
    const pill = document.querySelector(".seg-slide-ind") as HTMLElement;
    expect(pill.style.transform).toBe("translateX(40px)");
    expect(pill.style.width).toBe("28px");
    expect(pill.dataset.segId).toBe("b");
    expect(pill.style.transition).toBe("");
    expect(screen.getByRole("tab", { name: "Debug" })).toHaveAttribute("aria-selected", "true");
  });
});

import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderMapsTab } from "./renderMapsTab";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("sliding tab indicators", () => {
  it("the Countries|Regions indicator moves from 0 to 1 when Regions is clicked", async () => {
    await renderMapsTab();
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
    });

    const ind = document.querySelector(".seg-slide-ind") as HTMLElement;
    expect(ind.style.getPropertyValue("--seg-i")).toBe("0");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Regions" }));
    });

    expect(ind.style.getPropertyValue("--seg-i")).toBe("1");
  });

  it("the inspector-tab indicator reads 0 on Properties and 3 after clicking Export", async () => {
    await renderMapsTab();

    const ind = document.querySelector(".maps-insp-ind") as HTMLElement;
    expect(ind.style.getPropertyValue("--seg-i")).toBe("0");

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });

    expect(ind.style.getPropertyValue("--seg-i")).toBe("3");
  });
});

import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeCamera, makeDoc, makeJob, makeSlide } from "./fakes/doc";
import { renderMapsTab } from "./renderMapsTab";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("sliding tab indicators", () => {
  it("the Countries|Regions pill follows the active tab", async () => {
    await renderMapsTab();
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
    });

    const ind = document.querySelector(".seg-slide-ind") as HTMLElement;
    expect(ind.dataset.segId).toBe("countries");

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Regions" }));
    });

    expect(ind.dataset.segId).toBe("regions");
  });

  it("the LW|CG pill is measured and Merge CG sits outside it", async () => {
    const slide = makeSlide({
      cg: {
        camera: makeCamera(),
        style: "positron",
        highlights: [],
        churches: [],
      },
    });
    await renderMapsTab({ job: makeJob({ result: { ...makeDoc({ slides: [slide] }), stateRevision: 1 } }) });
    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
    });

    const pills = [...document.querySelectorAll(".seg-slide-ind")] as HTMLElement[];
    const audience = pills.find((el) => el.dataset.segId === "lw" || el.dataset.segId === "cg");
    expect(audience?.dataset.segId).toBe("lw");
    expect(audience?.closest(".seg-slide")?.textContent).not.toContain("Merge CG");
    expect(screen.getByRole("button", { name: "Merge CG" })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "CG" }));
    });

    expect(audience?.dataset.segId).toBe("cg");
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

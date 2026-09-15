import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderMapsTab } from "./renderMapsTab";

beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

async function openProperties() {
  await act(async () => {
    fireEvent.click(screen.getByRole("tab", { name: "Properties" }));
  });
}

describe("collapsible inspector sub-sections", () => {
  it("default open, with their bodies visible", async () => {
    await renderMapsTab();
    await openProperties();

    const head = screen.getByRole("button", { name: "Camera" });
    expect(head).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Latitude:").closest(".insp-sec-body")).not.toHaveAttribute("hidden");
  });

  it("clicking a section head collapses it and persists the choice to sessionStorage", async () => {
    await renderMapsTab();
    await openProperties();

    const head = screen.getByRole("button", { name: "Camera" });
    await act(async () => {
      fireEvent.click(head);
    });

    expect(head).toHaveAttribute("aria-expanded", "false");
    const body = screen.getByText("Latitude:").closest(".insp-sec-body");
    expect(body).toHaveAttribute("hidden");
    expect(body).not.toBeVisible();
    expect(sessionStorage.getItem("obed-edom.maps.section.camera")).toBe("0");
  });

  it("starts collapsed when the session key is pre-seeded", async () => {
    sessionStorage.setItem("obed-edom.maps.section.camera", "0");
    await renderMapsTab();
    await openProperties();

    const head = screen.getByRole("button", { name: "Camera" });
    expect(head).toHaveAttribute("aria-expanded", "false");
  });
});

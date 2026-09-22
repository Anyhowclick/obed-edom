import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FramingDecision } from "../src/api";
import { FramingReview, type FramingPage, type PlannedRect } from "../src/components/FramingReview";

// Full_Report_Card_Wall slide 58's shape: the planner carries slide 57's affine onto a photo-only
// backdrop (autoRects), which is NOT what pinning the same template slide would produce (the
// candidate). An unpinned page must preview the planner's own framing, not the candidate's.
const AUTO_RECT: PlannedRect = { role: "other", kind: "image", x: -1565, y: 100, w: 3840, h: 1080 };
const CANDIDATE_RECT: PlannedRect = { role: "other", kind: "image", x: -544, y: 0, w: 3840, h: 1080 };

function page(overrides: Partial<FramingPage> = {}): FramingPage {
  return {
    slide: 58,
    index: 57,
    thumb: null,
    autoTransform: { s: 0.5, tx: -100, ty: 0 },
    autoRects: [AUTO_RECT],
    autoTemplateSlide: 1,
    autoFellBack: false,
    needsAttention: false,
    noUsableFraming: false,
    candidates: [
      {
        templateSlide: 1,
        agreement: 1,
        fit: 0.9,
        wouldFallBack: false,
        pinOverridden: false,
        transform: { s: 0.5, tx: 0, ty: 0 },
        rects: [CANDIDATE_RECT],
      },
    ],
    ...overrides,
  };
}

function renderReview(p: FramingPage) {
  return render(
    <FramingReview
      proposal={{ pages: [p], destWidth: 1920, destHeight: 1080, wallWidth: 7680, wallHeight: 1080 }}
      jobId="job"
      busy={false}
      onSave={() => {}}
      onApply={() => {}}
    />
  );
}

function rectLefts(container: HTMLElement, width: number): number[] {
  const k = width / 1920;
  return Array.from(container.querySelectorAll<HTMLElement>(".plan-rect.role-other")).map(
    (el) => Math.round(parseFloat(el.style.left) / k)
  );
}

describe("framing review auto state", () => {
  it("previews the planner's own auto rects, not the same template slide's pinned candidate", () => {
    const { container } = renderReview(page());
    const chip = container.querySelector<HTMLElement>(".framing-chip")!;
    expect(rectLefts(chip, 104)).toEqual([AUTO_RECT.x]);

    fireEvent.click(screen.getByRole("button", { name: /Open pages/ }));
    const after = container.querySelector<HTMLElement>(".framing-after")!;
    const large = after.querySelector<HTMLElement>(".crop-preview")!;
    expect(rectLefts(large, 440)).toEqual([AUTO_RECT.x]);
  });

  it("previews the candidate once the operator clicks it", () => {
    const { container } = renderReview(page());
    fireEvent.click(screen.getByRole("button", { name: /Open pages/ }));
    fireEvent.click(container.querySelector<HTMLElement>(".framing-option")!);
    const large = container.querySelector<HTMLElement>(".framing-after .crop-preview")!;
    expect(rectLefts(large, 440)).toEqual([CANDIDATE_RECT.x]);
  });
});

describe("framing review overridden pin", () => {
  it("says plainly that the run will not use a pin the planner overrides", () => {
    const decision: FramingDecision = { wallIndex: 57, state: "pinned", templateSlide: 3 };
    const p = page({
      decision,
      candidates: [
        {
          templateSlide: 3,
          agreement: 0,
          fit: 0.2,
          wouldFallBack: false,
          pinOverridden: true,
          transform: { s: 0.5, tx: -100, ty: 0 },
          rects: [AUTO_RECT],
        },
      ],
    });
    const { container } = renderReview(p);
    fireEvent.click(screen.getByRole("button", { name: /^Reviewed/ }));
    expect(container.querySelector(".framing-chip")!.getAttribute("title")).toContain(
      "the run won't use this pin"
    );
    fireEvent.click(screen.getByRole("button", { name: /Open pages/ }));
    expect(screen.getByText(/The run won't use this pin: its framing would push the page off the frame/)).toBeTruthy();
    expect(screen.getByText(/The run will frame this slide automatically instead\./)).toBeTruthy();
    expect(screen.queryByText(/This framing applies cleanly/)).toBeNull();
  });

  it("keeps the clean note for a pin the run honours", () => {
    const decision: FramingDecision = { wallIndex: 57, state: "pinned", templateSlide: 1 };
    const { container } = renderReview(page({ decision }));
    fireEvent.click(screen.getByRole("button", { name: /^Reviewed/ }));
    expect(container.querySelector(".framing-chip")!.getAttribute("title")).not.toContain(
      "won't use this pin"
    );
    fireEvent.click(screen.getByRole("button", { name: /Open pages/ }));
    expect(screen.getByText(/This framing applies cleanly/)).toBeTruthy();
    expect(screen.queryByText(/won't use this pin/)).toBeNull();
  });
});

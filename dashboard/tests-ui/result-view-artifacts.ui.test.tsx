import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Job } from "../src/api";
import { ArtifactActions } from "../src/components/ArtifactActions";
import { GenerateResultView } from "../src/components/GenerateResultView";
import { InspectResultView } from "../src/components/InspectResultView";
import { makeJob } from "./fakes/doc";

const openPath = vi.fn(async (_path: string) => undefined);
const reveal = vi.fn(async (_path: string) => undefined);

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    openPath: (path: string) => openPath(path),
    reveal: (path: string) => reveal(path),
  };
});

function noText(root: HTMLElement, needle: string) {
  for (const el of root.querySelectorAll("*")) {
    expect(el.textContent || "").not.toContain(needle);
  }
}

describe("GenerateResultView artifact buttons", () => {
  it("shows Open buttons for lwKey/dskKey/cuedDocx/reviewPath and never prints the paths", () => {
    const outputDir = "/tmp/out/2026-09-12-run";
    const job: Job = makeJob({
      kind: "generate",
      feature: "generate",
      result: {
        stem: "wall",
        outputDir,
        lwKey: `${outputDir}/LW.key`,
        dskKey: `${outputDir}/DSK.key`,
        cuedDocx: `${outputDir}/cued.docx`,
        reviewPath: `${outputDir}/review.pdf`,
        previewFiles: { lw: [], dsk: [] },
        flags: [],
        lwCount: 3,
        dskCount: 2,
      },
    });

    const { container } = render(<GenerateResultView job={job} onOpen={vi.fn()} />);

    expect(screen.getByRole("button", { name: /Open LW\.key/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open DSK\.key/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open cued outline/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open review\.pdf/ })).toBeInTheDocument();
    noText(container, outputDir);
  });
});

describe("History resize case: ArtifactActions + InspectResultView", () => {
  it("shows an Open CG deck button and never prints the path", () => {
    const destPath = "/tmp/out/2026-09-12-run/CG.key";
    const job: Job = makeJob({
      kind: "resize",
      feature: "resize",
      result: { destPath, flags: [], previewFileNames: [] },
    });

    const { container } = render(
      <>
        <ArtifactActions artifacts={[{ label: "CG deck", path: destPath }]} />
        <InspectResultView job={job} onOpen={vi.fn()} />
      </>
    );

    expect(screen.getByRole("button", { name: /Open CG deck/ })).toBeInTheDocument();
    noText(container, destPath);
  });
});

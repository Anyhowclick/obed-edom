import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ArtifactActions } from "../src/components/ArtifactActions";
import { renderMapsTab } from "./renderMapsTab";
import { makeDoc, makeJob } from "./fakes/doc";

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

describe("ArtifactActions", () => {
  it("renders an Open button per artifact and one Show in enclosing folder button", async () => {
    render(
      <ArtifactActions
        artifacts={[
          { label: "LED wall", path: "/tmp/out/wall.key" },
          { label: "CG", path: "/tmp/out/cg.key" },
        ]}
      />
    );

    const openWall = screen.getByRole("button", { name: /Open LED wall/ });
    const openCg = screen.getByRole("button", { name: /Open CG/ });
    const reveal_ = screen.getByRole("button", { name: "Show in enclosing folder" });

    expect(openWall).toHaveAttribute("title", "/tmp/out/wall.key");
    expect(openCg).toHaveAttribute("title", "/tmp/out/cg.key");
    expect(reveal_).toHaveAttribute("title", "/tmp/out/wall.key");

    await act(async () => {
      fireEvent.click(openCg);
    });
    expect(openPath).toHaveBeenCalledWith("/tmp/out/cg.key");

    await act(async () => {
      fireEvent.click(reveal_);
    });
    expect(reveal).toHaveBeenCalledWith("/tmp/out/wall.key");
  });

  it("renders nothing when there are no artifacts", () => {
    const { container } = render(<ArtifactActions artifacts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("MapsTab export panel", () => {
  it("shows Open LED wall once the job is done with a destPath", async () => {
    const job = makeJob({
      status: "done",
      result: { ...makeDoc(), stateRevision: 1, destPath: "/tmp/out/wall.key" },
    });

    await renderMapsTab({ job });

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "Export" }));
    });

    expect(screen.getByRole("button", { name: /Open LED wall/ })).toBeInTheDocument();
  });
});

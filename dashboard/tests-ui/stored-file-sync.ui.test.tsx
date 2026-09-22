import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getSettings, putSettings } from "../src/api";
import { refreshStoredTemplates, useStoredTemplate } from "../src/prefs";

const emptySettings = {
  reuseThreshold: 0.6,
  reusePairings: true,
  reusePreviews: true,
  defaultExportDir: "",
  highlightColour: "#e8772a",
  lwTemplate: "",
  dskTemplate: "",
};

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    getSettings: vi.fn(async () => emptySettings),
    putSettings: vi.fn(async (next) => ({ ...emptySettings, ...next })),
  };
});

function Consumer({ label }: { label: string }) {
  const [file, setFile] = useStoredTemplate("dskTemplate");
  return (
    <div>
      <span data-testid={`${label}-value`}>{file?.name || "none"}</span>
      <button onClick={() => setFile({ path: "/tmp/a.key", name: "a.key" }).catch(() => undefined)}>{`${label}-choose`}</button>
      <button onClick={() => setFile(null).catch(() => undefined)}>{`${label}-clear`}</button>
    </div>
  );
}

beforeEach(() => {
  refreshStoredTemplates();
  vi.mocked(getSettings).mockReset();
  vi.mocked(putSettings).mockReset();
  vi.mocked(getSettings).mockResolvedValue(emptySettings);
  vi.mocked(putSettings).mockImplementation(async (next) => ({ ...emptySettings, ...next }));
});

describe("useStoredTemplate", () => {
  it("keeps two mounted subscribers in sync after choose and clear, with one settings fetch", async () => {
    render(
      <>
        <Consumer label="a" />
        <Consumer label="b" />
      </>
    );
    await act(async () => {});

    expect(getSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("a-value")).toHaveTextContent("none");
    expect(screen.getByTestId("b-value")).toHaveTextContent("none");

    await act(async () => {
      fireEvent.click(screen.getByText("a-choose"));
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("a.key");
    expect(screen.getByTestId("b-value")).toHaveTextContent("a.key");

    await act(async () => {
      fireEvent.click(screen.getByText("b-clear"));
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("none");
    expect(screen.getByTestId("b-value")).toHaveTextContent("none");
  });

  it("shows the remembered template to a subscriber that mounts while the fetch is in flight", async () => {
    let resolve!: (value: typeof emptySettings) => void;
    vi.mocked(getSettings).mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    render(<Consumer label="a" />);
    render(<Consumer label="b" />);

    await act(async () => {
      resolve({ ...emptySettings, dskTemplate: "/tmp/remembered.key" });
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("remembered.key");
    expect(screen.getByTestId("b-value")).toHaveTextContent("remembered.key");
  });

  it("keeps a template chosen while the first fetch is still in flight", async () => {
    let resolve!: (value: typeof emptySettings) => void;
    vi.mocked(getSettings).mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    render(<Consumer label="a" />);

    await act(async () => {
      fireEvent.click(screen.getByText("a-choose"));
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("a.key");

    await act(async () => {
      resolve({ ...emptySettings, dskTemplate: "" });
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("a.key");
  });

  it("keeps the fetched templates when the one-time legacy migration write fails", async () => {
    localStorage.setItem("obed-edom.generate.lwTemplate", JSON.stringify({ path: "/tmp/legacy-lw.key", name: "legacy-lw.key" }));
    vi.mocked(getSettings).mockResolvedValue({ ...emptySettings, dskTemplate: "/tmp/kept.key" });
    vi.mocked(putSettings).mockRejectedValueOnce(new Error("read-only"));
    render(<Consumer label="a" />);
    await act(async () => {});

    expect(screen.getByTestId("a-value")).toHaveTextContent("kept.key");
    expect(localStorage.getItem("obed-edom.generate.lwTemplate")).not.toBeNull();
  });

  it("rolls a failed save back to the previous value without blanking the other template", async () => {
    vi.mocked(getSettings).mockResolvedValue({ ...emptySettings, lwTemplate: "/tmp/lw.key", dskTemplate: "/tmp/old.key" });
    vi.mocked(putSettings).mockRejectedValueOnce(new Error("read-only"));
    function Lw() {
      const [file] = useStoredTemplate("lwTemplate");
      return <span data-testid="lw">{file?.name || "none"}</span>;
    }
    render(<><Consumer label="a" /><Lw /></>);
    await act(async () => {});

    await act(async () => {
      fireEvent.click(screen.getByText("a-choose"));
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("old.key");
    expect(screen.getByTestId("lw")).toHaveTextContent("lw.key");
  });
});

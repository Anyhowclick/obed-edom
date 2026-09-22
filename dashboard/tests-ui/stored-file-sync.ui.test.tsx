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

  it("rolls a failed write back to what the fetch found, leaving the other field alone", async () => {
    let resolveGet!: (value: typeof emptySettings) => void;
    vi.mocked(getSettings).mockReturnValueOnce(new Promise((r) => { resolveGet = r; }));
    let rejectPut!: (err: Error) => void;
    vi.mocked(putSettings).mockReturnValueOnce(new Promise((_r, rej) => { rejectPut = rej; }));
    function Lw() {
      const [file] = useStoredTemplate("lwTemplate");
      return <span data-testid="lw">{file?.name || "none"}</span>;
    }
    render(<><Consumer label="a" /><Lw /></>);

    await act(async () => {
      fireEvent.click(screen.getByText("a-choose"));
    });
    await act(async () => {
      resolveGet({ ...emptySettings, lwTemplate: "/tmp/lw.key", dskTemplate: "/tmp/old.key" });
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("a.key");
    expect(screen.getByTestId("lw")).toHaveTextContent("lw.key");

    await act(async () => {
      rejectPut(new Error("read-only"));
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("old.key");
    expect(screen.getByTestId("lw")).toHaveTextContent("lw.key");
  });

  it("a later write of the same field still lands after an earlier one fails", async () => {
    const puts: Array<{ resolve: (v: typeof emptySettings) => void; reject: (e: Error) => void }> = [];
    vi.mocked(putSettings).mockImplementation(
      () => new Promise((resolve, reject) => { puts.push({ resolve, reject }); })
    );
    render(<Consumer label="a" />);
    await act(async () => {});

    await act(async () => {
      fireEvent.click(screen.getByText("a-choose"));
    });
    await act(async () => {
      fireEvent.click(screen.getByText("a-clear"));
    });
    expect(puts).toHaveLength(1);

    await act(async () => {
      puts[0].reject(new Error("early failure"));
    });
    expect(puts).toHaveLength(2);
    await act(async () => {
      puts[1].resolve({ ...emptySettings, dskTemplate: "" });
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("none");
  });

  it("restores the value the fetch discovered when a write started before the fetch fails", async () => {
    let resolveGet!: (value: typeof emptySettings) => void;
    vi.mocked(getSettings).mockReturnValueOnce(new Promise((r) => { resolveGet = r; }));
    let rejectPut!: (err: Error) => void;
    vi.mocked(putSettings).mockReturnValueOnce(new Promise((_r, rej) => { rejectPut = rej; }));
    render(<Consumer label="a" />);

    await act(async () => {
      fireEvent.click(screen.getByText("a-choose"));
    });
    await act(async () => {
      resolveGet({ ...emptySettings, dskTemplate: "/tmp/old.key" });
    });
    await act(async () => {
      rejectPut(new Error("read-only"));
    });
    expect(screen.getByTestId("a-value")).toHaveTextContent("old.key");
  });

  it("does not let the legacy migration overwrite a field chosen while the fetch was in flight", async () => {
    localStorage.setItem("obed-edom.generate.dskTemplate", JSON.stringify({ path: "/tmp/legacy.key", name: "legacy.key" }));
    let resolveGet!: (value: typeof emptySettings) => void;
    vi.mocked(getSettings).mockReturnValueOnce(new Promise((r) => { resolveGet = r; }));
    render(<Consumer label="a" />);

    await act(async () => {
      fireEvent.click(screen.getByText("a-choose"));
    });
    await act(async () => {
      resolveGet(emptySettings);
    });
    await act(async () => {});

    expect(putSettings).toHaveBeenCalledTimes(1);
    expect(putSettings).toHaveBeenCalledWith({ dskTemplate: "/tmp/a.key" });
    expect(screen.getByTestId("a-value")).toHaveTextContent("a.key");
  });

  it("sends writes to settings.json one at a time, in order", async () => {
    const order: string[] = [];
    let release!: () => void;
    vi.mocked(putSettings).mockImplementationOnce(async (next) => {
      order.push("start:" + JSON.stringify(next));
      await new Promise<void>((r) => { release = r; });
      order.push("end:" + JSON.stringify(next));
      return { ...emptySettings, ...next };
    });
    vi.mocked(putSettings).mockImplementationOnce(async (next) => {
      order.push("start:" + JSON.stringify(next));
      order.push("end:" + JSON.stringify(next));
      return { ...emptySettings, ...next };
    });
    render(<Consumer label="a" />);
    await act(async () => {});

    await act(async () => {
      fireEvent.click(screen.getByText("a-choose"));
    });
    await act(async () => {
      fireEvent.click(screen.getByText("a-clear"));
    });
    expect(order).toEqual(['start:{"dskTemplate":"/tmp/a.key"}']);
    await act(async () => {
      release();
    });
    expect(order).toEqual([
      'start:{"dskTemplate":"/tmp/a.key"}',
      'end:{"dskTemplate":"/tmp/a.key"}',
      'start:{"dskTemplate":""}',
      'end:{"dskTemplate":""}',
    ]);
    expect(screen.getByTestId("a-value")).toHaveTextContent("none");
  });
});

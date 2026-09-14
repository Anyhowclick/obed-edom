import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsTab } from "../src/tabs/SettingsTab";
import { DEFAULT_HIGHLIGHT_COLOUR } from "../src/maps/highlight";
import type { Settings } from "../src/api";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    json: async () => body,
  } as unknown as Response;
}

const baseSettings: Settings = {
  reuseThreshold: 0.6,
  reusePairings: true,
  reusePreviews: true,
  defaultExportDir: "",
  highlightColour: "#e8772a",
};

describe("SettingsTab highlight colour", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        return jsonResponse({ ...baseSettings, ...body });
      }
      return jsonResponse(baseSettings);
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function renderSettings() {
    const utils = render(<SettingsTab />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    return utils;
  }

  it("persists the colour picker after a debounce, with a single PUT body", async () => {
    await renderSettings();
    const picker = screen.getByLabelText("Highlight colour") as HTMLInputElement;

    fireEvent.change(picker, { target: { value: "#123abc" } });
    fetchMock.mockClear();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(249);
    });
    expect(fetchMock).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    const putCall = fetchMock.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === "PUT");
    expect(putCall).toBeDefined();
    const body = JSON.parse(String((putCall![1] as RequestInit).body));
    expect(body.highlightColour).toBe("#123abc");
  });

  it("commits the colour picker on blur even without a prior debounce firing", async () => {
    await renderSettings();
    const picker = screen.getByLabelText("Highlight colour") as HTMLInputElement;

    fireEvent.change(picker, { target: { value: "#456def" } });
    fetchMock.mockClear();
    await act(async () => {
      fireEvent.blur(picker);
    });

    const putCall = fetchMock.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === "PUT");
    expect(putCall).toBeDefined();
    const body = JSON.parse(String((putCall![1] as RequestInit).body));
    expect(body.highlightColour).toBe("#456def");
  });

  it("normalises an invalid hex text entry to the default colour, not the previous value", async () => {
    await renderSettings();
    fetchMock.mockClear();
    await act(async () => {
      const putCall0 = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === "PUT");
      expect(putCall0).toBeUndefined();
    });

    const hexInput = screen.getByLabelText("Highlight colour hex") as HTMLInputElement;
    fireEvent.change(hexInput, { target: { value: "#0a84ff" } });
    fireEvent.blur(hexInput);
    await act(async () => {
      await Promise.resolve();
    });
    fetchMock.mockClear();

    fireEvent.change(hexInput, { target: { value: "not-a-colour" } });
    await act(async () => {
      fireEvent.blur(hexInput);
      await Promise.resolve();
    });

    const putCall = fetchMock.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === "PUT");
    expect(putCall).toBeDefined();
    const body = JSON.parse(String((putCall![1] as RequestInit).body));
    expect(body.highlightColour).toBe(DEFAULT_HIGHLIGHT_COLOUR);
    expect(hexInput.value).toBe(DEFAULT_HIGHLIGHT_COLOUR);
  });
});

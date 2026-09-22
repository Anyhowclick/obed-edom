import { afterEach, describe, expect, it, vi } from "vitest";
import { FieldError, startDsk } from "../src/api";

describe("startDsk", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the chosen DSK template as the dsk_template form field", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = init?.body as FormData;
      expect(body.get("dsk_template")).toBe("/tmp/template.key");
      return { ok: true, json: async () => ({ id: "job-1" }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    await startDsk("/tmp/fw.key", { dskTemplate: "/tmp/template.key" });

    expect(fetchMock).toHaveBeenCalledWith("/api/dsk", expect.objectContaining({ method: "POST" }));
  });

  it("throws a FieldError when the error response names the offending field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        statusText: "Bad Request",
        json: async () => ({ detail: { field: "dskTemplate", message: "Choose the DSK template (.key) to continue." } }),
      })) as unknown as typeof fetch
    );

    await expect(startDsk("/tmp/fw.key")).rejects.toBeInstanceOf(FieldError);
    await expect(startDsk("/tmp/fw.key")).rejects.toMatchObject({
      field: "dskTemplate",
      message: "Choose the DSK template (.key) to continue.",
    });
  });

  it("throws a plain message, not JSON, for a generic error detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        statusText: "Bad Request",
        json: async () => ({ detail: "Something went wrong" }),
      })) as unknown as typeof fetch
    );

    await expect(startDsk("/tmp/fw.key")).rejects.toThrow("Something went wrong");
  });
});

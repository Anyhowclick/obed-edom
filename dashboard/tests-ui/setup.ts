import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

class FakeResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  if (!URL.createObjectURL) URL.createObjectURL = vi.fn(() => "blob:fake");
  else vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake");
  if (!URL.revokeObjectURL) URL.revokeObjectURL = vi.fn();
  else vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  if (!window.matchMedia) {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

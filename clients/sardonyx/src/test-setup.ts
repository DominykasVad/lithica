import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { setCredentials } from "./api/client";

afterEach(() => {
  // what one test rendered, stored or logged in to is gone before the next
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
  setCredentials(null);
  document.documentElement.classList.remove("dark");
});

// What a browser has and jsdom has not, which the UI components (Radix)
// use: they only need it to be there.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};

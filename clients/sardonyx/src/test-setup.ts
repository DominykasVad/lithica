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
  scrollTo(0, 0);
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

// jsdom does not scroll. Here the window's scroll position is a number that
// scrollTo sets, followed by the scroll event a browser would send: what
// the router and the virtualised list read.
let scrolled = 0;
Object.defineProperty(window, "scrollY", { configurable: true, get: () => scrolled });
Object.defineProperty(window, "pageYOffset", {
  configurable: true,
  get: () => scrolled,
});
// Nor does it lay anything out: the page is taken as tall enough to be
// scrolled anywhere (what a scroll is limited to).
Object.defineProperty(document.documentElement, "scrollHeight", {
  configurable: true,
  get: () => 10_000_000,
});
window.scrollTo = ((first?: ScrollToOptions | number, second?: number) => {
  const top = typeof first === "object" ? first.top : second;
  if (typeof top === "number" && Number.isFinite(top)) {
    scrolled = Math.max(0, top);
  }
  // at the document, from where it reaches the window, as in a browser
  document.dispatchEvent(new Event("scroll", { bubbles: true }));
}) as typeof window.scrollTo;

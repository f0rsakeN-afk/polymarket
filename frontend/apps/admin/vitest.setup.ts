import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

class TestResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe() {
    this.callback(
      [
        {
          contentRect: { width: 600, height: 220, toJSON: () => ({}) } as DOMRectReadOnly,
          target: null as unknown as Element,
          borderBoxSize: [],
          contentBoxSize: [],
          devicePixelContentBoxSize: [],
        },
      ],
      this as unknown as ResizeObserver
    );
  }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = TestResizeObserver as unknown as typeof globalThis.ResizeObserver;

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// Base UI reads matchMedia during dialog setup.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

/**
 * jsdom has no `document.elementFromPoint`.
 *
 * `input-otp` calls it from a `setTimeout` to place a one-time-code paste badge,
 * and the timer fires *after* the test that rendered it has finished. The result
 * is an uncaught exception in a test file that passed — which fails the run and
 * blames the wrong file entirely, because the stack names a dependency's internal
 * hook rather than anything the test did.
 *
 * Returning the body is enough: the badge is a paste affordance, and no assertion
 * depends on where it lands.
 */
if (!document.elementFromPoint) {
  document.elementFromPoint = (() =>
    document.body) as unknown as typeof document.elementFromPoint;
}

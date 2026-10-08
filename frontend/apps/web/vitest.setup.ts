import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

// jsdom implements neither of these, and the visx chart needs a real
// measurement: ParentSize reports width 0 until ResizeObserver fires, and the
// chart renders null while innerWidth/innerHeight are <= 0.
const CHART_WIDTH = 600;
const CHART_HEIGHT = 220;

class TestResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe(target: Element) {
    // Fire on the next tick so React has mounted and the ref is attached.
    setTimeout(() => {
      this.callback(
        [
          {
            target,
            contentRect: {
              x: 0,
              y: 0,
              width: CHART_WIDTH,
              height: CHART_HEIGHT,
              top: 0,
              left: 0,
              right: CHART_WIDTH,
              bottom: CHART_HEIGHT,
              toJSON: () => ({}),
            } as DOMRectReadOnly,
          } as ResizeObserverEntry,
        ],
        this as unknown as ResizeObserver
      );
    }, 0);
  }
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver;

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
// getBBox is not in the DOM lib types, so reach it through a loose cast for
// both the read and the write.
const svgProto = SVGElement.prototype as unknown as Record<string, unknown>;
if (typeof svgProto.getBBox !== "function") {
  svgProto.getBBox = () => ({ x: 0, y: 0, width: 0, height: 0 });
}

// Base UI / Radix read matchMedia during theme + dialog setup.
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
import "@testing-library/jest-dom";

// Recharts' ResponsiveContainer relies on ResizeObserver, which jsdom does
// not implement. Stub it so chart-bearing components can mount in tests.
if (typeof window !== "undefined" && !window.ResizeObserver) {
  window.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

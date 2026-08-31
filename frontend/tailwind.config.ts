import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
        sans: [
          "var(--font-sans)",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
      },
      colors: {
        base: {
          950: "#0a0e14",
          900: "#0d1117",
          850: "#111823",
          800: "#151d2b",
          700: "#1c2636",
          600: "#28344a",
          500: "#3a4a66",
          400: "#5b6b85",
          300: "#8593a8",
          200: "#b4bfcf",
          100: "#dbe2ec",
          50: "#f0f3f8",
        },
        accent: {
          DEFAULT: "#22d3ee",
          dim: "#0e7490",
        },
        ok: "#34d399",
        warn: "#fbbf24",
        err: "#f87171",
        crit: "#fb7185",
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.03) inset",
      },
    },
  },
  plugins: [],
};

export default config;

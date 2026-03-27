import type { Config } from "tailwindcss";

// Obsidian Design System
// Background       : #0b0b0e
// Surface          : #101015
// Surface Elevated : #16161e
// Border           : #1c1c24
// Border Subtle    : rgba(255,255,255,0.06)
// Accent           : #9580c4
// Accent Dim       : rgba(149,128,196,0.15)
// Accent Glow      : rgba(149,128,196,0.35)
// Text             : #e0dde6
// Muted            : #8a8694

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        black: "#0b0b0e",
        white: "#e0dde6",
        // Semantic Obsidian tokens
        obsidian: {
          bg:                 "#0b0b0e",
          surface:            "#101015",
          "surface-elevated": "#16161e",
          border:             "#1c1c24",
          "border-subtle":    "rgba(255,255,255,0.06)",
          accent:             "#9580c4",
          "accent-dim":       "rgba(149,128,196,0.15)",
          "accent-glow":      "rgba(149,128,196,0.35)",
          text:               "#e0dde6",
          muted:              "#8a8694",
        },
        // Strict obsidian scale — keeps all slate-* classNames working
        slate: {
          50:  "#e0dde6",
          100: "#e0dde6",
          200: "#e0dde6",
          300: "#8a8694",
          400: "#8a8694",
          500: "#8a8694",
          600: "#8a8694",
          700: "#1c1c24",
          800: "#1c1c24",
          900: "#101015",
          950: "#0b0b0e",
        },
        // Remap sky → accent
        sky: {
          50: "#9580c4", 100: "#9580c4", 200: "#9580c4", 300: "#9580c4",
          400: "#9580c4", 500: "#9580c4", 600: "#9580c4", 700: "#9580c4",
          800: "#9580c4", 900: "#9580c4", 950: "#9580c4",
        },
        // Remap emerald → accent
        emerald: {
          50: "#9580c4", 100: "#9580c4", 200: "#9580c4", 300: "#9580c4",
          400: "#9580c4", 500: "#9580c4", 600: "#9580c4", 700: "#9580c4",
          800: "#9580c4", 900: "#9580c4", 950: "#9580c4",
        },
        // Keep rose for danger states (actual red spectrum)
        rose: {
          50:  "#fff1f2", 100: "#ffe4e6", 200: "#fecdd3", 300: "#fda4af",
          400: "#fb7185", 500: "#f43f5e", 600: "#e11d48", 700: "#be123c",
          800: "#9f1239", 900: "#881337", 950: "#4c0519",
        },
        // Red for danger (used by ErrorBanner, danger Button)
        red: {
          50:  "#fef2f2", 100: "#fee2e2", 200: "#fecaca", 300: "#fca5a5",
          400: "#f87171", 500: "#ef4444", 600: "#dc2626", 700: "#b91c1c",
          800: "#991b1b", 900: "#7f1d1d", 950: "#450a0a",
        },
        // Green for success states
        green: {
          50:  "#f0fdf4", 100: "#dcfce7", 200: "#bbf7d0", 300: "#86efac",
          400: "#4ade80", 500: "#22c55e", 600: "#16a34a", 700: "#15803d",
          800: "#166534", 900: "#14532d", 950: "#052e16",
        },
      },
      fontFamily: {
        display: ['"Cal Sans"', '"Geist"', "sans-serif"],
        sans:    ['"Geist"', "system-ui", "-apple-system", "sans-serif"],
        mono:    ['"Geist Mono"', "ui-monospace", "Menlo", "monospace"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "1rem" }],
      },
      boxShadow: {
        soft:        "0 6px 18px rgba(11,11,14,0.6)",
        accent:      "0 0 0 3px rgba(149,128,196,0.35)",
        "accent-lg": "0 8px 32px rgba(149,128,196,0.25)",
        surface:     "0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3)",
      },
      borderRadius: {
        xl:    "0.75rem",
        "2xl": "1rem",
        "3xl": "1.25rem",
      },
      transitionDuration: {
        DEFAULT: "150ms",
      },
      transitionTimingFunction: {
        DEFAULT: "cubic-bezier(0.4, 0, 0.2, 1)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.96)" },
          to:   { opacity: "1", transform: "scale(1)" },
        },
        spin: {
          from: { transform: "rotate(0deg)" },
          to:   { transform: "rotate(360deg)" },
        },
        "letter-breathe": {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0.45" },
        },
        "halo-pulse": {
          "0%":   { boxShadow: "0 0 0 0px rgba(255,255,255,0.8), 0 0 0 0px rgba(255,255,255,0.4)" },
          "20%":  { boxShadow: "0 0 0 3px rgba(255,255,255,0.5), 0 0 0 7px rgba(255,255,255,0.2)" },
          "100%": { boxShadow: "0 0 0 10px rgba(255,255,255,0), 0 0 0 18px rgba(255,255,255,0)" },
        },
        "shimmer": {
          "0%":   { backgroundPosition: "100% center" },
          "100%": { backgroundPosition: "0% center" },
        },
        "dot-blink": {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0.2" },
        },
      },
      animation: {
        "fade-in":  "fade-in 150ms cubic-bezier(0.4, 0, 0.2, 1)",
        "scale-in": "scale-in 150ms cubic-bezier(0.4, 0, 0.2, 1)",
        spin:       "spin 700ms linear infinite",
        "letter-breathe": "letter-breathe 2.8s ease-in-out infinite",
        "halo-pulse":     "halo-pulse 2s ease-out infinite",
        "shimmer":        "shimmer 2.5s linear infinite",
        "dot-blink":      "dot-blink 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;

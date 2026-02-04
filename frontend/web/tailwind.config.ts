import type { Config } from "tailwindcss";

// Obsidian theme tokens (strict)
// Background : #0b0b0e
// Surface    : #101015
// Border     : #1c1c24
// Accent     : #9580c4
// Text       : #e0dde6
// Muted      : #8a8694

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        black: "#0b0b0e",
        white: "#e0dde6",
        // Strict obsidian scale: only uses the six tokens above.
        slate: {
          50: "#e0dde6",
          100: "#e0dde6",
          200: "#e0dde6",
          300: "#8a8694",
          400: "#8a8694",
          500: "#8a8694",
          600: "#8a8694",
          700: "#1c1c24",
          800: "#1c1c24",
          900: "#101015",
          950: "#0b0b0e"
        },
        // Remap sky -> accent for all sky-* classes (links, badges, etc.)
        sky: {
          50: "#9580c4",
          100: "#9580c4",
          200: "#9580c4",
          300: "#9580c4",
          400: "#9580c4",
          500: "#9580c4",
          600: "#9580c4",
          700: "#9580c4",
          800: "#9580c4",
          900: "#9580c4",
          950: "#9580c4"
        },
        // Remap emerald -> accent for all emerald-* classes (progress, chips, etc.)
        emerald: {
          50: "#9580c4",
          100: "#9580c4",
          200: "#9580c4",
          300: "#9580c4",
          400: "#9580c4",
          500: "#9580c4",
          600: "#9580c4",
          700: "#9580c4",
          800: "#9580c4",
          900: "#9580c4",
          950: "#9580c4"
        },
        // Remap rose -> accent so status/danger styles stay within the palette
        rose: {
          50: "#9580c4",
          100: "#9580c4",
          200: "#9580c4",
          300: "#9580c4",
          400: "#9580c4",
          500: "#9580c4",
          600: "#9580c4",
          700: "#9580c4",
          800: "#9580c4",
          900: "#9580c4",
          950: "#9580c4"
        }
      },
      boxShadow: {
        soft: "0 6px 18px rgba(11,11,14,0.6)"
      },
      borderRadius: {
        xl: "8px"
      },
      fontFamily: {
        sans: ["\"Space Grotesk\"", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["\"JetBrains Mono\"", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"]
      }
    }
  },
  plugins: []
} satisfies Config;

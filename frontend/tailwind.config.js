/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Semantic theme tokens. Values are RGB triplets defined in src/index.css
        // and flipped by the `.dark` class, so every utility below (including
        // opacity modifiers like text-muted/70) adapts to both themes.
        page: "rgb(var(--bg) / <alpha-value>)",
        band: "rgb(var(--band) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        raised: "rgb(var(--raised) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        faint: "rgb(var(--faint) / <alpha-value>)",
        hairline: "rgb(var(--hairline) / <alpha-value>)",
        "hairline-strong": "rgb(var(--hairline-strong) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        "accent-vivid": "rgb(var(--accent-vivid) / <alpha-value>)",
        "on-accent": "rgb(var(--on-accent) / <alpha-value>)",
        // Fixed brand palette (theme-independent identity colors).
        brand: {
          black: "#0b0c10",
          dark: "#1f2833",
          red: "#e63946",
          accent: "#ff4d5a",
          white: "#f8f9fa",
        },
      },
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "system-ui", "sans-serif"],
        display: ['"Space Grotesk Variable"', "Space Grotesk", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono Variable"', "JetBrains Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgb(var(--ink) / 0.04), 0 8px 24px rgb(var(--ink) / 0.05)",
        pop: "0 16px 48px rgb(var(--ink) / 0.12)",
      },
    },
  },
  plugins: [],
};

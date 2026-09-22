import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      screens: {
        mobile: "390px",
      },
      fontFamily: {
        sans: ["var(--font-poppins)", "Poppins", "sans-serif"],
        serif: ["var(--font-instrument-serif)", "Instrument Serif", "serif"],
      },
      colors: {
        brand: {
          dark: "#2b2b2b",
          darker: "#2c2c2e",
          gold: "#e8a910",
          yellow: "#fcd34d",
          purple: "#d8b4fe",
        },
      },
      maxWidth: {
        mobile: "390px",
      },
    },
  },
  plugins: [],
};

export default config;

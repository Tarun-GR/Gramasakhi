/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      fontFamily: {
        sans: ["var(--font-vietnam)", "Plus Jakarta Sans", "Noto Sans Kannada", "system-ui", "sans-serif"],
        display: ["Bebas Neue", "Plus Jakarta Sans", "sans-serif"],
      },
      colors: {
        gs: {
          forest: "var(--gs-forest)",
          rainforest: "var(--gs-rainforest)",
          teal: "var(--gs-teal)",
          paddy: "var(--gs-paddy)",
          leaf: "var(--gs-leaf)",
          rice: "var(--gs-rice)",
          stone: "var(--gs-stone)",
          mist: "var(--gs-mist)",
          cream: "var(--gs-cream)",
          "rain-white": "var(--gs-rain-white)",
          terracotta: "var(--gs-terracotta)",
          coconut: "var(--gs-coconut)",
        },
        primary: {
          DEFAULT: "var(--gs-primary)",
          foreground: "var(--gs-on-primary)",
          container: "var(--gs-primary-container)",
          "on-container": "var(--gs-on-primary-container)",
          fixed: "var(--gs-primary-fixed)",
          "fixed-dim": "var(--gs-primary-fixed-dim)",
        },
        secondary: {
          DEFAULT: "var(--gs-secondary)",
          foreground: "var(--gs-on-secondary)",
          container: "var(--gs-secondary-container)",
          "on-container": "var(--gs-on-secondary-container)",
          fixed: "var(--gs-secondary-fixed)",
          "fixed-dim": "var(--gs-secondary-fixed-dim)",
        },
        tertiary: {
          DEFAULT: "var(--gs-tertiary)",
          foreground: "var(--gs-on-tertiary)",
          container: "var(--gs-tertiary-container)",
          "on-container": "var(--gs-on-tertiary-container)",
          fixed: "var(--gs-tertiary-fixed)",
          "fixed-dim": "var(--gs-tertiary-fixed-dim)",
        },
        surface: {
          DEFAULT: "var(--gs-surface)",
          dim: "var(--gs-surface-dim)",
          bright: "var(--gs-surface-bright)",
          container: "var(--gs-surface-container)",
          "container-low": "var(--gs-surface-container-low)",
          "container-high": "var(--gs-surface-container-high)",
          "container-highest": "var(--gs-surface-container-highest)",
          "container-lowest": "var(--gs-surface-container-lowest)",
          variant: "var(--gs-surface-variant)",
          tint: "var(--gs-surface-tint)",
        },
        background: "var(--gs-background)",
        foreground: "var(--gs-on-background)",
        error: {
          DEFAULT: "var(--gs-error)",
          container: "var(--gs-error-container)",
          "on-container": "var(--gs-on-error-container)",
        },
        outline: {
          DEFAULT: "var(--gs-outline)",
          variant: "var(--gs-outline-variant)",
        },
        border: "var(--gs-outline-variant)",
        "on-background": "var(--gs-on-background)",
        "on-surface": "var(--gs-on-surface)",
        "on-surface-variant": "var(--gs-on-surface-variant)",
        "on-primary": "var(--gs-on-primary)",
        "on-primary-container": "var(--gs-on-primary-container)",
        "on-secondary-container": "var(--gs-on-secondary-container)",
        "on-tertiary-fixed": "var(--gs-on-tertiary-fixed)",
        "on-error-container": "var(--gs-on-error-container)",
        /* Legacy auth/admin tokens (HSL) */
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        ring: "hsl(var(--ring))",
        input: "hsl(var(--input))",
      },
      borderRadius: {
        DEFAULT: "1rem",
        sm: "0.5rem",
        md: "1.5rem",
        lg: "2rem",
        xl: "3rem",
      },
      spacing: {
        "margin-mobile": "20px",
        "margin-desktop": "64px",
        gutter: "16px",
      },
      boxShadow: {
        ambient: "0px 4px 20px rgba(31, 59, 46, 0.08)",
        "ambient-lg": "0px 10px 30px rgba(31, 59, 46, 0.12)",
      },
      keyframes: {
        fadeIn: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        fadeIn: "fadeIn 0.25s ease-out",
      },
    },
  },
  plugins: [],
};

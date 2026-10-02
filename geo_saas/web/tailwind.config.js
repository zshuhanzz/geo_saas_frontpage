/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    './index.html',
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        sans: ['Inter', 'Noto Sans SC', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'glow-sm': 'var(--primary-glow)',
        'glow': '0 0 30px rgba(46, 232, 158, 0.15)',
        'glow-md': '0 0 24px rgba(0, 230, 118, 0.2)',
        'glow-lg': '0 0 50px rgba(46, 232, 158, 0.2)',
        'card-hover': '0 8px 30px rgba(0, 0, 0, 0.08)',
        'card-hover-dark': '0 8px 40px rgba(0, 0, 0, 0.5), 0 0 20px rgba(0, 230, 118, 0.06)',
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
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
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(16px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in-scale": {
          from: { opacity: "0", transform: "scale(0.95)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        "shimmer": {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "pulse-glow": {
          "0%, 100%": { boxShadow: "0 0 20px rgba(46, 232, 158, 0.1)" },
          "50%": { boxShadow: "0 0 30px rgba(46, 232, 158, 0.25)" },
        },
        "gradientFlow": {
          "0%": { backgroundPosition: "0% center" },
          "50%": { backgroundPosition: "100% center" },
          "100%": { backgroundPosition: "0% center" },
        },
        "borderRotate": {
          "0%": { backgroundPosition: "0% 50%" },
          "100%": { backgroundPosition: "400% 50%" },
        },
        "aurora-float": {
          "0%, 100%": { transform: "translateY(0) scale(1)" },
          "50%": { transform: "translateY(-20px) scale(1.05)" },
        },
        "beam-pulse": {
          "0%, 100%": { opacity: "0.3", height: "30vh" },
          "50%": { opacity: "0.7", height: "45vh" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-in": "fade-in 0.3s ease-out",
        "fade-up": "fade-up 0.5s ease-out both",
        "fade-in-scale": "fade-in-scale 0.2s ease-out",
        "shimmer": "shimmer 2s linear infinite",
        "pulse-glow": "pulse-glow 3s ease-in-out infinite",
        "gradient-flow": "gradientFlow 5s ease-in-out infinite",
        "border-rotate": "borderRotate 4s linear infinite",
        "aurora": "aurora-float 10s ease-in-out infinite",
        "beam": "beam-pulse 3s ease-in-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate"), require("@tailwindcss/typography")],
}

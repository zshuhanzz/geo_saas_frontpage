/** @type {import('tailwindcss').Config} */
export default {
	content: [
		"./index.html",
		"./src/**/*.{js,ts,jsx,tsx}",
	],
	darkMode: ["class"],
	theme: {
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
				primary: {
					'50': '#ecfdf5',
					'100': '#d1fae5',
					'200': '#a7f3d0',
					'300': '#6ee7b7',
					'400': '#34d399',
					'500': '#2EE89E',
					'600': '#3AB575',
					'700': '#059669',
					'800': '#047857',
					'900': '#065f46',
					DEFAULT: 'hsl(var(--primary))',
					foreground: 'hsl(var(--primary-foreground))'
				},
				dark: {
					'50': '#f7f7f8',
					'100': '#eeeef0',
					'200': '#d9d9de',
					'300': '#b8b9c1',
					'400': '#92939f',
					'500': '#747584',
					'600': '#5e5f6c',
					'700': '#4d4e58',
					'800': '#42434b',
					'900': '#1a1b23',
					'950': '#0d0e14'
				},
				background: 'hsl(var(--background))',
				foreground: 'hsl(var(--foreground))',
				card: {
					DEFAULT: 'hsl(var(--card))',
					foreground: 'hsl(var(--card-foreground))'
				},
				popover: {
					DEFAULT: 'hsl(var(--popover))',
					foreground: 'hsl(var(--popover-foreground))'
				},
				secondary: {
					DEFAULT: 'hsl(var(--secondary))',
					foreground: 'hsl(var(--secondary-foreground))'
				},
				muted: {
					DEFAULT: 'hsl(var(--muted))',
					foreground: 'hsl(var(--muted-foreground))'
				},
				accent: {
					DEFAULT: 'hsl(var(--accent))',
					foreground: 'hsl(var(--accent-foreground))'
				},
				destructive: {
					DEFAULT: 'hsl(var(--destructive))',
					foreground: 'hsl(var(--destructive-foreground))'
				},
				border: 'hsl(var(--border))',
				input: 'hsl(var(--input))',
				ring: 'hsl(var(--ring))',
				chart: {
					'1': 'hsl(var(--chart-1))',
					'2': 'hsl(var(--chart-2))',
					'3': 'hsl(var(--chart-3))',
					'4': 'hsl(var(--chart-4))',
					'5': 'hsl(var(--chart-5))'
				}
			},
			keyframes: {
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
			},
			animation: {
				'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
				"fade-in": "fade-in 0.3s ease-out",
				"fade-up": "fade-up 0.5s ease-out both",
				"fade-in-scale": "fade-in-scale 0.2s ease-out",
				"shimmer": "shimmer 2s linear infinite",
				"pulse-glow": "pulse-glow 3s ease-in-out infinite",
				"gradient-flow": "gradientFlow 5s ease-in-out infinite",
				"border-rotate": "borderRotate 4s linear infinite",
				"aurora": "aurora-float 10s ease-in-out infinite",
			},
			borderRadius: {
				lg: 'var(--radius)',
				md: 'calc(var(--radius) - 2px)',
				sm: 'calc(var(--radius) - 4px)'
			}
		}
	},
	plugins: [require("tailwindcss-animate")],
}

/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    darkMode: 'class',
    theme: {
        extend: {
            colors: {
                // AnswerX Brand Green Colors (from logo)
                primary: {
                    50: '#ecfdf5',
                    100: '#d1fae5',
                    200: '#a7f3d0',
                    300: '#6ee7b7',
                    400: '#34d399',
                    500: '#2EE89E',   // Logo bright green
                    600: '#3AB575',   // Logo dark green
                    700: '#059669',
                    800: '#047857',
                    900: '#065f46',
                },
                dark: {
                    50: '#f7f7f8',
                    100: '#eeeef0',
                    200: '#d9d9de',
                    300: '#b8b9c1',
                    400: '#92939f',
                    500: '#747584',
                    600: '#5e5f6c',
                    700: '#4d4e58',
                    800: '#42434b',
                    900: '#1a1b23',
                    950: '#0d0e14',
                }
            },
            animation: {
                'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
            }
        },
    },
    plugins: [],
}

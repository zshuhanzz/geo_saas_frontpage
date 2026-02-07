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
                // Custom dark theme colors inspired by Profound
                primary: {
                    50: '#f0f5ff',
                    100: '#e0ebff',
                    200: '#c7d9ff',
                    300: '#a3bfff',
                    400: '#7a9cff',
                    500: '#5b78ff',
                    600: '#4a5cf5',
                    700: '#3d48d9',
                    800: '#3340af',
                    900: '#2e3a8a',
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

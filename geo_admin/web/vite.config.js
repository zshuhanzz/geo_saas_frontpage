import path from "path"
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    // Load env files per mode:
    //   npm run dev                      → mode=development → .env.local
    //   npm run dev -- --mode claude     → mode=claude      → .env.local.claude
    const env = loadEnv(mode, process.cwd(), "")

    return {
        plugins: [react()],
        resolve: {
            alias: {
                "@": path.resolve(__dirname, "./src"),
            },
        },
        server: {
            host: "localhost",
            port: parseInt(env.VITE_DEV_PORT || "5174"),
            strictPort: true,
            proxy: {
                '/api': {
                    target: env.VITE_ADMIN_API_PROXY || 'http://localhost:8000',
                    changeOrigin: true,
                },
            },
        },
    }
})

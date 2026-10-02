import path from "path"
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load env files per mode:
  //   npm run dev                      → mode=development → loads .env, .env.local
  //   npm run dev -- --mode claude     → mode=claude      → loads .env, .env.local.claude
  // Third arg "" = no prefix filter so we can read dev-server-level vars (not just VITE_*).
  const env = loadEnv(mode, process.cwd(), "")

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      port: parseInt(env.VITE_DEV_PORT || "5173"),
      proxy: {
        "/api/agent": {
          target: env.VITE_AGENT_API_PROXY || "http://localhost:8002",
          changeOrigin: true,
        },
        "/api": {
          target: env.VITE_SAAS_API_PROXY || "http://localhost:8001",
          changeOrigin: true,
        },
      },
    },
  }
})

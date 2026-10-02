import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
    plugins: [react()],
    define: {
        // In production, use env var; in dev, use local proxy
        'import.meta.env.VITE_API_URL': JSON.stringify(process.env.VITE_API_URL || ''),
    },
    server: {
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
        },
    },
})

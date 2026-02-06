import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api/v1/ws': {
        target: 'ws://localhost:8170',
        ws: true,
      },
      '/api': {
        target: 'http://localhost:8170',
        changeOrigin: true,
      },
    },
  },
})

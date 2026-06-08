import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5190,
    proxy: {
      // Forward API calls to FastAPI during development — avoids CORS
      '/macro': 'http://localhost:8090',
      '/markets': 'http://localhost:8090',
      '/pipeline': 'http://localhost:8090',
      '/health': 'http://localhost:8090',
    },
  },
})

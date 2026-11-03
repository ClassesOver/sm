import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

export default defineConfig({
  base: '/reports/v1/slides/',
  build: {
    emptyOutDir: true,
    outDir: '../static/slides',
    rollupOptions: { input: { index: fileURLToPath(new URL('./slides.html', import.meta.url)) } },
  },
})

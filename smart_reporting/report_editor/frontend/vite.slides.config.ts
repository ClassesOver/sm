import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

export default defineConfig({
  root: fileURLToPath(new URL('./slides', import.meta.url)),
  base: '/reports/v1/slides/assets/',
  build: {
    target: 'es2022',
    outDir: fileURLToPath(new URL('../static/slides', import.meta.url)),
    emptyOutDir: true,
    manifest: true,
  },
})

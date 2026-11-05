import { fileURLToPath } from 'node:url'
import { slidesReact } from './vite.slides-react'
import { defineConfig } from 'vite'
import editorConfig from './vite.config'

export default defineConfig({
  base: '/reports/v1/slides/',
  plugins: [slidesReact()],
  esbuild: { jsxFactory: 'h', jsxFragment: 'Fragment' },
  resolve: editorConfig.resolve,
  build: {
    emptyOutDir: true,
    outDir: '../static/slides',
    rollupOptions: {
      input: { index: fileURLToPath(new URL('./slides.html', import.meta.url)) },
      output: { manualChunks: { 'slides-react': ['react', 'react-dom/client'], 'slides-bindings': ['react-konva'], 'slides-konva': ['konva'] } },
    },
  },
})

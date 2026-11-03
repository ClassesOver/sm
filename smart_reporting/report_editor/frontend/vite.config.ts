import { fileURLToPath } from 'node:url'
import { slidesReact } from './vite.slides-react'

import { defineConfig } from 'vitest/config'

export default defineConfig({
  base: '/reports/v1/editor/assets/',
  plugins: [slidesReact()],
  esbuild: {
    jsxFactory: 'h',
    jsxFragment: 'Fragment',
  },
  optimizeDeps: {
    esbuildOptions: {
      jsxFactory: 'h',
      jsxFragment: 'Fragment',
    },
  },
  resolve: {
    alias: [
      { find: '@genoffice/pptx-render', replacement: fileURLToPath(new URL('../../reporting/slides_engine/packages/pptx-render/src/browser.ts', import.meta.url)) },
      {
        find: '@milkdown/crepe/feature/ai',
        replacement: fileURLToPath(
          new URL('./node_modules/@milkdown/crepe/src/feature/ai/index.ts', import.meta.url),
        ),
      },
      {
        find: '@milkdown/crepe/feature/toolbar',
        replacement: fileURLToPath(
          new URL('./node_modules/@milkdown/crepe/src/feature/toolbar/index.ts', import.meta.url),
        ),
      },
    ],
  },
  build: {
    manifest: true,
    emptyOutDir: true,
    outDir: '../static',
    rollupOptions: {
      output: {
        manualChunks: {
          milkdown: ['@milkdown/crepe', '@milkdown/kit'],
          icons: ['lucide'],
          diff: ['diff'],
          'slides-react': ['react', 'react-dom/client'], 'slides-bindings': ['react-konva'],
          'slides-konva': ['konva'],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
})

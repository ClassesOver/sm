import { defineConfig } from 'vitest/config'

export default defineConfig({
  base: '/reports/v1/editor/assets/',
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
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
})

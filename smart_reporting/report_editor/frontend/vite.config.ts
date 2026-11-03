import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitest/config'
import { precomputedCjkModule } from './scripts/precomputed-cjk'

export default defineConfig({
  base: '/reports/v1/editor/assets/',
  plugins: [{
    name: 'workbook-precomputed-cjk-charsets',
    enforce: 'pre',
    // cjk-regex's public API computes three fixed sets. Precompute them during
    // the build so the browser need not load every Unicode category table.
    resolveId(id) { return id === 'cjk-regex' ? '\0workbook-cjk-charsets' : undefined },
    load(id) {
      if (id !== '\0workbook-cjk-charsets') return undefined
      return precomputedCjkModule()
    },
  }],
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
        onlyExplicitManualChunks: true,
        chunkFileNames: 'assets/lazy-[name]-[hash].js',
        manualChunks(id) {
          const univer = id.match(/node_modules\/@univerjs\/([^/]+)/)?.[1]
          if (univer) {
            if (id.endsWith('/index.js')) return `workbook-${univer}`
            if (univer === 'engine-render') return `workbook-dictionary-${id.split('/').at(-1)!.split('-').slice(0, -1).join('-')}`
            return `workbook-${univer}`
          }
          if (id.includes('/node_modules/hyphen/')) return `workbook-hyphen-${id.split('/').at(-1)?.replace(/\.[^.]+$/, '')}`
          if (id.includes('/workbook_engine/')) return 'workbook-engine'
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'workbook-react'
          if (id.includes('/node_modules/opentype.js/')) return 'workbook-opentype'
          if (id.includes('/node_modules/franc-min/')) return 'workbook-language'
          if (id.includes('/node_modules/rxjs/')) return 'workbook-observable'
          if (/node_modules\/(zod|jszip|numfmt)\//.test(id)) return 'workbook-format'
          if (id.includes('/node_modules/@milkdown/')) return 'milkdown'
          if (id.includes('/node_modules/lucide/')) return 'icons'
          if (id.includes('/node_modules/diff/')) return 'diff'
          if (/node_modules\/prosemirror-[^/]+\//.test(id)) return 'milkdown-prosemirror'
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
})

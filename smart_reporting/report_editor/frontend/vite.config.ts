import { fileURLToPath } from 'node:url'
import { cp, mkdir } from 'node:fs/promises'
import { slidesReact } from './vite.slides-react'

import { configDefaults, defineConfig } from 'vitest/config'
import { precomputedCjkModule } from './scripts/precomputed-cjk'

export default defineConfig({
  base: '/reports/v1/editor/assets/',
  plugins: [slidesReact(), {
    name: 'native-pdf-runtime-assets',
    async writeBundle() {
      await mkdir(new URL('../static/licenses', import.meta.url), { recursive: true })
      await cp(new URL('./node_modules/pdfjs-dist/LICENSE', import.meta.url), new URL('../static/licenses/pdfjs-LICENSE', import.meta.url))
      for (const file of ['LICENSE', 'NOTICE']) await cp(new URL(`./src/vendor/genoffice-docs/${file}`, import.meta.url), new URL(`../static/licenses/genoffice-docs-${file}`, import.meta.url))
      for (const folder of ['cmaps', 'standard_fonts', 'wasm']) {
        await cp(new URL(`./node_modules/pdfjs-dist/${folder}`, import.meta.url),
          new URL(`../static/pdfjs/${folder}`, import.meta.url), { recursive: true })
      }
    },
  }, {
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
      { find: /^@sheets-web\/xlsx-engine$/, replacement: fileURLToPath(new URL('../../reporting/workbook_engine/packages/xlsx-engine/src/index.ts', import.meta.url)) },
      { find: /^@sheets-web\/xlsx-engine\/(.+)$/, replacement: fileURLToPath(new URL('../../reporting/workbook_engine/packages/xlsx-engine/src/', import.meta.url)) + '$1.ts' },
      { find: '@genoffice/docx-engine', replacement: fileURLToPath(new URL('../../reporting/slides_engine/packages/docx-engine/src/index.ts', import.meta.url)) },
      { find: /^@genoffice\/pptx-engine\/(.+)$/, replacement: fileURLToPath(new URL('../../reporting/slides_engine/packages/pptx-engine/src/', import.meta.url)) + '$1.ts' },
      { find: '@genoffice/pptx-render/preset-geometry', replacement: fileURLToPath(new URL('../../reporting/slides_engine/packages/pptx-render/src/preset-geometry.ts', import.meta.url)) },
      { find: /^@genoffice\/agent-core\/(redact-range|redact-core)$/, replacement: fileURLToPath(new URL('../../reporting/slides_engine/packages/agent-core/src/', import.meta.url)) + '$1.ts' },
      { find: '@genoffice/zip-gate', replacement: fileURLToPath(new URL('../../reporting/slides_engine/packages/zip-gate/src/index.ts', import.meta.url)) },
      { find: '@genoffice/font-metrics/resolve', replacement: fileURLToPath(new URL('./src/vendor/genoffice-docs/packages/font-metrics/src/resolve.ts', import.meta.url)) },
      { find: '@genoffice/font-metrics/word-faces.json', replacement: fileURLToPath(new URL('./src/vendor/genoffice-docs/packages/font-metrics/word-faces.json', import.meta.url)) },
      { find: '@genoffice/i18n', replacement: fileURLToPath(new URL('./src/vendor/genoffice-docs/packages/i18n/src/index.ts', import.meta.url)) },
      { find: '@genoffice/ui', replacement: fileURLToPath(new URL('./src/vendor/genoffice-docs/packages/ui/src/browser.ts', import.meta.url)) },
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
      preserveEntrySignatures: 'exports-only',
      input: { index: 'index.html', native: 'native.html', upload: 'src/native-upload.ts' },
      output: {
        entryFileNames: chunk => chunk.name === 'upload' ? 'native-upload.js' : 'assets/[name]-[hash].js',
        onlyExplicitManualChunks: true,
        chunkFileNames: 'assets/lazy-[name]-[hash].js',
        manualChunks(id) {
          if (id.includes('/node_modules/pdfjs-dist/')) return 'native-pdfjs'
          if (/\/vendor\/genoffice-docs\/.*\/i18n\/.*\.(json|ts)$/.test(id) && !id.endsWith('/index.ts')) return `native-docx-locale-${id.split('/i18n/').at(-1)!.replace(/[^a-zA-Z0-9]/g, '-')}`
          if (id.endsWith('/font-metrics/word-faces.json')) return 'native-docx-font-metrics'
          if (id.includes('/vendor/genoffice-docs/')) return 'native-docx-render'
          if (id.includes('/slides_engine/packages/docx-engine/')) return 'native-docx-engine'
          if (/node_modules\/(@tiptap|prosemirror-)/.test(id)) return 'native-tiptap'
          const univer = id.match(/node_modules\/@univerjs\/([^/]+)/)?.[1]
          if (univer) {
            if (id.endsWith('/index.js')) return `workbook-${univer}`
            if (univer === 'engine-render') return `workbook-dictionary-${id.split('/').at(-1)!.split('-').slice(0, -1).join('-')}`
            return `workbook-${univer}`
          }
          if (id.includes('/node_modules/hyphen/')) return `workbook-hyphen-${id.split('/').at(-1)?.replace(/\.[^.]+$/, '')}`
          if (id.includes('/workbook_engine/')) return 'workbook-engine'
          // Keep individually lazy-loaded React packages below the ordinary chunk cap.
          if (/node_modules\/scheduler\//.test(id)) return 'scheduler'
          if (/node_modules\/react\//.test(id)) return 'react'
          if (id.includes('/node_modules/react-konva/')) return 'slides-bindings'
          if (id.includes('/node_modules/konva/')) return 'slides-konva'
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
    setupFiles: ['src/test-env-polyfills.ts'],
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
})

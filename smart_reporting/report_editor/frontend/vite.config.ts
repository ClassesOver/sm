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
      { find: '@genoffice/docx-engine', replacement: fileURLToPath(new URL('../../reporting/doc_engine/packages/docx-engine/src/index.ts', import.meta.url)) },
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
          if (/\/src\/(?:pdf-replace-text-style|pdf-text-selection|pdf-selection-style-source|pdf-static-text|pdf-text-edit-shortcuts)\.ts$/.test(id)) return 'native-pdf-text-controls'
          if (/\/src\/pdf-form-(?:create|design|radio-extension|text-properties|canvas)\.ts$/.test(id)) return 'native-pdf-form-controls'
          if (id.endsWith('/src/office-ai-entry.tsx')) return 'office-ai-entry'
          if (/\/src\/docx-ruler\.tsx$/.test(id) || id.endsWith('/docx-ruler-indent.ts') || id.endsWith('/docx-tab-stops.ts') || /\/vendor\/genoffice-docs\/apps\/docs\/src\/renderer\/(?:components\/Ruler\.tsx|use-measurement\.ts|units\.ts)$/.test(id)) return 'docx-ruler'
          // Keep native review adapters and draft planners out of editor command chunks.
          // Static ESM imports preserve their existing synchronous call paths.
          if (/\/src\/docx-comment-(?:create|reply|thread|text)\.ts$/.test(id)) return 'docx-comment-model'
          if (/\/src\/slides-(?:groups|native-clipboard|native-media-draft|element-order|arrange|format-brush)\.ts$/.test(id)) return 'slides-draft-plans'
          if (id.endsWith('/src/docx-line-spacing.ts')) return 'docx-line-spacing'
          if (id.endsWith('/src/docx-special-indent.ts')) return 'docx-special-indent'
          if (/\/src\/docx-navigation(?:-search|-pages)?\.ts$/.test(id)) return 'docx-navigation'
          if (id.endsWith('/renderer/ai/table-ops.ts')) return 'native-docx-table-ops'
          if (/\/vendor\/genoffice-docs\/apps\/docs\/src\/renderer\/(?:pagination-sections|page-margins)\.ts$/.test(id)) return 'native-docx-section-layout'
          if (/\/vendor\/genoffice-docs\/apps\/docs\/src\/renderer\/editor\/(?:column-layout(?:-recovery)?|top-level-pos)\.ts$/.test(id)) return 'native-docx-column-layout'
          if (id.endsWith('/src/docx-footnote-pagination.ts')) return 'docx-footnote-pagination'
          if (/\/vendor\/genoffice-docs\/apps\/docs\/src\/renderer\/(?:editor\/note-dom|note-format)\.ts$/.test(id)) return 'native-docx-note-dom'
          if (id.endsWith('/renderer/editor/table-input-paragraphs.ts')) return 'native-docx-table-input'
          if (id.endsWith('/renderer/editor/table-cell-shape-source.ts')) return 'native-docx-table-cell-shape'
          if (id.endsWith('/renderer/editor/table-column-width-source.ts')) return 'native-docx-table-column-width'
          if (id.endsWith('/renderer/ai/lengths.ts')) return 'native-docx-lengths'
          if (id.endsWith('/vendor/genoffice-docs/apps/docs/src/renderer/components/icons.tsx')) return 'native-docx-ribbon-icons'
          if (id.endsWith('/src/workbook-ribbon.ts')) return 'workbook-ribbon'
          if (/\/workbook_engine\/packages\/xlsx-engine\/src\/pivot-(?:add|refresh|standard-grouping|layout|formula|grouping|filters)\.ts$/.test(id)) return 'workbook-pivot-calculation'
          if (id.endsWith('/workbook_engine/packages/xlsx-engine/src/chart-edit.ts')) return 'workbook-chart-edit'
          if (/\/src\/workbook-queries(?:-reader)?\.ts$/.test(id) || /\/src\/workbook-vendor\/grid\/(?:workbook-queries|query-parts)\.ts$/.test(id)) return 'workbook-queries'
          if (/\/src\/workbook-(?:print-header-footer|header-footer-editor)\.ts$/.test(id)) return 'workbook-print-settings'
          if (id.endsWith('/src/workbook-import-csv.ts') || id.endsWith('/src/workbook-vendor/grid/csv-import.ts')) return 'workbook-import-csv'
          if (/\/src\/workbook-pivot(?:-dialog)?\.ts$/.test(id)) return 'workbook-pivot'
          if (id.endsWith('/src/workbook-cross-highlight.ts')) return 'workbook-cross-highlight'
          if (/\/src\/workbook-page-break-(?:preview\.tsx|(?:controller|context)\.ts)$/.test(id)) return 'workbook-page-break-preview'
          if (/\/node_modules\/(?:saxes|xmlchars)\//.test(id)) return 'workbook-xml-parser'
          if (/\/src\/workbook-chart-(?:source|sheet-removal)\.ts$/.test(id)) return 'workbook-chart-references'
          if (id.endsWith('/src/workbook-data-validation.ts')) return 'workbook-data-validation-controls'
          if (id.endsWith('/src/workbook-data-validation-structure.ts')) return 'workbook-structure-followers'
          if (id.endsWith('/src/workbook-conditional-formatting.ts')) return 'workbook-conditional-formatting-controls'
          if (id.endsWith('/src/workbook-rtl.ts') || id.includes('/src/vendor/genoffice-rtl/')) return 'workbook-rtl'
          if (id.endsWith('/workbook_engine/packages/xlsx-engine/src/conditional-formatting-source.ts')) return 'workbook-conditional-formatting'
          if (/\/src\/workbook-(?:headings|formula-bar-view|view|statistics)\.ts$/.test(id)) return 'workbook-view-controls'
          if (id.endsWith('/src/workbook-checkbox.ts')) return 'workbook-checkbox-control'
          if (id.endsWith('/src/workbook-watch-window.ts')) return 'workbook-watch-window'
          if (id.endsWith('/src/workbook-sparklines.ts')) return 'workbook-sparklines'
          if (/\/src\/workbook-subtotal(?:-dialog|-preflight)?\.ts$/.test(id)) return 'workbook-subtotal'
          if (/\/src\/workbook-advanced-filter(?:-dialog|-preflight)?\.ts$/.test(id)) return 'workbook-advanced-filter'
          if (/\/src\/workbook-(?:sort-dialog|fill-series|dedupe|text-to-columns|flash-fill)\.ts$/.test(id)) return 'workbook-data-tools'
          if (/\/src\/workbook-grid-(?:operations|guards)\.ts$/.test(id)) return 'workbook-grid-operations'
          if (id.endsWith('/src/workbook-error-checking.ts')) return 'workbook-error-checking'
          if (/\/src\/workbook-(?:print|print-scale|page-break-context)\.ts$/.test(id)) return 'workbook-print-settings'
          if (id.endsWith('/src/workbook-protection.ts')) return 'workbook-protection'
          if (id.endsWith('/src/workbook-cell-style-presets.ts')) return 'workbook-cell-style-presets'
          if (id.endsWith('/workbook_engine/packages/xlsx-engine/src/checkbox-validation.ts')) return 'workbook-checkbox-validation'
          if (id.endsWith('/workbook_engine/packages/xlsx-engine/src/future-functions.ts')) return 'workbook-future-functions'
          if (/\/src\/workbook-(?:goto|goto-reveal|render-ready)\.ts$/.test(id)) return 'workbook-navigation'
          if (id.endsWith('/src/workbook-shortcut-target.ts')) return 'workbook-shortcut-target'
          if (id.endsWith('/src/workbook-zoom-selection.ts')) return 'workbook-zoom-selection'
          if (/\/src\/workbook-zoom-(?:dialog|launcher)\.ts$/.test(id)) return 'workbook-zoom-dialog'
          if (/\/src\/workbook-(?:insert-function|function-[^/]+)\.(?:ts|tsx)$/.test(id)) return 'workbook-insert-function'
          if (/\/workbook_engine\/packages\/xlsx-engine\/src\/outline(?:-read)?\.ts$/.test(id) || /\/src\/workbook-outline(?:-(?:gutter(?:-model)?|shortcuts))?\.ts$/.test(id)) return 'workbook-outline'
          if (id.endsWith('/workbook_engine/packages/xlsx-engine/src/table-style-read.ts')) return 'workbook-table-style-read'
          if (/\/src\/workbook-defined-name(?:s|-scope)\.ts$/.test(id) || /\/workbook_engine\/packages\/xlsx-engine\/src\/defined-names\.ts$/.test(id)) return 'workbook-defined-names'
          if (/\/src\/workbook-table-(?:totals|style-edit|convert|create|header-row|filter-button)\.ts$/.test(id)) return 'workbook-table-design'
          if (/\/src\/workbook-(?:data-table|goal-seek)(?:-dialog)?\.ts$/.test(id)) return 'workbook-what-if'
          if (/\/src\/workbook-(?:consolidate(?:-dialog)?|edit-budget)\.ts$/.test(id)) return 'workbook-consolidate'
          if (id.includes('/node_modules/pdfjs-dist/')) return 'native-pdfjs'
          if (/\/vendor\/genoffice-docs\/.*\/i18n\/.*\.(json|ts)$/.test(id) && !id.endsWith('/index.ts')) return `native-docx-locale-${id.split('/i18n/').at(-1)!.replace(/[^a-zA-Z0-9]/g, '-')}`
          if (id.endsWith('/font-metrics/word-faces.json')) return 'native-docx-font-metrics'
          if (id.endsWith('/vendor/genoffice-docs/apps/docs/src/renderer/components/icons.tsx')) return 'native-docx-ribbon-icons'
          if (id.includes('/vendor/genoffice-docs/apps/docs/src/') && ['renderer/html-export.ts','renderer/export-markdown.ts','renderer/word-count.ts','renderer/ai/protocol.ts','renderer/ai/revision-ops.ts','renderer/ai/redact-view.ts','renderer/ai/page-setup.ts','renderer/ai/revision-author.ts','renderer/ai/inherit-formatting.ts','renderer/ai/ops.ts','renderer/ai/style-ops.ts','renderer/ai/field-ops.ts','renderer/ai/tab-stops.ts','renderer/ai/after-text.ts','shared/ipc.ts'].some(path=>id.endsWith('/'+path))) return 'native-pdf-text-serializer'
          if (id.includes('/vendor/genoffice-docs/')) return 'native-docx-render'
          if (id.includes('/doc_engine/packages/docx-engine/')) return 'native-docx-engine'
          if (/node_modules\/(@tiptap|prosemirror-)/.test(id)) return 'native-tiptap'
          const univer = id.match(/node_modules\/@univerjs\/([^/]+)/)?.[1]
          if (univer) {
            if (id.endsWith('/index.js')) return `workbook-${univer}`
            if (univer === 'engine-render') return `workbook-dictionary-${id.split('/').at(-1)!.split('-').slice(0, -1).join('-')}`
            return `workbook-${univer}`
          }
          if (id.includes('/node_modules/hyphen/')) return `workbook-hyphen-${id.split('/').at(-1)?.replace(/\.[^.]+$/, '')}`
          if (id.includes('/node_modules/zod/')) return id.includes('/workbook_engine/') ? 'workbook-engine-schema' : 'workbook-schema'
          if (id.includes('/workbook_engine/') && !id.includes('/node_modules/')) return 'workbook-engine'
          // Keep individually lazy-loaded React packages below the ordinary chunk cap.
          if (/node_modules\/scheduler\//.test(id)) return 'scheduler'
          if (/node_modules\/react\//.test(id)) return 'react'
          if (id.endsWith('/src/office-ribbon-scroll.ts')) return 'office-ribbon-scroll'
          if (id.endsWith('/src/slides-shape-format-pane.tsx')) return 'native-pptx-shape-format'
          if (id.endsWith('/src/slides-geometry-pane.ts')) return 'native-pptx-geometry'
          if (id.endsWith('/src/slides-chart-format-pane.tsx') || id.includes('/src/vendor/genoffice-slides/ui/color-picker')) return 'native-pptx-chart-format'
          if (id.includes('/node_modules/react-konva/')) return 'slides-bindings'
          if (id.includes('/node_modules/konva/')) return 'slides-konva'
          if (id.includes('/node_modules/opentype.js/')) return 'workbook-opentype'
          if (id.includes('/node_modules/franc-min/')) return 'workbook-language'
          if (id.includes('/node_modules/rxjs/')) return 'workbook-observable'
          if (id.includes('/node_modules/jszip/')) return id.includes('/workbook_engine/') ? 'workbook-engine-zip' : id.includes('/slides_engine/') ? 'slides-zip' : 'workbook-zip'
          if (id.includes('/node_modules/numfmt/')) return id.includes('/workbook_engine/') ? 'workbook-engine-format' : 'workbook-format'
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

import { defineConfig } from 'vitest/config'

export default defineConfig({
  base: '/management/',
  esbuild: { jsx: 'automatic' },
  plugins: [
    {
      name: 'management-dependency-boundary',
      generateBundle(_, bundle) {
        const modules = Object.values(bundle).flatMap((item) =>
          item.type === 'chunk' ? Object.keys(item.modules) : [],
        )
        const forbidden = modules.filter((id) =>
          /milkdown|univerjs|slides_engine|doc_engine|workbook_engine|pdfjs-dist|plotly|react-konva/.test(
            id,
          ),
        )
        if (forbidden.length)
          this.error('管理构建引入了编辑器或图表引擎：' + forbidden.join(','))
        this.emitFile({
          type: 'asset',
          fileName: 'management-modules.json',
          source: JSON.stringify({ moduleCount: modules.length, forbidden }),
        })
      },
    },
  ],
  build: {
    outDir: '../static/management',
    manifest: true,
    emptyOutDir: true,
    rollupOptions: { input: 'management.html' },
  },
  test: {
    environment: 'jsdom',
    include: ['src/management/**/*.test.{ts,tsx}'],
  },
})

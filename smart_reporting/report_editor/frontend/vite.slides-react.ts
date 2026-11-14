import { transformWithEsbuild, type Plugin } from 'vite'

// Milkdown's source aliases use Vue JSX; only the PPTX canvas uses React JSX.
export function slidesReact(): Plugin {
  return {
    name: 'slides-react-jsx',
    enforce: 'pre',
    async transform(code, id) {
      if (id.endsWith('.tsx') && (id.includes('/src/vendor/genoffice-pdf/') || id.includes('/src/vendor/genoffice-docs/') || id.includes('/src/vendor/genoffice-sheets-format/') || id.includes('/src/vendor/genoffice-sheets-pivot/') || id.endsWith('/src/workbook-pivot-pane.tsx') || /\/src\/docx-mail-merge-(?:panel|controls)\.tsx$/.test(id) || id.includes('/src/vendor/genoffice-slides/model3d/') || id.endsWith('/src/vendor/genoffice-slides/components/icons.tsx') || id.endsWith('/src/docx-main.tsx') || id.endsWith('/src/docx-equation-source.tsx') || id.endsWith('/src/pdf-form-design-layer-source.tsx') || id.endsWith('/src/slides-model3d-ui.tsx') || /\/src\/workbook-threaded-comments-(?:host|pane)\.tsx$/.test(id))) {
        const result = await transformWithEsbuild(code, id, { loader: 'tsx', jsx: 'automatic' })
        return { code: result.code, map: JSON.stringify(result.map) }
      }
      if (!id.endsWith('.tsx') || !(id.includes('/src/vendor/genoffice/') || id.endsWith('/src/slides-canvas.tsx') || id.endsWith('/src/slides-zoom-grid.tsx'))) return
      const result = await transformWithEsbuild(code, id, { loader: 'tsx', jsxFactory: 'React.createElement', jsxFragment: 'React.Fragment' })
      return { code: result.code, map: JSON.stringify(result.map) }
    },
  }
}

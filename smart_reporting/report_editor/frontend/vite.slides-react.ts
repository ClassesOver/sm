import { transformWithEsbuild, type Plugin } from 'vite'

// Milkdown's source aliases use Vue JSX; only the PPTX canvas uses React JSX.
export function slidesReact(): Plugin {
  return {
    name: 'slides-react-jsx',
    enforce: 'pre',
    async transform(code, id) {
      if (!id.endsWith('.tsx') || !(id.includes('/src/vendor/genoffice/') || id.endsWith('/src/slides-canvas.tsx'))) return
      const result = await transformWithEsbuild(code, id, { loader: 'tsx', jsxFactory: 'React.createElement', jsxFragment: 'React.Fragment' })
      return { code: result.code, map: JSON.stringify(result.map) }
    },
  }
}

import { defineConfig } from 'vite'
import { nodePolyfills } from 'vite-plugin-node-polyfills'

export default defineConfig({
  publicDir: false,
  define: {
    'process.env.NODE_ENV': JSON.stringify('production')
  },
  plugins: [
    {
      name: 'browser-fs-promises-shim',
      enforce: 'pre',
      resolveId(id) {
        return id === 'fs/promises' ? '\0browser-fs-promises' : undefined
      },
      load(id) {
        if (id !== '\0browser-fs-promises') return undefined
        return 'export async function readFile() { throw new Error("fs/promises is unavailable in browsers") }'
      }
    },
    nodePolyfills({
      include: ['buffer', 'events', 'path', 'process', 'stream', 'string_decoder', 'util', 'zlib'],
      globals: { Buffer: true, global: true, process: true },
      protocolImports: true
    })
  ],
  build: {
    emptyOutDir: false,
    outDir: '../static/lib/agui-chat-react',
    lib: {
      entry: 'src/file-viewer-entry.ts',
      formats: ['iife'],
      name: 'AguiFileViewerBundle',
      fileName: () => 'agui_file_viewer.12.0.8.8.0.js'
    },
    rollupOptions: {
      external: ['react', 'react/jsx-runtime'],
      output: {
        globals: {
          react: 'AguiChatReact',
          'react/jsx-runtime': 'AguiChatReactJSXRuntime'
        }
      }
    }
  }
})

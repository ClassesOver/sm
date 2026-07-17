import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig(({ command }) => ({
  define: {
    'process.env.NODE_ENV': JSON.stringify(command === 'build' ? 'production' : 'development')
  },
  plugins: [
    react(),
    {
      name: 'dev-attachment-fixture',
      configureServer(server) {
        server.middlewares.use('/agui_chat/attachment/upload', (_request, response) => {
          response.statusCode = 200
          response.setHeader('Content-Type', 'application/json')
          response.end(JSON.stringify({
            attachment: {
              id: 'dev-upload',
              name: 'dev-upload',
              mimeType: 'application/octet-stream',
              size: 1024,
              modality: 'document'
            }
          }))
        })
        server.middlewares.use('/agui_chat/attachment/dev-image', (_request, response) => {
          response.statusCode = 302
          response.setHeader('Location', '/dev-attachment.svg')
          response.end()
        })
      }
    }
  ],
  build: {
    minify: false,
    emptyOutDir: true,
    outDir: '../static/lib/agui-chat-react',
    lib: {
      entry: 'src/index.tsx',
      formats: ['iife'],
      name: 'AguiChatReactBundle',
      fileName: () => 'agui_chat_widget.12.0.8.2.0.js',
      cssFileName: 'agui_chat_widget.12.0.8.2.0'
    },
    rollupOptions: {
      output: {
        assetFileNames: (assetInfo) =>
          assetInfo.name === 'style.css'
            ? 'agui_chat_widget.12.0.8.2.0.css'
            : '[name][extname]'
      }
    }
  }
}))

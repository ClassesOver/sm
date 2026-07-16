import type { Config } from 'tailwindcss'

export default {
  corePlugins: {
    container: false,
    preflight: false
  },
  content: ['./src/**/*.{ts,tsx}'],
  important: '.agui-chat-react',
  theme: {
    extend: {
      colors: {
        primary: '#18181b',
        primaryAccent: '#ffffff',
        brand: '#e23b16',
        background: {
          DEFAULT: '#f8fafc',
          secondary: '#f1f5f9',
          panel: '#ffffff'
        },
        secondary: '#27272a',
        border: '#d8dee8',
        accent: '#f1f5f9',
        muted: '#64748b',
        destructive: '#dc2626',
        positive: '#15803d',
        warning: '#b45309'
      },
      borderRadius: {
        xl: '10px'
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'sans-serif'
        ],
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'Liberation Mono',
          'monospace'
        ]
      }
    }
  },
  plugins: []
} satisfies Config

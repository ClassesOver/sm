export const genOfficeHomeClipboardLocales = {
  en: {
    group: 'Clipboard',
    paste: 'Paste',
    cut: 'Cut',
    copy: 'Copy',
    formatPainter: 'Format Painter',
    pasteUnavailable: 'The source command uses the desktop clipboard bridge, unavailable in the browser editor.',
    clipboardUnavailable: 'The source command uses native clipboard integration, unavailable in the browser editor.',
    formatPainterUnavailable: 'The source format painter state and selection callbacks are not connected to the browser editor.',
  },
  zh: {
    group: '剪贴板',
    paste: '粘贴',
    cut: '剪切',
    copy: '复制',
    formatPainter: '格式刷',
    pasteUnavailable: '上游命令依赖桌面剪贴板桥接，浏览器编辑器无法调用。',
    clipboardUnavailable: '上游命令依赖本机剪贴板集成，浏览器编辑器无法调用。',
    formatPainterUnavailable: '上游格式刷状态和选区回调尚未接入浏览器编辑器。',
  },
} as const

export function genOfficeHomeClipboardLocale(language: string) {
  return language.toLowerCase().startsWith('zh') ? genOfficeHomeClipboardLocales.zh : genOfficeHomeClipboardLocales.en
}

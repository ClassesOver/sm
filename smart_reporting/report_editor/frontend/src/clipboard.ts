function copyWithSelection(text: string): boolean {
  if (typeof document.execCommand !== 'function') return false
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  textarea.setSelectionRange(0, text.length)
  let copied = false
  try {
    copied = document.execCommand('copy')
  } catch {
    copied = false
  }
  textarea.remove()
  return copied
}

function fallbackCopy(text: string): Promise<void> {
  if (copyWithSelection(text)) return Promise.resolve()
  return Promise.reject(new Error('clipboard unavailable'))
}

export function copyText(text: string): Promise<void> {
  const clipboard = navigator.clipboard
  if (!clipboard || typeof clipboard.writeText !== 'function') return fallbackCopy(text)
  return clipboard.writeText(text).catch(() => {
    // Firefox 等环境在异步回调或权限受限时拒绝 Clipboard API，降级到选区复制
    return fallbackCopy(text)
  })
}

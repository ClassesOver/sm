import { readStorage, removeStorage, writeStorage } from './storage'

export function createLocalDraftController(
  root: HTMLElement,
  storageKey: string,
  restore: (markdown: string) => void,
) {
  const banner = document.createElement('section')
  banner.className = 'draft-recovery'
  banner.hidden = true
  banner.innerHTML = `<div><strong>发现未同步的本地草稿</strong><span>可能来自上次异常关闭或断网编辑。</span></div><button type="button" data-draft="restore">恢复草稿</button><button type="button" data-draft="discard">放弃</button>`
  const appBar = root.querySelector('.app-bar')
  if (appBar) appBar.insertAdjacentElement('afterend', banner)
  else root.prepend(banner)
  let pendingMarkdown: string | null = null
  let storeTimer: number | undefined
  const cancelPendingStore = () => {
    window.clearTimeout(storeTimer)
    storeTimer = undefined
    pendingMarkdown = null
  }
  const flush = () => {
    if (pendingMarkdown === null) return
    try {
      if (writeStorage(storageKey, pendingMarkdown)) {
        pendingMarkdown = null
      }
    } finally {
      storeTimer = undefined
    }
  }
  const hide = () => { banner.hidden = true }
  banner.querySelector<HTMLButtonElement>('[data-draft="restore"]')!.addEventListener('click', () => {
    const draft = readStorage(storageKey)
    if (draft !== null) restore(draft)
    hide()
  })
  banner.querySelector<HTMLButtonElement>('[data-draft="discard"]')!.addEventListener('click', () => {
    cancelPendingStore()
    removeStorage(storageKey)
    hide()
  })
  window.addEventListener('beforeunload', flush)
  return {
    banner,
    offer(serverMarkdown: string) {
      const draft = readStorage(storageKey)
      banner.hidden = draft === null || draft === serverMarkdown
    },
    store(markdown: string) {
      pendingMarkdown = markdown
      window.clearTimeout(storeTimer)
      storeTimer = window.setTimeout(flush, 2000)
    },
    clear() {
      cancelPendingStore()
      removeStorage(storageKey)
      hide()
    },
  }
}

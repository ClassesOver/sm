import type { Editor } from '@tiptap/core'

/** 固定源 App.showGrid：只切换现有 24px 屏幕辅助网格，不修改 Word docGrid 或表格网格线。 */
export function createDocxGridlines(options: { editor: Editor; root: HTMLElement; onVisibilityChange?(visible: boolean): void }) {
  const previousClass = options.root.classList.contains('show-grid')
  let visible = false, disposed = false
  const reason = (): string | null => disposed || options.editor.isDestroyed ? 'Word 网格线视图已关闭' : null
  const refresh = () => { if (!reason()) options.root.classList.toggle('show-grid', visible) }
  refresh()
  return {
    get visible() { return !disposed && visible },
    reason,
    refresh,
    toggle() {
      if (reason()) return
      visible = !visible
      refresh()
      options.onVisibilityChange?.(visible)
    },
    dispose() {
      if (disposed) return
      disposed = true
      options.root.classList.toggle('show-grid', previousClass)
    },
  }
}

/** 固定源 Word Table Layout ▸ View Gridlines：仅显示表格单元格边界，不修改文档。 */
export interface DocxGridlineStorage { getItem(key: string): string | null; setItem(key: string, value: string): void }
const tableGridlinesStorageKey = 'aidocs.tableGridlines'

function defaultGridlineStorage(): DocxGridlineStorage | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage }
  catch { return null }
}

export function createDocxTableGridlines(options: { editor: Editor; root: HTMLElement; storage?: DocxGridlineStorage | null; storageKey?: string }) {
  const previousClass = options.root.classList.contains('show-table-gridlines')
  const storage = options.storage === undefined ? defaultGridlineStorage() : options.storage
  const storageKey = options.storageKey ?? tableGridlinesStorageKey
  let visible = false, disposed = false
  try { visible = storage?.getItem(storageKey) === 'true' } catch { visible = false }
  const reason = (): string | null => disposed || options.editor.isDestroyed ? '表格网格线视图已关闭' : null
  const refresh = () => { if (!reason()) options.root.classList.toggle('show-table-gridlines', visible) }
  refresh()
  return {
    get visible() { return !disposed && visible },
    reason,
    refresh,
    toggle() {
      if (reason()) return
      visible = !visible
      refresh()
      try { storage?.setItem(storageKey, String(visible)) } catch { /* Keep the in-memory view state. */ }
    },
    dispose() {
      if (disposed) return
      disposed = true
      options.root.classList.toggle('show-table-gridlines', previousClass)
    },
  }
}

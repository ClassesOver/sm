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

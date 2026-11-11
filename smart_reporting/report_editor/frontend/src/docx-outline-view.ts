import type { Editor } from '@tiptap/core'
import { outlineViewKey } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/outline-view'

/** 大纲只改变 GenOffice plugin metadata 与显示 class，不提交正文或原生操作。 */
export function createDocxOutlineView(options: { editor: Editor; root: HTMLElement; onError?(error: unknown): void }) {
  const { editor, root } = options
  const previousClass = root.classList.contains('view-outline')
  let disposed = false
  const mode = (): 'page' | 'outline' => !editor.isDestroyed && outlineViewKey.getState(editor.state)?.active ? 'outline' : 'page'
  const refresh = () => { if (!disposed) root.classList.toggle('view-outline', mode() === 'outline') }
  const reason = (label: string): string | null => {
    if (disposed || editor.isDestroyed) return 'Word 大纲视图已关闭'
    if (label !== '大纲' && label !== '页面视图') return '此命令不属于 Word 大纲视图'
    return outlineViewKey.getState(editor.state) ? null : '当前 Word 引擎未提供大纲视图'
  }
  editor.on('transaction', refresh)
  refresh()
  return {
    get mode() { return mode() },
    reason,
    run(label: string) {
      if (reason(label)) return
      try {
        if (!editor.commands.setOutlineViewActive(label === '大纲')) throw new Error('无法切换 Word 大纲视图')
        refresh()
      } catch (error) { options.onError?.(error) }
    },
    refresh,
    dispose() {
      if (disposed) return
      disposed = true
      editor.off('transaction', refresh)
      try { if (!editor.isDestroyed) editor.commands.setOutlineViewActive(false) }
      catch (error) { options.onError?.(error) }
      finally { root.classList.toggle('view-outline', previousClass) }
    },
  }
}

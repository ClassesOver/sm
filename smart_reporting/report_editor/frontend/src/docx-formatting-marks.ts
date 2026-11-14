import type { Editor } from '@tiptap/core'
import type { SectionInfo } from '@genoffice/docx-engine'
import { formattingMarksPluginKey, sectionBreakMap } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/formatting-marks'

/** Home > Show/Hide formatting marks is a view toggle, never a document edit. */
export function createDocxFormattingMarks(options: { editor: Editor; root: HTMLElement; sections: readonly SectionInfo[] }) {
  const previousClass = options.root.classList.contains('show-marks')
  let visible = false, disposed = false
  const reason = (): string | null => disposed || options.editor.isDestroyed ? '编辑标记视图已关闭' : null
  const refresh = () => { if (!reason()) options.root.classList.toggle('show-marks', visible) }
  const sync = () => {
    if (reason()) return
    options.editor.view.dispatch(options.editor.state.tr
      .setMeta(formattingMarksPluginKey, { on: visible, breaks: sectionBreakMap(options.sections) })
      .setMeta('addToHistory', false))
    refresh()
  }
  refresh()
  return {
    get visible() { return !disposed && visible },
    reason,
    refresh: sync,
    toggle() {
      if (reason()) return
      visible = !visible
      sync()
    },
    dispose() {
      if (disposed) return
      visible = false
      sync()
      disposed = true
      options.root.classList.toggle('show-marks', previousClass)
    },
  }
}

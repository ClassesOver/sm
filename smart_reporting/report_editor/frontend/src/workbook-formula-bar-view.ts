// 固定源 App.tsx:4733 / styles.css:6041：会话级编辑栏显隐，不进入文件或撤销历史。
import './workbook-formula-bar-view.css'

const HIDDEN_CLASS = 'workbook-formula-bar-hidden'

export function createFormulaBarView(host: HTMLElement): {
  visible(): boolean
  toggle(): boolean
  dispose(): void
} {
  let visible = true, disposed = false
  host.classList.remove(HIDDEN_CLASS)
  return {
    visible: () => visible,
    toggle() {
      if (disposed) return visible
      visible = !visible
      host.classList.toggle(HIDDEN_CLASS, !visible)
      return visible
    },
    dispose() {
      if (disposed) return
      disposed = true
      visible = true
      host.classList.remove(HIDDEN_CLASS)
    },
  }
}

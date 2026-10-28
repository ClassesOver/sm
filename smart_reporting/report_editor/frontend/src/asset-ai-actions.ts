import { findEvidenceTableId } from './evidence-location'

interface AssetAIActionsOptions {
  onChartEdit?: (image: HTMLImageElement) => void
  onTableEdit?: (tableId: string) => void
}

/** 操作入口放在编辑器外，避免操作按钮被序列化进报告正文。 */
export function createAssetAIActions(editor: HTMLElement, options: AssetAIActionsOptions) {
  const toolbar = document.createElement('div')
  toolbar.className = 'asset-ai-actions'
  toolbar.setAttribute('role', 'toolbar')
  toolbar.setAttribute('aria-label', '图表 AI 编辑')
  toolbar.hidden = true
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'asset-ai-edit-button'
  toolbar.append(button)
  document.body.append(toolbar)
  let target: HTMLElement | null = null
  let action: (() => void) | null = null

  const hide = () => { toolbar.hidden = true; target = null; action = null }
  const position = () => {
    if (!target || !editor.contains(target)) return hide()
    const rect = target.getBoundingClientRect()
    if (rect.bottom < 0 || rect.top > window.innerHeight) return hide()
    toolbar.style.top = `${Math.max(8, rect.top - 40)}px`
    toolbar.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 120))}px`
  }
  const showTarget = (element: Element) => {
    const asset = element.closest<HTMLImageElement | HTMLTableElement>('img, table')
    if (!asset || !editor.contains(asset) || asset.closest('.drag-preview')) return hide()
    if (asset instanceof HTMLImageElement && options.onChartEdit && !asset.classList.contains('interactive-chart-fallback')) {
      button.textContent = 'AI 改图'
      action = () => options.onChartEdit?.(asset)
    } else if (asset instanceof HTMLTableElement && options.onTableEdit) {
      const tableId = findEvidenceTableId(editor, asset)
      if (!tableId) return hide()
      button.textContent = 'AI 改表'
      action = () => {
        // 草稿可能在按钮显示后重绘，点击时重新确认表格身份。
        if (findEvidenceTableId(editor, asset) === tableId) options.onTableEdit?.(tableId)
      }
    } else return hide()
    button.title = `${button.textContent}：输入要求，预览后接受替换`
    target = asset
    toolbar.hidden = false
    position()
  }
  const showFor = (event: Event) => {
    if (!(event.target instanceof Element)) return
    // 从表格移向浮动按钮时会经过正文空隙，保持入口可点击。
    if (event.type === 'pointerover' && !event.target.closest('img, table')) return
    showTarget(event.target)
  }
  const selectionChanged = () => {
    const anchor = window.getSelection()?.anchorNode
    const element = anchor instanceof Element ? anchor : anchor?.parentElement
    if (element && editor.contains(element)) showTarget(element)
  }
  const dismiss = (event: Event) => {
    if (event.target instanceof Node && !toolbar.contains(event.target) && !editor.contains(event.target)) hide()
  }
  const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') hide() }
  button.addEventListener('click', () => {
    const run = target && editor.contains(target) ? action : null
    hide()
    run?.()
  })
  editor.addEventListener('pointerover', showFor)
  editor.addEventListener('click', showFor)
  editor.addEventListener('focusin', showFor)
  document.addEventListener('pointerdown', dismiss)
  document.addEventListener('focusin', dismiss)
  document.addEventListener('keydown', escape)
  document.addEventListener('selectionchange', selectionChanged)
  window.addEventListener('scroll', position, true)
  window.addEventListener('resize', position)
  return {
    dispose() {
      editor.removeEventListener('pointerover', showFor)
      editor.removeEventListener('click', showFor)
      editor.removeEventListener('focusin', showFor)
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('focusin', dismiss)
      document.removeEventListener('keydown', escape)
      document.removeEventListener('selectionchange', selectionChanged)
      window.removeEventListener('scroll', position, true)
      window.removeEventListener('resize', position)
      toolbar.remove()
    },
  }
}

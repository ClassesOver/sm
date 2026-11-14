// 固定源f8c17004 ZoomDialog.tsx：五预设、适合选区、自定义与确认后应用。
import { createModal } from './modal'
import './workbook-zoom-dialog.css'
export const WORKBOOK_ZOOM_PRESETS = [200, 100, 75, 50, 25] as const
export type WorkbookZoomCommand = `zoom:${number}` | 'zoom-to-selection'
export function parseWorkbookZoomPercent(raw: string): number {
  const value = Number(raw.trim().replace(/%$/, ''))
  if (!Number.isFinite(value) || value !== Math.min(400, Math.max(10, Math.round(value))))
    throw new Error('缩放比例须为 10–400 之间的整数')
  return value
}
export type WorkbookZoomTarget = { workbookCore: unknown; sheetCore: unknown }
export function captureWorkbookZoomTarget(runtime: any): WorkbookZoomTarget | undefined {
  const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
  return workbook && sheet ? { workbookCore: workbook.getWorkbook?.() ?? workbook, sheetCore: sheet.getSheet?.() ?? sheet } : undefined
}
export function isWorkbookZoomTargetCurrent(runtime: any, target: WorkbookZoomTarget | undefined): boolean {
  const current = captureWorkbookZoomTarget(runtime)
  return !!target && !!current && target.workbookCore === current.workbookCore && target.sheetCore === current.sheetCore
}
export function createWorkbookZoomDialog(root: HTMLElement, onCommand: (command: WorkbookZoomCommand, target?: WorkbookZoomTarget) => void) {
  let target: WorkbookZoomTarget | undefined
  let disposed = false
  const modal = createModal({ root, label: '缩放', overlayClass: 'workbook-zoom-overlay',
    cardClass: 'workbook-ribbon-format-dialog workbook-zoom-dialog', content: `
    <h2>缩放</h2><form novalidate><fieldset><legend>缩放比例</legend>
    ${WORKBOOK_ZOOM_PRESETS.map(value => `<label><input type="radio" name="workbook-zoom-choice" value="${value}">${value}%</label>`).join('')}
    <label><input type="radio" name="workbook-zoom-choice" value="fit">适合选定区域</label>
    <label><input type="radio" name="workbook-zoom-choice" value="custom">自定义 <input data-zoom-custom type="number" min="10" max="400" aria-label="自定义缩放比例">%</label>
    </fieldset><p class="workbook-ribbon-format-error" role="alert"></p>
    <div class="workbook-ribbon-format-actions"><button type="button" data-zoom-cancel>取消</button><button type="submit" data-zoom-apply>确定</button></div></form>` })
  const choices = [...modal.card.querySelectorAll<HTMLInputElement>('[name="workbook-zoom-choice"]')]
  const input = modal.card.querySelector<HTMLInputElement>('[data-zoom-custom]')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  input.addEventListener('focus', () => { choices.find(choice => choice.value === 'custom')!.checked = true })
  input.addEventListener('input', () => { error.textContent = ''; input.removeAttribute('aria-invalid') })
  modal.card.querySelector('[data-zoom-cancel]')!.addEventListener('click', modal.close)
  const apply = () => {
    if (disposed) return
    try {
      const choice = choices.find(item => item.checked)!.value
      onCommand(choice === 'fit' ? 'zoom-to-selection' : `zoom:${choice === 'custom' ? parseWorkbookZoomPercent(input.value) : Number(choice)}`, target)
      modal.close()
    } catch (cause) { error.textContent = (cause as Error).message; input.setAttribute('aria-invalid', 'true') }
  }
  modal.card.querySelector('form')!.addEventListener('submit', event => { event.preventDefault(); apply() })
  modal.card.addEventListener('keydown', event => {
    if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return
    if (event.key === 'Enter' && !(event.target instanceof HTMLButtonElement)) { event.preventDefault(); apply() }
  })
  return {
    open(percent: number, captured?: WorkbookZoomTarget) {
      if (disposed) return
      target = captured
      input.value = String(percent); error.textContent = ''; input.removeAttribute('aria-invalid')
      const preset = WORKBOOK_ZOOM_PRESETS.find(value => value === percent)
      choices.forEach(choice => { choice.checked = choice.value === String(preset ?? 'custom') })
      modal.open(preset ? choices.find(choice => choice.checked) : input)
    },
    dispose() { disposed = true; target = undefined; modal.remove() },
  }
}

// 不对保护或只读做推断；宿主复用视图操作门禁，按实际zoom差分决定是否保存。
export async function applyWorkbookZoomPercent(runtime: any, percent: number, target?: WorkbookZoomTarget) {
  if (target && !isWorkbookZoomTargetCurrent(runtime, target)) return { changed: false, message: '原工作表已切换，请重新打开缩放设置' }
  parseWorkbookZoomPercent(String(percent))
  const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
  if (!workbook || !sheet) return { changed: false, message: '工作表视图尚未就绪' }
  const core = workbook.getWorkbook?.() ?? workbook
  const current = Math.round(sheet.getZoom() * 100)
  let cause: unknown
  try { await runtime.univerAPI.executeCommand('sheet.command.set-zoom-ratio', {
    unitId: workbook.getId(), subUnitId: sheet.getSheetId(), zoomRatio: percent / 100,
  }) } catch (error) { cause = error }
  const active = runtime.univerAPI.getActiveWorkbook()
  if (!active || (active.getWorkbook?.() ?? active) !== core) return { changed: false, message: '工作簿已关闭或替换' }
  if (Math.round(sheet.getZoom() * 100) !== percent) {
    if (cause) throw cause
    return { changed: false, message: '缩放未应用' }
  }
  return { changed: current !== percent, percent, message: `缩放已调整为 ${percent}%${current !== percent ? '，修改尚未保存' : ''}。` }
}

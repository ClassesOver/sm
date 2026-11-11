import { createModal } from './modal'
import { buttonClasses } from './button'
import { parseTwips } from './vendor/genoffice-docs/apps/docs/src/renderer/ai/lengths'

export type DocxTableMargins = { top: number; right: number; bottom: number; left: number }
const sides = ['top', 'right', 'bottom', 'left'] as const
/** pt初值可精确表达整数twip；未改字段直接保留capture值，避免单位往返量化。 */
export function openDocxCellMarginsDialog(root: HTMLElement, initial: DocxTableMargins, inherited: readonly string[], apply: (margins: DocxTableMargins) => void) {
  const labels = { top: '上', right: '右', bottom: '下', left: '左' }
  const modal = createModal({ root, label: '默认单元格边距', closeLabel: '关闭默认单元格边距', onRequestClose: () => modal.remove(), content: `
    <h2>默认单元格边距</h2><form novalidate>
      ${sides.map(side => `<label>${labels[side]}（pt）<input data-margin="${side}" aria-label="${labels[side]}边距（pt）" type="text">${inherited.includes(side) ? '<small>使用来源默认值</small>' : ''}</label>`).join('')}
      <p>调整整表默认值，保留单元格已有自定义边距。可输入 cm、mm、in、pt 等单位；未写单位按 pt。</p>
      <p role="alert"></p><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button></form>` })
  const inputs = Object.fromEntries(sides.map(side => [side, modal.card.querySelector<HTMLInputElement>(`[data-margin="${side}"]`)!])) as Record<typeof sides[number], HTMLInputElement>
  const original = Object.fromEntries(sides.map(side => [side, String(initial[side] / 20)])) as Record<typeof sides[number], string>
  for (const side of sides) inputs[side].value = original[side]
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      const margins = { ...initial }
      for (const side of sides) {
        const value = inputs[side].value.trim()
        if (value === original[side]) continue
        const numeric = /^-?\d+(?:\.\d+)?$/.test(value)
        const twips = parseTwips(numeric ? `${value}pt` : value)
        if (!value || value.startsWith('-') || twips === undefined || !Number.isSafeInteger(twips) || twips < 0 || twips > 28350 || numeric && Number(value) < 0) throw new Error('边距须为 0–1417.5 pt 的有效长度')
        margins[side] = twips
      }
      apply(margins); modal.remove()
    } catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  })
  modal.open(inputs.top)
}

import { createModal } from './modal'
import { buttonClasses } from './button'
import { parseTwips } from './vendor/genoffice-docs/apps/docs/src/renderer/ai/lengths'
import type { DocxTableMargins } from './docx-table-cell-margins-controls'

const sides = ['top', 'right', 'bottom', 'left'] as const
/** null初值表示选区混合值；undefined回执表示未修改，仍交宿主校验过期选区。 */
export function openDocxCellMarginOverridesDialog(root: HTMLElement, initial: Record<keyof DocxTableMargins, number | null>, coverage: string, apply: (value: DocxTableMargins | null | undefined) => void, rows?: { reason: string | null; open: () => void }, alignment?: { reason: string | null; open: () => void }) {
  const labels = { top: '上', right: '右', bottom: '下', left: '左' }
  const modal = createModal({ root, label: '单元格边距', closeLabel: '关闭单元格边距', onRequestClose: () => modal.remove(), content: `
    <h2>单元格边距</h2>${rows ? '<button type="button" data-action="row-breaks">行跨页</button><p data-row-reason></p>' : ''}${alignment ? '<button type="button" data-action="table-alignment">整表对齐</button><p data-alignment-reason></p>' : ''}<form novalidate>
      ${sides.map(side => `<label>${labels[side]}（pt）<input data-margin="${side}" aria-label="${labels[side]}边距（pt）" type="text"></label>`).join('')}
      <p data-source-state></p><p>仅调整所选单元格。多个值留空；自定义时需填写完整四边。可输入 cm、mm、in、pt 等单位，未写单位按 pt。</p>
      <p>恢复继承会移除单元格自定义边距，采用来源样式、行和整表默认值。</p>
      <p role="alert"></p><button type="button" data-action="inherit" class="${buttonClasses('secondary')}">恢复继承</button><button type="button" data-action="cancel" class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button></form>` })
  if (rows) {
    const button = modal.card.querySelector<HTMLButtonElement>('[data-action="row-breaks"]')!
    button.disabled = rows.reason !== null; modal.card.querySelector('[data-row-reason]')!.textContent = rows.reason
    button.addEventListener('click', () => { try { rows.open(); modal.remove() } catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) } })
  }
  if (alignment) {
    const button = modal.card.querySelector<HTMLButtonElement>('[data-action="table-alignment"]')!
    button.disabled = alignment.reason !== null; modal.card.querySelector('[data-alignment-reason]')!.textContent = alignment.reason
    button.addEventListener('click', () => { try { alignment.open(); modal.remove() } catch (error) { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) } })
  }
  modal.card.querySelector('[data-source-state]')!.textContent = coverage
  const inputs = Object.fromEntries(sides.map(side => [side, modal.card.querySelector<HTMLInputElement>(`[data-margin="${side}"]`)!])) as Record<typeof sides[number], HTMLInputElement>
  const original = Object.fromEntries(sides.map(side => [side, initial[side] === null ? '' : String(initial[side]! / 20)])) as Record<typeof sides[number], string>
  for (const side of sides) { inputs[side].value = original[side]; if (initial[side] === null) inputs[side].placeholder = '多个值' }
  const submit = (value: DocxTableMargins | null | undefined) => { apply(value); modal.remove() }
  const fail = (error: unknown) => { modal.card.querySelector('[role="alert"]')!.textContent = error instanceof Error ? error.message : String(error) }
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.remove)
  modal.card.querySelector('[data-action="inherit"]')!.addEventListener('click', () => { try { submit(null) } catch (error) { fail(error) } })
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (sides.every(side => inputs[side].value.trim() === original[side])) { submit(undefined); return }
      const margins = {} as DocxTableMargins
      for (const side of sides) {
        const value = inputs[side].value.trim()
        if (!value && initial[side] === null) throw new Error('选区包含多个值，自定义时请填写完整四边边距')
        if (value === original[side] && initial[side] !== null) { margins[side] = initial[side]!; continue }
        const numeric = /^-?\d+(?:\.\d+)?$/.test(value)
        const twips = parseTwips(numeric ? `${value}pt` : value)
        if (!value || value.startsWith('-') || twips === undefined || !Number.isSafeInteger(twips) || twips < 0 || twips > 28350) throw new Error('边距须为 0–1417.5 pt 的有效长度')
        margins[side] = twips
      }
      submit(sides.every(side => margins[side] === initial[side]) ? undefined : margins)
    } catch (error) { fail(error) }
  })
  modal.open(inputs.top)
}

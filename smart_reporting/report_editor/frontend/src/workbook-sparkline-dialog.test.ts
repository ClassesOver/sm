import { expect, it, vi } from 'vitest'
import { createSparklineDialog } from './workbook-sparkline-dialog'

it('prepopulates group settings, applies them to captured host and supports cancel', () => {
  document.body.replaceChildren()
  const apply = vi.fn(), dialog = createSparklineDialog(document.body, apply)
  const spec = { kind: 'winLoss' as const, source: 'A1:C1', target: 'D1', color: '#123456', negativeColor: '#654321', markers: true, showAxis: true }
  const target = { sheetId: 'sheet-1', target: 'D1' }
  dialog.open(spec, target)
  expect((document.querySelector('[aria-label="迷你图类型"]') as HTMLSelectElement).value).toBe('stacked')
  expect((document.querySelector('[aria-label="系列颜色"]') as HTMLInputElement).value).toBe('#123456')
  expect((document.querySelector('[aria-label="负值颜色"]') as HTMLInputElement).value).toBe('#654321')
  document.querySelector<HTMLButtonElement>('[data-sparkline-cancel]')!.click()
  expect(apply).not.toHaveBeenCalled()
  dialog.open(spec, target)
  document.querySelector<HTMLFormElement>('form')!.requestSubmit()
  expect(apply).toHaveBeenCalledWith({ type: 'stacked', color: '#123456', negativeColor: '#654321', markers: true, showAxis: true }, target)
  dialog.dispose(); document.body.replaceChildren()
})

it('keeps the dialog open and reports apply failures', () => {
  document.body.replaceChildren()
  const dialog = createSparklineDialog(document.body, () => { throw new Error('保存中') })
  dialog.open({ kind: 'line', source: 'A1:C1', target: 'D1' }, { sheetId: 'sheet-1', target: 'D1' })
  document.querySelector<HTMLFormElement>('form')!.requestSubmit()
  expect(document.querySelector('[role=alert]')!.textContent).toBe('保存中')
  expect(document.querySelector('[role=dialog]')!.hasAttribute('hidden')).toBe(false)
  dialog.dispose(); document.body.replaceChildren()
})

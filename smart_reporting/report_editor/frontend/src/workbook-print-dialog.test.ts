import { afterEach, expect, it, vi } from 'vitest'
import { buildWorkbookPrintJob, createPrintPreviewDialog, createWorkbookPrintPreviewDialog, printDialogSettings, printDialogPatch, printJobPageRange, type WorkbookPrintJob } from './workbook-print-preview'
import type { SheetPrintSetup } from './workbook-print'

const setup: SheetPrintSetup = { orientation: 'landscape', paperSize: 12, scale: 85, fitToPage: true, fitToWidth: 2, fitToHeight: 3, margins: { left: .31, right: .42, top: .53, bottom: .64 }, printGridlines: true, printHeadings: false, printArea: null, printTitles: null, rowBreaks: [], colBreaks: [] }
const job = (): WorkbookPrintJob => buildWorkbookPrintJob(['First', 'Second', 'Third'].map((name, index) => ({ sheetId: String(index), source: { name, cells: { A1: { value: name } }, merges: [], columnWidths: {}, rowHeights: {}, hiddenColumns: new Set<number>(), hiddenRows: new Set<number>() }, setup: { ...setup, fitToPage: false, scale: 100 } })))!
const settle = () => new Promise(resolve => setTimeout(resolve, 180))
const root = () => { const node = document.createElement('div'); document.body.append(node); return node }
const change = (root: HTMLElement, field: string, value: string | boolean) => {
  const input = root.querySelector<HTMLInputElement>(`[data-print-${field}]`)!
  if (typeof value === 'boolean') input.checked = value
  else input.value = value
  input.dispatchEvent(new Event('change'))
}
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })

it('preserves file fit counts/custom margins and derives all source scaling modes', () => {
  const initial = printDialogSettings(setup, 'custom')
  expect(initial).toMatchObject({ orientation: 'landscape', paperSize: 12, margins: 'custom', scaling: 'fit-file', scale: 100 })
  expect(printDialogPatch(initial)).toEqual({ orientation: 'landscape', paperSize: 12, printGridlines: true, printHeadings: false })
  for (const [scaling, expected] of [
    ['sheet', { fitToWidth: 1, fitToHeight: 1, fitToPage: true }],
    ['columns', { fitToWidth: 1, fitToHeight: 0, fitToPage: true }],
    ['rows', { fitToWidth: 0, fitToHeight: 1, fitToPage: true }],
    ['none', { scale: 100, fitToPage: false }],
    ['custom', { scale: 175, fitToPage: false }],
  ] as const) expect(printDialogPatch({ ...initial, scaling, scale: 175 })).toMatchObject(expected)
  expect(printDialogSettings({ ...setup, fitToPage: false }, 'normal').scaling).toBe('custom')
  expect(printDialogSettings({ ...setup, fitToPage: false, scale: 100 }, 'normal').scaling).toBe('none')
  expect(() => printDialogPatch({ ...initial, scaling: 'custom', scale: 401 })).toThrow('10')
})

it('filters inclusive output pages without changing original job or job-wide page numbers', () => {
  const built = job(), html = printJobPageRange(built, { from: 2, to: 3 })
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  expect(parsed.querySelectorAll('.page')).toHaveLength(2)
  expect(parsed.body.textContent).toContain('Second'); expect(parsed.body.textContent).toContain('Third')
  expect(parsed.body.textContent).not.toContain('First')
  expect(new DOMParser().parseFromString(built.html, 'text/html').querySelectorAll('.page')).toHaveLength(3)
  for (const range of [{ from: 0, to: 1 }, { from: 2, to: 1 }, { from: 1, to: 4 }, { from: 1.5, to: 2 }]) expect(() => printJobPageRange(built, range)).toThrow('页码')
})

it('shows source settings, persists one field, rebuilds previews, and prints only requested pages', async () => {
  const node = root(), patches: unknown[] = [], printed: string[] = []
  const dialog = createPrintPreviewDialog(node, {
    initial: async () => ({ setup, marginsPreset: 'custom', canEdit: true }),
    applySetup: async patch => { patches.push(patch) },
    buildJob: async () => job(), print: html => { printed.push(html); return true },
  })
  dialog.open({ hasSelection: true, sheetCount: 3 }); await settle()
  expect(node.querySelectorAll('[data-print-paper] option')).toHaveLength(9)
  expect((node.querySelector('[data-print-scaling]') as HTMLSelectElement).value).toBe('fit-file')
  expect((node.querySelector('[data-print-margins]') as HTMLSelectElement).value).toBe('custom')
  change(node, 'orientation', 'portrait'); await settle(); expect(patches).toEqual([{ orientation: 'portrait' }])
  change(node, 'scaling', 'columns'); await settle(); expect(patches[1]).toEqual({ fitToWidth: 1, fitToHeight: 0, fitToPage: true })
  change(node, 'gridlines', false); await settle(); expect(patches[2]).toEqual({ printGridlines: false })
  change(node, 'pages-mode', 'range'); change(node, 'from', '3'); change(node, 'to', '2')
  expect((node.querySelector('[data-print-submit]') as HTMLButtonElement).disabled).toBe(true)
  change(node, 'from', '2'); change(node, 'to', '3')
  ;(node.querySelector('[data-print-submit]') as HTMLButtonElement).click(); await settle()
  expect(printed).toHaveLength(1)
  expect(new DOMParser().parseFromString(printed[0]!, 'text/html').querySelectorAll('.page')).toHaveLength(2)
  dialog.dispose()
})

it('refreshes after page setup and exposes actual/fit zoom without writing settings', async () => {
  const node = root(); let builds = 0, pageSetups = 0
  const dialog = createPrintPreviewDialog(node, { initial: async () => ({ setup, marginsPreset: 'custom', canEdit: true }), applySetup: async () => {}, buildJob: async () => { builds++; return job() }, print: () => true, pageSetup: async () => { pageSetups++ } })
  dialog.open({ hasSelection: true, sheetCount: 3 }); await settle()
  const zoom = node.querySelector<HTMLButtonElement>('[data-print-zoom]')!
  zoom.click(); expect(node.querySelector<HTMLIFrameElement>('iframe')!.style.transform).toBe('scale(1)')
  expect(zoom.getAttribute('aria-pressed')).toBe('false')
  ;(node.querySelector('[data-print-page-setup]') as HTMLButtonElement).click(); await settle()
  expect(pageSetups).toBe(1); expect(builds).toBe(2)
  ;(node.querySelector('[data-print-refresh]') as HTMLButtonElement).click(); await settle(); expect(builds).toBe(3)
  dialog.dispose()
})

it('drops stale/failed preview and never enables output after cancellation or build failure', async () => {
  const node = root(); let complete!: (job: WorkbookPrintJob) => void, calls = 0
  const dialog = createPrintPreviewDialog(node, { initial: async () => ({ setup, marginsPreset: 'custom', canEdit: true }), applySetup: async () => {}, buildJob: async () => { calls++; if (calls === 1) return job(); if (calls === 2) throw new Error('capture stale'); return new Promise(resolve => { complete = resolve }) }, print: () => true })
  dialog.open({ hasSelection: false, sheetCount: 3 }); await settle()
  ;(node.querySelector('[data-print-refresh]') as HTMLButtonElement).click(); await settle()
  expect(node.querySelector('iframe')!.srcdoc).toBe('')
  expect((node.querySelector('[data-print-submit]') as HTMLButtonElement).disabled).toBe(true)
  expect(node.querySelector('[role=alert]')!.textContent).toContain('capture stale')
  ;(node.querySelector('[data-print-refresh]') as HTMLButtonElement).click(); await settle()
  ;(node.querySelector('[data-print-cancel]') as HTMLButtonElement).click(); complete(job()); await settle()
  expect(node.querySelector('iframe')!.srcdoc).toBe(''); dialog.dispose()
})

it('applies overrides only to the active sheet and refuses stale settings writes', async () => {
  const node = root(), writes: unknown[] = []; let current = true
  const capture = async () => ({ snapshot: { sheetOrder: ['a', 'b'], sheets: { a: { name: 'A', cellData: { 0: { 0: { v: 'A' } } } }, b: { name: 'B', cellData: { 0: { 0: { v: 'B' } } } } } }, model: { sheets: [{ name: 'A', pageSetup: { orientation: 'portrait' as const, paperSize: 9 } }, { name: 'B', pageSetup: { orientation: 'portrait' as const, paperSize: 9 } }] }, activeSheetId: 'a', selection: null, current: () => current, canEdit: true })
  const printed: string[] = [], dialog = createWorkbookPrintPreviewDialog(node, { capture, applySetup: async (_captured, patch) => { writes.push(patch) }, print: html => { printed.push(html); return true } })
  dialog.open({ hasSelection: false, sheetCount: 2 }); await settle()
  change(node, 'orientation', 'landscape'); await settle(); change(node, 'scope', 'workbook'); await settle()
  ;(node.querySelector('[data-print-submit]') as HTMLButtonElement).click(); await settle()
  expect(printed[0]).toContain('@page sheet0'); expect(printed[0]).toContain('size: 11.69in 8.27in')
  expect(printed[0]).toContain('size: 8.27in 11.69in')
  dialog.open({ hasSelection: false, sheetCount: 2 }); await settle(); current = false
  change(node, 'paper', '8'); await settle(); expect(writes).toEqual([{ orientation: 'landscape' }])
  expect(node.querySelector('[role=alert]')!.textContent).toMatch(/变化|重新/); dialog.dispose()
})

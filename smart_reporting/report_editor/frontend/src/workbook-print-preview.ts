import { buildSheetPrintHtml, planSheetPrint, printSourceFromSnapshotSheet, type PrintArea, type SheetPrintContext, type SheetPrintSetup, type SheetPrintSource } from './workbook-print'
import { pageBreakPreviewSetup } from './workbook-page-break-context'
import type { UniverStyleData } from './workbook-vendor/core/style-map'
import { createModal } from './modal'

// Fixed GenOffice f8c17004 PrintDialog / assemblePrintHtml: job-wide page
// numbers, sheet-local first-page variants, and named paper per document.
export type PrintScope = 'active' | 'selection' | 'workbook'
export interface WorkbookPrintInput { sheetId: string; source: SheetPrintSource; setup: SheetPrintSetup }
export interface PrintSnapshot { sheetOrder: readonly string[]; sheets: Readonly<Record<string, { name?: string; hidden?: number }>>; styles?: Readonly<Record<string, UniverStyleData>> }
export interface PrintModel { sheets: readonly (NonNullable<Parameters<typeof pageBreakPreviewSetup>[0]> & { name: string })[] }
export function printInputsForScope(snapshot: PrintSnapshot, model: PrintModel, scope: PrintScope, activeSheetId: string, selection: PrintArea | null): WorkbookPrintInput[] {
  if (scope === 'selection' && !selection) throw new Error('请先选定需要打印的区域。')
  const ids = scope === 'workbook' ? snapshot.sheetOrder.filter(id => snapshot.sheets[id] && snapshot.sheets[id]!.hidden !== 1) : [activeSheetId]
  return ids.map(sheetId => {
    const sheet = snapshot.sheets[sheetId], file = model.sheets.find(item => item.name === sheet?.name)
    if (!sheet?.name || !file) throw new Error('无法读取工作表打印设置或网格快照，请重新加载。')
    const setup = pageBreakPreviewSetup(file, {})
    if (scope === 'selection' && selection) {
      const column = (index: number) => { let name = ''; for (let value = index + 1; value > 0; value = Math.floor((value - 1) / 26)) name = String.fromCharCode(65 + (value - 1) % 26) + name; return name }
      return { sheetId, source: printSourceFromSnapshotSheet(sheet, snapshot.styles), setup: { ...setup, printArea: `${column(selection.startColumn)}${selection.startRow + 1}:${column(selection.endColumn)}${selection.endRow + 1}` } }
    }
    return { sheetId, source: printSourceFromSnapshotSheet(sheet, snapshot.styles), setup }
  })
}
export interface WorkbookPrintJob {
  html: string
  pages: readonly { sheetId: string; sheetName: string; widthIn: number; heightIn: number }[]
  pageCount: number
}
export function buildWorkbookPrintJob(inputs: readonly WorkbookPrintInput[], context: SheetPrintContext = {}): WorkbookPrintJob | null {
  const planned = inputs.map(input => ({ input, plan: planSheetPrint(input.source, input.setup) })).filter(item => item.plan !== null)
  const pageCount = planned.reduce((sum, item) => sum + item.plan!.pages.length, 0)
  if (!pageCount) return null
  const styles: string[] = [], bodies: string[] = [], pages: WorkbookPrintJob['pages'][number][] = []
  const now = context.now ?? new Date()
  for (const [index, { input, plan }] of planned.entries()) {
    const html = buildSheetPrintHtml(input.source, input.setup, { ...context, now, pageOffset: pages.length, totalPages: pageCount, pageName: `sheet${index}` })!
    const parsed = new DOMParser().parseFromString(html, 'text/html')
    styles.push(parsed.querySelector('style')!.textContent!)
    bodies.push(parsed.body.innerHTML)
    for (const _page of plan!.pages) pages.push({ sheetId: input.sheetId, sheetName: input.source.name, ...plan!.paper })
  }
  return { html: `<!DOCTYPE html><html><head><meta charset="utf-8"><title>打印工作簿</title><style>${styles.join('')}</style></head><body>${bodies.join('')}</body></html>`, pages, pageCount }
}

interface PrintPreviewHost { buildJob(scope: PrintScope): Promise<WorkbookPrintJob>; print(html: string): boolean }
export interface WorkbookPrintCapture { snapshot: PrintSnapshot; model: PrintModel; activeSheetId: string; selection: PrintArea | null; current: () => boolean; fileName?: string }
export function createWorkbookPrintPreviewDialog(root: HTMLElement, host: { capture(): Promise<WorkbookPrintCapture>; print(html: string): boolean }) {
  return createPrintPreviewDialog(root, {
    buildJob: async scope => {
      const captured = await host.capture()
      if (!captured.current()) throw new Error('工作簿或选区已变化，请重新预览或打印。')
      const job = buildWorkbookPrintJob(printInputsForScope(captured.snapshot, captured.model, scope, captured.activeSheetId, captured.selection), { fileName: captured.fileName ?? '' })
      if (!job) throw new Error('没有可打印的内容。')
      return job
    },
    print: host.print,
  })
}
export function createPrintPreviewDialog(root: HTMLElement, host: PrintPreviewHost) {
  let generation = 0, disposed = false, job: WorkbookPrintJob | undefined, page = 0
  const close = () => { generation++; job = undefined; frame.srcdoc = ''; modal.close() }
  const modal = createModal({ root, label: '打印预览', variant: 'wide', onRequestClose: close, content: `<h2>打印预览</h2><label>打印范围 <select data-print-scope><option value=active>当前工作表</option><option value=selection>选定区域</option><option value=workbook>整个工作簿</option></select></label><div style="display:flex;align-items:center;gap:12px;margin:12px 0"><button type=button data-print-prev>上一页</button><span data-print-page aria-live=polite></span><button type=button data-print-next>下一页</button></div><div data-print-pane style="height:52vh;overflow:auto;background:#e8e8e8;display:flex;justify-content:center;align-items:flex-start"><iframe data-print-preview title="打印页面预览" sandbox="" style="border:0;flex-shrink:0;transform-origin:top center"></iframe></div><p data-print-error role=alert></p><div class=workbook-ribbon-format-actions><button type=button data-print-cancel>取消</button><button type=button data-print-submit>打印</button></div>` })
  const find = <T extends HTMLElement>(name: string) => modal.card.querySelector<T>(`[data-print-${name}]`)!
  const scope = find<HTMLSelectElement>('scope'), frame = find<HTMLIFrameElement>('preview'), error = find('error')
  const previous = find<HTMLButtonElement>('prev'), next = find<HTMLButtonElement>('next'), submit = find<HTMLButtonElement>('submit')
  const show = () => {
    if (!job) return
    page = Math.max(0, Math.min(page, job.pageCount - 1))
    const current = job.pages[page]!
    find('page').textContent = `${page + 1} / ${job.pageCount} · ${current.sheetName}`
    previous.disabled = page === 0; next.disabled = page === job.pageCount - 1
    const width = current.widthIn * 96, height = current.heightIn * 96
    const zoom = Math.min(1, (find('pane').clientWidth || 700) / width, (find('pane').clientHeight || 440) / height)
    frame.style.width = `${width}px`; frame.style.height = `${height}px`; frame.style.transform = `scale(${zoom})`
    frame.srcdoc = job.html.replace('</style>', `.page{display:none}.page:nth-child(${page + 1}){display:block}</style>`)
  }
  const build = async (printing = false) => {
    const token = ++generation
    submit.disabled = true; previous.disabled = true; next.disabled = true; error.textContent = ''
    try {
      const fresh = await host.buildJob(scope.value as PrintScope)
      if (disposed || modal.overlay.hidden || token !== generation) return
      job = fresh; show(); submit.disabled = false
      if (printing) {
        if (!host.print(fresh.html)) throw new Error('当前环境无法打开打印对话框。')
        close()
      }
    } catch (cause) {
      if (disposed || modal.overlay.hidden || token !== generation) return
      error.textContent = cause instanceof Error ? cause.message : String(cause)
      submit.disabled = false
    }
  }
  scope.addEventListener('change', () => { page = 0; job = undefined; frame.srcdoc = ''; void build() })
  previous.addEventListener('click', () => { page--; show() })
  next.addEventListener('click', () => { page++; show() })
  submit.addEventListener('click', () => { if (!modal.overlay.hidden && !submit.disabled) void build(true) })
  find('cancel').addEventListener('click', close)
  return {
    open(options: { hasSelection: boolean; sheetCount: number }) {
      if (disposed) return
      scope.value = 'active'; scope.querySelector<HTMLOptionElement>('[value=selection]')!.disabled = !options.hasSelection
      scope.querySelector<HTMLOptionElement>('[value=workbook]')!.textContent = `整个工作簿（${options.sheetCount} 张表）`
      page = 0; job = undefined; frame.srcdoc = ''; find('page').textContent = '正在准备预览…'; modal.open(scope); void build()
    },
    dispose() { disposed = true; generation++; job = undefined; modal.remove() },
  }
}

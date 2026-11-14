import { buildSheetPrintHtml, planSheetPrint, printSourceFromSnapshotSheet, PRINT_MARGIN_PRESETS, type PrintMarginPreset, type PrintArea, type SheetPrintContext, type SheetPrintSetup, type SheetPrintSource } from './workbook-print'
import { pageBreakPreviewSetup } from './workbook-page-break-context'
import type { HeaderFooterPicture } from '@sheets-web/xlsx-engine'
import type { UniverStyleData } from './workbook-vendor/core/style-map'
import { createModal } from './modal'
import './workbook-print-preview.css'

// Fixed GenOffice f8c17004 PrintDialog / assemblePrintHtml: job-wide page
// numbers, sheet-local first-page variants, and named paper per document.
export type PrintScope = 'active' | 'selection' | 'workbook'
export interface WorkbookPrintInput { sheetId: string; source: SheetPrintSource; setup: SheetPrintSetup }
export interface PrintSnapshot { sheetOrder: readonly string[]; sheets: Readonly<Record<string, { name?: string; hidden?: number }>>; styles?: Readonly<Record<string, UniverStyleData>> }
export interface PrintModel { sheets: readonly (NonNullable<Parameters<typeof pageBreakPreviewSetup>[0]> & { name: string })[] }
export function printInputsForScope(snapshot: PrintSnapshot, model: PrintModel, scope: PrintScope, activeSheetId: string, selection: PrintArea | null,
  headerFooterPictures?: ReadonlyMap<string, ReadonlyMap<string, HeaderFooterPicture>>): WorkbookPrintInput[] {
  if (scope === 'selection' && !selection) throw new Error('请先选定需要打印的区域。')
  const ids = scope === 'workbook' ? snapshot.sheetOrder.filter(id => snapshot.sheets[id] && snapshot.sheets[id]!.hidden !== 1) : [activeSheetId]
  return ids.map(sheetId => {
    const sheet = snapshot.sheets[sheetId], file = model.sheets.find(item => item.name === sheet?.name)
    if (!sheet?.name || !file) throw new Error('无法读取工作表打印设置或网格快照，请重新加载。')
    const setup = pageBreakPreviewSetup(file, {})
    if (scope === 'selection' && selection) {
      const column = (index: number) => { let name = ''; for (let value = index + 1; value > 0; value = Math.floor((value - 1) / 26)) name = String.fromCharCode(65 + (value - 1) % 26) + name; return name }
      return { sheetId, source: printSourceFromSnapshotSheet(sheet, snapshot.styles, headerFooterPictures?.get(file.name)), setup: { ...setup, printArea: `${column(selection.startColumn)}${selection.startRow + 1}:${column(selection.endColumn)}${selection.endRow + 1}` } }
    }
    return { sheetId, source: printSourceFromSnapshotSheet(sheet, snapshot.styles, headerFooterPictures?.get(file.name)), setup }
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

type Scaling = 'none' | 'sheet' | 'columns' | 'rows' | 'fit-file' | 'custom'
export interface PrintDialogSettings { orientation: 'portrait' | 'landscape'; paperSize: number; margins: PrintMarginPreset; scaling: Scaling; scale: number; printGridlines: boolean; printHeadings: boolean }
export interface PrintDialogPatch { orientation?: 'portrait' | 'landscape'; paperSize?: number; margins?: Exclude<PrintMarginPreset, 'custom'>; scale?: number; fitToPage?: boolean; fitToWidth?: number; fitToHeight?: number; printGridlines?: boolean; printHeadings?: boolean }
interface PrintDialogInitial { setup: SheetPrintSetup; marginsPreset: PrintMarginPreset; canEdit: boolean }
const papers = [[1, 'Letter'], [5, 'Legal'], [3, 'Tabloid'], [7, 'Executive'], [8, 'A3'], [9, 'A4'], [11, 'A5'], [12, 'B4'], [13, 'B5']] as const
// Fixed source PrintDialog.tsx: file-only margins and non-standard fit counts
// stay untouched until the user chooses another preset.
export function printDialogSettings(setup: SheetPrintSetup, margins: PrintMarginPreset): PrintDialogSettings {
  const scaling: Scaling = !setup.fitToPage ? setup.scale === 100 ? 'none' : 'custom'
    : setup.fitToWidth === 1 && setup.fitToHeight === 1 ? 'sheet'
      : setup.fitToWidth === 1 && setup.fitToHeight === 0 ? 'columns'
        : setup.fitToWidth === 0 && setup.fitToHeight === 1 ? 'rows' : 'fit-file'
  return { orientation: setup.orientation, paperSize: setup.paperSize, margins, scaling, scale: setup.fitToPage ? 100 : setup.scale, printGridlines: setup.printGridlines, printHeadings: setup.printHeadings }
}
const fitFor = (scaling: Scaling) => scaling === 'sheet' ? { fitToWidth: 1, fitToHeight: 1 } : scaling === 'columns' ? { fitToWidth: 1, fitToHeight: 0 } : scaling === 'rows' ? { fitToWidth: 0, fitToHeight: 1 } : null
export function printDialogPatch(settings: PrintDialogSettings): PrintDialogPatch {
  if (settings.scaling === 'custom' && (!Number.isInteger(settings.scale) || settings.scale < 10 || settings.scale > 400)) throw new Error('打印缩放比例须为 10–400 之间的整数。')
  const fit = fitFor(settings.scaling)
  return { orientation: settings.orientation, paperSize: settings.paperSize, ...(settings.margins === 'custom' ? {} : { margins: settings.margins }),
    ...(fit ? { ...fit, fitToPage: true } : settings.scaling === 'fit-file' ? {} : { scale: settings.scaling === 'none' ? 100 : settings.scale, fitToPage: false }),
    printGridlines: settings.printGridlines, printHeadings: settings.printHeadings }
}
export function printJobPageRange(job: WorkbookPrintJob, range: { from: number; to: number } | null): string {
  if (!range) return job.html
  if (!Number.isInteger(range.from) || !Number.isInteger(range.to) || range.from < 1 || range.to < range.from || range.to > job.pageCount) throw new Error('页码范围须在预览页数内，且结束页不得小于起始页。')
  const parsed = new DOMParser().parseFromString(job.html, 'text/html')
  parsed.querySelectorAll('.page').forEach((page, index) => { if (index + 1 < range.from || index + 1 > range.to) page.remove() })
  return '<!DOCTYPE html>' + parsed.documentElement.outerHTML
}
interface PrintPreviewHost {
  buildJob(scope: PrintScope, overrides?: PrintDialogPatch): Promise<WorkbookPrintJob>
  print(html: string): boolean
  initial?(): Promise<PrintDialogInitial>
  applySetup?(patch: PrintDialogPatch): Promise<void>
  pageSetup?: (() => Promise<void>) | undefined
}
export interface WorkbookPrintCapture { snapshot: PrintSnapshot; model: PrintModel; activeSheetId: string; selection: PrintArea | null; current: () => boolean; fileName?: string; marginsPreset?: PrintMarginPreset; canEdit?: boolean; headerFooterPictures?: ReadonlyMap<string, ReadonlyMap<string, HeaderFooterPicture>> }
export function createWorkbookPrintPreviewDialog(root: HTMLElement, host: { capture(): Promise<WorkbookPrintCapture>; print(html: string): boolean; applySetup?(captured: WorkbookPrintCapture, patch: PrintDialogPatch): void; pageSetup?(captured: WorkbookPrintCapture): Promise<void> }) {
  let target: WorkbookPrintCapture | undefined
  const capture = async () => {
    const captured = await host.capture()
    if (!captured.current()) throw new Error('工作簿或选区已变化，请重新预览或打印。')
    target = captured
    return captured
  }
  return createPrintPreviewDialog(root, {
    initial: async () => {
      const captured = await capture(), input = printInputsForScope(captured.snapshot, captured.model, 'active', captured.activeSheetId, captured.selection)[0]!
      return { setup: input.setup, marginsPreset: captured.marginsPreset ?? 'custom', canEdit: captured.canEdit !== false && Boolean(host.applySetup) }
    },
    applySetup: async patch => {
      if (!target?.current()) throw new Error('工作簿或选区已变化，请重新打开打印预览。')
      if (target.canEdit === false || !host.applySetup) throw new Error('当前工作表不可编辑打印设置。')
      host.applySetup(target, patch)
      await capture()
    },
    pageSetup: host.pageSetup ? async () => {
      if (!target?.current()) throw new Error('工作簿或选区已变化，请重新打开打印预览。')
      await host.pageSetup!(target)
    } : undefined,
    buildJob: async (scope, overrides) => {
      const captured = await capture()
      const inputs = printInputsForScope(captured.snapshot, captured.model, scope, captured.activeSheetId, captured.selection, captured.headerFooterPictures).map(input => input.sheetId !== captured.activeSheetId || !overrides ? input : {
        ...input, setup: { ...input.setup, ...overrides, margins: overrides.margins ? PRINT_MARGIN_PRESETS[overrides.margins] : input.setup.margins },
      })
      const job = buildWorkbookPrintJob(inputs, { fileName: captured.fileName ?? '' })
      if (!job) throw new Error('没有可打印的内容。')
      if (!captured.current()) throw new Error('工作簿或选区已变化，请重新预览或打印。')
      return job
    },
    print: host.print,
  })
}
export function createPrintPreviewDialog(root: HTMLElement, host: PrintPreviewHost) {
  let generation = 0, disposed = false, job: WorkbookPrintJob | undefined, page = 0, fit = true, busy = false
  let settings: PrintDialogSettings | undefined, initial: PrintDialogInitial | undefined, timer: ReturnType<typeof setTimeout> | undefined
  const close = () => { generation++; clearTimeout(timer); job = undefined; frame.srcdoc = ''; modal.close() }
  const modal = createModal({ root, label: '打印预览', variant: 'wide', cardClass: 'workbook-ribbon-format-dialog workbook-print-preview-dialog', onRequestClose: close, content: `<h2>打印预览</h2><div class="workbook-print-dialog-body"><div class="workbook-print-dialog-settings"><p>打印机、份数和逐份由浏览器系统打印对话框管理；另存为 PDF 也在系统对话框中选择。</p><label>打印范围 <select data-print-scope><option value=active>当前工作表</option><option value=selection>选定区域</option><option value=workbook>整个工作簿</option></select></label><label>打印页码<select data-print-pages-mode><option value=all>全部页</option><option value=range>指定页</option></select></label><div class="workbook-print-pages-row"><label>从<input data-print-from aria-label="起始页" type=number min=1 value=1 disabled></label><label>至<input data-print-to aria-label="结束页" type=number min=1 value=1 disabled></label></div><fieldset data-print-settings disabled><legend>当前工作表页面设置</legend><label>方向<select data-print-orientation><option value=portrait>纵向</option><option value=landscape>横向</option></select></label><label>纸张<select data-print-paper>${papers.map(([code, label]) => `<option value=${code}>${label}</option>`).join('')}</select></label><label>页边距<select data-print-margins><option value=normal>常规</option><option value=wide>宽</option><option value=narrow>窄</option></select></label><label>缩放<select data-print-scaling><option value=none>无缩放</option><option value=sheet>将工作表调整为一页</option><option value=columns>将所有列调整为一页</option><option value=rows>将所有行调整为一页</option><option value=custom>自定义比例</option></select></label><label data-print-scale-row hidden>自定义比例（%）<input data-print-scale type=number min=10 max=400 step=1></label><label class="workbook-print-check"><input data-print-gridlines type=checkbox>打印网格线</label><label class="workbook-print-check"><input data-print-headings type=checkbox>打印行号列标</label></fieldset><p data-print-settings-note>页面设置更改立即写入草稿；取消只关闭预览。</p></div><div class="workbook-print-dialog-preview"><div class="workbook-print-preview-toolbar"><button type=button data-print-prev aria-label="上一页">‹</button><span data-print-page aria-live=polite></span><button type=button data-print-next aria-label="下一页">›</button><button type=button data-print-zoom aria-pressed=true>实际大小</button><button type=button data-print-refresh>刷新预览</button></div><div data-print-pane class="workbook-print-preview-pane" tabindex="0" role="region" aria-label="打印预览区域"><div data-print-paper-box><iframe data-print-preview title="打印页面预览" sandbox="" tabindex="-1" style="border:0;transform-origin:top left"></iframe></div></div></div></div><p class="workbook-ribbon-format-error" data-print-error role=alert></p><div class=workbook-ribbon-format-actions><button type=button data-print-page-setup>页面设置（页眉页脚）</button><span class=workbook-print-action-spacer></span><button type=button data-print-cancel>取消</button><button type=button data-print-pdf title="打开系统打印，在目标打印机中选择另存为 PDF">另存为 PDF…</button><button type=button class="workbook-ribbon-format-apply" data-print-submit>打印</button></div>` })
  const find = <T extends HTMLElement>(name: string) => modal.card.querySelector<T>(`[data-print-${name}]`)!
  const scope = find<HTMLSelectElement>('scope'), frame = find<HTMLIFrameElement>('preview'), error = find('error')
  const previous = find<HTMLButtonElement>('prev'), next = find<HTMLButtonElement>('next'), submit = find<HTMLButtonElement>('submit'), pdf = find<HTMLButtonElement>('pdf')
  const fields = find<HTMLFieldSetElement>('settings'), pageSetup = find<HTMLButtonElement>('page-setup')
  const pageRange = () => find<HTMLSelectElement>('pages-mode').value === 'all' ? null : { from: Number(find<HTMLInputElement>('from').value), to: Number(find<HTMLInputElement>('to').value) }
  const outputState = () => {
    let invalid = false
    if (job) { try { printJobPageRange(job, pageRange()) } catch { invalid = true } }
    submit.disabled = pdf.disabled = busy || !job || invalid
    fields.disabled = busy || !initial?.canEdit || !host.applySetup
    pageSetup.disabled = busy || !initial?.canEdit || !host.pageSetup
  }
  const syncSettings = () => {
    if (!settings) return
    for (const key of ['orientation', 'paperSize', 'margins', 'scaling', 'scale'] as const) {
      const field = find<HTMLInputElement | HTMLSelectElement>(key === 'paperSize' ? 'paper' : key)
      if (field instanceof HTMLSelectElement && ![...field.options].some(option => option.value === String(settings![key]))) {
        const option = new Option(key === 'paperSize' ? '文件中的纸张' : key === 'margins' ? '文件中的自定义页边距' : `文件中的分页（${initial!.setup.fitToWidth || '*'} × ${initial!.setup.fitToHeight || '*'}）`, String(settings[key]))
        option.dataset.printFileOption = ''; field.add(option)
      }
      field.value = String(settings[key])
    }
    find<HTMLInputElement>('gridlines').checked = settings.printGridlines; find<HTMLInputElement>('headings').checked = settings.printHeadings
    find('scale-row').hidden = settings.scaling !== 'custom'
  }
  const show = () => {
    if (!job) return
    page = Math.max(0, Math.min(page, job.pageCount - 1))
    const current = job.pages[page]!
    find('page').textContent = `${page + 1} / ${job.pageCount} · ${current.sheetName}`
    previous.disabled = page === 0; next.disabled = page === job.pageCount - 1
    const width = current.widthIn * 96, height = current.heightIn * 96
    const zoom = fit ? Math.max(.05, Math.min(((find('pane').clientWidth || 700) - 24) / width, ((find('pane').clientHeight || 440) - 24) / height)) : 1
    frame.style.width = `${width}px`; frame.style.height = `${height}px`; frame.style.transform = `scale(${zoom})`
    find('paper-box').style.width = `${width * zoom}px`; find('paper-box').style.height = `${height * zoom}px`
    frame.srcdoc = job.html.replace('</style>', `.page{display:none}.page:nth-child(${page + 1}){display:block}</style>`)
  }
  const build = async (printing = false) => {
    clearTimeout(timer)
    const token = ++generation
    busy = true; job = undefined; frame.srcdoc = ''; outputState(); previous.disabled = true; next.disabled = true; error.textContent = ''; find('page').textContent = '正在准备预览…'
    try {
      const fresh = settings ? await host.buildJob(scope.value as PrintScope, printDialogPatch(settings)) : await host.buildJob(scope.value as PrintScope)
      if (disposed || modal.overlay.hidden || token !== generation) return
      job = fresh
      for (const name of ['from', 'to']) find<HTMLInputElement>(name).max = String(fresh.pageCount)
      if (Number(find<HTMLInputElement>('to').value) > fresh.pageCount) find<HTMLInputElement>('to').value = String(fresh.pageCount)
      show()
      if (printing) {
        if (!host.print(printJobPageRange(fresh, pageRange()))) throw new Error('当前环境无法打开打印对话框。')
        close()
      }
    } catch (cause) {
      if (disposed || modal.overlay.hidden || token !== generation) return
      error.textContent = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (token === generation) { busy = false; outputState() }
    }
  }
  const update = async (value: Partial<PrintDialogSettings>, patch: PrintDialogPatch) => {
    if (!settings || !host.applySetup || fields.disabled || modal.overlay.hidden) return
    const token = ++generation, nextSettings = { ...settings, ...value }
    try {
      printDialogPatch(nextSettings); busy = true; job = undefined; frame.srcdoc = ''; outputState(); error.textContent = ''
      await host.applySetup(patch)
      if (disposed || modal.overlay.hidden || token !== generation) return
      settings = nextSettings; syncSettings(); busy = false; outputState()
      timer = setTimeout(() => { void build() }, 120)
    } catch (cause) {
      if (disposed || modal.overlay.hidden || token !== generation) return
      busy = false; syncSettings(); outputState(); error.textContent = cause instanceof Error ? cause.message : String(cause)
    }
  }
  for (const name of ['orientation', 'paper', 'margins', 'gridlines', 'headings'] as const) find(name).addEventListener('change', () => {
    const field = find<HTMLInputElement>(name), key = name === 'paper' ? 'paperSize' : name === 'gridlines' ? 'printGridlines' : name === 'headings' ? 'printHeadings' : name
    const value = field.type === 'checkbox' ? field.checked : name === 'paper' ? Number(field.value) : field.value
    void update({ [key]: value }, name === 'margins' && value === 'custom' ? {} : { [key]: value })
  })
  const scalingChanged = () => {
    if (!settings) return
    const scaling = find<HTMLSelectElement>('scaling').value as Scaling, scale = Number(find<HTMLInputElement>('scale').value)
    const fit = fitFor(scaling)
    void update({ scaling, scale }, fit ? { ...fit, fitToPage: true } : scaling === 'fit-file' ? { fitToWidth: initial!.setup.fitToWidth, fitToHeight: initial!.setup.fitToHeight, fitToPage: true } : { scale: scaling === 'none' ? 100 : scale, fitToPage: false })
  }
  find('scaling').addEventListener('change', scalingChanged); find('scale').addEventListener('change', scalingChanged)
  for (const name of ['pages-mode', 'from', 'to']) find(name).addEventListener('change', () => {
    const all = find<HTMLSelectElement>('pages-mode').value === 'all'
    find<HTMLInputElement>('from').disabled = find<HTMLInputElement>('to').disabled = all
    outputState()
  })
  scope.addEventListener('change', () => { page = 0; job = undefined; frame.srcdoc = ''; void build() })
  previous.addEventListener('click', () => { page--; show() })
  next.addEventListener('click', () => { page++; show() })
  find('zoom').addEventListener('click', () => { fit = !fit; find('zoom').setAttribute('aria-pressed', String(fit)); find('zoom').textContent = fit ? '实际大小' : '适合页面'; show() })
  find('refresh').addEventListener('click', () => { if (!modal.overlay.hidden && !busy) void build() })
  pageSetup.addEventListener('click', () => {
    if (!host.pageSetup || pageSetup.disabled || modal.overlay.hidden) return
    const token = ++generation; busy = true; outputState()
    void host.pageSetup().then(() => { if (!disposed && !modal.overlay.hidden && token === generation) void build() }).catch(cause => {
      if (!disposed && !modal.overlay.hidden && token === generation) { busy = false; outputState(); error.textContent = cause instanceof Error ? cause.message : String(cause) }
    })
  })
  submit.addEventListener('click', () => { if (!modal.overlay.hidden && !submit.disabled) void build(true) })
  pdf.addEventListener('click', () => { if (!modal.overlay.hidden && !pdf.disabled) void build(true) })
  find('cancel').addEventListener('click', close)
  const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(() => { if (!modal.overlay.hidden) show() })
  observer?.observe(find('pane'))
  return {
    open(options: { hasSelection: boolean; sheetCount: number }) {
      if (disposed) return
      scope.value = 'active'; scope.querySelector<HTMLOptionElement>('[value=selection]')!.disabled = !options.hasSelection
      scope.querySelector<HTMLOptionElement>('[value=workbook]')!.textContent = `整个工作簿（${options.sheetCount} 张表）`
      clearTimeout(timer); const token = ++generation
      page = 0; fit = true; job = undefined; settings = undefined; initial = undefined; busy = true; frame.srcdoc = ''; error.textContent = ''
      find<HTMLSelectElement>('pages-mode').value = 'all'; find<HTMLInputElement>('from').value = find<HTMLInputElement>('to').value = '1'; find<HTMLInputElement>('from').disabled = find<HTMLInputElement>('to').disabled = true
      find('zoom').setAttribute('aria-pressed', 'true'); find('zoom').textContent = '实际大小'
      modal.card.querySelectorAll('[data-print-file-option]').forEach(option => option.remove())
      find('page').textContent = '正在准备预览…'; outputState(); modal.open(scope)
      if (!host.initial) void build()
      else void host.initial().then(value => {
        if (disposed || modal.overlay.hidden || token !== generation) return
        initial = value; settings = printDialogSettings(value.setup, value.marginsPreset); syncSettings()
        // The file-fit option remains selectable after choosing another mode.
        if (value.setup.fitToPage && ![...find<HTMLSelectElement>('scaling').options].some(option => option.value === 'fit-file')) {
          const option = new Option(`文件中的分页（${value.setup.fitToWidth || '*'} × ${value.setup.fitToHeight || '*'}）`, 'fit-file')
          option.dataset.printFileOption = ''; find<HTMLSelectElement>('scaling').add(option)
        }
        find('settings-note').textContent = value.canEdit ? '页面设置更改立即写入草稿；取消只关闭预览。' : '当前工作表只可预览和打印，页面设置不可编辑。'
        void build()
      }).catch(cause => { if (!disposed && !modal.overlay.hidden && token === generation) { busy = false; outputState(); error.textContent = cause instanceof Error ? cause.message : String(cause) } })
    },
    dispose() { disposed = true; generation++; clearTimeout(timer); observer?.disconnect(); job = undefined; modal.remove() },
  }
}

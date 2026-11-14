import type { NativeDraft, NativeOperation } from './native-draft'
import type { PdfPageIdentity } from './pdf-operations'

export const PDF_STATIC_TEXT_ALONE_REASON = '插入文字须单独保存，请先保存或撤销其他修改'
interface TextConfig { text: string; fontSize: number; color: [number, number, number]; align: 'left' | 'center' | 'right'; font?: 'arial' | 'times' | 'courier'; bold?: boolean; italic?: boolean; lineLeading?: number }
function validateConfig(config: TextConfig) {
  if (typeof config.text !== 'string' || !config.text.trim() || config.text.length > 1000 || /[\p{Cc}\p{Cf}\u2028\u2029]/u.test(config.text.replace(/\n/g, ''))) throw new Error('请输入 1–1000 个字符的文字，仅允许换行，不得含其他控制字符')
  if (!Number.isFinite(config.fontSize) || config.fontSize < 6 || config.fontSize > 72) throw new Error('字号须为 6–72')
  if (!Array.isArray(config.color) || config.color.length !== 3 || config.color.some(value => !Number.isFinite(value) || value < 0 || value > 1)) throw new Error('文字颜色无效')
  if (!['left', 'center', 'right'].includes(config.align)) throw new Error('文字对齐无效')
  if (config.font !== undefined && !['arial', 'times', 'courier'].includes(config.font)) throw new Error('文字字体无效')
  if (config.bold !== undefined && typeof config.bold !== 'boolean' || config.italic !== undefined && typeof config.italic !== 'boolean') throw new Error('文字样式无效')
  if (config.lineLeading !== undefined && (!Number.isFinite(config.lineLeading) || config.lineLeading <= 0)) throw new Error('文字行距须为正数')
}
export function validatePdfStaticText(pages: PdfPageIdentity[], operations: NativeOperation[]) {
  const inserts = operations.filter(operation => operation.kind === 'insertText')
  if (!inserts.length) return
  if (operations.length !== 1) throw new Error(PDF_STATIC_TEXT_ALONE_REASON)
  const operation = inserts[0]!
  if (Object.keys(operation).some(key => !['kind', 'sourceSha256', 'pageId', 'origin', 'text', 'fontSize', 'color', 'align', 'font', 'bold', 'italic', 'lineLeading'].includes(key))) throw new Error('插入文字参数无效')
  validateConfig(operation as unknown as TextConfig)
  const page = pages.find(page => page.pageId === operation.pageId)
  if (!page || page.blank || typeof operation.sourceSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(operation.sourceSha256) || !page.pageId.startsWith(`sha256:${operation.sourceSha256}:page:`)) throw new Error('插入文字来源或页面身份已变化')
  const point = operation.origin
  if (!Array.isArray(point) || point.length !== 2 || point.some(value => typeof value !== 'number' || !Number.isFinite(value))) throw new Error('插入文字落点无效')
  const box = page.cropBox
  if (point[0] < box.x || point[1] < box.y || point[0] > box.x + box.width || point[1] > box.y + box.height) throw new Error('插入文字落点超出当前页面')
}

/** 固定源 App.tsx 的字号/颜色/对齐配置与首行基线放置；保存使用真实 PDF 预览。 */
export function bindPdfStaticText(options: {
  root: HTMLElement; draft: NativeDraft; pages: () => PdfPageIdentity[]
  unavailable: () => string | null; start: () => void; stop: () => void
  refresh: () => Promise<void>; status: (text: string) => void
}) {
  const owner = options.root.ownerDocument, dialog = owner.createElement('dialog')
  dialog.className = 'pdf-layout-dialog pdf-static-text-dialog'; dialog.setAttribute('aria-label', '插入文字')
  const heading = owner.createElement('h3'); heading.textContent = '插入文字'
  const hint = owner.createElement('p'); hint.textContent = '插入可搜索的多行文字。确定后点击页面设置首行对齐基线；每次插入须单独保存。字体缺字可能使用替代字体，请核对 PDF 预览和验收提示。'
  function label(name: string, input: HTMLElement) { const row = owner.createElement('label'); row.textContent = name; input.setAttribute('aria-label', `插入文字${name}`); row.append(input); dialog.append(row); return input }
  dialog.append(heading, hint)
  const text = label('内容', owner.createElement('textarea')) as HTMLTextAreaElement; text.maxLength = 1000; text.rows = 4
  const size = label('字号', owner.createElement('input')) as HTMLInputElement; size.type = 'number'; size.min = '6'; size.max = '72'; size.value = '14'; size.step = 'any'
  const color = label('颜色', owner.createElement('input')) as HTMLInputElement; color.type = 'color'; color.value = '#111111'
  const align = label('对齐', owner.createElement('select')) as HTMLSelectElement
  for (const [value, name] of [['left', '左对齐'], ['center', '居中'], ['right', '右对齐']]) { const option = owner.createElement('option'); option.value = value!; option.textContent = name!; align.append(option) }
  const font = label('字体', owner.createElement('select')) as HTMLSelectElement
  for (const [value, name] of [['', '自动字体'], ['arial', 'Arial / Liberation Sans'], ['times', 'Times / Liberation Serif'], ['courier', 'Courier / Liberation Mono']]) { const option = owner.createElement('option'); option.value = value!; option.textContent = name!; font.append(option) }
  const bold = label('粗体', owner.createElement('input')) as HTMLInputElement; bold.type = 'checkbox'
  const italic = label('斜体', owner.createElement('input')) as HTMLInputElement; italic.type = 'checkbox'
  const leading = label('行距', owner.createElement('input')) as HTMLInputElement; leading.type = 'number'; leading.min = '0'; leading.step = 'any'; leading.placeholder = '自动（字号 × 1.2）'
  const error = owner.createElement('p'); error.setAttribute('role', 'alert')
  const confirm = owner.createElement('button'); confirm.type = 'button'; confirm.textContent = '确定并选择落点'; confirm.dataset.pdfStaticTextConfirm = ''
  const dismiss = owner.createElement('button'); dismiss.type = 'button'; dismiss.textContent = '取消'
  const actions = owner.createElement('div'); actions.className = 'pdf-layout-actions'; actions.append(dismiss, confirm)
  dialog.append(error, actions); options.root.append(dialog)
  let disposed = false, pending: TextConfig | undefined, snapshot = ''
  function cancel() { pending = undefined; if (dialog.open) dialog.close(); options.stop() }
  function reason() { return options.unavailable() ?? (snapshot !== JSON.stringify(options.draft.operations) ? '草稿已变化，请重新配置插入文字' : null) }
  dismiss.addEventListener('click', cancel)
  dialog.addEventListener('cancel', () => { pending = undefined; options.stop() })
  confirm.addEventListener('click', () => {
    if (disposed || !dialog.open) return
    try {
      const blocked = reason(); if (blocked) throw new Error(blocked)
      const rgb = color.value.match(/^#([a-f0-9]{2})([a-f0-9]{2})([a-f0-9]{2})$/i)
      const config = { text: text.value, fontSize: Number(size.value), color: (rgb ? rgb.slice(1).map(value => Number.parseInt(value, 16) / 255) : []) as [number, number, number], align: align.value as TextConfig['align'], ...(font.value ? { font: font.value as TextConfig['font'] } : {}), ...(bold.checked ? { bold: true } : {}), ...(italic.checked ? { italic: true } : {}), ...(leading.value ? { lineLeading: Number(leading.value) } : {}) }
      validateConfig(config); dialog.close(); pending = config; options.start(); options.status('请点击页面选择插入文字的首行基线；按 Escape 取消')
    } catch (cause) { error.textContent = cause instanceof Error ? cause.message : String(cause) }
  })
  const key = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return
    if (event.key === 'Escape' && pending) { cancel(); options.status('已取消插入文字') }
  }
  options.root.addEventListener('keydown', key)
  return {
    open() {
      if (disposed) return
      const blocked = options.unavailable(); if (blocked) { options.status(blocked); return }
      cancel(); snapshot = JSON.stringify(options.draft.operations); error.textContent = ''; text.value = ''; dialog.showModal(); text.focus()
    },
    incompleteReason() { return dialog.open ? '请先完成或取消插入文字配置' : pending ? '请先点击页面选择插入文字落点，或按 Escape 取消' : null },
    cancel,
    refresh() { if (!disposed && (pending || dialog.open) && reason()) cancel() },
    async place(pageId: string, origin: number[]) {
      if (disposed || !pending) return
      const blocked = reason(); if (blocked) { cancel(); throw new Error(blocked) }
      const operation = { kind: 'insertText', sourceSha256: options.draft.identity.sourceSha256, pageId, origin, ...pending }
      validatePdfStaticText(options.pages(), [operation]); options.draft.setOperations([operation]); cancel(); await options.refresh()
    },
    dispose() { if (disposed) return; disposed = true; pending = undefined; options.root.removeEventListener('keydown', key); dialog.remove() },
  }
}

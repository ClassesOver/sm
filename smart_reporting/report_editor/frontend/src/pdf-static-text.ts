import type { NativeDraft, NativeOperation } from './native-draft'
import type { PdfPageIdentity } from './pdf-operations'
import {validatePdfStyledReplacement} from './pdf-replace-text-style'

export const PDF_STATIC_TEXT_ALONE_REASON = '新增文字仅可与原位改字同批；其他类型修改请单独保存'
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
  if (operations.some(operation=>operation.kind!=='insertText'&&operation.kind!=='replaceText')) throw new Error(PDF_STATIC_TEXT_ALONE_REASON)
  validatePdfStyledReplacement(pages,operations)
  if (operations.length > 500) throw new Error('原生编辑操作超限')
  for (const operation of inserts) {
    if (Object.keys(operation).some(key => !['kind', 'sourceSha256', 'pageId', 'origin', 'text', 'fontSize', 'color', 'align', 'font', 'bold', 'italic', 'lineLeading'].includes(key))) throw new Error('插入文字参数无效')
    validateConfig(operation as unknown as TextConfig)
    const page = pages.find(page => page.pageId === operation.pageId)
    if (!page || page.blank || typeof operation.sourceSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(operation.sourceSha256) || !page.pageId.startsWith(`sha256:${operation.sourceSha256}:page:`)) throw new Error('插入文字来源或页面身份已变化')
    const point = operation.origin
    if (!Array.isArray(point) || point.length !== 2 || point.some(value => typeof value !== 'number' || !Number.isFinite(value))) throw new Error('插入文字落点无效')
    const box = page.cropBox
    if (point[0] < box.x || point[1] < box.y || point[0] > box.x + box.width || point[1] > box.y + box.height) throw new Error('插入文字落点超出当前页面')
  }
}

/** 固定源 App.tsx 的字号/颜色/对齐配置与首行基线放置；保存使用真实 PDF 预览。 */
export function bindPdfStaticText(options: {
  root: HTMLElement; draft: NativeDraft; pages: () => PdfPageIdentity[]
  unavailable: () => string | null; editUnavailable?: () => string | null; start: () => void; stop: () => void
  refresh: () => Promise<void>; status: (text: string) => void
}) {
  const owner = options.root.ownerDocument, dialog = owner.createElement('dialog')
  dialog.className = 'pdf-layout-dialog pdf-static-text-dialog'; dialog.setAttribute('aria-label', '插入文字')
  const heading = owner.createElement('h3'); heading.textContent = '插入文字'
  const hint = owner.createElement('p'); hint.textContent = '插入可搜索的多行文字。确定后点击页面设置首行对齐基线；可连续插入多段文字后统一预览和保存。字体缺字可能使用替代字体，请核对 PDF 预览和验收提示。'
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
  const coordinates = owner.createElement('fieldset'); coordinates.hidden = true
  const coordinate = (name: string) => {
    const row=owner.createElement('label');row.textContent=name
    const input=owner.createElement('input');input.type='number';input.step='any';input.setAttribute('aria-label',`插入文字基线 ${name}`);row.append(input);coordinates.append(row);return input
  }
  const originX=coordinate('X'),originY=coordinate('Y');dialog.append(coordinates)
  const error = owner.createElement('p'); error.setAttribute('role', 'alert')
  const confirm = owner.createElement('button'); confirm.type = 'button'; confirm.textContent = '确定并选择落点'; confirm.dataset.pdfStaticTextConfirm = ''
  const dismiss = owner.createElement('button'); dismiss.type = 'button'; dismiss.textContent = '取消'
  const actions = owner.createElement('div'); actions.className = 'pdf-layout-actions'; actions.append(dismiss, confirm)
  dialog.append(error, actions); options.root.append(dialog)
  let disposed = false, pending: TextConfig | undefined, snapshot = '', editIndex: number | undefined
  function cancel() { pending = undefined; editIndex = undefined; if (dialog.open) dialog.close(); options.stop() }
  function reason() { return (editIndex === undefined ? options.unavailable() : (options.editUnavailable ?? options.unavailable)()) ?? (snapshot !== JSON.stringify(options.draft.operations) ? '草稿已变化，请重新配置插入文字' : null) }
  dismiss.addEventListener('click', cancel)
  dialog.addEventListener('cancel', cancel)
  confirm.addEventListener('click', () => {
    if (disposed || !dialog.open) return
    try {
      const blocked = reason(); if (blocked) throw new Error(blocked)
      const rgb = color.value.match(/^#([a-f0-9]{2})([a-f0-9]{2})([a-f0-9]{2})$/i)
      const config = { text: text.value, fontSize: Number(size.value), color: (rgb ? rgb.slice(1).map(value => Number.parseInt(value, 16) / 255) : []) as [number, number, number], align: align.value as TextConfig['align'], ...(font.value ? { font: font.value as TextConfig['font'] } : {}), ...(bold.checked ? { bold: true } : {}), ...(italic.checked ? { italic: true } : {}), ...(leading.value ? { lineLeading: Number(leading.value) } : {}) }
      validateConfig(config)
      if(editIndex !== undefined){
        const operations=options.draft.operations,original=operations[editIndex]!
        if(!originX.value.trim()||!originY.value.trim())throw Error('请输入文字基线 X 和 Y')
        operations[editIndex]={kind:'insertText',sourceSha256:original.sourceSha256,pageId:original.pageId,origin:[Number(originX.value),Number(originY.value)],...config}
        validatePdfStaticText(options.pages(),operations);options.draft.setOperations(operations);cancel()
        options.status('文字修改已加入草稿，请核对实际 PDF 预览')
        void options.refresh().catch(cause=>options.status(`文字修改已加入草稿，但刷新失败：${cause instanceof Error?cause.message:String(cause)}`))
      }else{dialog.close();pending=config;options.start();options.status('请点击页面选择插入文字的首行基线；按 Escape 取消')}

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
      cancel(); snapshot = JSON.stringify(options.draft.operations); error.textContent = ''; text.value = ''; coordinates.hidden=true;heading.textContent='插入文字';hint.textContent='插入可搜索的多行文字。确定后点击页面设置首行对齐基线；可连续插入多段文字后统一预览和保存。字体缺字可能使用替代字体，请核对 PDF 预览和验收提示。';confirm.textContent='确定并选择落点';dialog.setAttribute('aria-label','插入文字');dialog.showModal(); text.focus()
    },
    edit(index: number) {
      if(disposed)return
      const blocked=(options.editUnavailable ?? options.unavailable)();if(blocked){options.status(blocked);return}
      const operations=options.draft.operations,operation=operations[index]
      if(!Number.isInteger(index)||!operation||operation.kind!=='insertText'){options.status('待保存文字已变化，请重新选择');return}
      try{validatePdfStaticText(options.pages(),operations)}catch(cause){options.status(cause instanceof Error?cause.message:String(cause));return}
      cancel();editIndex=index;snapshot=JSON.stringify(operations);error.textContent='';coordinates.hidden=false
      heading.textContent='编辑待保存文字';hint.textContent='修改文字内容、样式或同页基线位置。应用后请核对 PDF 预览；取消不会改变草稿。';dialog.setAttribute('aria-label','编辑待保存文字');confirm.textContent='应用文字修改'
      text.value=String(operation.text);size.value=String(operation.fontSize);align.value=String(operation.align);font.value=String(operation.font??'')
      color.value='#'+(operation.color as number[]).map(value=>Math.round(value*255).toString(16).padStart(2,'0')).join('')
      bold.checked=operation.bold===true;italic.checked=operation.italic===true;leading.value=operation.lineLeading===undefined?'':String(operation.lineLeading)
      const origin=operation.origin as number[];originX.value=String(origin[0]);originY.value=String(origin[1]);dialog.showModal();text.focus()
    },
    incompleteReason() { return dialog.open ? '请先完成或取消插入文字配置' : pending ? '请先点击页面选择插入文字落点，或按 Escape 取消' : null },
    cancel,
    refresh() { if (!disposed && (pending || dialog.open) && reason()) cancel() },
    async place(pageId: string, origin: number[]) {
      if (disposed || !pending) return
      const blocked = reason(); if (blocked) { cancel(); throw new Error(blocked) }
      const operation = { kind: 'insertText', sourceSha256: options.draft.identity.sourceSha256, pageId, origin, ...pending }
      const operations = [...options.draft.operations, operation].map(item=>item.kind==='replaceText'&&item.sourceSha256===undefined?{...item,sourceSha256:options.draft.identity.sourceSha256}:item)
      validatePdfStaticText(options.pages(), operations); options.draft.setOperations(operations); cancel(); await options.refresh()
    },
    dispose() { if (disposed) return; disposed = true; pending = undefined; options.root.removeEventListener('keydown', key); dialog.remove() },
  }
}

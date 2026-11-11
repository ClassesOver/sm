import type { NativeSaveResponse } from './native-api'

/** 页码属于已保存来源；保持用户给出的顺序，不默默去重或丢弃越界项。 */
export function parsePdfExtractPages(value: string, total: number): number[] {
  if (!Number.isSafeInteger(total) || total < 1 || total > 10000 || !value.trim()) throw new Error('请输入有效页码')
  const pages: number[] = [], used = new Set<number>()
  for (const part of value.split(',')) {
    const match = /^\s*(\d+)(?:\s*-\s*(\d+))?\s*$/.exec(part)
    if (!match) throw new Error('页码格式无效，请使用 1,3-5')
    const first = Number(match[1]), last = Number(match[2] ?? match[1])
    if (!Number.isSafeInteger(first) || !Number.isSafeInteger(last) || first < 1 || last > total || last < first) throw new Error('页码超出范围或顺序无效')
    for (let page = first; page <= last; page++) {
      if (used.has(page)) throw new Error('页码不能重复')
      used.add(page); pages.push(page)
    }
  }
  return pages
}

export function bindPdfExtractDialog(options: {
  root: HTMLElement
  sourceSha256: string
  pageCount: () => number
  currentPage: () => number
  unavailable: () => string | null
  extract: (payload: {requestId: string; expectedSha256: string; pages: number[]}) => Promise<NativeSaveResponse>
}) {
  const owner = options.root.ownerDocument
  const dialog = owner.createElement('dialog'); dialog.className = 'pdf-layout-dialog'; dialog.setAttribute('aria-label', '提取页面')
  const title = owner.createElement('h3'); title.textContent = '提取页面为独立 PDF'
  const hint = owner.createElement('p'); hint.textContent = '从已保存版本提取，不改变当前文档。当前支持无表单、批注或保护信息的 PDF；按输入顺序生成新 PDF，书签与附件不保留。关闭窗口不会撤销服务器已生成的产物，可重新打开查看结果。'
  const label = owner.createElement('label'); label.textContent = '页码（例如 4,1-2）'
  const input = owner.createElement('input'); input.type = 'text'; input.setAttribute('aria-label', '提取页码'); label.append(input)
  const apply = owner.createElement('button'); apply.type = 'button'; apply.textContent = '生成独立 PDF'; apply.dataset.pdfExtractApply = ''
  const close = owner.createElement('button'); close.type = 'button'; close.textContent = '关闭'
  const message = owner.createElement('p'); message.setAttribute('role', 'status')
  const links = owner.createElement('div')
  dialog.append(title, hint, label, apply, close, message, links); options.root.append(dialog)
  let disposed = false, busy = false, generation = 0
  let requestKey = '', requestId = '', cached: NativeSaveResponse | undefined
  const safeLink = (value: string | undefined) => {
    if (!value) return null
    try {
      const url = new URL(value, owner.baseURI)
      return ['http:', 'https:'].includes(url.protocol) && url.origin === new URL(owner.baseURI).origin ? value : null
    } catch { return null }
  }
  const show = (result: NativeSaveResponse) => {
    links.replaceChildren()
    message.textContent = `${result.validation.ok ? '验收通过' : '验收未通过，PDF 已生成'}${result.validation.issues.length ? '：' + result.validation.issues.map(issue => issue.message || issue.code).join('；') : ''}`
    for (const [label, value] of [['下载提取 PDF', result.artifacts.pdf?.downloadUrl], ['打开独立文档', result.editor?.openUrl]]) {
      const href = safeLink(value)
      if (!href) continue
      const link = owner.createElement('a'); link.textContent = label!; link.href = href; link.rel = 'noopener'; links.append(link, owner.createTextNode(' '))
    }
  }
  dialog.addEventListener('close', () => { generation++ })
  close.addEventListener('click', () => dialog.close())
  apply.addEventListener('click', () => { void submit() })
  async function submit() {
    if (disposed || busy || !dialog.open) return
    const reason = options.unavailable()
    if (reason) { message.textContent = reason; return }
    let pages: number[]
    try { pages = parsePdfExtractPages(input.value, options.pageCount()) }
    catch (error) { message.textContent = error instanceof Error ? error.message : String(error); return }
    const key = JSON.stringify(pages)
    if (key !== requestKey) { requestKey = key; requestId = crypto.randomUUID(); cached = undefined }
    const token = generation
    busy = true; apply.disabled = true; input.disabled = true; links.replaceChildren(); message.textContent = '正在生成独立 PDF…'
    try {
      const result = await options.extract({requestId, expectedSha256: options.sourceSha256, pages})
      cached = result
      if (!disposed && dialog.open && token === generation) show(result)
    } catch (error) {
      if (!disposed && dialog.open && token === generation) message.textContent = error instanceof Error ? error.message : String(error)
    } finally {
      busy = false
      if (!disposed && dialog.open && token === generation) { apply.disabled = false; input.disabled = false }
    }
  }
  return {
    open() {
      if (disposed || busy || dialog.open) return
      const reason = options.unavailable()
      if (reason) return
      generation++; apply.disabled = false; input.disabled = false
      if (!input.value) input.value = String(options.currentPage())
      if (cached) show(cached); else { message.textContent = ''; links.replaceChildren() }
      dialog.showModal()
    },
    dispose() { if (disposed) return; disposed = true; generation++; dialog.remove() },
  }
}

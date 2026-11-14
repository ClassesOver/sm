import { installFocusTrap } from './focus-trap'

/** Fixed-source range semantics: ignore empty parts, de-duplicate, and print in ascending visible order. */
export function parsePdfPrintPages(value: string, total: number): number[] | null {
  const pages = new Set<number>()
  for (const part of value.split(/[,，]/)) {
    const text = part.trim()
    if (!text) continue
    const match = /^(\d+)\s*[-–]\s*(\d+)$|^(\d+)$/.exec(text)
    if (!match) return null
    const first = Number(match[1] ?? match[3]), last = Number(match[2] ?? match[3])
    if (first < 1 || last > total || first > last) return null
    for (let page = first; page <= last; page++) pages.add(page)
  }
  return pages.size ? [...pages].sort((a, b) => a - b) : null
}

export function bindPdfPrintDialog(options: {
  root: HTMLElement
  trigger: HTMLButtonElement
  pageCount: () => number
  currentPage: () => number
  unavailable?: () => string | null
  print: (visiblePages: number[]) => void
}) {
  const owner = options.root.ownerDocument
  const dialog = owner.createElement('dialog'); dialog.className = 'pdf-layout-dialog pdf-print-dialog'; dialog.setAttribute('aria-label', '打印 PDF')
  const header = owner.createElement('header'), title = owner.createElement('h3'); title.textContent = '打印 PDF'
  const titleClose = owner.createElement('button'); titleClose.type = 'button'; titleClose.textContent = '×'; titleClose.setAttribute('aria-label', '关闭打印 PDF')
  header.append(title, titleClose)
  const fieldset = owner.createElement('fieldset'), legend = owner.createElement('legend'); legend.textContent = '打印范围'
  fieldset.append(legend)
  const modes = [
    { value: 'all', label: '全部页面' },
    { value: 'current', label: '当前页' },
    { value: 'custom', label: '指定页码' },
  ]
  for (const mode of modes) {
    const label = owner.createElement('label'), radio = owner.createElement('input')
    radio.type = 'radio'; radio.name = 'pdf-print-mode'; radio.value = mode.value; radio.checked = mode.value === 'all'
    label.append(radio, owner.createTextNode(mode.label)); fieldset.append(label)
  }
  const rangeLabel = owner.createElement('label'); rangeLabel.textContent = '页码（例如 1,3-5）'
  const range = owner.createElement('input'); range.type = 'text'; range.setAttribute('aria-label', '打印页码'); range.disabled = true; rangeLabel.append(range)
  const parityLabel = owner.createElement('label'); parityLabel.textContent = '页面子集'
  const parity = owner.createElement('select'); parity.setAttribute('aria-label', '打印页面子集')
  for (const [value, label] of [['all', '全部页面'], ['odd', '奇数页'], ['even', '偶数页']]) {
    const option = owner.createElement('option'); option.value = value; option.textContent = label; parity.append(option)
  }
  parityLabel.append(parity)
  const message = owner.createElement('p'); message.setAttribute('role', 'status')
  const cancel = owner.createElement('button'); cancel.type = 'button'; cancel.textContent = '取消'
  const confirm = owner.createElement('button'); confirm.type = 'button'; confirm.textContent = '打印'; confirm.dataset.pdfPrintConfirm = ''
  const actions = owner.createElement('footer'); actions.className = 'pdf-layout-actions'; actions.append(cancel, confirm)
  dialog.append(header, fieldset, rangeLabel, parityLabel, message, actions); options.root.append(dialog)
  const releaseFocusTrap = installFocusTrap(dialog)
  let disposed = false, opener: HTMLElement | null = null
  const selectedMode = () => dialog.querySelector<HTMLInputElement>('input[name="pdf-print-mode"]:checked')?.value ?? 'all'
  const close = () => { if (dialog.open) dialog.close() }
  const onClose = () => { message.textContent = ''; if (opener?.isConnected) opener.focus({ preventScroll: true }) }
  const onModeChange = () => { range.disabled = selectedMode() !== 'custom'; message.textContent = '' }
  for (const radio of dialog.querySelectorAll<HTMLInputElement>('input[name="pdf-print-mode"]')) radio.addEventListener('change', onModeChange)
  parity.addEventListener('change', () => { message.textContent = '' })
  titleClose.addEventListener('click', close); cancel.addEventListener('click', close)
  dialog.addEventListener('close', onClose)
  const submit = () => {
    if (disposed) return
    const reason = options.unavailable?.()
    if (reason) { message.textContent = reason; return }
    const count = options.pageCount(), mode = selectedMode()
    const pages = mode === 'all' ? Array.from({ length: count }, (_item, index) => index + 1)
      : mode === 'current' ? [options.currentPage()] : parsePdfPrintPages(range.value, count)
    if (!pages) {
      message.textContent = '页码格式无效或超出范围'; return
    }
    if (!pages.length || pages.some(page => !Number.isSafeInteger(page) || page < 1 || page > count)) {
      message.textContent = '所选打印页为空或超出范围'; return
    }
    const filtered = parity.value === 'odd' ? pages.filter(page => page % 2 === 1)
      : parity.value === 'even' ? pages.filter(page => page % 2 === 0) : pages
    if (!filtered.length) { message.textContent = '筛选后的打印页为空，请调整范围或页面子集'; return }
    close(); options.print(filtered)
  }
  confirm.addEventListener('click', submit)
  range.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); submit() } })
  options.trigger.addEventListener('click', open)
  function open() {
    if (disposed || dialog.open || options.trigger.disabled) return
    const reason = options.unavailable?.()
    if (reason) return
    message.textContent = ''; opener = owner.activeElement instanceof HTMLElement ? owner.activeElement : options.trigger
    dialog.showModal()
    const selected = dialog.querySelector<HTMLInputElement>('input[name="pdf-print-mode"]:checked')
    selected?.focus()
  }
  return { dialog, dispose() { if (disposed) return; disposed = true; options.trigger.removeEventListener('click', open); dialog.removeEventListener('close', onClose); releaseFocusTrap(); dialog.remove() } }
}

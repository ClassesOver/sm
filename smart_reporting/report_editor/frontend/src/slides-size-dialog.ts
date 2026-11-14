import { emuToLength, lengthToEmu, MIN_SLIDE_EMU, MAX_SLIDE_EMU, type SizeUnit } from './vendor/genoffice-slides/slide-size'
import { installFocusTrap } from './focus-trap'

type SlideSize = { cx: number; cy: number }

/** Web adapter for the pinned Slide Size units. Commit both dimensions as one draft edit. */
export function openSlidesSizeDialog(host: HTMLElement, initial: SlideSize, apply: (size: SlideSize) => void) {
  const dialog = document.createElement('dialog')
  dialog.className = 'slides-table-dialog slides-size-dialog'
  dialog.setAttribute('aria-label', '自定义幻灯片尺寸')
  let opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const release = installFocusTrap(dialog)
  const close = () => {
    release()
    dialog.remove()
    if (opener?.isConnected) opener.focus({ preventScroll: true })
    opener = null
  }
  const header = document.createElement('header')
  const heading = document.createElement('h2')
  heading.textContent = '自定义幻灯片尺寸'
  const closeButton = document.createElement('button')
  closeButton.type = 'button'
  closeButton.className = 'slides-size-close'
  closeButton.setAttribute('aria-label', '关闭自定义幻灯片尺寸')
  closeButton.textContent = '×'
  closeButton.addEventListener('click', close)
  header.append(heading, closeButton)
  const width = document.createElement('input')
  const height = document.createElement('input')
  for (const [input, label] of [[width, '幻灯片宽度'], [height, '幻灯片高度']] as const) {
    input.type = 'text'
    input.inputMode = 'decimal'
    input.setAttribute('aria-label', label)
  }
  const unit = document.createElement('select')
  unit.setAttribute('aria-label', '尺寸单位')
  for (const value of ['cm', 'mm', 'in']) unit.add(new Option(value, value))
  let activeUnit: SizeUnit = 'cm'
  let current = { ...initial }
  let shownWidth = ''
  let shownHeight = ''
  const render = () => {
    shownWidth = width.value = emuToLength(current.cx, activeUnit)
    shownHeight = height.value = emuToLength(current.cy, activeUnit)
  }
  const error = document.createElement('p')
  error.setAttribute('role', 'alert')
  error.setAttribute('aria-label', '尺寸校验提示')
  error.tabIndex = 0
  const read = (): SlideSize | null => {
    // Avoid rounding an untouched source coordinate when changing units or applying.
    const cx = width.value === shownWidth ? current.cx : lengthToEmu(width.value, activeUnit)
    const cy = height.value === shownHeight ? current.cy : lengthToEmu(height.value, activeUnit)
    if (cx === null || cy === null || !Number.isInteger(cx) || !Number.isInteger(cy) ||
        cx < MIN_SLIDE_EMU || cx > MAX_SLIDE_EMU || cy < MIN_SLIDE_EMU || cy > MAX_SLIDE_EMU) {
      error.textContent = '宽和高均须为 2.54–142.24 cm（1–56 in）范围内的数值。'
      return null
    }
    error.textContent = ''
    return { cx, cy }
  }
  unit.addEventListener('change', () => {
    const size = read()
    if (!size) { unit.value = activeUnit; return }
    current = size
    activeUnit = unit.value as SizeUnit
    render()
  })
  const cancel = document.createElement('button')
  cancel.type = 'button'
  cancel.textContent = '取消'
  cancel.dataset.command = 'cancelCustomSlideSize'
  cancel.addEventListener('click', close)
  const confirm = document.createElement('button')
  confirm.type = 'button'
  confirm.value = 'ok'
  confirm.textContent = '应用'
  confirm.dataset.command = 'applyCustomSlideSize'
  confirm.addEventListener('click', () => {
    const size = read()
    if (!size) return
    apply(size)
    close()
  })
  dialog.addEventListener('close', close, { once: true })
  dialog.addEventListener('cancel', event => { event.preventDefault(); close() })
  const widthLabel = document.createElement('label')
  widthLabel.append('宽 ', width)
  const heightLabel = document.createElement('label')
  heightLabel.append('高 ', height)
  const unitLabel = document.createElement('label')
  unitLabel.append('单位 ', unit)
  const description = document.createElement('p')
  description.textContent = '保存新修订后生效，内容按宽高比例缩放。'
  description.setAttribute('role', 'region')
  description.setAttribute('aria-label', '幻灯片尺寸保存说明')
  description.tabIndex = 0
  const actions = document.createElement('div')
  actions.className = 'slides-table-actions'
  actions.append(cancel, confirm)
  const body = document.createElement('div')
  body.className = 'slides-size-body'
  body.append(widthLabel, heightLabel, unitLabel, description)
  const footer = document.createElement('footer')
  footer.append(error, actions)
  dialog.append(header, body, footer)
  render()
  host.append(dialog)
  if (typeof dialog.showModal === 'function') dialog.showModal()
  else dialog.setAttribute('open', '')
  width.focus()
  return { dispose: close }
}

/** 固定源 CropDialog 的八向控制柄和框内平移；结果仍交给已有裁切逆坐标合同。 */
type CropHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'move'
type Margins = [number, number, number, number]
const handles: Exclude<CropHandle, 'move'>[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']

export function mountPdfCropCanvas(options: {
  host: HTMLElement
  canvas: HTMLCanvasElement
  enabled: () => boolean
  change: (margins: Margins) => void
}) {
  const { host, canvas } = options
  const document = host.ownerDocument, window = document.defaultView!
  const stage = document.createElement('div')
  stage.dataset.pdfCropCanvas = ''
  stage.setAttribute('role', 'img')
  Object.assign(stage.style, { position: 'relative', width: `${Math.min(520, canvas.width)}px`, maxWidth: '100%', overflow: 'hidden', touchAction: 'none' })
  Object.assign(canvas.style, { width: '100%', height: 'auto', display: 'block' })
  const region = document.createElement('div')
  region.dataset.pdfCropRegion = ''
  region.setAttribute('aria-hidden', 'true')
  Object.assign(region.style, { position: 'absolute', border: '2px solid #2563eb', boxSizing: 'border-box', cursor: 'move', boxShadow: '0 0 0 1000px #0007', touchAction: 'none' })
  stage.append(canvas, region); host.append(stage)
  let values: Margins = [0, 0, 0, 0], disposed = false
  let drag: { handle: CropHandle; id: number; x: number; y: number; left: number; top: number; width: number; height: number; start: Margins } | undefined
  const cancel = () => { drag = undefined }
  const scroll = () => {
    if (!drag) return
    const bounds = stage.getBoundingClientRect()
    if (bounds.left !== drag.left || bounds.top !== drag.top || bounds.width !== drag.width || bounds.height !== drag.height) cancel()
  }
  const margins = (): Margins => [...values]
  const render = () => {
    const [left, top, right, bottom] = values
    stage.setAttribute('aria-label', `裁切预览：左侧裁去 ${left}%，顶部裁去 ${top}%，右侧裁去 ${right}%，底部裁去 ${bottom}%`)
    Object.assign(region.style, { left: `${left}%`, top: `${top}%`, width: `${100 - left - right}%`, height: `${100 - top - bottom}%` })
  }
  function begin(event: PointerEvent, handle: CropHandle) {
    if (disposed || !options.enabled() || !stage.isConnected || event.button !== 0 || event.isPrimary === false) return
    const bounds = stage.getBoundingClientRect()
    if (bounds.width <= 0 || bounds.height <= 0) return
    event.preventDefault(); event.stopPropagation()
    drag = { handle, id: event.pointerId, x: event.clientX, y: event.clientY, left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height, start: margins() }
  }
  region.addEventListener('pointerdown', event => begin(event, 'move'))
  for (const handle of handles) {
    const element = document.createElement('span')
    element.dataset.pdfCropHandle = handle
    const horizontal = handle.includes('w') ? '0%' : handle.includes('e') ? '100%' : '50%'
    const vertical = handle.includes('n') ? '0%' : handle.includes('s') ? '100%' : '50%'
    const cursor = ['nw', 'se'].includes(handle) ? 'nwse-resize' : ['ne', 'sw'].includes(handle) ? 'nesw-resize' : ['n', 's'].includes(handle) ? 'ns-resize' : 'ew-resize'
    Object.assign(element.style, { position: 'absolute', left: horizontal, top: vertical, width: '10px', height: '10px', transform: 'translate(-50%, -50%)', border: '1.5px solid #2563eb', background: 'white', boxSizing: 'border-box', cursor, touchAction: 'none' })
    element.addEventListener('pointerdown', event => begin(event, handle))
    region.append(element)
  }
  function move(event: PointerEvent) {
    if (!drag || event.pointerId !== drag.id) return
    if (disposed || !options.enabled() || !stage.isConnected) { cancel(); return }
    event.preventDefault()
    const [left, top, right, bottom] = drag.start
    const dx = (event.clientX - drag.x) / drag.width * 100
    const dy = (event.clientY - drag.y) / drag.height * 100
    let l = left, t = top, r = right, b = bottom
    if (drag.handle === 'move') {
      l = Math.min(Math.max(0, left + dx), left + right)
      t = Math.min(Math.max(0, top + dy), top + bottom)
      r = left + right - l; b = top + bottom - t
    } else {
      const minWidth = Math.min(100 - left - right, 1600 / drag.width)
      const minHeight = Math.min(100 - top - bottom, 1600 / drag.height)
      if (drag.handle.includes('w')) l = Math.min(Math.max(0, left + dx), 100 - right - minWidth)
      if (drag.handle.includes('e')) r = Math.min(Math.max(0, right - dx), 100 - left - minWidth)
      if (drag.handle.includes('n')) t = Math.min(Math.max(0, top + dy), 100 - bottom - minHeight)
      if (drag.handle.includes('s')) b = Math.min(Math.max(0, bottom - dy), 100 - top - minHeight)
    }
    values = [l, t, r, b].map(value => Math.round(value * 10000) / 10000) as Margins
    render(); options.change(margins())
  }
  function end(event: PointerEvent) { if (event.pointerId === drag?.id) cancel() }
  function key(event: KeyboardEvent) {
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return
    if (event.key === 'Escape') cancel()
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', end)
  window.addEventListener('pointercancel', end)
  window.addEventListener('blur', cancel)
  window.addEventListener('resize', cancel)
  document.addEventListener('scroll', scroll, true)
  document.addEventListener('wheel', cancel, true)
  document.addEventListener('keydown', key)
  render()
  return {
    margins,
    cancel,
    setMargins(next: number[]) {
      if (next.length !== 4 || next.some(value => !Number.isFinite(value) || value < 0 || value >= 100) || next[0]! + next[2]! >= 100 || next[1]! + next[3]! >= 100) throw new Error('裁切边距无效')
      cancel(); values = [...next] as Margins; render()
    },
    dispose() {
      if (disposed) return
      disposed = true; cancel(); stage.remove()
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
      window.removeEventListener('blur', cancel)
      window.removeEventListener('resize', cancel)
      document.removeEventListener('scroll', scroll, true)
      document.removeEventListener('wheel', cancel, true)
      document.removeEventListener('keydown', key)
    },
  }
}

import './slides-geometry-pane.css'

type Geometry = { x: number; y: number; width: number; height: number }
type Axis = keyof Geometry
type Field = Axis | 'scaleWidth' | 'scaleHeight'
type State = { target: string; geometry: Geometry; slideSize: { width: number; height: number }; reason?: string; picture?: boolean }
const pxPerCm = 96 / 2.54
const axes: Axis[] = ['width', 'height', 'x', 'y']
const fieldOrder: Field[] = ['width', 'height', 'scaleHeight', 'scaleWidth', 'x', 'y']
const labels = { width: '宽度', height: '高度', x: '水平位置', y: '垂直位置', scaleWidth: '缩放宽度', scaleHeight: '缩放高度' }
const scaleAxis = (field: Field) => field === 'scaleWidth' ? 'width' : field === 'scaleHeight' ? 'height' : undefined
const same = (a: Geometry, b: Geometry) => axes.every(key => Math.round(a[key] * 9525) === Math.round(b[key] * 9525))

/** 固定源FormatPane大小/位置行为适配；geometry保持来源96dpi坐标，不受画布缩放影响。 */
export function createSlidesGeometryPane(onConfirm: (geometry: Geometry, target: string) => void) {
  const element = document.createElement('section'); element.className = 'slides-geometry-pane'; element.setAttribute('aria-label', '大小与位置')
  const messageId = `slides-geometry-status-${crypto.randomUUID()}`
  let state: State | null = null, locked = false, disposed = false, generation = 0, ratio = false, committing = false
  const reference = { x: 'tl', y: 'tl' }
  let scaleBase: Pick<Geometry, 'width' | 'height'> | undefined
  let natural: Pick<Geometry, 'width' | 'height'> | undefined, relativeOriginal = true, imageLoading = false, imageIssue = ''
  let imageSequence = 0, imageTarget: string | undefined, imageUrl: string | undefined, imageReplaced = false
  let originalControl: HTMLInputElement | undefined, originalStatus: HTMLParagraphElement | undefined
  let fields = new Map<Field, { input: HTMLInputElement; displayed: string }>()
  let message: HTMLParagraphElement
  const available = () => !disposed && !locked && !!state && !state.reason
  const scaleBasis = () => relativeOriginal && natural ? natural : scaleBase!
  const scaleDisabled = () => !available() || (relativeOriginal && imageLoading)
  function display(field: Field) {
    const dim = scaleAxis(field)
    if (dim) return String(Math.round(state!.geometry[dim] / scaleBasis()[dim] * 100))
    const axis = field as Axis, dimension = axis === 'x' ? 'width' : 'height'
    const offset = (axis === 'x' || axis === 'y') && reference[axis] === 'center' ? (state!.slideSize[dimension] - state!.geometry[dimension]) / 2 : 0
    return String(Math.round((state!.geometry[axis] - offset) / pxPerCm * 100) / 100)
  }
  function refreshValues() {
    if (!state) return
    for (const [axis, field] of fields) {
      field.displayed = display(axis)
      field.input.value = field.displayed; field.input.removeAttribute('aria-invalid')
    }
    message.textContent = state.reason ?? ''
  }
  function report(error: unknown) {
    message.textContent = error instanceof Error ? error.message : '位置或大小未能应用，请重试'
  }
  function syncOriginal(refreshScale = false) {
    for (const axis of ['scaleWidth', 'scaleHeight'] as const) {
      const field = fields.get(axis)
      if (!field) continue
      if (refreshScale) { field.displayed = display(axis); field.input.value = field.displayed; field.input.removeAttribute('aria-invalid') }
      field.input.disabled = scaleDisabled()
      for (const button of element.querySelectorAll<HTMLButtonElement>(`[data-geometry-step^="${axis}:"]`)) button.disabled = scaleDisabled()
    }
    if (originalControl) {
      originalControl.checked = !!state?.picture && relativeOriginal && !!natural
      originalControl.disabled = !available() || !state?.picture || !natural || imageReplaced
    }
    if (originalStatus) originalStatus.textContent = state?.picture ? imageLoading ? '正在读取图片原始尺寸' : imageIssue : ''
  }
  /** 只解码当前渲染树的图片；对象、dataUrl或待保存替换变化后，旧结果失效。 */
  function setPictureSource(target: string, node?: { type: string; dataUrl?: string }, replaced = false) {
    if (disposed || !state?.picture || state.target !== target) return
    const url = node?.type === 'picture' && node.dataUrl?.startsWith('data:image/') ? node.dataUrl : undefined
    if (imageTarget === target && imageUrl === url && imageReplaced === replaced) return
    // 来源失效不依赖输入是否合法；不提交厘米输入，取消旧基准下尚未提交的百分比。
    imageTarget = target; imageUrl = url; imageReplaced = replaced
    const version = ++imageSequence
    natural = undefined; imageLoading = false
    imageIssue = replaced ? '此图片有待保存的替换，请先保存或撤回替换；使用选中尺寸基准' : '图片原始尺寸尚未就绪，使用选中尺寸基准'
    if (!url || replaced) { syncOriginal(relativeOriginal); return }
    imageLoading = true; syncOriginal(relativeOriginal)
    const image = new Image()
    const valid = () => !disposed && version === imageSequence && state?.target === target && imageUrl === url && !imageReplaced
    const failed = () => {
      if (!valid()) return
      imageLoading = false; imageIssue = '无法读取图片原始尺寸，使用选中尺寸基准'; syncOriginal(relativeOriginal)
    }
    image.onerror = failed
    image.onload = () => {
      if (!valid()) return
      const width = image.naturalWidth, height = image.naturalHeight
      if (!(width > 0 && height > 0 && Number.isFinite(width * height) && width * height <= 100_000_000)) { failed(); return }
      natural = { width, height }; imageLoading = false; imageIssue = ''; syncOriginal(relativeOriginal)
    }
    image.src = url
  }
  function candidate(box: Geometry, axis: Axis, value: number, step = false): Geometry {
    const next = { ...box }
    if (axis === 'width' || axis === 'height') {
      next[axis] = step ? box[axis] + value : value
      if (next[axis] < 1) throw new Error('宽度和高度至少为1像素')
      if (ratio) { const other = axis === 'width' ? 'height' : 'width'; next[other] = box[other] * next[axis] / box[axis] }
    } else {
      const dimension = axis === 'x' ? 'width' : 'height'
      next[axis] = step ? box[axis] + value : value + (reference[axis] === 'center' ? (state!.slideSize[dimension] - box[dimension]) / 2 : 0)
    }
    if (axes.some(key => !Number.isFinite(next[key]) || next[key] < (key === 'width' || key === 'height' ? 1 : 0) || next[key] > 100000))
      throw new Error('实际位置须为0至100000像素，宽高须为1至100000像素；未提交修改')
    return next
  }
  function commit(next: Geometry) {
    if (!available()) return false
    if (same(next, state!.geometry)) { refreshValues(); return true }
    const current = state!, version = generation
    try {
      committing = true; onConfirm(next, current.target)
      // 宿主通常在回调中回填；独立使用时也维护已提交值。
      if (version === generation) { state = { ...state!, geometry: next }; refreshValues() }
      return true
    } catch (error) { report(error); return false } finally { committing = false }
  }
  function flush(): boolean {
    if (!available()) return true
    let next = state!.geometry, changed = false
    try {
      for (const [axis, { input, displayed }] of fields) {
        if (scaleAxis(axis) && scaleDisabled()) continue
        if (input.value === displayed) continue
        const dim = scaleAxis(axis), value = (dim ? input.value.trim().replace(/%$/, '') : input.value).trim()
        if (!value || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value) || !Number.isFinite(Number(value))) {
          input.setAttribute('aria-invalid', 'true'); throw new Error(`${labels[axis]}请输入完整的${dim ? '百分比' : '厘米'}数值`)
        }
        if (dim && value === displayed) continue
        try { next = candidate(next, dim ?? axis as Axis, Number(value) * (dim ? scaleBasis()[dim] / 100 : pxPerCm)) }
        catch (error) { input.setAttribute('aria-invalid', 'true'); throw error }
        changed = true
      }
      if (changed) return commit(next)
      refreshValues(); return true
    } catch (error) { report(error); return false }
  }
  function render(focusSelector?: string) {
    const restoreFocus = !!focusSelector && element.contains(document.activeElement)
    const version = ++generation
    element.hidden = !state
    element.replaceChildren(); fields = new Map(); originalControl = undefined; originalStatus = undefined
    if (!state) return
    const heading = document.createElement('h3'); heading.textContent = '大小与位置'; element.append(heading)
    const groups = new Map<string, HTMLFieldSetElement>()
    for (const [key, title] of [['size', '尺寸'], ['scale', '缩放'], ['position', '位置']]) {
      const group = document.createElement('fieldset'), legend = document.createElement('legend')
      legend.textContent = title!; group.append(legend); element.append(group); groups.set(key!, group)
    }
    const valid = () => version === generation && available()
    for (const axis of fieldOrder) {
      const dim = scaleAxis(axis)
      const group = groups.get(dim ? 'scale' : axis === 'x' || axis === 'y' ? 'position' : 'size')!
      const row = document.createElement('label'); row.className = 'geometry-cm-row'
      const caption = document.createElement('span'); caption.textContent = labels[axis]
      const input = document.createElement('input'); input.type = 'text'; input.inputMode = 'decimal'; input.dataset.geometry = axis; input.setAttribute('aria-label', `${labels[axis]}（${dim ? '百分比' : '厘米'}）`)
      input.setAttribute('aria-describedby', messageId)
      input.value = display(axis)
      input.disabled = !available(); fields.set(axis, { input, displayed: input.value })
      input.addEventListener('change', () => { if (valid()) flush() })
      input.addEventListener('blur', () => { if (valid()) flush() })
      input.addEventListener('keydown', event => {
        if (!valid() || event.isComposing || event.keyCode === 229 || event.defaultPrevented) return
        if (event.key === 'Enter') { event.preventDefault(); flush() }
        if (event.key === 'Escape') { event.preventDefault(); render(`[data-geometry="${axis}"]`) }
      })
      const unit = document.createElement('span'); unit.textContent = dim ? '%' : '厘米'; unit.className = 'geometry-cm-unit'
      row.append(caption, input, unit)
      for (const direction of [-1, 1]) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = direction < 0 ? '−' : '+'; button.dataset.geometryStep = `${axis}:${direction}`
        button.setAttribute('aria-label', `${labels[axis]}${direction < 0 ? '减少' : '增加'}${dim ? '1%' : '0.1厘米'}`); button.disabled = !available()
        button.addEventListener('mousedown', event => event.preventDefault())
        button.addEventListener('click', () => {
          if (!valid() || (dim && scaleDisabled()) || !flush() || !available()) return
          try {
            const value = dim ? scaleBasis()[dim] * Math.max(1, Math.round(state!.geometry[dim] / scaleBasis()[dim] * 100) + direction) / 100 : direction * 0.1 * pxPerCm
            commit(candidate(state!.geometry, dim ?? axis as Axis, value, !dim))
          } catch (error) { report(error) }
        }); row.append(button)
      }
      group.append(row)
      if (axis === 'height') {
        const label = document.createElement('label'); label.className = 'geometry-ratio'
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.dataset.geometryRatio = ''; checkbox.checked = ratio; checkbox.disabled = !available()
        checkbox.addEventListener('change', () => { if (!valid()) return; const checked = checkbox.checked; if (!flush()) { checkbox.checked = ratio; return }; ratio = checked; render('[data-geometry-ratio]') })
        label.append(checkbox, '锁定纵横比'); group.append(label)
      }
      if (axis === 'scaleWidth') {
        const label = document.createElement('label'); label.className = 'geometry-ratio'
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.dataset.geometryOriginal = ''; originalControl = checkbox
        checkbox.addEventListener('change', () => {
          const checked = checkbox.checked
          if (!valid() || !natural || imageReplaced || !flush()) { syncOriginal(); return }
          relativeOriginal = checked; syncOriginal(true)
        })
        label.append(checkbox, '相对图片原始尺寸'); group.append(label)
        originalStatus = document.createElement('p'); originalStatus.dataset.geometryOriginalStatus = ''; group.append(originalStatus)
      }
      if (axis === 'x' || axis === 'y') {
        const label = document.createElement('label'); label.className = 'geometry-reference'; label.append('相对于')
        const select = document.createElement('select'); select.dataset.geometryReference = axis; select.setAttribute('aria-label', `${labels[axis]}参考点`)
        for (const [value, text] of [['tl', '左上角'], ['center', '幻灯片中心']]) { const option = document.createElement('option'); option.value = value!; option.textContent = text!; select.append(option) }
        select.value = reference[axis]; select.disabled = !available()
        select.addEventListener('change', () => { if (!valid()) return; const value = select.value; if (!flush()) { select.value = reference[axis]; return }; reference[axis] = value; render(`[data-geometry-reference="${axis}"]`) })
        label.append(select); group.append(label)
      }
    }
    message = document.createElement('p'); message.id = messageId; message.tabIndex = 0; message.setAttribute('role', 'status'); message.setAttribute('aria-label', '大小与位置状态'); message.textContent = state.reason ?? ''; element.append(message)
    syncOriginal()
    if (restoreFocus) element.querySelector<HTMLElement>(focusSelector!)?.focus()
  }
  return {
    element, flush, setPictureSource,
    update(next: State | null, nextLocked = false) {
      if (disposed) return
      // 其他属性的防抖提交也会回填此窗格；相同来源不能重建尚在编辑的字段。
      if (next && state && next.target === state.target && next.reason === state.reason && next.picture === state.picture && locked === nextLocked
        && axes.every(axis => next.geometry[axis] === state!.geometry[axis])
        && next.slideSize.width === state.slideSize.width && next.slideSize.height === state.slideSize.height) return
      const retain = committing && next?.target === state?.target && next?.reason === state?.reason && locked === nextLocked
      if (next?.target !== state?.target || next?.picture !== state?.picture) {
        ++imageSequence; natural = undefined; imageLoading = false; imageIssue = ''; imageTarget = undefined; imageUrl = undefined; imageReplaced = false; relativeOriginal = true
      }
      // 固定源会话基准：同目标的尺寸提交/历史回填不重置，结束选择或换对象后重新建立。
      if (!next) scaleBase = undefined
      else if (next.target !== state?.target) scaleBase = { width: next.geometry.width, height: next.geometry.height }
      state = next; locked = nextLocked; if (!retain) render()
    },
    setLocked(value: boolean) { if (disposed) return; locked = value; render() },
    focus() { fields.get('width')?.input.focus(); element.scrollIntoView?.({ block: 'nearest' }) },
    dispose() { disposed = true; ++generation; ++imageSequence; fields.clear(); element.remove() },
  }
}

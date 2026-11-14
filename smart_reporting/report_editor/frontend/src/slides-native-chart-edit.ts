/** 固定源 f8c17004 ChartDataDialog / ChartTypeDialog 的原生 DOM 适配。 */
import { CHART_STYLE_PRESETS, chartColorSchemes, validChartDesign, type ChartColorScheme, type ChartDesignPatch } from '../../../reporting/slides_engine/bridge/pptx-chart-design'
import { validChartPointColors, type ChartPointColors } from '../../../reporting/slides_engine/bridge/pptx-chart-data'
export const NATIVE_CHART_TYPES = [
  ['bar', '簇状柱形图'], ['barStacked', '堆积柱形图'], ['barPercentStacked', '百分比堆积柱形图'],
  ['barH', '条形图'], ['bar3D', '三维柱形图'], ['line', '折线图'], ['area', '面积图'],
  ['pie', '饼图'], ['pie3D', '三维饼图'], ['doughnut', '圆环图'], ['scatter', '散点图'], ['radar', '雷达图'], ['comboBarLine', '柱形与折线组合图'],
] as const
export type NativeChartKind = typeof NATIVE_CHART_TYPES[number][0]
export type NativeChartData = { categories: string[]; series: { name: string; values: number[] }[] }
export type NativeChartStyle = { title: string; catAxisTitle: string; valAxisTitle: string; legendPos: 'b' | 't' | 'r' | 'l' | 'none'; dataLabels: boolean; gridlines: boolean }
export const CHART_STYLE_FIELDS = ['title', 'catAxisTitle', 'valAxisTitle', 'legendPos', 'dataLabels', 'gridlines', 'colorScheme', 'gapWidthPct', 'pointColors'] as const
export type NativeChartPatch = Partial<NativeChartData & NativeChartStyle> & ChartDesignPatch & { kind?: NativeChartKind; switchRowCol?: boolean; pointColors?: ChartPointColors }
export function validChartStyle(value: Record<string, unknown>): boolean {
  return validChartDesign(value) && (!Object.hasOwn(value, 'pointColors') || validChartPointColors(value.pointColors, 20, 100)) && ['title', 'catAxisTitle', 'valAxisTitle'].every(key => !Object.hasOwn(value, key) || typeof value[key] === 'string' && [...value[key] as string].length <= 1000 && !/[\u0000-\u001f\u007f\ud800-\udfff\ufffe\uffff]/u.test(value[key] as string))
    && (!Object.hasOwn(value, 'legendPos') || ['b', 't', 'r', 'l', 'none'].includes(value.legendPos as string))
    && ['dataLabels', 'gridlines'].every(key => !Object.hasOwn(value, key) || typeof value[key] === 'boolean')
}
type Options = { mode: 'data' | 'type' | 'style' | 'design' | 'points'; initial: NativeChartData & Partial<NativeChartStyle> & ChartDesignPatch & { kind: NativeChartKind; pointColors?: ChartPointColors; seriesColors?: (string | null)[] }; colorSchemes?: ChartColorScheme[] | null; onConfirm: (patch: NativeChartPatch) => void; onClose: () => void }

export function createNativeChartEditDialog(host: HTMLElement, options: Options) {
  const previous = document.activeElement instanceof HTMLElement ? document.activeElement : undefined
  const dialog = document.createElement('dialog')
  dialog.className = 'slides-native-chart-dialog'
  dialog.dataset.chartMode = options.mode
  dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true')
  const title = options.mode === 'data' ? '编辑图表数据' : options.mode === 'style' ? '图表元素' : options.mode === 'design' ? '图表配色与样式' : options.mode === 'points' ? '图表单点配色' : '更改图表类型'
  dialog.setAttribute('aria-label', title)
  let active = true, selected = options.initial.kind
  let categories = [...options.initial.categories]
  let names = options.initial.series.map(series => series.name)
  let values = options.initial.series.map(series => categories.map((_, index) => String(series.values[index] ?? '')))
  const changedPoints: ChartPointColors = {}
  const heading = document.createElement('h2'); heading.textContent = title; dialog.append(heading)
  const content = document.createElement('div'); content.className = 'slides-chart-content'; dialog.append(content)
  const error = document.createElement('p'); error.setAttribute('role', 'alert'); dialog.append(error)
  const actions = document.createElement('div'); actions.className = 'slides-table-actions'; dialog.append(actions)
  function button(label: string, action: () => void) {
    const control = document.createElement('button'); control.type = 'button'; control.textContent = label; control.addEventListener('click', action); return control
  }
  const dispose = () => { if (!active) return; active = false; dialog.remove(); if (previous?.isConnected) previous.focus(); options.onClose() }
  function readGrid() {
    for (const input of content.querySelectorAll<HTMLInputElement>('input')) {
      if (input.dataset.chartCategory !== undefined) categories[Number(input.dataset.chartCategory)] = input.value
      if (input.dataset.chartSeries !== undefined) names[Number(input.dataset.chartSeries)] = input.value
      if (input.dataset.chartValue !== undefined) { const [si, ci] = input.dataset.chartValue.split(':').map(Number); values[si!]![ci!] = input.value }
    }
  }
  function confirm() {
    if (!active) return
    if (options.mode === 'points') {
      const points: ChartPointColors = {}
      for (const [si, row] of Object.entries(changedPoints)) for (const [pi, color] of Object.entries(row)) {
        if (color !== (options.initial.pointColors?.[Number(si)]?.[Number(pi)] ?? null)) (points[Number(si)] ??= {})[Number(pi)] = color
      }
      try { if (Object.keys(points).length) options.onConfirm({ pointColors: points }) }
      catch (cause) { error.textContent = cause instanceof Error ? cause.message : '单点配色未能应用，请重试。'; return }
      dispose(); return
    }
    if (options.mode === 'design') {
      const patch: NativeChartPatch = {}
      const scheme = content.querySelector<HTMLSelectElement>('[data-chart-palette]')!.value
      const preset = CHART_STYLE_PRESETS.find(item => item.key === content.querySelector<HTMLSelectElement>('[data-chart-preset]')!.value)
      if (scheme && scheme !== options.initial.colorScheme) {
        const selected = (options.colorSchemes ?? chartColorSchemes()).find(item => item.key === scheme)
        if (!selected) { error.textContent = '此来源配色不可用，请重新打开图表设计。'; return }
        patch.colorScheme = selected.key
      }
      if (preset) for (const key of ['legendPos', 'dataLabels', 'gridlines', 'gapWidthPct'] as const) {
        const before = key === 'gapWidthPct' ? options.initial.gapWidthPct ?? 150 : options.initial[key] ?? style[key]
        if (preset.style[key] !== before) Object.assign(patch, { [key]: preset.style[key] })
      }
      try { if (Object.keys(patch).length) options.onConfirm(patch) }
      catch (cause) { error.textContent = cause instanceof Error ? cause.message : '图表设计未能应用，请重新选择后重试。'; return }
      dispose(); return
    }
    if (options.mode === 'style') {
      const patch: Record<string, unknown> = {}
      for (const control of content.querySelectorAll<HTMLInputElement | HTMLSelectElement>('[data-chart-style]')) {
        if (control.disabled) continue
        const key = control.dataset.chartStyle as keyof NativeChartStyle
        const value = control instanceof HTMLInputElement && control.type === 'checkbox' ? control.checked : control.value.trim()
        if (value !== style[key]) patch[key] = value
      }
      if (!validChartStyle(patch)) { error.textContent = '标题最多 1000 字，且不能包含控制字符或无效 XML 字符。'; return }
      try { if (Object.keys(patch).length) options.onConfirm(patch as NativeChartPatch) }
      catch (cause) { error.textContent = cause instanceof Error ? cause.message : '图表修改未能应用，请重新选择后重试。'; return }
      dispose(); return
    }
    readGrid()
    if ([...categories, ...names].some(value => [...value].length > 100 || /[\u0000-\u001f\u007f]/.test(value))) {
      error.textContent = '类别名和系列名最多 100 字，且不能包含控制字符。'; return
    }
    const kind = options.mode === 'type' ? selected : options.initial.kind
    if ((kind === 'scatter' && categories.some(value => !value.trim() || !Number.isFinite(Number(value)))) || (kind === 'comboBarLine' && names.length < 2)) {
      error.textContent = kind === 'scatter' ? '散点图类别必须是有效的 X 数值，请先编辑图表数据。' : '组合图至少需要两个系列，请先编辑图表数据。'; return
    }
    const patch: NativeChartPatch = options.mode === 'type' ? { kind: selected } : {
      categories: categories.map(value => value.trim()),
      series: names.map((name, si) => ({ name: name.trim(), values: categories.map((_, ci) => { const number = Number(values[si]?.[ci] ?? ''); return Number.isFinite(number) ? number : 0 }) })),
    }
    try { options.onConfirm(patch) }
    catch (cause) { error.textContent = cause instanceof Error ? cause.message : '图表修改未能应用，请重新选择后重试。'; return }
    dispose()
  }
  function renderData(focusSelector?: string) {
    content.replaceChildren()
    const grid = document.createElement('div'); grid.className = 'slides-chart-data-grid'; content.append(grid)
    const table = document.createElement('table'); table.style.borderSpacing = '6px'; grid.append(table)
    const head = table.createTHead().insertRow(); head.insertCell()
    names.forEach((name, si) => {
      const cell = head.insertCell(), input = document.createElement('input'); input.value = name; input.dataset.chartSeries = String(si); input.setAttribute('aria-label', `系列 ${si + 1} 名称`); cell.append(input)
      const remove = button('删除系列', () => { readGrid(); names.splice(si, 1); values.splice(si, 1); renderData(`[data-chart-series="${Math.min(si, names.length - 1)}"]`) }); remove.disabled = names.length <= 1; cell.append(remove)
    })
    const body = table.createTBody()
    categories.forEach((category, ci) => {
      const row = body.insertRow(), cell = row.insertCell(), input = document.createElement('input'); input.value = category; input.dataset.chartCategory = String(ci); input.setAttribute('aria-label', `类别 ${ci + 1}`); cell.append(input)
      const remove = button('删除类别', () => { readGrid(); categories.splice(ci, 1); values.forEach(series => series.splice(ci, 1)); renderData(`[data-chart-category="${Math.min(ci, categories.length - 1)}"]`) }); remove.disabled = categories.length <= 1; cell.append(remove)
      names.forEach((_, si) => { const value = document.createElement('input'); value.value = values[si]?.[ci] ?? ''; value.inputMode = 'decimal'; value.dataset.chartValue = `${si}:${ci}`; value.setAttribute('aria-label', `类别 ${ci + 1} 系列 ${si + 1} 数值`); row.insertCell().append(value) })
    })
    const addCategory = button('添加类别', () => { readGrid(); categories.push(`类别 ${categories.length + 1}`); values.forEach(series => series.push('')); renderData(`[data-chart-category="${categories.length - 1}"]`) }); addCategory.dataset.chartAddCategory = ''; addCategory.disabled = categories.length >= 100
    const addSeries = button('添加系列', () => { readGrid(); names.push(`系列 ${names.length + 1}`); values.push(categories.map(() => '')); renderData(`[data-chart-series="${names.length - 1}"]`) }); addSeries.dataset.chartAddSeries = ''; addSeries.disabled = names.length >= 20
    content.append(addCategory, addSeries)
    const note = document.createElement('p'); note.textContent = '空白或无效数值按 0 保存。'; content.append(note)
    if (focusSelector) {
      const input = content.querySelector<HTMLInputElement>(focusSelector)
      input?.focus(); input?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
    }
  }
  const style: NativeChartStyle = { title: '', catAxisTitle: '', valAxisTitle: '', legendPos: 'none', dataLabels: false, gridlines: false, ...Object.fromEntries(CHART_STYLE_FIELDS.filter(key => options.initial[key] !== undefined).map(key => [key, options.initial[key]])) }
  if (options.mode === 'points') {
    const palette = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000', '#5B9BD5', '#70AD47']
    for (const [si, series] of options.initial.series.entries()) {
      const name = document.createElement('h3'); name.textContent = series.name || `系列 ${si + 1}`; content.append(name)
      for (const [pi, category] of categories.entries()) {
        const row = document.createElement('div'); row.className = 'slides-chart-point-row'
        const label = document.createElement('label'); label.textContent = category || `#${pi + 1}`
        const input = document.createElement('input'); input.type = 'color'; input.dataset.chartPoint = `${si}:${pi}`; input.setAttribute('aria-label', `系列 ${si + 1} 数据点 ${pi + 1} 颜色`)
        const colors = options.initial.seriesColors
        const fallback = ['pie', 'pie3D', 'doughnut'].includes(options.initial.kind) ? palette[pi % palette.length]! : (colors?.length ? colors[si % colors.length] : undefined) ?? palette[si % palette.length]!
        input.value = options.initial.pointColors?.[si]?.[pi] ?? fallback
        input.addEventListener('input', () => { (changedPoints[si] ??= {})[pi] = input.value.toUpperCase() })
        const reset = button('恢复系列配色', () => { (changedPoints[si] ??= {})[pi] = null; input.value = fallback }); reset.dataset.chartPointReset = `${si}:${pi}`
        label.append(input); row.append(label, reset); content.append(row)
      }
    }
  }
  else if (options.mode === 'design') {
    const paletteLabel = document.createElement('label'); paletteLabel.textContent = '配色方案'
    const palette = document.createElement('select'); palette.dataset.chartPalette = ''; palette.setAttribute('aria-label', '配色方案')
    palette.add(new Option('保留当前配色', ''))
    const schemes = options.colorSchemes ?? chartColorSchemes()
    for (const scheme of schemes) palette.add(new Option(scheme.label, scheme.key))
    palette.value = options.initial.colorScheme ?? ''; paletteLabel.append(palette)
    const swatches = document.createElement('div'); swatches.setAttribute('role', 'group'); swatches.setAttribute('aria-label', '配色预览')
    Object.assign(swatches.style, { display: 'flex', flexWrap: 'wrap', gap: '6px', minHeight: '24px' })
    const renderSwatches = () => {
      swatches.replaceChildren()
      for (const color of schemes.find(item => item.key === palette.value)?.colors ?? []) {
        const swatch = document.createElement('span'); swatch.dataset.chartSwatch = ''; swatch.title = color
        swatch.setAttribute('role', 'img'); swatch.setAttribute('aria-label', color)
        Object.assign(swatch.style, { display: 'inline-block', width: '28px', height: '24px', backgroundColor: color, border: '1px solid #cad4df' }); swatches.append(swatch)
      }
    }
    palette.addEventListener('change', renderSwatches); renderSwatches()
    const presetLabel = document.createElement('label'); presetLabel.textContent = '样式预设'
    const preset = document.createElement('select'); preset.dataset.chartPreset = ''; preset.setAttribute('aria-label', '样式预设')
    preset.add(new Option('保留当前样式', ''))
    for (const item of CHART_STYLE_PRESETS) preset.add(new Option(item.label, item.key))
    presetLabel.append(preset)
    const note = document.createElement('p'); note.textContent = '预设设置图例、数据标签和网格线；粗柱、细柱的间距仅作用于柱形/条形图。标题与数据保留。'
    content.append(paletteLabel, swatches, presetLabel, note)
  }
  else if (options.mode === 'style') {
    for (const [key, caption] of [['title', '图表标题'], ['catAxisTitle', '分类轴标题'], ['valAxisTitle', '数值轴标题']] as const) {
      const label = document.createElement('label'); label.textContent = caption
      const input = document.createElement('input'); input.value = style[key]; input.dataset.chartStyle = key; input.setAttribute('aria-label', caption)
      input.disabled = key !== 'title' && ['pie', 'pie3D', 'doughnut'].includes(options.initial.kind)
      label.append(input); content.append(label)
    }
    const label = document.createElement('label'); label.textContent = '图例位置'
    const select = document.createElement('select'); select.dataset.chartStyle = 'legendPos'; select.setAttribute('aria-label', '图例位置')
    for (const [value, caption] of [['none', '无'], ['b', '下方'], ['t', '上方'], ['r', '右侧'], ['l', '左侧']]) { const item = document.createElement('option'); item.value = value!; item.textContent = caption!; select.append(item) }
    select.value = style.legendPos; label.append(select); content.append(label)
    for (const [key, caption] of [['dataLabels', '数据标签'], ['gridlines', '网格线']] as const) {
      const label = document.createElement('label'), input = document.createElement('input'); input.type = 'checkbox'; input.checked = style[key]; input.dataset.chartStyle = key
      input.disabled = key === 'gridlines' && ['pie', 'pie3D', 'doughnut'].includes(options.initial.kind)
      label.append(input, document.createTextNode(caption)); content.append(label)
    }
  }
  else if (options.mode === 'data') renderData()
  else {
    for (const [kind, label] of NATIVE_CHART_TYPES) {
      const pick = button(label, () => { selected = kind; for (const control of content.querySelectorAll<HTMLButtonElement>('[data-chart-kind]')) control.setAttribute('aria-pressed', String(control.dataset.chartKind === kind)) })
      pick.dataset.chartKind = kind; pick.setAttribute('aria-pressed', String(kind === selected)); pick.addEventListener('dblclick', () => { selected = kind; confirm() }); content.append(pick)
    }
  }
  const cancel = button('取消', dispose), ok = button('确定', confirm); ok.dataset.chartConfirm = ''; ok.value = 'ok'; actions.append(cancel, ok)
  dialog.addEventListener('cancel', event => { event.preventDefault(); dispose() })
  dialog.addEventListener('keydown', event => { if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return; if (event.key === 'Escape') { event.preventDefault(); dispose() } })
  dialog.addEventListener('close', dispose)
  host.append(dialog)
  if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '')
  return { dispose }
}

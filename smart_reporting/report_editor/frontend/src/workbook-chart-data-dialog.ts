import { formatAddress, parseRange, type ChartReadSpec, type ChartSeriesSetEntry } from '@sheets-web/xlsx-engine'
import { createModal } from './modal'
import './workbook-chart-data-dialog.css'

export interface ChartDataVector { vector: readonly unknown[]; ref: string }
interface ChartDataWorkbook { getSheets(): { getSheetName(): string; getRange(range: string): { getRawValues(): unknown[][] } }[] }
const numeric = (value: unknown) => { const number = typeof value === 'number' ? value : Number(String(value ?? '').trim()); return Number.isFinite(number) ? number : 0 }
const category = (value: unknown) => String(value ?? '').slice(0, 255)

// 固定源 univer-sync.readChartRangeVector：默认图表所在表、跨表不区分大小写，最多1000个单向量原始值。
export function readChartDataVector(workbook: ChartDataWorkbook, chartSheet: string, text: string): ChartDataVector {
  const match = /^(?:'((?:[^']|'')+)'|([^'!\[\]]+))!(.+)$/.exec(text.trim())
  const name = match ? match[1]?.replaceAll("''", "'") ?? match[2]! : chartSheet
  const range = (match ? match[3]! : text).trim().toUpperCase().replaceAll('$', '')
  if (/[\[\]]/.test(name) || !/^[A-Z]{1,3}[1-9]\d*(?::[A-Z]{1,3}[1-9]\d*)?$/.test(range)) throw new Error('请使用当前工作簿内的有效单元格区域')
  const bounds = parseRange(range)
  if (bounds.endRow >= 1048576 || bounds.endColumn >= 16384) throw new Error('图表数据区域超出工作表范围')
  if (bounds.startRow !== bounds.endRow && bounds.startColumn !== bounds.endColumn) throw new Error('图表数据区域必须为一行或一列')
  if ((bounds.endRow - bounds.startRow + 1) * (bounds.endColumn - bounds.startColumn + 1) > 1000) throw new Error('图表数据区域最多包含 1000 个单元格')
  const sheet = workbook.getSheets().find(sheet => sheet.getSheetName().toLowerCase() === name.toLowerCase())
  if (!sheet) throw new Error('图表数据区域的工作表不存在')
  const absolute = (row: number, column: number) => formatAddress(row, column).replace(/^([A-Z]+)(\d+)$/, '$$$1$$$2')
  return { vector: sheet.getRange(range).getRawValues().flat(), ref: `'${sheet.getSheetName().replaceAll("'", "''")}'!${absolute(bounds.startRow, bounds.startColumn)}:${absolute(bounds.endRow, bounds.endColumn)}` }
}

export function hydrateChartDataSeries(chart: ChartReadSpec, read: (range: string) => ChartDataVector): ChartSeriesSetEntry[] {
  if (!chart.series.length) throw new Error('当前图表的数据系列无法读取，不能替换')
  return chart.series.map((entry, index) => {
    const values = entry.valuesRef ? read(entry.valuesRef).vector.map(numeric) : entry.values
    if (!values) throw new Error('当前图表的数据系列无法读取，不能替换')
    const categoriesRef = entry.xValuesRef ?? entry.categoriesRef
    const categories = categoriesRef ? read(categoriesRef).vector.map(category) : entry.xValues?.map(category) ?? entry.categories?.map(category)
    const name = entry.nameRef ? category(read(entry.nameRef).vector[0]) : entry.name ?? `系列 ${index + 1}`
    return { name, values, ...(entry.valuesRef ? { valuesRef: entry.valuesRef } : {}), ...(categories === undefined ? {} : { categories }),
      ...(categoriesRef ? { categoriesRef } : {}), ...(entry.color === undefined ? {} : { color: entry.color }),
      ...(chart.kind === 'combo' ? { plot: entry.plot ?? (index === chart.series.length - 1 ? 'lineChart' : 'barChart'), secondaryAxis: entry.secondaryAxis ?? index === chart.series.length - 1 } : {}) }
  })
}

// 固定源 chart-visual.transposeChartSeries：切换原始系列缓存，最多前24个分类，输出字面系列。
export function transposeChartDataSeries(series: readonly ChartSeriesSetEntry[], combo = false): ChartSeriesSetEntry[] | null {
  const names = series.map((entry, index) => entry.name || `系列 ${index + 1}`), categories = series[0]?.categories ?? []
  if (!categories.length) return null
  const result = categories.slice(0, 24)
  return result.map((name, index) => ({ name: (name || `系列 ${index + 1}`).slice(0, 255), values: series.map(entry => entry.values[index] ?? 0), categories: names,
    ...(combo ? { plot: result.length >= 2 && index === result.length - 1 ? 'lineChart' as const : 'barChart' as const, secondaryAxis: result.length >= 2 && index === result.length - 1 } : {}) }))
}

interface SeriesRow { name: string; valuesRange: string; categoriesRange: string; source: number | null; plot: 'barChart' | 'lineChart'; secondary: boolean }
export function createChartDataDialog(root: HTMLElement, host: { readVector(range: string): Promise<ChartDataVector>; apply(series: readonly ChartSeriesSetEntry[]): Promise<void> }) {
  let initial: readonly ChartSeriesSetEntry[] = [], rows: SeriesRow[] = [], generation = 0, phase: 'reading' | 'applying' | undefined, disposed = false, combo = false
  const requestClose = () => { if (phase !== 'applying') close() }
  const modal = createModal({ root, label: '选择数据源', closeLabel: '关闭选择数据源', variant: 'wide', cardClass: 'workbook-ribbon-format-dialog workbook-chart-data-dialog', onRequestClose: requestClose,
    content: '<h2>选择数据源</h2><form><div class="workbook-chart-data-head"><span>系列名称</span><span>系列数值区域</span><span>分类标签区域</span><span data-chart-data-combo-heading hidden>系列类型</span><span data-chart-data-combo-heading hidden>次坐标轴</span><span>系列顺序</span></div><div data-chart-data-rows></div><div class="workbook-chart-data-tools"><button type="button" data-chart-data-add>添加系列</button><button type="button" data-chart-data-switch>切换行/列</button></div><p role="alert" class="workbook-ribbon-format-error"></p><p role="status" aria-live="polite" data-chart-data-progress hidden>正在读取或应用图表数据…</p><div class="workbook-ribbon-format-actions"><button type="button" data-chart-data-cancel>取消</button><button type="submit" data-chart-data-submit>确定</button></div></form>' })
  const form = modal.card.querySelector('form')!, container = modal.card.querySelector<HTMLElement>('[data-chart-data-rows]')!, error = modal.card.querySelector<HTMLElement>('[role=alert]')!
  const add = modal.card.querySelector<HTMLButtonElement>('[data-chart-data-add]')!, submit = modal.card.querySelector<HTMLButtonElement>('[data-chart-data-submit]')!, cancel = modal.card.querySelector<HTMLButtonElement>('[data-chart-data-cancel]')!
  const switchButton = modal.card.querySelector<HTMLButtonElement>('[data-chart-data-switch]')!, progress = modal.card.querySelector<HTMLElement>('[data-chart-data-progress]')!
  const controls = () => {
    modal.card.setAttribute('aria-busy', String(Boolean(phase))); progress.hidden = !phase
    form.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement>('input,button,select').forEach(node => { node.disabled = Boolean(phase) })
    add.disabled = Boolean(phase) || rows.length >= 24; submit.disabled = Boolean(phase) || !rows.length
    switchButton.disabled = Boolean(phase) || !initial.length; cancel.disabled = phase === 'applying'
    if (modal.closeButton) modal.closeButton.disabled = phase === 'applying'
    container.querySelectorAll<HTMLElement>('[data-chart-data-row]').forEach((node, index) => {
      node.querySelector<HTMLButtonElement>('[data-chart-data-up]')!.disabled = Boolean(phase) || index === 0
      node.querySelector<HTMLButtonElement>('[data-chart-data-down]')!.disabled = Boolean(phase) || index === rows.length - 1
    })
  }
  const render = () => {
    container.replaceChildren()
    rows.forEach((row, index) => {
      const node = document.createElement('div'); node.className = 'workbook-chart-data-row'; node.dataset.chartDataRow = ''
      for (const [field, key, placeholder] of [['name', 'name', `系列 ${index + 1}`], ['values', 'valuesRange', row.source === null ? '例如 Sheet1!B2:B10' : initial[row.source]?.valuesRef ?? '保持原数据'], ['categories', 'categoriesRange', row.source === null ? '例如 Sheet1!A2:A10' : initial[row.source]?.categoriesRef ?? '保持原分类']] as const) {
        const input = document.createElement('input'); input.dataset[`chartData${field[0]!.toUpperCase()}${field.slice(1)}`] = ''; input.value = row[key]; input.placeholder = placeholder
        input.setAttribute('aria-label', `系列 ${index + 1} ${field === 'name' ? '名称' : field === 'values' ? '数值区域' : '分类区域'}`)
        input.addEventListener('input', () => { row[key] = input.value }); node.append(input)
      }
      if (combo) {
        const select = document.createElement('select'); select.dataset.chartDataPlot = ''; select.setAttribute('aria-label', `系列 ${index + 1} 类型`)
        for (const [value, text] of [['barChart', '柱形图'], ['lineChart', '折线图']]) { const option = document.createElement('option'); option.value = value!; option.textContent = text!; select.append(option) }
        select.value = row.plot; select.addEventListener('change', () => { row.plot = select.value as SeriesRow['plot'] }); node.append(select)
        const label = document.createElement('label'), checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.dataset.chartDataSecondary = ''; checkbox.checked = row.secondary; checkbox.setAttribute('aria-label', `系列 ${index + 1} 次坐标轴`)
        checkbox.addEventListener('change', () => { row.secondary = checkbox.checked }); label.append(checkbox, '次坐标轴'); node.append(label)
      }
      const actions = document.createElement('span'); actions.className = 'workbook-chart-data-row-actions'
      for (const [action, text, label] of [['up', '↑', '上移'], ['down', '↓', '下移'], ['remove', '×', '删除系列']] as const) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = text; button.dataset[`chartData${action[0]!.toUpperCase()}${action.slice(1)}`] = ''; button.setAttribute('aria-label', `系列 ${index + 1} ${label}`)
        button.addEventListener('click', () => {
          if (phase) return
          const nextIndex = action === 'remove' ? Math.min(index, rows.length - 2) : index + (action === 'up' ? -1 : 1)
          if (action === 'remove') rows.splice(index, 1)
          else { const at = nextIndex; if (rows[at]) [rows[index], rows[at]] = [rows[at]!, rows[index]!] }
          render()
          ;(container.children[nextIndex]?.querySelector<HTMLInputElement>('[data-chart-data-name]') ?? add).focus()
        }); actions.append(button)
      }
      node.append(actions); container.append(node)
    }); controls()
  }
  const close = () => { generation++; phase = undefined; modal.close() }
  cancel.addEventListener('click', requestClose)
  add.addEventListener('click', () => { if (!phase && rows.length < 24) { rows.push({ name: '', valuesRange: '', categoriesRange: '', source: null, plot: 'barChart', secondary: false }); render(); container.lastElementChild?.querySelector('input')?.focus() } })
  const apply = async (build: () => Promise<readonly ChartSeriesSetEntry[]>) => {
    if (phase || disposed || modal.overlay.hidden) return
    const token = ++generation; phase = 'reading'; error.textContent = ''; controls()
    try {
      const series = await build()
      if (disposed || token !== generation) return
      if (!series.length) throw new Error('至少保留一个数据系列')
      phase = 'applying'; controls(); await host.apply(series)
      if (!disposed && token === generation) close()
    } catch (cause) { if (!disposed && token === generation) error.textContent = cause instanceof Error ? cause.message : String(cause) }
    finally { if (!disposed && token === generation) { phase = undefined; controls() } }
  }
  form.addEventListener('submit', event => {
    event.preventDefault(); void apply(async () => {
      const result: ChartSeriesSetEntry[] = []
      for (const [index, row] of rows.entries()) {
        const original = row.source === null ? undefined : initial[row.source], name = (row.name.trim() || original?.name || `系列 ${index + 1}`).slice(0, 255)
        if (!original && !row.valuesRange.trim()) throw new Error(`系列“${name}”需要数值区域`)
        const values = row.valuesRange.trim() ? await host.readVector(row.valuesRange.trim()) : undefined
        const categories = row.categoriesRange.trim() ? await host.readVector(row.categoriesRange.trim()) : undefined
        result.push({ ...original, name, values: values ? values.vector.map(numeric) : original?.values ?? [], ...(values ? { valuesRef: values.ref } : {}), ...(categories ? { categories: categories.vector.map(category), categoriesRef: categories.ref } : {}), ...(combo ? { plot: row.plot, secondaryAxis: row.secondary } : {}) })
      }
      return result
    })
  })
  switchButton.addEventListener('click', () => { void apply(async () => { const result = transposeChartDataSeries(initial, combo); if (!result) throw new Error('没有可切换的分类标签'); return result }) })
  return {
    open(series: readonly ChartSeriesSetEntry[], isCombo = false) { if (disposed || phase) return; generation++; combo = isCombo; initial = structuredClone(series); rows = initial.map((entry, index) => ({ name: entry.name, valuesRange: '', categoriesRange: '', source: index, plot: entry.plot ?? (combo && index === initial.length - 1 ? 'lineChart' : 'barChart'), secondary: entry.secondaryAxis ?? (combo && index === initial.length - 1) })); modal.card.classList.toggle('workbook-chart-data-combo', combo); modal.card.querySelectorAll<HTMLElement>('[data-chart-data-combo-heading]').forEach(node => { node.hidden = !combo }); error.textContent = ''; render(); modal.open(container.querySelector('input')) },
    isApplying: () => phase === 'applying', isBusy: () => Boolean(phase), close,
    dispose() { if (disposed) return; disposed = true; generation++; modal.remove() },
  }
}

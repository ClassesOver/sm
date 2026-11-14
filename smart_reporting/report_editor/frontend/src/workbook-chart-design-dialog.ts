import { createModal } from './modal'
import type { ChartReadDesign } from '@sheets-web/xlsx-engine'

export type ChartDesignTarget = { initial?: ChartReadDesign } & (
  | { chartPath: string; sheetId: string; sheetName: string; property: 'title'; initialTitle?: string }
  | { chartPath: string; sheetId: string; sheetName: string; property: 'categoryTitle' | 'valueTitle' }
  | { chartPath: string; sheetId: string; sheetName: string; property: 'labels' | 'format' | 'legend' })

export type ChartDesignEdit = {
  chartPath: string
  title?: string
  legend?: 'none' | 'left' | 'right' | 'top' | 'bottom'
  axisTitles?: { category?: string | null; value?: string | null }
  dataLabels?: 'none' | 'value' | 'percent' | 'category-percent'
  grouping?: 'clustered' | 'stacked' | 'percentStacked'
  gridlines?: boolean
}

export function createChartDesignDialog(root: HTMLElement, apply: (edit: ChartDesignEdit, target: ChartDesignTarget) => void | Promise<void>) {
  let applying = false, disposed = false, generation = 0
  const requestClose = () => { if (!applying) close() }
  const modal = createModal({
    root,
    label: '编辑图表设计',
    closeLabel: '关闭图表设计',
    overlayClass: 'workbook-ribbon-format-overlay',
    cardClass: 'workbook-ribbon-format-dialog',
    onRequestClose: requestClose,
    content: '<h2>编辑图表设计</h2><form class="workbook-ribbon-format-form"><label data-chart-design-axis>标题<input aria-label="图表轴标题" type="text"></label><label data-chart-design-labels>数据标签<select aria-label="数据标签"><option value="none">无</option><option value="value">值</option><option value="percent">百分比</option><option value="category-percent">分类和百分比</option></select></label><label data-chart-design-format>分组<select aria-label="图表分组"><option value="clustered">簇状</option><option value="stacked">堆积</option><option value="percentStacked">百分比堆积</option></select></label><label data-chart-design-gridlines><input aria-label="显示主网格线" type="checkbox">显示主网格线</label><p role="alert" class="workbook-ribbon-format-error"></p><div class="workbook-ribbon-format-actions"><button type="button" data-chart-design-cancel>取消</button><button type="submit" data-chart-design-submit>确定</button></div></form>',
  })
  const form = modal.card.querySelector('form')!, axis = modal.card.querySelector<HTMLElement>('[data-chart-design-axis]')!
  const input = modal.card.querySelector<HTMLInputElement>('[aria-label="图表轴标题"]')!
  const labels = modal.card.querySelector<HTMLElement>('[data-chart-design-labels]')!
  const select = modal.card.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')!
  const format = modal.card.querySelector<HTMLElement>('[data-chart-design-format]')!
  const grouping = modal.card.querySelector<HTMLSelectElement>('[aria-label="图表分组"]')!
  const gridline = modal.card.querySelector<HTMLInputElement>('[aria-label="显示主网格线"]')!
  const gridlines = modal.card.querySelector<HTMLElement>('[data-chart-design-gridlines]')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  const legendLabel = document.createElement('label')
  legendLabel.innerHTML = '图例位置<select aria-label="图例位置"><option value="">请选择</option><option value="none">无</option><option value="left">左侧</option><option value="right">右侧</option><option value="top">顶部</option><option value="bottom">底部</option></select>'
  form.insertBefore(legendLabel, error)
  const legend = legendLabel.querySelector('select')!
  let target: ChartDesignTarget | undefined
  let opened = { input: '', legend: '', labels: '', grouping: '', gridlines: false }
  const current = () => ({ input: input.value, legend: legend.value, labels: select.value, grouping: grouping.value, gridlines: gridline.checked })
  const selectCurrent = (control: HTMLSelectElement, value: string | undefined) => {
    control.querySelector('[data-chart-design-preserve]')?.remove()
    if (![...control.options].some(option => option.value === value)) {
      const option = document.createElement('option'); option.value = ''; option.textContent = value === 'top-right' ? '右上角（保留原设置）' : '自定义（保留原设置）'
      option.dataset.chartDesignPreserve = ''; control.prepend(option); control.value = ''
    } else control.value = value!
  }
  const submit = modal.card.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!
  const progress = document.createElement('p')
  progress.setAttribute('role', 'status'); progress.tabIndex = -1; progress.hidden = true
  progress.textContent = '正在应用图表修改，请稍候…'; error.before(progress)
  const setApplying = (value: boolean) => {
    applying = value
    modal.card.setAttribute('aria-busy', String(value))
    form.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>('input,select,button').forEach(control => { control.disabled = value })
    if (modal.closeButton) modal.closeButton.disabled = value
    submit.textContent = value ? '正在应用…' : '确定'
    progress.hidden = !value
    if (value) progress.focus()
  }
  const onPendingKeyDown = (event: KeyboardEvent) => {
    if (applying && !modal.overlay.hidden && modal.overlay.getAttribute('aria-modal') === 'true' && event.key === 'Tab' && !event.isComposing && event.keyCode !== 229 && !event.defaultPrevented) {
      event.preventDefault(); progress.focus()
    }
  }
  window.addEventListener('keydown', onPendingKeyDown)
  const close = () => { generation++; setApplying(false); modal.close() }
  modal.card.querySelector('[data-chart-design-cancel]')!.addEventListener('click', requestClose)
  form.addEventListener('submit', async event => {
    event.preventDefault()
    if (applying || disposed || modal.overlay.hidden) return
    const token = ++generation
    error.textContent = ''
    try {
      if (!target) throw new Error('请重新选择图表')
      const unchanged = (key: keyof typeof opened) => target!.initial !== undefined && current()[key] === opened[key]
      const edit: ChartDesignEdit = { chartPath: target.chartPath }
      if (target.property === 'title') {
        if (!unchanged('input')) {
          if (input.value.length > 200) throw new Error('图表标题最多 200 个字符')
          edit.title = input.value
        }
      }
      else if (target.property === 'legend') {
        if (!unchanged('legend')) {
          if (!['none', 'left', 'right', 'top', 'bottom'].includes(legend.value)) throw new Error('请选择图例位置')
          edit.legend = legend.value as NonNullable<ChartDesignEdit['legend']>
        }
      }
      else if (target.property === 'labels') { if (!unchanged('labels')) edit.dataLabels = select.value as NonNullable<ChartDesignEdit['dataLabels']> }
      else if (target.property === 'format') {
        if (!unchanged('grouping')) edit.grouping = grouping.value as NonNullable<ChartDesignEdit['grouping']>
        if (!unchanged('gridlines')) edit.gridlines = gridline.checked
      }
      else if (!unchanged('input')) edit.axisTitles = target.property === 'categoryTitle' ? { category: input.value.trim() || null } : { value: input.value.trim() || null }
      if (Object.keys(edit).length === 1) { close(); return }
      setApplying(true)
      const result = apply(edit, { ...target })
      if (result) await result
      if (!disposed && token === generation) close()
    } catch (cause) {
      if (!disposed && token === generation) error.textContent = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (!disposed && token === generation) {
        setApplying(false)
        if (!modal.overlay.hidden && (document.activeElement === document.body || document.activeElement === progress)) submit.focus()
      }
    }
  })
  return {
    open(next: ChartDesignTarget) {
      if (disposed || applying) return
      generation++
      target = { ...next }
      const isLabels = next.property === 'labels', isFormat = next.property === 'format', isLegend = next.property === 'legend'
      axis.hidden = isLabels || isFormat || isLegend; labels.hidden = !isLabels; format.hidden = !isFormat; gridlines.hidden = !isFormat; legendLabel.hidden = !isLegend
      input.setAttribute('aria-label', next.property === 'title' ? '图表标题' : next.property === 'categoryTitle' ? '分类轴标题' : '数值轴标题')
      input.value = next.property === 'title' ? next.initialTitle ?? '' : next.property === 'categoryTitle' ? next.initial?.axisTitles?.category ?? '' : next.initial?.axisTitles?.value ?? ''
      input.placeholder = next.initial && next.property !== 'title' && next.initial.axisTitles?.[next.property === 'categoryTitle' ? 'category' : 'value'] === undefined ? '保留当前设置；输入新标题可替换' : ''
      selectCurrent(legend, next.initial ? next.initial.legend : '')
      selectCurrent(select, next.initial ? next.initial.dataLabels : 'none')
      selectCurrent(grouping, next.initial ? next.initial.grouping : 'clustered')
      gridline.checked = next.initial?.gridlines ?? false; gridline.indeterminate = next.initial !== undefined && next.initial.gridlines === undefined
      error.textContent = ''; opened = current()
      modal.open(isLegend ? legend : isLabels ? select : isFormat ? grouping : input)
    },
    isApplying: () => applying,
    close,
    dispose() { disposed = true; applying = false; generation++; window.removeEventListener('keydown', onPendingKeyDown); modal.remove() },
  }
}

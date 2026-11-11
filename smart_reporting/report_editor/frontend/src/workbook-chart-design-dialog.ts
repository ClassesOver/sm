import { createModal } from './modal'

export type ChartDesignTarget =
  | { chartPath: string; sheetId: string; sheetName: string; property: 'title'; initialTitle?: string }
  | { chartPath: string; sheetId: string; sheetName: string; property: 'categoryTitle' | 'valueTitle' }
  | { chartPath: string; sheetId: string; sheetName: string; property: 'labels' | 'format' | 'legend' }

export type ChartDesignEdit = {
  chartPath: string
  title?: string
  legend?: 'none' | 'left' | 'right' | 'top' | 'bottom'
  axisTitles?: { category?: string | null; value?: string | null }
  dataLabels?: 'none' | 'value' | 'percent' | 'category-percent'
  grouping?: 'clustered' | 'stacked' | 'percentStacked'
  gridlines?: boolean
}

export function createChartDesignDialog(root: HTMLElement, apply: (edit: ChartDesignEdit, target: ChartDesignTarget) => void) {
  const modal = createModal({
    root,
    label: '编辑图表设计',
    closeLabel: '关闭图表设计',
    overlayClass: 'workbook-ribbon-format-overlay',
    cardClass: 'workbook-ribbon-format-dialog',
    content: '<h2>编辑图表设计</h2><form><label data-chart-design-axis>标题<input aria-label="图表轴标题" type="text"></label><label data-chart-design-labels>数据标签<select aria-label="数据标签"><option value="none">无</option><option value="value">值</option><option value="percent">百分比</option><option value="category-percent">分类和百分比</option></select></label><label data-chart-design-format>分组<select aria-label="图表分组"><option value="clustered">簇状</option><option value="stacked">堆积</option><option value="percentStacked">百分比堆积</option></select></label><label data-chart-design-gridlines><input aria-label="显示主网格线" type="checkbox">显示主网格线</label><p role="alert"></p><div><button type="button" data-chart-design-cancel>取消</button><button type="submit" data-chart-design-submit>确定</button></div></form>',
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
  modal.card.querySelector('[data-chart-design-cancel]')!.addEventListener('click', modal.close)
  form.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (!target) throw new Error('请重新选择图表')
      const edit: ChartDesignEdit = { chartPath: target.chartPath }
      if (target.property === 'title') {
        if (input.value.length > 200) throw new Error('图表标题最多 200 个字符')
        edit.title = input.value
      }
      else if (target.property === 'legend') {
        if (!['none', 'left', 'right', 'top', 'bottom'].includes(legend.value)) throw new Error('请选择图例位置')
        edit.legend = legend.value as NonNullable<ChartDesignEdit['legend']>
      }
      else if (target.property === 'labels') edit.dataLabels = select.value as NonNullable<ChartDesignEdit['dataLabels']>
      else if (target.property === 'format') { edit.grouping = grouping.value as NonNullable<ChartDesignEdit['grouping']>; edit.gridlines = gridline.checked }
      else edit.axisTitles = target.property === 'categoryTitle' ? { category: input.value.trim() || null } : { value: input.value.trim() || null }
      apply(edit, target); modal.close()
    } catch (cause) { error.textContent = (cause as Error).message }
  })
  return {
    open(next: ChartDesignTarget) {
      target = { ...next }
      const isLabels = next.property === 'labels', isFormat = next.property === 'format', isLegend = next.property === 'legend'
      axis.hidden = isLabels || isFormat || isLegend; labels.hidden = !isLabels; format.hidden = !isFormat; gridlines.hidden = !isFormat; legendLabel.hidden = !isLegend
      input.setAttribute('aria-label', next.property === 'title' ? '图表标题' : next.property === 'categoryTitle' ? '分类轴标题' : '数值轴标题')
      input.value = next.property === 'title' ? next.initialTitle ?? '' : ''; legend.value = ''; select.value = 'none'; grouping.value = 'clustered'; gridline.checked = false; error.textContent = ''
      modal.open(isLegend ? legend : isLabels ? select : isFormat ? grouping : input)
    },
    close: modal.close,
    dispose: modal.remove,
  }
}

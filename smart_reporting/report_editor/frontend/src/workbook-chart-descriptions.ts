import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import { createModal } from './modal'
import { chartLegendName, type Worksheet } from './workbook-vendor/grid/chart-legend'
import './workbook-chart-descriptions.css'

const kinds: Record<ChartReadSpec['kind'], string> = {
  column: '柱形图', bar: '条形图', line: '折线图', area: '面积图', pie: '饼图',
  doughnut: '圆环图', scatter: '散点图', radar: '雷达图', combo: '组合图',
}

/** 画布之外的只读文本入口，供完整标题阅读和辅助技术使用。 */
export function createWorkbookChartDescriptions(host: HTMLElement) {
  let disposed = false
  const modal = createModal({ root: host, label: '图表说明', closeLabel: '关闭图表说明', cardClass: 'workbook-chart-descriptions',
    content: '<h2>图表说明</h2><p data-chart-description-sheet></p><p>当前工作表可预览图表的完整标题与数据来源。</p><div class="workbook-chart-descriptions-scroll" tabindex="0" role="region" aria-label="图表说明列表"><p data-chart-description-empty hidden>当前工作表没有可预览的图表。</p><ol></ol></div><footer><button type="button" data-chart-descriptions-close>关闭</button></footer>',
  })
  const list = modal.card.querySelector('ol')!, empty = modal.card.querySelector<HTMLElement>('[data-chart-description-empty]')!
  const close = () => modal.close()
  modal.card.querySelector('[data-chart-descriptions-close]')!.addEventListener('click', close)
  return {
    open(sheetName: string, charts: readonly ChartReadSpec[], worksheet?: Worksheet, select?: (chartPath: string) => void) {
      if (disposed) return
      modal.card.querySelector<HTMLElement>('[data-chart-description-sheet]')!.textContent = `工作表：${sheetName}`
      list.replaceChildren(); empty.hidden = charts.length > 0
      charts.forEach((chart, index) => {
        const item = document.createElement('li'), heading = document.createElement('h3'), type = document.createElement('p'), seriesList = document.createElement('ul')
        item.dataset.chartDescription = String(index)
        heading.textContent = chart.title?.trim() ? chart.title : `未命名图表 ${index + 1}`
        type.textContent = kinds[chart.kind]
        chart.series.forEach((series, seriesIndex) => {
          const row = document.createElement('li'), name = document.createElement('strong'), sources = document.createElement('p')
          name.textContent = worksheet ? chartLegendName(series, seriesIndex, worksheet)
            : series.nameCache || (!series.nameRef && series.name) || `系列 ${seriesIndex + 1}`
          sources.textContent = [series.nameRef && `名称：${series.nameRef}`, `值：${series.valuesRef || '来源区域未提供'}`,
            series.categoriesRef && `分类：${series.categoriesRef}`, series.xValuesRef && `X 值：${series.xValuesRef}`].filter(Boolean).join('；')
          row.append(name, sources); seriesList.append(row)
          const fills = [series.color && `系列填充：${series.color === 'transparent' ? '无填充' : series.color}`,
            ...Object.entries(series.pointColors ?? {}).map(([index, color]) => `第 ${Number(index) + 1} 个数据点：${color === 'transparent' ? '无填充' : color}`)]
            .filter(Boolean)
          if (fills.length || series.colorPreviewUnavailable) {
            const colors = document.createElement('p')
            colors.dataset.chartFillDescription = ''
            colors.textContent = [...fills, series.colorPreviewUnavailable && '来源填充暂不支持预览，请下载原件查看'].filter(Boolean).join('；')
            row.append(colors)
          }
        })
        item.append(heading, type, seriesList)
        if (select) {
          const button = document.createElement('button');button.type = 'button';button.dataset.selectChart = chart.chartPath
          button.textContent = '选择此图表';button.setAttribute('aria-label', `选择图表 ${index+1}：${heading.textContent}`)
          button.addEventListener('click', () => { select(chart.chartPath);modal.close() })
          item.append(button)
        }
        list.append(item)
      })
      if (modal.overlay.hidden) modal.open()
      modal.card.querySelector<HTMLElement>('.workbook-chart-descriptions-scroll')!.scrollTop = 0
    },
    close,
    dispose() { if (disposed) return; disposed = true; modal.remove() },
  }
}

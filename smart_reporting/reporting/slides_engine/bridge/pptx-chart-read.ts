/** Read parsed OOXML caches without granting chart rebuild permission or opening links. */
import type { ChartModel } from '@genoffice/pptx-engine'

export function inspectChartReadData(chart: ChartModel) {
  return {
    source: 'ooxml-cache',
    kind: chart.kind,
    title: chart.title ?? '',
    categories: [...chart.categories],
    series: chart.series.map(series => ({
      name: series.name ?? '',
      values: [...series.values],
      ...(series.xValues ? { xValues: [...series.xValues] } : {}),
      ...(series.bubbleSizes ? { bubbleSizes: [...series.bubbleSizes] } : {}),
      ...(series.plotKind ? { plotKind: series.plotKind } : {}),
    })),
  }
}

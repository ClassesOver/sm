// 使用官方 Univer 网格、单元格文字/合并/边框/角标和实际图表扩展，不替换绘制器。
import { LocaleType } from '@univerjs/core'
import { IRenderManagerService } from '@univerjs/engine-render'
import { UniverSheetsCorePreset } from '@univerjs/preset-sheets-core'
import EnUS from '@univerjs/preset-sheets-core/locales/en-US'
import '@univerjs/preset-sheets-core/lib/index.css'
import { createUniver } from '../src/workbook-vendor/grid/create-univer'
import { setCharts } from '../src/workbook-vendor/grid/chart-render'

const id = 'chart-layering-component', sheetId = 'summary'
const runtime = createUniver({
  locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: EnUS },
  presets: [UniverSheetsCorePreset({ container: 'workbook-grid', header: false, toolbar: false, formulaBar: false, footer: false })],
})
setCharts(id, sheetId, [{
  chartPath: 'xl/charts/chart1.xml', kind: 'column', title: 'Anchored chart above source cells',
  anchor: { fromRow: 1, fromColumn: 3, toRow: 15, toColumn: 10, toColumnOffset: 66000, toRowOffset: 33000 },
  series: [{ valuesRef: 'B2:B3', categoriesRef: 'A2:A3', color: '#2F9E6E' }],
}])
const workbook = (runtime.univerAPI as unknown as { createWorkbook(data: unknown): unknown }).createWorkbook({
  id, name: 'Layering regression', appVersion: '0.25.1', locale: LocaleType.EN_US,
  sheetOrder: [sheetId], styles: { numeric: { n: { pattern: '0.00' } }, frameCell: { bd: { t: { s: 1, cl: { rgb: '#D00000' } } } } }, sheets: { [sheetId]: {
    id: sheetId, name: 'Summary', rowCount: 40, columnCount: 20,
    defaultColumnWidth: 80, defaultRowHeight: 20,
    mergeData: [{ startRow: 6, endRow: 6, startColumn: 3, endColumn: 5 }],
    cellData: {
      0: { 0: { v: 'Quarter' }, 1: { v: 'Sales' } },
      1: { 0: { v: 'Q1' }, 1: { v: 10, t: 2, s: 'numeric' }, 3: { v: 'Cell below frame', s: 'frameCell' } },
      2: { 0: { v: 'Q2' }, 1: { v: 20 } },
      3: { 3: { v: 30, f: '=SUM(B2:B3)', markers: { tr: { color: '#F97316', size: 8 } } } },
      4: { 4: { v: 'Preserved hyperlink', s: { cl: { rgb: '#0000FF' }, ul: { s: 1 } } } },
      6: { 3: { v: 'Preserve merged data', s: { bg: { rgb: '#FFF2CC' }, bd: { t: { s: 1, cl: { rgb: '#D00000' } } } } } },
      18: { 3: { v: 'Visible source cell outside chart' } },
    },
  } },
})
;(window as unknown as { layeringComponent: unknown }).layeringComponent = {
  workbook,
  diagnostics: () => {
    const render = runtime.univer.__getInjector().get(IRenderManagerService).getRenderById(id)
    const component = render?.mainComponent
    const worksheet = component?.getSkeleton().worksheet
    return { extensions: component?.getExtensionsByOrder().map(extension => ({ key: extension.uKey, zIndex: extension.zIndex })), numericSource: { raw: worksheet?.getCellRaw(1, 1), display: worksheet?.getCell(1, 1) }, preservedCells: [worksheet?.getCellRaw(3, 3), worksheet?.getCellRaw(4, 4), worksheet?.getCellRaw(6, 3), worksheet?.getCellRaw(18, 3)] }
  },
}

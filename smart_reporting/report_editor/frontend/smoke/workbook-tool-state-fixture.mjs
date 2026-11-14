// 真实监视组件与透视几何适配器；工作簿读取、视口映射和提交为显式夹具。
import { createWorkbookWatchWindow } from '../src/workbook-watch-window'
import { installPivotControlGeometry } from '../src/workbook-pivot-control-geometry'
import { CanvasFloatDomService } from '@univerjs/ui'
import { IRenderManagerService, SHEET_VIEWPORT_KEY } from '@univerjs/engine-render'
import { BehaviorSubject } from 'rxjs'
import '../src/style.css'
import '../src/office-theme.css'
import '../src/workbook.css'

const mode = new URLSearchParams(location.search).get('mode')
const root = document.body.appendChild(document.createElement('main'))
const heading = root.appendChild(document.createElement('h1')); heading.textContent = '工作表工具动态状态检查'
const opener = root.appendChild(document.createElement('button')); opener.id = 'tool-open'; opener.textContent = '打开工具'
const outside = root.appendChild(document.createElement('button')); outside.id = 'tool-outside'; outside.textContent = '返回工作表'
let unavailable = false, reads = 0, commits = [], errors = [], consumeEscape = false
const identity = {}, sheet = {
  getSheetId: () => 'sheet', getSheetName: () => '跨年度部门汇总与费用分析', getMaxRows: () => 100, getMaxColumns: () => 100,
  getRange: (row, column) => ({ getDisplayValue: () => column === 0 ? '长内容逐字保留用于监视核对。'.repeat(16) : String(row * 10 + column), getFormula: () => column === 1 ? '=' + Array(50).fill('A1').join('+') : '' }),
}
const book = { getWorkbook: () => identity, getActiveSheet: () => sheet, getActiveRange: () => mode === 'empty' ? null : ({ getRange: () => ({ startRow: 0, endRow: 3, startColumn: 0, endColumn: 2 }) }), getSheetBySheetId: () => unavailable ? null : sheet }
const watch = createWorkbookWatchWindow(root, () => { reads++; return book })
const service = new CanvasFloatDomService()
const source = new BehaviorSubject({ startX: 0, startY: 0, endX: 140, endY: 110, width: 140, height: 110, rotate: 0, absolute: { left: true, top: true } })
let geometry, form, drag
if (mode === 'pivot') {
  const canvas = root.appendChild(document.createElement('section')); canvas.setAttribute('aria-label', '视口映射夹具'); canvas.style.cssText = 'position:fixed;left:16px;top:100px;right:16px;bottom:16px;border:1px solid var(--office-border)'
  form = canvas.appendChild(document.createElement('form')); form.style.cssText = 'position:absolute;left:4px;top:4px;width:140px;height:110px;background:var(--office-chrome);border:1px solid var(--office-border);padding:8px;box-sizing:border-box'
  drag = form.appendChild(document.createElement('button')); drag.type = 'button'; drag.id = 'pivot-drag'; drag.textContent = '移动透视控件'; drag.style.touchAction = 'none'
  form.appendChild(document.createElement('p')).textContent = '拖动预览；松开提交，Esc 撤回。'
  service.addFloatDom({ id: 'fixture', unitId: 'book', componentKey: 'fixture', position$: source, onPointerDown() {}, onPointerMove() {}, onPointerUp() {}, onWheel() {} })
  const pane = { viewportKey: SHEET_VIEWPORT_KEY.VIEW_MAIN, isActive: true, left: 0, top: 0, width: innerWidth - 32, height: innerHeight - 116 }
  const scene = { getViewports: () => [pane], getAncestorScale: () => ({ scaleX: 1, scaleY: 1 }), getActiveViewportByCoord: () => pane, getCoordRelativeToViewport: value => value, getScrollXYInfoByViewport: () => ({ x: 0, y: 0 }) }
  const render = { scene, engine: { getCanvasElement: () => canvas }, with: () => ({ getCurrentSkeleton: () => ({ getCellWithCoordByOffset: (x, y) => ({ actualRow: Math.floor(y / 20), actualColumn: Math.floor(x / 50) }) }) }) }
  const univer = { __getInjector: () => ({ get: token => token === CanvasFloatDomService ? service : token === IRenderManagerService ? { getRenderById: () => render } : undefined }) }
  window.addEventListener('keydown', event => { if (consumeEscape && event.key === 'Escape') { consumeEscape = false; event.preventDefault() } }, true)
  geometry = installPivotControlGeometry(univer, 'fixture', { row: 0, column: 0, width: 140, height: 110 }, { canEdit: () => true, commit: async value => { commits.push(value) }, error: message => errors.push(message) })
  drag.addEventListener('pointerdown', event => geometry.start(event, drag, 'move'))
  opener.addEventListener('click', () => drag.focus())
} else opener.addEventListener('click', () => {
  watch.toggle()
  if (mode !== 'empty' && watch.state().active) root.querySelector('[data-watch-add]').click()
  if (mode === 'unavailable') unavailable = true
})
window.workbookToolFixture = {
  stats: () => ({ reads, commits, errors, active: watch.state().active, preview: service.domLayers[0]?.[1].position$ !== source }),
  restore: () => { unavailable = false }, removeSource: () => { unavailable = true },
  consumeNextEscape: () => { consumeEscape = true }, dispose: () => { geometry?.dispose(); watch.dispose() },
}
document.documentElement.dataset.fixtureReady = 'true'

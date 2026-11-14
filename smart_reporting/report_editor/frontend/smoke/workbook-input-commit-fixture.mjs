// 使用真实产品组件；工作表及文件服务只以显式回调计数，不模拟保存成功。
import React from 'react'
import { createRoot } from 'react-dom/client'
import { createWorkbookZoomDialog } from '../src/workbook-zoom-dialog'
import { createConsolidateDialog } from '../src/workbook-consolidate-dialog'
import { FunctionArgumentsDialog } from '../src/workbook-function-arguments-dialog'
import { InsertFunctionDialog } from '../src/workbook-function-catalog-dialog'
import '../src/style.css'
import '../src/office-theme.css'
import '../src/workbook.css'
import '../src/workbook-insert-function.css'

const mode = new URLSearchParams(location.search).get('mode')
const main = document.body.appendChild(document.createElement('main'))
const heading = main.appendChild(document.createElement('h1')); heading.textContent = '工作表输入与确认检查'
const trigger = main.appendChild(document.createElement('button')); trigger.id = 'open-dialog'; trigger.textContent = '打开设置'
const outside = main.appendChild(document.createElement('button')); outside.id = 'worksheet'; outside.textContent = '工作表焦点入口'
const container = main.appendChild(document.createElement('div')); container.className = 'workbook-function-root'
let commits = [], cancels = 0, root
const spec = { name: 'SUM', category: 'Math', syntax: 'SUM(number1)', abstract: '求和', description: '对选定数值区域求和。', params: [{ name: 'number1', detail: '需要计算的数值区域', require: true, repeat: false }] }
const target = { workbookCore: {}, sheetCore: {}, unitId: 'book', sheetId: 'sheet', sheetName: 'Sheet', row: 0, col: 0, label: 'A1', formula: '', caret: 0, editorText: null }
const host = {
  evaluate: async (_target, expressions) => expressions.map(() => 6),
  observeRangePick: () => () => {}, pickExternalRange: () => () => {},
  listExternalPickTargets: async () => mode === 'external' ? [{ index: 1, name: '预算.xlsx', source: '/fixture/budget.xlsx', open: false, wcId: null, sheetNames: ['数据表'] }] : [],
}
const close = () => { root?.unmount(); root = null }
const ok = value => { commits.push(value); close() }
const cancel = () => { cancels++; close() }
const zoom = mode === 'zoom' ? createWorkbookZoomDialog(main, ok) : null
const consolidate = mode === 'consolidate' ? createConsolidateDialog(main, (_target, value) => ok(value)) : null
trigger.addEventListener('click', () => {
  if (zoom) return zoom.open(137)
  if (consolidate) return consolidate.open({ workbookId: 'book', sheetId: 'sheet', row: 0, column: 4, defaultReference: '', targetLabel: 'Summary!E1' })
  root = createRoot(container)
  root.render(mode === 'catalog'
    ? React.createElement(InsertFunctionDialog, { targetLabel: 'A1', catalog: [spec], recent: [], initialCategory: 'All', onPick: ok, onClose: cancel })
    : React.createElement(FunctionArgumentsDialog, { spec, target, initialArgs: ['A1:A3'], host, error: null, onOk: ok, onCancel: cancel }))
})
window.workbookInputFixture = { stats: () => ({ commits, cancels }) }
document.documentElement.dataset.fixtureReady = 'true'

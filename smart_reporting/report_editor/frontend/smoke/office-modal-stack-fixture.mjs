// 真实产品弹窗的层级组件夹具；回调只计数，不模拟文件或后端授权。
import { createModal } from '../src/modal'
import { createWorkbookZoomDialog } from '../src/workbook-zoom-dialog'
import { openDocxTableAltTextDialog } from '../src/docx-table-alt-text-controls'
import { openSlidesSizeDialog } from '../src/slides-size-dialog'
import { bindPdfExtractDialog } from '../src/pdf-extract-dialog'
import '../src/style.css'
import '../src/office-theme.css'
import '../src/docx.css'
import '../src/workbook.css'
import '../src/slides.css'
import '../src/pdf.css'

const mode = new URLSearchParams(location.search).get('mode')
const root = document.body.appendChild(document.createElement('main'))
const heading = document.createElement('h1'); heading.textContent = 'Office 弹窗层级检查'
const trigger = document.createElement('button'); trigger.textContent = '打开编辑设置'; trigger.id = 'stack-trigger'
root.append(heading, trigger)
let commits = 0, requests = 0, ancestorRequests = 0, busy = mode === 'busy'
// 特意先创建子窗、再创建父窗，检查可复用窗口的视觉顺序与监听顺序。
const zoom = mode === 'xlsx' ? createWorkbookZoomDialog(root, () => { commits++ }) : null
const parent = createModal({ root, label: '编辑设置', closeLabel: '关闭编辑设置', cardClass: 'docx-settings-dialog', content: '<h2>编辑设置</h2><form><label>当前草稿<input aria-label="当前草稿" value="尚未提交的父窗口中文草稿"></label><button type="button" data-open-child>更多设置</button></form>' })
const childTrigger = parent.card.querySelector('[data-open-child]')
parent.overlay.addEventListener('keydown', event => { if (event.isTrusted && event.key === 'Escape') ancestorRequests++ })
let child
if (['nested', 'busy', 'remove-parent'].includes(mode)) child = createModal({ root: mode === 'nested' ? parent.card : root, label: '高级设置', cardClass: 'docx-settings-dialog', content: '<h2>高级设置</h2><label>高级草稿<input aria-label="高级草稿" value="尚未提交的子窗口中文草稿"></label>', onRequestClose() { requests++; if (!busy) child.close() } })
childTrigger.addEventListener('click', () => {
  if (mode === 'xlsx') zoom.open(132)
  if (mode === 'docx') openDocxTableAltTextDialog(root, { title: '尚未提交的标题', description: '完整表格说明' }, () => { commits++ })
  if (['nested', 'busy', 'remove-parent'].includes(mode)) child.open()
  if (mode === 'pptx') openSlidesSizeDialog(root, { cx: 9144000, cy: 6858000 }, () => { commits++ })
  if (mode === 'pdf') bindPdfExtractDialog({ root, sourceSha256: 'a'.repeat(64), pageCount: () => 5, currentPage: () => 2, unavailable: () => null, extract: () => { commits++; return new Promise(() => {}) } }).open()
})
trigger.addEventListener('click', () => parent.open())
window.modalStackFixture = { parent, child, stats: () => ({ commits, requests, ancestorRequests }), release() { busy = false }, reopenParent() { parent.open() }, removeParent() { parent.remove() } }
document.documentElement.dataset.fixtureReady = 'true'

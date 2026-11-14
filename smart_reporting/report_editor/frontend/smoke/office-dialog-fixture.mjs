// 组件视觉夹具：使用产品弹窗与样式，不模拟文件保存或真实后端授权。
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { createDocxNoteDialog } from '../src/docx-notes-source'
import { createWorkbookZoomDialog } from '../src/workbook-zoom-dialog'
import { FunctionArgumentsDialog } from '../src/workbook-function-arguments-dialog'
import { bindPdfExtractDialog } from '../src/pdf-extract-dialog'
import { openSlidesSizeDialog } from '../src/slides-size-dialog'
import { openDocxRowBreaksDialog } from '../src/docx-table-row-breaks-controls'
import { openDocxColumnWidthDialog } from '../src/docx-table-column-width-controls'
import { openDocxRowHeightDialog } from '../src/docx-table-row-height-controls'
import { openDocxTableAlignmentDialog } from '../src/docx-table-alignment-controls'
import { openDocxCellSplitDialog } from '../src/docx-table-cell-shape-controls'
import { openDocxTableAltTextDialog } from '../src/docx-table-alt-text-controls'
import { openDocxCellWrapDialog } from '../src/docx-table-cell-wrap-controls'
import { openDocxCellMarginsDialog } from '../src/docx-table-cell-margins-controls'
import { openDocxCellMarginOverridesDialog } from '../src/docx-table-cell-margin-overrides-controls'
import { openDocxTablePropertiesSourceDialog } from '../src/docx-table-properties-source'
import { openDocxLineSpacingDialog } from '../src/docx-line-spacing'
import { openDocxSpecialIndentDialog } from '../src/docx-special-indent'
import { createDocxCaptionDialog } from '../src/docx-caption-dialog'
import { createDocxCaption, NativeDocxCaption } from '../src/docx-caption'
import { createDocxViewCommands } from '../src/docx-view'
import { createDocxTextRevisionControls } from '../src/docx-text-revision-controls'
import { Editor } from '@tiptap/core'
import { editorExtensions } from '../src/vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { blocksToPmDoc, pmDocOptions } from '../src/vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { parseDocx, readSections } from '@genoffice/docx-engine'
import { buildDocx } from '../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'
import { createTableCreateDialog } from '../src/workbook-table-create-dialog'
import { createSubtotalDialog } from '../src/workbook-subtotal-dialog'
import { createConsolidateDialog } from '../src/workbook-consolidate-dialog'
import { createFormatCellsDialog } from '../src/workbook-format-cells-host'
import { createSortDialog } from '../src/workbook-sort-dialog'
import { createAdvancedFilterDialog } from '../src/workbook-advanced-filter-dialog'
import { createGoalSeekDialog } from '../src/workbook-goal-seek-dialog'
import { createDataTableDialog } from '../src/workbook-data-table-dialog'
import { createEditableRangesDialog } from '../src/workbook-editable-ranges-dialog'
import { createChartDesignDialog } from '../src/workbook-chart-design-dialog'
import { createSparklineDialog } from '../src/workbook-sparkline-dialog'
import { createTableResizeDialog } from '../src/workbook-table-resize-dialog'
import { createPivotDialog } from '../src/workbook-pivot-dialog'
import { createPivotFilterDialog } from '../src/workbook-pivot-filters-dialog'
import { createBlankWorkbook, applyCellEdits } from '@sheets-web/xlsx-engine'
import { createPivotPlan, readWorkbookPivots } from '../src/workbook-pivot'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { bindPdfProtectionDialog } from '../src/pdf-protection'
import { bindPdfExportTextDialog } from '../src/pdf-export-text'
import { bindPdfExternalPagesDialog } from '../src/pdf-external-pages'
import { bindPdfStaticText } from '../src/pdf-static-text'
import { bindPdfConvertOfficeDialog } from '../src/pdf-convert-office'
import { bindPdfImageExportDialog } from '../src/pdf-image-export'
import { bindPdfExistingImagePanel } from '../src/pdf-existing-image'
import { NativeDraft } from '../src/native-draft'
import { createNativeChartEditDialog } from '../src/slides-native-chart-edit'
import { openSlidesLink } from '../src/slides-native-link'
import { openSlidesFindReplace } from '../src/slides-find-replace'
import { workbookSettingsModes, openWorkbookSettings } from './office-workbook-settings-fixture.mjs'
import '../src/style.css'
import '../src/office-theme.css'
import '../src/docx.css'
import '../src/workbook.css'
import '../src/workbook-insert-function.css'
import '../src/pdf.css'
import '../src/slides.css'

const format = new URLSearchParams(location.search).get('format') ?? 'xlsx-functions'
const opener = document.createElement('button')
opener.textContent = '打开设置'
opener.className = 'ui-button'
const root = document.createElement('main')
if (format.startsWith('docx')) root.className = 'docx-native'
document.body.append(opener, root)
const host = {
  evaluate: async (_target, expressions) => expressions.map(() => 3),
  observeRangePick: () => () => {},
  listExternalPickTargets: async () => [],
  pickExternalRange: async () => {},
}
const cases = {
  docx() {
    const dialog = createDocxNoteDialog(root)
    dialog.open('插入脚注', '脚注内容可以保留中文与长文本。', () => {})
  },
  xlsx() { createWorkbookZoomDialog(root, () => {}).open(100) },
  'xlsx-functions'() {
    root.className = 'workbook-function-root'
    const react = createRoot(root)
    react.render(createElement(FunctionArgumentsDialog, {
      spec: { name: 'SUM', category: 'Math', syntax: 'SUM(number1, [number2], …)', abstract: '求和',
        description: '返回指定数值或单元格区域的总和。',
        params: [{ name: '数值参数一', detail: '参与求和的数值或区域', require: true, repeat: false },
          { name: '可选的第二个数值参数', detail: '其他数值或区域', require: false, repeat: false }] },
      target: { sheetId: 'fixture', row: 0, col: 0 }, initialArgs: ['A1:A3', '2'], host,
      error: null, onOk: () => react.unmount(), onCancel: () => react.unmount(),
    }))
  },
  pdf() {
    bindPdfExtractDialog({ root, sourceSha256: 'a'.repeat(64), pageCount: () => 5,
      currentPage: () => 1, unavailable: () => null,
      extract: async () => { throw new Error('视觉夹具不生成文件') },
    }).open()
  },
  pptx() { openSlidesSizeDialog(root, { cx: 9144123, cy: 6858000 }, () => {}) },
  'docx-row-breaks'() { openDocxRowBreaksDialog(root, null, 0, 3, () => {}) },
  'docx-column-width'() { openDocxColumnWidthDialog(root, 2400, () => {}) },
  'docx-row-height'() { openDocxRowHeightDialog(root, 600, 14400, () => {}) },
  'docx-table-alignment'() { openDocxTableAlignmentDialog(root, 'left', true, () => {}) },
  'docx-table-alignment-portal'() { openDocxTableAlignmentDialog(document.body, 'left', true, () => {}) },
  'docx-default-margins-portal'() { openDocxCellMarginsDialog(document.body, { top: 0, right: 109, bottom: 7, left: 108 }, ['top', 'bottom'], () => {}) },
  'docx-cell-split'() { openDocxCellSplitDialog(root, () => {}) },
  'docx-alt-text'() { openDocxTableAltTextDialog(root, { title: '年度经营数据', description: '按地区和季度对收入与成本进行比较。' }, () => {}) },
  'docx-cell-wrap'() { openDocxCellWrapDialog(root, null, () => {}) },
  async 'docx-table-properties'() {
    // 视觉夹具复用真实 DOCX 解析与产品弹窗；命令回调刻意不提交事务，专门检查布局、焦点和取消行为。
    const body = '<w:tbl><w:tblPr><w:tblW w:w="4800" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="2400"/><w:gridCol w:w="2400"/></w:tblGrid><w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>甲</w:t></w:r></w:p></w:tc><w:tc><w:tcPr/><w:p><w:r><w:t>乙</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>丙</w:t></w:r></w:p></w:tc><w:tc><w:tcPr/><w:p><w:r><w:t>丁</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    const parsed = await parseDocx(await buildDocx({ bodyXml: body }))
    const editor = new Editor({ extensions: editorExtensions, content: blocksToPmDoc(parsed.blocks, readSections(parsed), pmDocOptions(parsed)) })
    editor.commands.setTextSelection(2)
    window.officeTablePropertiesEditor = editor
    openDocxTablePropertiesSourceDialog(editor, 320, () => {})
  },
  'xlsx-table-create'() { createTableCreateDialog(root, () => {}).open({ sheetId: 'fixture', range: 'A1:D12' }) },
  'xlsx-subtotal'() { createSubtotalDialog(root, async () => {}).open({ workbookId: 'fixture', sheetId: 'fixture',
    range: { startRow: 0, endRow: 20, startColumn: 0, endColumn: 2 }, fields: [{ column: 0, label: '地区' }, { column: 1, label: '营业收入（万元）' }] }) },
  'xlsx-consolidate'() { createConsolidateDialog(root, () => {}).open({ workbookId: 'fixture', sheetId: 'fixture', row: 0, column: 0,
    defaultReference: '经营汇总!A1:D12', targetLabel: '汇总!A1' }) },
  'xlsx-sort'() { createSortDialog(root, () => {}).open({ startRow: 0, endRow: 20, startColumn: 0, endColumn: 12 }) },
  'xlsx-advanced-filter'() { advancedFilter() },
  'xlsx-advanced-filter-error'() { advancedFilter(true) },
  'xlsx-goal-seek'() { createGoalSeekDialog(root, async () => ({ found: true, solution: 1, reached: 10 })).open({ workbookId: 'fixture', sheetId: 'fixture', setCell: 'B5' }) },
  'xlsx-data-table'() { createDataTableDialog(root, async () => ({ cells: 12 })).open({ workbookId: 'fixture', sheetId: 'fixture', range: 'B4:D8' }) },
  'xlsx-editable-ranges'() { editableRanges(false) },
  'xlsx-editable-ranges-readonly'() { editableRanges(true) },
  'xlsx-table-resize'() { createTableResizeDialog(root, () => {}).open({ tableId: 'fixture', range: 'A1:D24' }) },
  'xlsx-sparkline'() { createSparklineDialog(root, () => {}).open({ kind: 'line', color: '#376092', negativeColor: '#d00000', markers: true, showAxis: true }, { sheetId: 'fixture', target: 'F2' }) },
  'xlsx-pivot-empty'() { pivotDialog(false) },
  'xlsx-pivot-configured'() { pivotDialog(true) },
  'pdf-protection'() { bindPdfProtectionDialog({ root, sourceSha256: 'a'.repeat(64), unavailable: () => null, submit: async () => {} }).open() },
  'pdf-export-text'() { bindPdfExportTextDialog({ root, sourceSha256: 'a'.repeat(64), unavailable: () => null, convertOffice: async () => {} }).open('markdown') },
  'pdf-external-insert'() { externalPages('insert') },
  'pdf-external-replace'() { externalPages('replace') },
  'pdf-static-text'() { bindPdfStaticText({ root, draft: { operations: [] }, pages: () => [], unavailable: () => null,
    start() {}, stop() {}, refresh: async () => {}, status() {} }).open() },
  'pptx-link'() { openSlidesLink(root, { elementLink: { kind: 'url', url: 'https://example.com' }, slides: [{ slideIndex: 0, label: '经营概览' }], onApply() {}, onCancel() {} }) },
  'pptx-find-ime'() {
    document.documentElement.dataset.primaryAction = 'none'
    openSlidesFindReplace(root, { getSlides: () => [], getEdits: () => [], isLocked: () => false, onNavigate() {}, onReplace() {} })
  },
}
const docxAnchors = [{ docxIndex: 0, blockId: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64), editable: true }]
function paragraphEditor(attrs = {}) {
  const editor = new Editor({ extensions: editorExtensions, editorProps: { handleScrollToSelection: () => true }, content: {
    type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0, ...attrs }, content: [{ type: 'text', text: '年度经营情况说明' }] }],
  } })
  editor.commands.setTextSelection(2)
  return editor
}
for (const rule of ['multiple', 'exact', 'atLeast', 'error']) cases['docx-line-' + rule] = () => {
  const editor = paragraphEditor({ lineSpacing: rule === 'multiple' ? 1.5 : null, lineRule: rule === 'error' ? 'multiple' : rule, lineRawTwips: 365 })
  openDocxLineSpacingDialog(root, editor, docxAnchors)
  if (rule === 'error') { root.querySelector('[aria-label="行距倍数"]').value = '0'; root.querySelector('form').requestSubmit() }
}
for (const kind of ['none', 'firstLine', 'hanging', 'chars', 'error']) cases['docx-indent-' + kind] = () => {
  const editor = paragraphEditor({ indentFirstLine: kind === 'none' ? 0 : kind === 'hanging' ? -480 : 480, indentFirstLineChars: kind === 'chars' ? 200 : null })
  openDocxSpecialIndentDialog(root, editor, docxAnchors)
  if (kind === 'error') { root.querySelector('input').value = '0'; root.querySelector('form').requestSubmit() }
}
const cellMargins = { top: 0, right: 109, bottom: 7, left: 108 }
for (const error of [false, true]) cases[`docx-default-margins${error ? '-error' : ''}`] = () => {
  openDocxCellMarginsDialog(root, cellMargins, ['top', 'bottom'], () => {})
  if (error) { root.querySelector('input').value = '-1'; root.querySelector('form').requestSubmit() }
}
for (const mode of ['mixed', 'custom', 'error', 'row-breaks', 'alignment']) cases['docx-cell-margins-' + mode] = () => {
  openDocxCellMarginOverridesDialog(root, mode === 'custom' ? cellMargins : { ...cellMargins, left: null }, '选中四个单元格；左边距包含多个来源值。', () => {},
    { reason: null, open: () => openDocxRowBreaksDialog(root, null, 0, 3, () => {}) },
    { reason: null, open: () => openDocxTableAlignmentDialog(root, 'left', true, () => {}) })
  if (mode === 'error') { root.querySelector('input').value = '1'; root.querySelector('form').requestSubmit() }
  if (mode === 'row-breaks' || mode === 'alignment') root.querySelector(`[data-action="${mode === 'row-breaks' ? 'row-breaks' : 'table-alignment'}"]`).click()
}
for (const state of ['default', 'selection', 'locked']) cases['docx-caption-' + state] = async () => {
  const parsed = await parseDocx(await buildDocx({ bodyXml: '<w:p><w:r><w:t>年度经营情况说明</w:t></w:r></w:p>' }))
  const editor = new Editor({ extensions: [...editorExtensions, NativeDocxCaption], content: blocksToPmDoc(parsed.blocks, readSections(parsed), pmDocOptions(parsed)) })
  if (state === 'selection') editor.commands.setTextSelection(2)
  const source = createDocxCaption(parsed, docxAnchors)
  const dialog = createDocxCaptionDialog({ editor, container: root, controls: source.controls(editor, () => [], () => {}),
    readOnlyReason: () => state === 'locked' ? '正在保存文档，请等待当前修订保存完成后再插入题注。' : null, onError() {} })
  dialog.open()
  const input = root.querySelector('[data-caption-text]'); input.value = '各地区年度经营收入与成本对照（单位：人民币万元）'; input.dispatchEvent(new Event('input'))
}
for (const error of [false, true]) cases[`docx-zoom${error ? '-error' : ''}`] = () => {
  const page = document.createElement('div'), scroller = document.createElement('div'); scroller.append(page)
  createDocxViewCommands({ root, scroller, page, pageSize: () => ({ width: 800, height: 1000 }), onPaginationPreview() {} }).run('缩放')
  if (error) { root.querySelector('input').value = '501'; root.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) }
}
for (const state of ['default', 'locked', 'empty']) cases['docx-revisions-' + state] = () => {
  const author = '审阅人员与长来源身份说明_' + 'reviewer'.repeat(10), date = '2026-11-12T08:00:00Z'
  const texts = ['本段增加了年度经营收入与成本对照，以及所有地区的合并统计说明。'.repeat(4), '删除不再适用的历史说明。']
  const editor = new Editor({ extensions: editorExtensions, content: { type: 'doc', content: texts.map((text, docxIndex) => ({ type: 'docParagraph', attrs: { docxIndex },
    content: [{ type: 'text', text, marks: state === 'empty' ? [] : [{ type: docxIndex ? 'del' : 'ins', attrs: { id: String(docxIndex), author, date } }] }] })) } })
  const anchors = state === 'empty' ? [] : texts.map((text, docxIndex) => ({ docxIndex, blockId: 'body-' + docxIndex, expectedObjectSha256: 'sha-' + docxIndex,
    reviewTargets: [{ revisionId: 'revision-' + docxIndex, blockId: 'body-' + docxIndex, expectedObjectSha256: 'sha-' + docxIndex, originalRevisionId: String(docxIndex),
      type: docxIndex ? 'deletion' : 'insertion', author, date, sourceRange: { from: 0, to: text.length, text } }] }))
  createDocxTextRevisionControls({ editor, baseline: editor.getJSON(), anchors, container: root,
    readOnlyReason: () => state === 'locked' ? '正在保存文档，请等待当前修订保存完成。' : null, onReviewAI() {}, onError() {} }).open()
  document.documentElement.dataset.primaryAction = 'none'
}
async function pivotSource() {
  const rows = [['地区', '日期', '收入'], ['华东区域', '2026-01-01', 10], ['华北区域', '2026-01-02', 20], ['华南区域', '2026-01-03', 30]]
  return applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, column) => ({ sheetName: 'Sheet1', row: r, column, writeValue: true, cell: { value } }))))
}
async function pivotDialog(configured) {
  const bytes = await pivotSource()
  await createPivotDialog(root, async () => {}).open({ bytes, sourceSheetName: 'Sheet1', sourceRange: 'A1:C4', targetCell: 'E1' })
  if (!configured) return
  root.querySelector('[data-add="rows"]').click()
  root.querySelector('[data-field="values"]').value = '收入'
  root.querySelector('[data-add="values"]').click()
  root.querySelector('[data-field="pages"]').value = '日期'
  root.querySelector('[data-add="pages"]').click()
  root.querySelector('[aria-label="计算字段名称"]').value = '折算收入'
  root.querySelector('[aria-label="计算字段公式"]').value = '收入/2'
  root.querySelector('[data-add="calculated"]').click()
}
for (const mode of ['slicer', 'timeline']) for (const native of [false, true]) {
  cases[`xlsx-pivot-${mode}${native ? '-native' : ''}`] = async () => {
    const source = await pivotSource()
    const config = { name: '年度经营收入分析', sourceSheetName: 'Sheet1', sourceRange: 'A1:C4', targetSheetName: 'Sheet1', targetCell: 'E1',
      rowFields: [mode === 'timeline' ? '日期' : '地区'], columnFields: [], values: [{ field: '收入', agg: 'sum' }] }
    const bytes = await applyWorkbookOperations(source, (await createPivotPlan(source, config)).operations)
    await createPivotFilterDialog(root, async () => {}).open({ bytes, pivots: await readWorkbookPivots(bytes), mode })
    if (native) root.querySelector('[data-native-control]').click()
  }
}
function advancedFilter(error = false) {
  createAdvancedFilterDialog(root, async () => {}).open({ unitId: 'fixture', sheetId: 'fixture', workbookCore: {}, sheetCore: {},
    range: { startRow: 0, endRow: 20, startColumn: 0, endColumn: 2 }, revision: 0, snapshotSignature: '', selectionSignature: '', filterSignature: '',
    fields: [{ colId: 0, label: '各地区年度经营收入与成本对照（单位：人民币万元）' }, { colId: 1, label: '地区' }] })
  if (error) root.querySelector('form').requestSubmit()
}
function editableRanges(protectedSheet) {
  createEditableRangesDialog(root, async () => {}).open({ sheetName: '经营汇总', protected: protectedSheet,
    ranges: [{ name: '年度收入及成本明细输入区域', sqref: 'B2:C24 E2:E24' }, { name: '备注', sqref: 'F2:F24' }], selection: 'H2:H24' })
}
for (const [category, pattern] of Object.entries({ general: 'General', number: '#,##0.00', currency: '¥#,##0.00', accounting: '_($* #,##0_);_($* (#,##0);_($* "-"_);_(@_)', date: 'yyyy-mm-dd', time: 'h:mm:ss', percentage: '0.00%', fraction: '# ?/?', scientific: '0.00E+00', text: '@', custom: '0.0" 万元"' })) {
  cases['xlsx-numfmt-' + category] = () => createFormatCellsDialog(root, { current: () => ({ pattern, anchor: -1234.56 }), apply() {} }).open()
}
for (const property of ['title', 'categoryTitle', 'valueTitle', 'labels', 'format', 'legend']) {
  cases['xlsx-chart-' + property] = () => createChartDesignDialog(root, () => {}).open({ chartPath: 'xl/charts/chart1.xml', sheetId: 'fixture', sheetName: '经营汇总', property, initialTitle: '各地区年度经营收入与成本对照' })
}
const operationError = '来源校验失败：' + '所选工作表数据已变化，请重新读取来源后重试。'.repeat(8)
for (const mode of ['signature-draw', 'signature-type', 'stamp', 'crop', 'size', 'merge', 'split', 'link', 'measure', 'note-edit', 'drawing-move', 'image-resize']) {
  cases['pdf-host-' + mode] = async () => (await import('./office-pdf-host-fixture.mjs')).openPdfHostDialog(root, mode)
}
for (const mode of ['pptx', 'docx', 'xlsx']) cases['pdf-convert-' + mode] = () => bindPdfConvertOfficeDialog({ root,
  sourceSha256: 'a'.repeat(64), unavailable: () => null, submit: async () => { throw new Error('组件夹具不执行转换') } }).open(mode)
for (const mode of ['png', 'jpeg']) cases['pdf-image-export-' + mode] = () => bindPdfImageExportDialog({ root,
  sourceSha256: 'a'.repeat(64), pageCount: () => 10, currentPage: () => 3, unavailable: () => null,
  exportImages: async () => { throw new Error('组件夹具不生成文件') } }).open(mode)
cases['pdf-existing-image'] = () => {
  const sourceSha256 = 'a'.repeat(64), pageId = 'sha256:' + sourceSha256 + ':page:0'
  bindPdfExistingImagePanel({ root, draft: new NativeDraft({ documentId: 'image-fixture', revision: 1, sourceSha256,
    scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' } }, localStorage),
    pages: () => [{ pageId, index: 0, rotation: 0, cropBox: { x: 0, y: 0, width: 612, height: 792 } }],
    images: () => [{ pageId, pageIndex: 0, rect: [72, 500, 180, 560], imageId: 'b'.repeat(64), expectedImageSha256: 'c'.repeat(64), aboveText: true, editable: true }],
    unavailable: () => null, refresh: async () => {}, status() {} }).open()
}
cases['pdf-existing-image-error'] = () => {
  cases['pdf-existing-image']()
  root.querySelector('[aria-label="已有图像宽度"]').value = ''
  root.querySelector('[data-pdf-existing-image-confirm]').click()
}
const pdfOperationError = 'PDF 操作失败：' + '来源服务暂时不可用，请保留当前文档，稍后重试。'.repeat(10)
for (const state of ['error', 'pending', 'result']) {
  const pending = () => new Promise(() => {})
  cases['pdf-convert-' + state] = () => {
    bindPdfConvertOfficeDialog({ root, sourceSha256: 'a'.repeat(64), unavailable: () => null,
      submit: state === 'pending' ? pending : async () => {
        if (state === 'error') throw new Error(pdfOperationError)
        return { documentId: 'converted', revision: 1, parentRevision: null, revisionRegistered: true,
          artifacts: { pptx: { downloadUrl: '/fixture-converted.pptx' } }, editor: { openUrl: '/fixture-converted/open' },
          validation: { ok: false, issues: [{ code: 'manual_review', message: '请人工核对原 PDF 的文字、表格和布局。'.repeat(6) }] },
          conversion: { warnings: ['扫描页保留为图片，未执行 OCR。'] } }
      } }).open('pptx')
    root.querySelector('[data-pdf-convert-office-apply]').click()
  }
  cases['pdf-image-export-' + state] = () => {
    bindPdfImageExportDialog({ root, sourceSha256: 'a'.repeat(64), pageCount: () => 10, currentPage: () => 3, unavailable: () => null,
      exportImages: state === 'pending' ? pending : async () => {
        if (state === 'error') throw new Error(pdfOperationError)
        const bytes = Uint8Array.from(atob(window.officePdfFixtureContent.zip), value => value.charCodeAt(0))
        return { content: bytes.buffer, size: bytes.length, sha256: window.officePdfFixtureContent.zipSha256,
          sourceSha256: 'a'.repeat(64), filename: 'fixture-pages.zip' }
      } }).open('png')
    root.querySelector('[data-pdf-image-export-apply]').click()
  }
}
for (const mode of ['goal-seek', 'data-table']) for (const state of ['error', 'busy']) {
  cases[`xlsx-${mode}-${state}`] = () => {
    const apply = () => state === 'error' ? Promise.reject(new Error(operationError)) : new Promise((_resolve, reject) => {
      window.officeDialogRelease = () => reject(new Error(operationError))
    })
    if (mode === 'goal-seek') {
      createGoalSeekDialog(root, apply).open({ workbookId: 'fixture', sheetId: 'fixture', setCell: 'B5' })
      root.querySelector('[aria-label="目标值"]').value = '10'
      root.querySelector('[aria-label="可变单元格"]').value = 'B2'
    } else {
      createDataTableDialog(root, apply).open({ workbookId: 'fixture', sheetId: 'fixture', range: 'B4:D8' })
      root.querySelector('[aria-label="行输入单元格"]').value = 'B1'
    }
    root.querySelector('input').dispatchEvent(new Event('input', { bubbles: true }))
    root.querySelector('form').requestSubmit()
  }
}
function externalPages(action) { bindPdfExternalPagesDialog({ root, sourceSha256: 'a'.repeat(64), pageCount: () => 5,
  currentPage: () => 1, unavailable: () => null, submit: async () => {} }).open(action) }
for (const mode of ['data', 'type', 'style', 'design', 'points']) cases['pptx-chart-' + mode] = () => createNativeChartEditDialog(root, {
  mode, initial: { kind: 'bar', categories: ['第一季度', '第二季度', '第三季度'],
    series: [{ name: '营业收入', values: [10, 20, 30] }, { name: '营业成本', values: [5, 10, 15] }] }, onConfirm() {}, onClose() {},
})
for (const mode of workbookSettingsModes) cases['xlsx-' + mode] = () => openWorkbookSettings(root, mode)
opener.addEventListener('click', () => cases[format]())
window.officeDialogCases = Object.keys(cases)
document.documentElement.dataset.fixtureReady = 'true'

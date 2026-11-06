import { ROTATION_VALUES, univerRotationToOoxml, type RotationValue } from './workbook-rotation'
import { BorderStyleTypes, BorderType } from '@univerjs/core'
import { renderToStaticMarkup } from 'react-dom/server'
import { computeSortChanges, formatAddress, parseAddress } from '@sheets-web/xlsx-engine'
import { RIBBON_GLYPH_ICONS } from './workbook-vendor/ui/ribbon-icons'

type RibbonTab =
  | 'Home'
  | 'Insert'
  | 'Page Layout'
  | 'Formulas'
  | 'Data'
  | 'Review'
  | 'View'
  | 'Chart Design'

type RibbonCommand =
  | 'bold'
  | 'italic'
  | 'underline'
  | 'wrap'
  | 'align:left'
  | 'align:center'
  | 'align:right'
  | 'valign:top'
  | 'valign:middle'
  | 'valign:bottom'
  | 'merge:center'
  | 'merge:cells'
  | 'merge:across'
  | 'merge:unmerge'
  | 'insert-row-here'
  | 'delete-row-here'
  | 'insert-col-here'
  | 'delete-col-here'
  | 'clear-contents'
  | 'insert-sheet'
  | `font-family:${string}`
  | `font-size:${number}`
  | `font-color:#${string}`
  | `fill:#${string}`
  | 'border:all'
  | 'format:0.00'
  | 'format:0%'
  | 'format:#,##0.00'
  | 'decimal-inc'
  | 'decimal-dec'
  | 'toggle-gridlines'
  | `autofn:${'SUM' | 'AVERAGE' | 'COUNT' | 'MAX' | 'MIN'}`
  | 'sort:asc'
  | 'sort:desc'
  | 'insert-function-open'
  | `insert-function-open:${string}`
  | 'rotate:45'
  | 'rotate:-45'
  | 'rotate:vertical'
  | 'rotate:90'
  | 'rotate:-90'
  | 'rotate:0'

type RibbonRange = {
  getRow(): number
  getColumn(): number
  getHeight(): number
  getWidth(): number
  sort(options: { column: number; ascending: boolean }): unknown
  getValues?(): Array<Array<unknown>>
  getFormulas?(): string[][]
  getCellStyleData(): { bl?: number; it?: number; ul?: { s?: number } } | null
  getWrap(): boolean
  setFontWeight(value: 'bold' | 'normal' | null): unknown
  setFontStyle(value: 'italic' | 'normal' | null): unknown
  setFontLine(value: 'underline' | 'line-through' | 'none' | null): unknown
  setWrap(value: boolean): unknown
  setFontFamily(value: string): unknown
  setFontSize(value: number): unknown
  setFontColor(value: string): unknown
  setBackgroundColor(value: string): unknown
  setBorder(type: BorderType, style: BorderStyleTypes, color?: string): unknown
  setNumberFormat(value: string): unknown
  setHorizontalAlignment(value: 'left' | 'center' | 'right' | 'justify'): unknown
  setVerticalAlignment(value: 'top' | 'middle' | 'bottom'): unknown
  merge(): unknown
  mergeAcross(): unknown
  breakApart(): unknown
  clearContent(): unknown
}

export type RibbonWorkbook = {
  getActiveSheet(): ({
    getSelection(): { getActiveRange(): RibbonRange | null } | null
    getRange(startRow: number, startColumn: number): {
      getCellStyleData?(): { tr?: { a?: number; v?: number } } | null
      setFormula(formula: string): unknown
      setValue(value: unknown): unknown
    }
    hasHiddenGridLines(): boolean
    setHiddenGridlines(hidden: boolean): unknown
    insertRowsBefore(position: number, count: number): unknown
    deleteRows(position: number, count: number): unknown
    insertColumnsBefore(position: number, count: number): unknown
    deleteColumns(position: number, count: number): unknown
  } | null)
  insertSheet(): unknown
}

const tabs: RibbonTab[] = ['Home', 'Insert', 'Page Layout', 'Formulas', 'Data', 'Review', 'View']

type RibbonAction = { label: string; id: string; command?: RibbonCommand }
type RibbonGroup = { title: string; actions: RibbonAction[] }

const action = (label: string, id: string, command?: RibbonCommand): RibbonAction =>
  command === undefined ? { label, id } : { label, id, command }

// Groups and command ids follow GenOffice ExcelShell.tsx at f8c17004.
const groups: Record<RibbonTab, RibbonGroup[]> = {
  Home: [
    { title: '剪贴板', actions: ['paste', 'cut', 'copy', 'format-painter'].map(id => action(id, id)) },
    { title: '字体', actions: [
      action('字体', 'font-family:Arial', 'font-family:Arial'), action('字号', 'font-size:12', 'font-size:12'),
      action('粗体', 'bold', 'bold'), action('斜体', 'italic', 'italic'), action('下划线', 'underline', 'underline'),
      action('删除线', 'strike'), action('上标', 'superscript'), action('下标', 'subscript'),
      action('字体颜色', 'font-color:#000000', 'font-color:#000000'), action('填充颜色', 'fill:#fff2cc', 'fill:#fff2cc'), action('边框', 'border:all', 'border:all'),
    ] },
    { title: '对齐方式', actions: [
      action('顶端对齐', 'valign:top', 'valign:top'), action('垂直居中', 'valign:middle', 'valign:middle'),
      action('底端对齐', 'valign:bottom', 'valign:bottom'), action('自动换行', 'wrap', 'wrap'),
      action('文本逆时针旋转', 'rotate:45', 'rotate:45'), action('文本顺时针旋转', 'rotate:-45', 'rotate:-45'),
      action('竖排文本', 'rotate:vertical', 'rotate:vertical'), action('向上旋转', 'rotate:90', 'rotate:90'),
      action('向下旋转', 'rotate:-90', 'rotate:-90'), action('清除旋转', 'rotate:0', 'rotate:0'),
      action('左对齐', 'align:left', 'align:left'),
      action('居中', 'align:center', 'align:center'), action('右对齐', 'align:right', 'align:right'),
      action('增加缩进', 'indent-step:increase'), action('减少缩进', 'indent-step:decrease'), action('合并单元格', 'merge:cells', 'merge:cells'),
      action('合并后居中', 'merge:center', 'merge:center'), action('跨越合并', 'merge:across', 'merge:across'),
      action('取消单元格合并', 'merge:unmerge', 'merge:unmerge'),
    ] },
    { title: '数字', actions: [
      action('小数', 'format:0.00', 'format:0.00'), action('百分比', 'format:0%', 'format:0%'), action('千位分隔', 'format:#,##0.00', 'format:#,##0.00'),
      action('增加小数位', 'decimal-inc', 'decimal-inc'), action('减少小数位', 'decimal-dec', 'decimal-dec'),
    ] },
    { title: '样式', actions: ['cf-open', 'format-as-table', 'cell-style'].map(id => action(id, id)) },
    { title: '单元格', actions: [
      action('设置单元格格式', 'format-cells'),
      action('插入行', 'insert-row-here', 'insert-row-here'),
      action('删除行', 'delete-row-here', 'delete-row-here'),
      action('插入列', 'insert-col-here', 'insert-col-here'),
      action('删除列', 'delete-col-here', 'delete-col-here'),
      action('插入单元格', 'insert-cells'), action('删除单元格', 'delete-cells'),
      action('行高', 'row-height-open'), action('自动调整行高', 'autofit-row-height'),
      action('列宽', 'col-width-open'), action('自动调整列宽', 'autofit-col-width'),
      action('全部清除', 'clear-all'), action('清除格式', 'clear-formats'),
      action('清除内容', 'clear-contents', 'clear-contents'),
    ] },
    { title: '编辑', actions: [
      ...(['SUM', 'AVERAGE', 'COUNT', 'MAX', 'MIN'] as const).map((fn, index) =>
        action(['自动求和', '平均值', '计数值', '最大值', '最小值'][index]!, `autofn:${fn}`, `autofn:${fn}`)),
      action('Sort', 'sort-custom-open'), action('Find', 'find'),
      action('Replace', 'replace'), action('Go To', 'goto-open'),
    ] },
  ],
  Insert: [
    { title: '表格', actions: ['pivot-open', 'pivot-edit', 'format-as-table'].map(id => action(id, id)) },
    { title: '插图', actions: ['insert-picture', 'insert-shape', 'insert-icons', 'insert-screenshot'].map(id => action(id, id)) },
    { title: '复选框', actions: ['insert-checkbox'].map(id => action(id, id)) },
    { title: '图表', actions: ['recommended-charts-open', 'insert-chart:column', 'insert-chart:bar', 'insert-chart:line', 'insert-chart:area', 'insert-chart:pie', 'insert-chart:scatter', 'insert-chart:radar', 'insert-chart:doughnut', 'insert-chart:combo'].map(id => action(id, id)) },
    { title: '迷你图', actions: ['sparkline:line', 'sparkline:column', 'sparkline:stacked'].map(id => action(id, id)) },
    { title: '筛选器', actions: ['slicer-open', 'timeline-open'].map(id => action(id, id)) },
    { title: '链接', actions: ['link-open'].map(id => action(id, id)) },
    { title: '批注', actions: [action('批注', 'note-open')] },
    { title: '文本', actions: ['insert-textbox', 'header-footer-open'].map(id => action(id, id)) },
    { title: '符号', actions: ['insert-equation', 'insert-symbol'].map(id => action(id, id)) },
  ],
  'Page Layout': [
    { title: '主题', actions: ['theme', 'theme-colors', 'theme-fonts', 'theme-effects'].map(id => action(id, id)) },
    { title: '页面设置', actions: ['margins', 'orientation', 'paper-size', 'print-area', 'page-breaks', 'background'].map(id => action(id, id)) },
    { title: '调整为合适大小', actions: ['fit-width', 'fit-height', 'scale'].map(id => action(id, id)) },
    { title: '工作表选项', actions: ['toggle-gridlines', 'print-gridlines', 'toggle-headings', 'print-headings'].map(id => action(id, id)) },
  ],
  Formulas: [
    { title: '函数库', actions: [
      action('插入函数', 'insert-function-open'),
      ...(['SUM', 'AVERAGE', 'COUNT', 'MAX', 'MIN'] as const).map((fn, index) =>
        action(['自动求和', '平均值', '计数', '最大值', '最小值'][index]!, `autofn:${fn}`, `autofn:${fn}`)),
      action('最近使用的函数', 'insert-function-open:All'),
      action('财务', 'insert-function-open:Financial'), action('逻辑', 'insert-function-open:Logical'),
      action('文本', 'insert-function-open:Text'), action('日期和时间', 'insert-function-open:Date & Time'),
      action('查找与引用', 'insert-function-open:Lookup'), action('数学和三角函数', 'insert-function-open:Math'),
      action('其他函数', 'insert-function-open:All'),
    ] },
    { title: '定义的名称', actions: ['name-manager-open', 'define-name', 'use-in-formula'].map(id => action(id, id)) },
    { title: '公式审核', actions: ['trace-precedents', 'trace-dependents', 'remove-arrows', 'toggle-show-formulas', 'error-checking', 'watch-window', 'external-links-panel'].map(id => action(id, id)) },
    { title: '计算', actions: ['calculate-now', 'calculate-sheet', 'calculation-options'].map(id => action(id, id)) },
  ],
  Data: [
    { title: '数据透视表', actions: ['pivot-open', 'pivot-edit'].map(id => action(id, id)) },
    { title: '获取数据', actions: ['import-csv', 'merge-workbooks', 'refresh-all', 'queries-open'].map(id => action(id, id)) },
    { title: '排序和筛选', actions: [
      action('升序', 'sort:asc', 'sort:asc'), action('降序', 'sort:desc', 'sort:desc'),
      action('自定义排序…', 'sort-custom-open'), action('筛选', 'filter-toggle'), action('清除筛选条件', 'filter-clear'),
      action('重新应用筛选', 'filter-reapply'), action('高级筛选', 'filter-advanced'),
    ] },
    { title: '数据工具', actions: [
      action('按逗号拆分', 'text-to-columns:2'), action('按分号拆分', 'text-to-columns:4'),
      action('按空格拆分', 'text-to-columns:8'), action('按制表符拆分', 'text-to-columns:1'),
      action('快速填充', 'flash-fill'), action('删除重复值', 'remove-duplicates-open'),
      action('数据验证', 'dv-open'), action('合并计算', 'consolidate-open'),
    ] },
    { title: '预测', actions: ['forecast-sheet', 'what-if-analysis'].map(id => action(id, id)) },
    { title: '分级显示', actions: [
      ...['outline-group:rows', 'outline-group:cols', 'outline-ungroup:rows', 'outline-ungroup:cols', 'outline-hide-detail', 'outline-show-detail'].map(id => action(id, id)),
      action('分类汇总', 'subtotal-open'),
    ] },
  ],
  Review: [
    { title: '校对', actions: [action('工作簿统计信息', 'workbook-statistics')] },
    { title: '语言', actions: [action('翻译', 'translate')] },
    { title: '批注', actions: [
      action('新建批注', 'note-open'), action('删除', 'note-delete'), action('上一条', 'note-prev'),
      action('下一条', 'note-next'), action('显示批注', 'note-show-toggle'),
    ] },
    { title: '注释', actions: [action('注释', 'note-open')] },
    { title: '保护', actions: [
      action('保护工作表', 'sheet-protect'), action('保护工作簿', 'workbook-protect'),
      action('允许编辑区域', 'allow-edit-ranges-open'),
    ] },
  ],
  View: [
    { title: '工作簿视图', actions: [action('普通', 'normal-view'), action('分页预览', 'toggle-page-break-preview')] },
    { title: '显示', actions: [
      action('网格线', 'toggle-gridlines', 'toggle-gridlines'), action('编辑栏', 'toggle-formula-bar'),
      action('标题', 'toggle-headings'), action('从右到左', 'toggle-right-to-left'),
      action('突出显示活动行和列', 'toggle-cross-highlight'),
    ] },
    { title: '缩放', actions: [
      action('缩放', 'zoom-open'), action('重置缩放', 'zoom-reset'), action('缩放到选定区域', 'zoom-to-selection'),
      action('放大', 'zoom-in'), action('缩小', 'zoom-out'),
    ] },
    { title: '窗口', actions: [
      action('新建窗口', 'new-window'), action('全部重排', 'arrange-all'), action('冻结窗格', 'freeze-panes'),
      action('拆分窗口', 'split-window'), action('隐藏窗口', 'hide-window'), action('切换窗口', 'switch-window'),
    ] },
  ],
  'Chart Design': [
    { title: '图表布局', actions: ['chart-title', 'chart-axis-cat', 'chart-axis-val', 'chart-legend', 'chart-labels'].map(id => action(id, id)) },
    { title: '更改图表类型', actions: ['chart-type-column', 'chart-type-bar', 'chart-type-line', 'chart-type-area', 'chart-type-pie', 'chart-type-doughnut'].map(id => action(id, id)) },
    { title: '数据', actions: ['chart-select-data', 'chart-switch-row-col', 'chart-format-pane'].map(id => action(id, id)) },
    { title: '图表操作', actions: ['chart-delete'].map(id => action(id, id)) },
  ],
}

const FONT_FAMILIES = ['Arial', 'Aptos', 'Calibri', 'Cambria', 'Times New Roman', 'Yu Gothic']
const FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72]
const COMMAND_GLYPHS: Record<string, string> = {
  bold: 'B', italic: 'I', underline: 'U', 'align:left': '≡', 'align:center': '≣', 'align:right': '☰',
  'valign:top': '⤒', 'valign:middle': '↕', 'valign:bottom': '⤓', wrap: '↩',
  'merge:cells': '⇔', 'merge:center': '⇔', 'merge:across': '⇔', 'merge:unmerge': '⊟',
  'decimal-inc': 'A↑', 'decimal-dec': 'A↓', 'format:0.00': '0.00', 'format:0%': '%',
  'format:#,##0.00': ',', 'border:all': '▦', 'clear-contents': '⌫',
  'insert-row-here': '⊞', 'delete-row-here': '⊟', 'insert-col-here': '⊞', 'delete-col-here': '⊟',
  find: '🔍', replace: '⇄', 'format-as-table': '▦', 'insert-chart:column': '📊',
}

const disabledReasons: Record<string, string> = {
  paste: 'Clipboard access is not wired to the native workbook editor.',
  cut: 'Clipboard access is not wired to the native workbook editor.',
  copy: 'Clipboard access is not wired to the native workbook editor.',
  'format-painter': 'Format-painter state and multi-selection are not wired to the native editor.',
  'underline:double': 'The current XLSX style diff does not preserve double underline.',
  strike: 'The current XLSX style diff does not preserve strike-through.',
  superscript: 'The current XLSX style diff does not preserve baseline offsets.',
  subscript: 'The current XLSX style diff does not preserve baseline offsets.',
  'cf-open': 'Conditional-formatting editor is not connected to the native draft operations.',
  'format-as-table': 'Table creation is not connected to the native XLSX operation schema.',
  'cell-style': 'Cell-style presets are not connected to the native XLSX operation schema.',
  'find': 'Find Replace is registered; its native dialog command is not wired to this ribbon yet.',
  'replace': 'Find Replace is registered; its native dialog command is not wired to this ribbon yet.',
  'insert-cells': 'The XLSX bridge has no insert-shifted-cells operation.',
  'delete-cells': 'The XLSX bridge has no delete-shifted-cells operation.',
  'format-cells': 'The native ribbon has no Format Cells dialog for number, border, protection, and alignment options.',
  'row-height-open': 'The native ribbon has no row-height dialog; geometry writeback supports measured edits only.',
  'col-width-open': 'The native ribbon has no column-width dialog; geometry writeback supports measured edits only.',
  'autofit-row-height': 'The native workbook bridge does not persist Univer auto-height commands as explicit row heights.',
  'autofit-col-width': 'The native workbook bridge does not persist Univer auto-width commands as explicit column widths.',
  'clear-all': 'The native ribbon adapter only supports clearing cell contents; full cell reset is not captured as one safe XLSX operation.',
  'clear-formats': 'The native workbook readback does not distinguish every cleared inherited/style component for a safe format-only reset.',
  'indent-step:increase': 'The native workbook bridge does not roundtrip OOXML indent styles from the current grid readback.',
  'indent-step:decrease': 'The native workbook bridge does not roundtrip OOXML indent styles from the current grid readback.',
  'insert-checkbox': 'Checkbox drawing creation is not captured by workbook readback or XLSX operations.',
  'recommended-charts-open': 'The native chart authoring dialog is not connected to the existing static chart writeback.',
  'insert-chart:column': 'Chart authoring is not connected to the native chart writeback operation.',
  'insert-chart:bar': 'Chart authoring is not connected to the native chart writeback operation.',
  'insert-chart:line': 'Chart authoring is not connected to the native chart writeback operation.',
  'insert-chart:area': 'Chart authoring is not connected to the native chart writeback operation.',
  'insert-chart:pie': 'Chart authoring is not connected to the native chart writeback operation.',
  'insert-chart:scatter': 'Chart authoring is not connected to the native chart writeback operation.',
  'insert-chart:radar': 'Chart authoring is not connected to the native chart writeback operation.',
  'insert-chart:doughnut': 'Chart authoring is not connected to the native chart writeback operation.',
  'insert-chart:combo': 'Chart authoring is not connected to the native chart writeback operation.',
  'sparkline:line': 'Sparkline drawing changes are not yet emitted as XLSX operations.',
  'sparkline:column': 'Sparkline drawing changes are not yet emitted as XLSX operations.',
  'sparkline:stacked': 'Sparkline drawing changes are not yet emitted as XLSX operations.',
  'slicer-open': 'Slicer creation has no native XLSX operation or readback support.',
  'timeline-open': 'Timeline creation has no native XLSX operation or readback support.',
  'sort-custom-open': 'The native ribbon has no custom-sort dialog for choosing a key column, headers, or sort levels.',
  'filter-toggle': 'Univer FilterModel serialization is available only with its preset, which is not registered here; the XLSX reader and save bridge have no autoFilter readback/writeback contract.',
  'filter-clear': 'The XLSX reader/grid has no filter criteria readback and the save bridge has no filter criteria writeback operation to clear safely.',
  'filter-reapply': 'The native editor has no persisted autoFilter criteria model to reapply through the XLSX save bridge.',
  'filter-advanced': 'The native ribbon has no advanced criteria dialog, and the XLSX bridge cannot persist its criteria as autoFilter XML.',
  'workbook-statistics': 'The native ribbon has no workbook-statistics view or snapshot adapter for presenting whole-workbook counts.',
  translate: 'The native ribbon has no selection-aware workbook AI translation action connected to this control.',
  'sheet-protect': 'XLSX protection writing exists, but the native workbook reader does not expose sheet protection state to verify toggles safely.',
  'workbook-protect': 'XLSX protection writing exists, but the native workbook reader does not expose workbook protection state to verify toggles safely.',
  'allow-edit-ranges-open': 'The XLSX writer can replace allow-edit ranges, but the native workbook reader has no protected-range readback or editor.',
  'text-to-columns:2': 'The native workbook engine has no text-to-columns command or XLSX writeback operation.',
  'text-to-columns:4': 'The native workbook engine has no text-to-columns command or XLSX writeback operation.',
  'text-to-columns:8': 'The native workbook engine has no text-to-columns command or XLSX writeback operation.',
  'text-to-columns:1': 'The native workbook engine has no text-to-columns command or XLSX writeback operation.',
  'flash-fill': 'The native XLSX writeback does not capture derived cell edits made by Flash Fill.',
  'remove-duplicates-open': 'The native ribbon has no selection-driven duplicate dialog or persisted row-deletion operation.',
  'dv-open': 'The native ribbon has no data-validation dialog connected to an XLSX data-validation writeback operation.',
  'consolidate-open': 'The native ribbon has no consolidate dialog or source-range formula writeback operation.',
  'subtotal-open': 'The native XLSX engine has no subtotal operation for inserting and persisting grouped summary rows.',
  'insert-function-open': 'The native ribbon has no function catalog dialog for selecting a function and inserting it at the active cell.',
  'insert-function-open:All': 'The native ribbon has no recent/all function catalog dialog; AutoSum functions remain available as direct commands.',
  'insert-function-open:Financial': 'The native ribbon has no function catalog dialog filtered to Financial functions.',
  'insert-function-open:Logical': 'The native ribbon has no function catalog dialog filtered to Logical functions.',
  'insert-function-open:Text': 'The native ribbon has no function catalog dialog filtered to Text functions.',
  'insert-function-open:Date & Time': 'The native ribbon has no function catalog dialog filtered to Date & Time functions.',
  'insert-function-open:Lookup': 'The native ribbon has no function catalog dialog filtered to Lookup functions.',
  'insert-function-open:Math': 'The native ribbon has no function catalog dialog filtered to Math functions.',
  'normal-view': 'The native XLSX editor renders only the normal grid view; page-break preview has no alternate renderer state.',
  'toggle-page-break-preview': 'The native XLSX editor has no page-break preview renderer or page-break view state.',
  'toggle-formula-bar': 'Formula bar visibility is fixed by the registered Univer core preset and has no safe runtime visibility API here.',
  'toggle-headings': 'Row and column heading visibility requires changing sheet header dimensions and viewport offsets, which this native ribbon adapter does not own.',
  'toggle-right-to-left': 'Right-to-left view is not represented in the XLSX readback/save operation contract.',
  'toggle-cross-highlight': 'Cross-highlight is transient UI state and the native editor has no cross-highlight view implementation.',
  'zoom-open': 'The native ribbon has no zoom picker control or verified zoom-ratio facade command.',
  'zoom-reset': 'The pinned public Univer worksheet facade exposes no zoom getter/setter in this runtime adapter.',
  'zoom-to-selection': 'Fit-selection zoom needs render skeleton dimensions and a verified viewport command adapter.',
  'zoom-in': 'The pinned public Univer worksheet facade exposes no zoom getter/setter in this runtime adapter.',
  'zoom-out': 'The pinned public Univer worksheet facade exposes no zoom getter/setter in this runtime adapter.',
  'new-window': 'Browser-native workbook editing does not manage desktop workbook windows.',
  'arrange-all': 'Browser-native workbook editing has no desktop window manager.',
  'freeze-panes': 'Freeze panes requires a menu adapter and freeze-state serialization not connected to this ribbon.',
  'split-window': 'The native editor has no split-window viewport state or writeback adapter.',
  'hide-window': 'Browser-native workbook editing does not manage desktop workbook windows.',
  'switch-window': 'Browser-native workbook editing does not manage desktop workbook windows.',
  'note-open': 'XLSX legacy notes have an engine writer, but the native reader/grid has no note state/readback to edit or preserve changes safely.',
  'note-delete': 'XLSX legacy note deletion cannot be synchronized because the native reader/grid has no note state/readback.',
  'note-prev': 'Note navigation requires the note collection and active-note selection state, which the native reader/grid does not expose.',
  'note-next': 'Note navigation requires the note collection and active-note selection state, which the native reader/grid does not expose.',
  'note-show-toggle': 'Pinned Univer Sheets Note preset is not registered and the native reader has no note visibility state to roundtrip.',
}

export function applyWorkbookRibbonCommand(
  command: RibbonCommand,
  workbook: RibbonWorkbook,
  stepDecimals?: (step: 1 | -1) => void,
  rotateSelection?: (value: RotationValue) => void,
): boolean {
  const unavailableReason = disabledReasons[command]
  if (unavailableReason !== undefined) throw new Error(unavailableReason)
  if (command === 'insert-sheet') {
    workbook.insertSheet()
    return true
  }
  const sheet = workbook.getActiveSheet()
  if (command === 'toggle-gridlines') {
    if (!sheet) return false
    sheet.setHiddenGridlines(!sheet.hasHiddenGridLines())
    return true
  }
  const range = sheet?.getSelection()?.getActiveRange() ?? null
  if (!range || !sheet) return false
  const [name, value] = command.split(/:(.*)/s).slice(0, 2)
  if (name === 'rotate') {
    const rotation = ROTATION_VALUES[command as keyof typeof ROTATION_VALUES]
    if (rotation === undefined) throw new Error('Unsupported text rotation.')
    if (!rotateSelection) throw new Error('Text rotation is not wired to the workbook runtime.')
    rotateSelection(rotation); return true
  }
  if (name === 'autofn') {
    const fn = value?.toUpperCase()
    if (!['SUM', 'AVERAGE', 'COUNT', 'MAX', 'MIN'].includes(fn ?? '')) throw new Error('Unsupported AutoSum function.')
    if (range.getHeight() < 2) throw new Error('Select at least two rows for AutoSum.')
    const columnLabel = (index: number) => {
      let label = ''
      for (let value = index + 1; value > 0; value = Math.floor((value - 1) / 26)) {
        label = String.fromCharCode(65 + ((value - 1) % 26)) + label
      }
      return label
    }
    const firstRow = range.getRow() + 1
    const lastRow = range.getRow() + range.getHeight()
    const targetRow = lastRow
    for (let offset = 0; offset < range.getWidth(); offset += 1) {
      const column = range.getColumn() + offset
      const label = columnLabel(column)
      sheet.getRange(targetRow, column).setFormula(`=${fn}(${label}${firstRow}:${label}${lastRow})`)
    }
    return true
  }
  if (name === 'sort') {
    if (range.getHeight() < 2) throw new Error('Select at least two rows to sort.')
    const values = range.getValues?.()
    const formulas = range.getFormulas?.()
    if (!values || !formulas) throw new Error('The active selection does not expose values and formulas for safe sorting.')
    const startRow = range.getRow()
    const startColumn = range.getColumn()
    const endRow = startRow + range.getHeight() - 1
    const endColumn = startColumn + range.getWidth() - 1
    const spec = {
      range: `${formatAddress(startRow, startColumn)}:${formatAddress(endRow, endColumn)}`,
      byColumn: formatAddress(0, startColumn).replace(/[0-9]/g, ''),
      ascending: value === 'asc',
      hasHeader: false,
    }
    const changes = computeSortChanges(spec, address => {
      const { row, column } = parseAddress(address)
      const value = values[row - startRow]?.[column - startColumn]
      return {
        value: value === undefined || value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
          ? value ?? null
          : String(value),
        ...(formulas[row - startRow]?.[column - startColumn] ? { formula: formulas[row - startRow]?.[column - startColumn] } : {}),
      }
    })
    for (const change of changes) {
      const { row, column } = parseAddress(change.address)
      sheet.getRange(row, column).setValue(change.after)
    }
    return true
  }
  if (name === 'font-family') {
    if (!value?.trim() || value.length > 100 || /[\x00-\x1f]/.test(value)) throw new Error('Invalid font family.')
    range.setFontFamily(value)
    return true
  }
  if (name === 'font-size') {
    const size = Number(value)
    if (!Number.isFinite(size) || size < 1 || size > 400) throw new Error('Font size must be between 1 and 400 pt.')
    range.setFontSize(size)
    return true
  }
  if (name === 'font-color' || name === 'fill') {
    if (!/^#[0-9a-f]{6}$/i.test(value ?? '')) throw new Error('Color must use six-digit hexadecimal RGB.')
    if (name === 'font-color') range.setFontColor(value!)
    else range.setBackgroundColor(value!)
    return true
  }
  switch (command) {
    case 'bold': range.setFontWeight(range.getCellStyleData()?.bl === 1 ? 'normal' : 'bold'); break
    case 'italic': range.setFontStyle(range.getCellStyleData()?.it === 1 ? 'normal' : 'italic'); break
    case 'underline': range.setFontLine(range.getCellStyleData()?.ul?.s === 1 ? 'none' : 'underline'); break
    case 'wrap': range.setWrap(!range.getWrap()); break
    case 'border:all': range.setBorder(BorderType.ALL, BorderStyleTypes.THIN, '#000000'); break
    case 'format:0.00': range.setNumberFormat('0.00'); break
    case 'format:0%': range.setNumberFormat('0%'); break
    case 'format:#,##0.00': range.setNumberFormat('#,##0.00'); break
    case 'decimal-inc':
    case 'decimal-dec':
      if (!stepDecimals) throw new Error('Decimal formatting is not wired to the workbook runtime.')
      stepDecimals(command === 'decimal-inc' ? 1 : -1)
      break
    case 'align:left': range.setHorizontalAlignment('left'); break
    case 'align:center': range.setHorizontalAlignment('center'); break
    case 'align:right': range.setHorizontalAlignment('right'); break
    case 'valign:top': range.setVerticalAlignment('top'); break
    case 'valign:middle': range.setVerticalAlignment('middle'); break
    case 'valign:bottom': range.setVerticalAlignment('bottom'); break
    case 'merge:cells': range.merge(); break
    case 'merge:center': range.merge(); range.setHorizontalAlignment('center'); break
    case 'merge:across': range.mergeAcross(); break
    case 'merge:unmerge': range.breakApart(); break
    case 'clear-contents': range.clearContent(); break
    case 'insert-row-here': sheet.insertRowsBefore(range.getRow(), 1); break
    case 'delete-row-here': sheet.deleteRows(range.getRow(), 1); break
    case 'insert-col-here': sheet.insertColumnsBefore(range.getColumn(), 1); break
    case 'delete-col-here': sheet.deleteColumns(range.getColumn(), 1); break
  }
  return true
}

export function mountWorkbookRibbon(
  container: HTMLElement,
  onCommand: (command: RibbonCommand) => void,
  view?: { rotation(): number | 'mixed' | undefined; editable(): boolean; unavailableReason?(): string | undefined },
) {
  container.innerHTML = `
    <header class="workbook-ribbon" aria-label="Excel ribbon">
      <nav class="workbook-ribbon-tabs" role="tablist" aria-label="Workbook tools"></nav>
      <div class="workbook-ribbon-body" role="tabpanel"></div>
    </header>`
  const nav = container.querySelector<HTMLElement>('.workbook-ribbon-tabs')!
  const body = container.querySelector<HTMLElement>('.workbook-ribbon-body')!
  let active: RibbonTab = 'Home'

  const refreshState = () => {
    if (!view) return
    const rotation = view.rotation(), editable = view.editable(), reason = view.unavailableReason?.()
    for (const [id, value] of Object.entries(ROTATION_VALUES)) {
      const button = body.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
      if (!button) continue
      button.disabled = !editable || rotation === undefined || !!reason
      const expected = value === 'v' ? 255 : value < 0 ? 90 - value : value
      button.setAttribute('aria-pressed', String(rotation === expected))
      if (button.disabled) { button.title = editable ? reason ?? '请先选择单元格或区域' : '当前工作簿不可编辑或正在保存'; button.setAttribute('aria-description', button.title) }
      else { button.title = button.textContent ?? ''; button.removeAttribute('aria-description') }
    }
  }
  const render = () => {
    nav.replaceChildren(...tabs.map(tab => {
      const button = document.createElement('button')
      button.type = 'button'
      button.setAttribute('role', 'tab')
      button.setAttribute('aria-selected', String(tab === active))
      button.dataset.ribbonTab = tab
      button.textContent = tab
      button.addEventListener('click', () => { active = tab; render() })
      return button
    }))
    const sections: HTMLElement[] = []
    for (const group of groups[active]) {
      const section = document.createElement('section')
      section.className = 'workbook-ribbon-group'
      const heading = document.createElement('h3')
      heading.textContent = group.title
      section.append(heading)
      if (active === 'Home' && group.title === '字体') {
        const family = document.createElement('select')
        family.className = 'workbook-ribbon-select'
        family.setAttribute('aria-label', '字体')
        family.dataset.ribbonControl = 'font-family'
        family.append(...FONT_FAMILIES.map(name => {
          const option = document.createElement('option')
          option.value = name
          option.textContent = name
          return option
        }))
        family.value = 'Arial'
        family.addEventListener('change', () => onCommand(`font-family:${family.value}`))
        section.append(family)

        const size = document.createElement('select')
        size.className = 'workbook-ribbon-select workbook-ribbon-size'
        size.setAttribute('aria-label', '字号')
        size.dataset.ribbonControl = 'font-size'
        size.append(...FONT_SIZES.map(value => {
          const option = document.createElement('option')
          option.value = String(value)
          option.textContent = String(value)
          return option
        }))
        size.value = '12'
        size.addEventListener('change', () => onCommand(`font-size:${Number(size.value)}`))
        section.append(size)

        for (const [control, label, kind] of [
          ['font-color', '字体颜色', 'font-color'], ['fill', '填充颜色', 'fill'],
        ] as const) {
          const wrapper = document.createElement('label')
          wrapper.className = 'workbook-ribbon-color'
          wrapper.title = label
          wrapper.setAttribute('aria-label', label)
          const input = document.createElement('input')
          input.type = 'color'
          input.value = kind === 'fill' ? '#fff2cc' : '#000000'
          input.dataset.ribbonControl = control
          input.setAttribute('aria-label', label)
          input.addEventListener('input', () => onCommand(`${kind}:${input.value}` as RibbonCommand))
          wrapper.append(input)
          section.append(wrapper)
        }
      }
      for (const item of group.actions) {
        if (active === 'Home' && group.title === '字体' && /^(font-family|font-size|font-color|fill):/.test(item.id)) continue
        const button = document.createElement('button')
        button.type = 'button'
        button.dataset.ribbonCommand = item.id
        const glyph = COMMAND_GLYPHS[item.id]
        const icon = glyph ? RIBBON_GLYPH_ICONS[glyph] : undefined
        if (icon) {
          const iconHost = document.createElement('span')
          iconHost.className = 'workbook-ribbon-icon'
          iconHost.setAttribute('aria-hidden', 'true')
          iconHost.innerHTML = renderToStaticMarkup(icon)
          const label = document.createElement('span')
          label.textContent = item.label
          button.append(iconHost, label)
        } else button.textContent = item.label
        if (item.command === undefined || disabledReasons[item.id] !== undefined) {
          button.disabled = true
          const reason = disabledReasons[item.id] ?? `The ${item.id} command has no XLSX writeback adapter.`
          button.title = reason
          button.setAttribute('aria-description', reason)
        } else {
          button.addEventListener('click', () => onCommand(item.command!))
        }
        section.append(button)
      }
      sections.push(section)
    }
    body.replaceChildren(...sections)
    refreshState()
  }
  render()
  return { refreshState, dispose() { container.replaceChildren() } }
}

/** Public FRange composed style access preserves inherited row/column rotation. */
export function selectedWorkbookRotation(workbook: RibbonWorkbook | null): number | 'mixed' | undefined {
  const sheet = workbook?.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
  if (!sheet || !range) return undefined
  if (range.getHeight() * range.getWidth() > 10000) return 'mixed'
  let selected: number | undefined
  for (let r = 0; r < range.getHeight(); r++) for (let c = 0; c < range.getWidth(); c++) {
    const cell = sheet.getRange(range.getRow() + r, range.getColumn() + c)
    if (!cell.getCellStyleData) return undefined
    const value = univerRotationToOoxml(cell.getCellStyleData()?.tr) ?? 0
    if (selected !== undefined && selected !== value) return 'mixed'
    selected = value
  }
  return selected
}

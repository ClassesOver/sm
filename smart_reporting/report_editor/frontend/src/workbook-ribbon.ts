import { ROTATION_VALUES, univerRotationToOoxml, type RotationValue } from './workbook-rotation'
import { BorderStyleTypes, BorderType } from '@univerjs/core'
import { renderToStaticMarkup } from 'react-dom/server'
import { RIBBON_GLYPH_ICONS } from './workbook-vendor/ui/ribbon-icons'
import { selectedWorkbookFormat, type WorkbookFormatState, type FormatValue, type NumberFormatTarget } from './workbook-format'
import { applyWorkbookFontDecoration, type FontDecorationRange } from './workbook-font'
import { indentToUniverPadding, univerPaddingToIndent, type UniverStyleData } from './workbook-vendor/core/style-map'
import { PASTE_SPECIAL_CHOICES, type PasteSpecialKind } from './workbook-clipboard'

type RibbonTab =
  | 'File'
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
  | 'underline:double'
  | 'strike'
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
  | 'clear-formats'
  | 'clear-all'
  | 'insert-sheet'
  | `font-family:${string}`
  | `font-size:${number}`
  | `font-color:#${string}`
  | `fill:#${string}`
  | 'border:all'
  | 'format:0.00'
  | 'format:0%'
  | 'format:#,##0.00'
  | 'format:custom-open'
  | 'decimal-inc'
  | 'decimal-dec'
  | 'toggle-gridlines'
  | `autofn:${'SUM' | 'AVERAGE' | 'COUNT' | 'MAX' | 'MIN'}`
  | 'sort:asc'
  | 'sort:desc'
  | 'insert-function-open'
  | 'find'
  | 'replace'
  | 'copy'
  | 'cut'
  | 'paste'
  | 'format-painter'
  | 'format-painter:dblclick'
  | `paste-special:${PasteSpecialKind}`
  | 'indent-step:increase'
  | 'indent-step:decrease'
  | 'note-open'
  | 'note-delete'
  | 'note-prev'
  | 'note-next'
  | 'note-show-toggle'
  | 'freeze-panes'
  | 'zoom-in'
  | 'zoom-out'
  | 'zoom-reset'
  | 'filter-toggle'
  | 'filter-clear'
  | 'filter-reapply'
  | `insert-function-open:${string}`
  | `page-margins:${'normal' | 'wide' | 'narrow'}`
  | `page-orientation:${'portrait' | 'landscape'}`
  | `page-paper:${number}`
  | 'print-area:set'
  | 'print-area:clear'
  | 'page-breaks:insert'
  | 'page-breaks:remove'
  | 'page-breaks:reset'
  | 'print-titles:first-row'
  | 'print-titles:selection'
  | 'print-titles:clear'
  | `page-fit:${'width' | 'height'}:${number}`
  | 'print-gridlines'
  | 'print-headings'
  | 'print'
  | 'undo'
  | 'redo'
  | 'name-manager-open'
  | 'define-name'
  | 'use-in-formula'
  | `use-in-formula:${string}`
  | 'rotate:45'
  | 'rotate:-45'
  | 'rotate:vertical'
  | 'rotate:90'
  | 'rotate:-90'
  | 'rotate:0'

export type RibbonSortBounds = { startRow: number; endRow: number; startColumn: number; endColumn: number; colIndex: number }

type RibbonRange = FontDecorationRange & {
  getRow(): number
  getColumn(): number
  getHeight(): number
  getWidth(): number
  getValues?(): Array<Array<unknown>>
  getFormulas?(): string[][]
  getCellStyleData(): UniverStyleData | null
  setValues?(values: Array<Array<{ s: UniverStyleData }>>): unknown
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
      getCellStyleData?(): UniverStyleData | null
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

// The pinned source's ribbon has no File tab (its File commands live in the
// native application menu, sheets-main.ts installApplicationMenu); the web
// editor mirrors the printable subset — File ▸ 打印 plus the File-menu
// history entries the source actually keeps in Edit ▸ Undo/Redo — as a tab.
const tabs: RibbonTab[] = ['File', 'Home', 'Insert', 'Page Layout', 'Formulas', 'Data', 'Review', 'View']

type RibbonAction = { label: string; id: string; command?: RibbonCommand }
type RibbonGroup = { title: string; actions: RibbonAction[] }

/// Active-sheet Page Layout state the ribbon selects and toggles render from;
/// built in workbook-main from the engine read model plus the session journal
/// (Univer has no page-setup facade — the grid never renders print settings).
export interface WorkbookPageSetupState {
  margins: 'normal' | 'wide' | 'narrow' | 'custom'
  orientation?: 'portrait' | 'landscape' | undefined
  paperSize?: number | undefined
  fitToWidth?: number | undefined
  fitToHeight?: number | undefined
  printGridlines: boolean
  printHeadings: boolean
  printArea?: string | undefined
}

// Menus follow GenOffice ExcelShell.tsx Page Layout tab at f8c17004: the
// source sets margins/orientation/paper/print-area/breaks/print-titles
// through dropdown menus (no dialogs), fit-width/fit-height through compact
// 0-5 page selects, and scale only inside the Print dialog.
const PAGE_MARGIN_CHOICES = [
  { value: 'normal', label: '常规' },
  { value: 'wide', label: '宽' },
  { value: 'narrow', label: '窄' },
] as const
const PAGE_ORIENTATION_CHOICES = [
  { value: 'portrait', label: '纵向' },
  { value: 'landscape', label: '横向' },
] as const
const PAGE_PAPER_CHOICES = [
  { value: '1', label: 'Letter' }, { value: '5', label: 'Legal' }, { value: '3', label: 'Tabloid' },
  { value: '7', label: 'Executive' }, { value: '8', label: 'A3' }, { value: '9', label: 'A4' },
  { value: '11', label: 'A5' },
] as const
const PRINT_AREA_CHOICES = [
  { value: 'print-area:set', label: '设置打印区域' },
  { value: 'print-area:clear', label: '取消打印区域' },
] as const
const PAGE_BREAK_CHOICES = [
  { value: 'page-breaks:insert', label: '插入分页符' },
  { value: 'page-breaks:remove', label: '删除分页符' },
  { value: 'page-breaks:reset', label: '重置所有分页符' },
] as const
const PRINT_TITLE_CHOICES = [
  { value: 'print-titles:first-row', label: '重复第 1 行' },
  { value: 'print-titles:selection', label: '重复所选行' },
  { value: 'print-titles:clear', label: '清除打印标题' },
] as const

const commandLabels: Record<string, string> = {
  "paste": "粘贴",
  "cut": "剪切",
  "copy": "复制",
  "format-painter": "格式刷",
  "cf-open": "条件格式",
  "format-as-table": "套用表格格式",
  "cell-style": "单元格样式",
  "pivot-open": "数据透视表",
  "pivot-edit": "编辑数据透视表",
  "insert-picture": "图片",
  "insert-shape": "形状",
  "insert-icons": "图标",
  "insert-screenshot": "屏幕截图",
  "insert-checkbox": "插入复选框",
  "recommended-charts-open": "推荐图表",
  "slicer-open": "切片器",
  "timeline-open": "时间线",
  "link-open": "链接",
  "insert-textbox": "文本框",
  "header-footer-open": "页眉和页脚",
  "insert-equation": "公式",
  "insert-symbol": "符号",
  "theme": "主题",
  "theme-colors": "主题颜色",
  "theme-fonts": "主题字体",
  "theme-effects": "主题效果",
  "margins": "页边距",
  "orientation": "纸张方向",
  "paper-size": "纸张大小",
  "print-area": "打印区域",
  "page-breaks": "分页符",
  "background": "背景",
  "fit-width": "调整宽度",
  "fit-height": "调整高度",
  "scale": "缩放比例",
  "toggle-gridlines": "显示网格线",
  "print-gridlines": "打印网格线",
  "toggle-headings": "显示标题",
  "print-headings": "打印标题",
  "name-manager-open": "名称管理器",
  "define-name": "定义名称",
  "use-in-formula": "用于公式",
  "trace-precedents": "追踪引用单元格",
  "trace-dependents": "追踪从属单元格",
  "remove-arrows": "移去箭头",
  "toggle-show-formulas": "显示公式",
  "error-checking": "错误检查",
  "watch-window": "监视窗口",
  "external-links-panel": "外部链接",
  "calculate-now": "开始计算",
  "calculate-sheet": "计算工作表",
  "calculation-options": "计算选项",
  "import-csv": "导入 CSV",
  "merge-workbooks": "合并工作簿",
  "refresh-all": "全部刷新",
  "queries-open": "查询",
  "forecast-sheet": "预测工作表",
  "what-if-analysis": "模拟分析",
  "outline-group:rows": "组合行",
  "outline-group:cols": "组合列",
  "outline-ungroup:rows": "取消行组合",
  "outline-ungroup:cols": "取消列组合",
  "outline-hide-detail": "隐藏明细",
  "outline-show-detail": "显示明细",
  "chart-title": "图表标题",
  "chart-axis-cat": "分类轴",
  "chart-axis-val": "数值轴",
  "chart-legend": "图例",
  "chart-labels": "数据标签",
  "chart-select-data": "选择数据",
  "chart-switch-row-col": "切换行列",
  "chart-format-pane": "图表格式",
  "chart-delete": "删除图表",
  "insert-chart:column": "柱形图",
  "insert-chart:bar": "条形图",
  "insert-chart:line": "折线图",
  "insert-chart:area": "面积图",
  "insert-chart:pie": "饼图",
  "insert-chart:scatter": "散点图",
  "insert-chart:radar": "雷达图",
  "insert-chart:doughnut": "圆环图",
  "insert-chart:combo": "组合图",
  "chart-type-column": "柱形图",
  "chart-type-bar": "条形图",
  "chart-type-line": "折线图",
  "chart-type-area": "面积图",
  "chart-type-pie": "饼图",
  "chart-type-scatter": "散点图",
  "chart-type-radar": "雷达图",
  "chart-type-doughnut": "圆环图",
  "chart-type-combo": "组合图",
  "sparkline:line": "折线迷你图",
  "sparkline:column": "柱形迷你图",
  "sparkline:stacked": "盈亏迷你图"
}

const action = (label: string, id: string, command?: RibbonCommand): RibbonAction =>
  command === undefined ? { label: commandLabels[id] ?? label, id } : { label: commandLabels[id] ?? label, id, command }

// Groups and command ids follow GenOffice ExcelShell.tsx at f8c17004.
const groups: Record<RibbonTab, RibbonGroup[]> = {
  File: [
    { title: '打印', actions: [action('打印', 'print', 'print')] },
    // 撤销/恢复 route to the live Univer undo/redo stacks (the same commands
    // the grid keyboard shortcuts run), mirroring the pinned source's menu
    // entries that call univerAPI.undo()/redo().
    { title: '编辑', actions: [action('撤销', 'undo', 'undo'), action('恢复', 'redo', 'redo')] },
  ],
  Home: [
    { title: '剪贴板', actions: [action('paste', 'paste', 'paste'), action('cut', 'cut', 'cut'), action('copy', 'copy', 'copy'), action('format-painter', 'format-painter', 'format-painter')] },
    { title: '字体', actions: [
      action('字体', 'font-family:Arial', 'font-family:Arial'), action('字号', 'font-size:12', 'font-size:12'),
      action('粗体', 'bold', 'bold'), action('斜体', 'italic', 'italic'), action('下划线', 'underline', 'underline'),
      action('双下划线', 'underline:double', 'underline:double'), action('删除线', 'strike', 'strike'), action('上标', 'superscript'), action('下标', 'subscript'),
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
      action('增加缩进', 'indent-step:increase', 'indent-step:increase'), action('减少缩进', 'indent-step:decrease', 'indent-step:decrease'), action('合并单元格', 'merge:cells', 'merge:cells'),
      action('合并后居中', 'merge:center', 'merge:center'), action('跨越合并', 'merge:across', 'merge:across'),
      action('取消单元格合并', 'merge:unmerge', 'merge:unmerge'),
    ] },
    { title: '数字', actions: [
      action('小数', 'format:0.00', 'format:0.00'), action('百分比', 'format:0%', 'format:0%'), action('千位分隔', 'format:#,##0.00', 'format:#,##0.00'),
      action('增加小数位', 'decimal-inc', 'decimal-inc'), action('减少小数位', 'decimal-dec', 'decimal-dec'),
      action('自定义数字格式', 'format:custom-open', 'format:custom-open'),
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
      action('全部清除', 'clear-all', 'clear-all'), action('清除格式', 'clear-formats', 'clear-formats'),
      action('清除内容', 'clear-contents', 'clear-contents'),
    ] },
    { title: '编辑', actions: [
      ...(['SUM', 'AVERAGE', 'COUNT', 'MAX', 'MIN'] as const).map((fn, index) =>
        action(['自动求和', '平均值', '计数值', '最大值', '最小值'][index]!, `autofn:${fn}`, `autofn:${fn}`)),
      action('排序', 'sort-custom-open'), action('查找', 'find', 'find'),
      action('替换', 'replace', 'replace'), action('定位', 'goto-open'),
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
    { title: '批注', actions: [action('批注', 'note-open', 'note-open')] },
    { title: '文本', actions: ['insert-textbox', 'header-footer-open'].map(id => action(id, id)) },
    { title: '符号', actions: ['insert-equation', 'insert-symbol'].map(id => action(id, id)) },
  ],
  'Page Layout': [
    { title: '主题', actions: ['theme', 'theme-colors', 'theme-fonts', 'theme-effects'].map(id => action(id, id)) },
    // 页边距/纸张方向/纸张大小/打印区域/分页符/顶端标题行 are dropdown
    // selects generated in render() (source ExcelShell MenuSelect form).
    { title: '页面设置', actions: [action('背景', 'background')] },
    { title: '调整为合适大小', actions: [action('缩放比例', 'scale')] },
    { title: '工作表选项', actions: [
      action('显示网格线', 'toggle-gridlines', 'toggle-gridlines'),
      action('打印网格线', 'print-gridlines', 'print-gridlines'),
      action('显示标题', 'toggle-headings'),
      action('打印标题', 'print-headings', 'print-headings'),
    ] },
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
    { title: '定义的名称', actions: [
      action('名称管理器', 'name-manager-open', 'name-manager-open'),
      action('定义名称', 'define-name', 'define-name'),
      // use-in-formula 渲染为已定义名称下拉，命令形如 use-in-formula:<name>。
      action('用于公式', 'use-in-formula', 'use-in-formula'),
    ] },
    { title: '公式审核', actions: ['trace-precedents', 'trace-dependents', 'remove-arrows', 'toggle-show-formulas', 'error-checking', 'watch-window', 'external-links-panel'].map(id => action(id, id)) },
    { title: '计算', actions: ['calculate-now', 'calculate-sheet', 'calculation-options'].map(id => action(id, id)) },
  ],
  Data: [
    { title: '数据透视表', actions: ['pivot-open', 'pivot-edit'].map(id => action(id, id)) },
    { title: '获取数据', actions: ['import-csv', 'merge-workbooks', 'refresh-all', 'queries-open'].map(id => action(id, id)) },
    { title: '排序和筛选', actions: [
      action('升序', 'sort:asc', 'sort:asc'), action('降序', 'sort:desc', 'sort:desc'),
      action('自定义排序…', 'sort-custom-open'), action('筛选', 'filter-toggle', 'filter-toggle'), action('清除筛选条件', 'filter-clear', 'filter-clear'),
      action('重新应用筛选', 'filter-reapply', 'filter-reapply'), action('高级筛选', 'filter-advanced'),
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
      action('新建/编辑批注', 'note-open', 'note-open'), action('删除', 'note-delete', 'note-delete'),
      action('上一条', 'note-prev', 'note-prev'), action('下一条', 'note-next', 'note-next'),
      action('显示批注', 'note-show-toggle', 'note-show-toggle'),
    ] },
    { title: '注释', actions: [action('注释', 'note-open', 'note-open')] },
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
      action('缩放', 'zoom-open'), action('重置缩放', 'zoom-reset', 'zoom-reset'), action('缩放到选定区域', 'zoom-to-selection'),
      action('放大', 'zoom-in', 'zoom-in'), action('缩小', 'zoom-out', 'zoom-out'),
    ] },
    { title: '窗口', actions: [
      action('新建窗口', 'new-window'), action('全部重排', 'arrange-all'), action('冻结窗格', 'freeze-panes', 'freeze-panes'),
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
  'superscript': '当前引擎尚无单元格上标样式的读取和写回字段，不能保证保存',
  'subscript': '当前引擎尚无单元格下标样式的读取和写回字段，不能保证保存',
  'cf-open': '尚未接入条件格式草稿编辑',
  'format-as-table': '尚未接入表格创建的文件回写',
  'cell-style': '尚未接入单元格样式预设的文件回写',
  'insert-cells': '尚无插入并移动单元格操作',
  'delete-cells': '尚无删除并移动单元格操作',
  'format-cells': '尚无完整单元格格式对话框；可使用数字组的自定义数字格式',
  'row-height-open': '尚无行高对话框',
  'col-width-open': '尚无列宽对话框',
  'autofit-row-height': '尚不能持久化自动行高',
  'autofit-col-width': '尚不能持久化自动列宽',
  'insert-checkbox': '尚未接入复选框绘图及文件回写',
  'recommended-charts-open': '尚未接入静态图表创建对话框与文件回写',
  'insert-chart:column': '尚未接入静态图表创建对话框与文件回写',
  'insert-chart:bar': '尚未接入静态图表创建对话框与文件回写',
  'insert-chart:line': '尚未接入静态图表创建对话框与文件回写',
  'insert-chart:area': '尚未接入静态图表创建对话框与文件回写',
  'insert-chart:pie': '尚未接入静态图表创建对话框与文件回写',
  'insert-chart:scatter': '尚未接入静态图表创建对话框与文件回写',
  'insert-chart:radar': '尚未接入静态图表创建对话框与文件回写',
  'insert-chart:doughnut': '尚未接入静态图表创建对话框与文件回写',
  'insert-chart:combo': '尚未接入静态图表创建对话框与文件回写',
  'sparkline:line': '尚不能回写迷你图修改',
  'sparkline:column': '尚不能回写迷你图修改',
  'sparkline:stacked': '尚不能回写迷你图修改',
  'slicer-open': '尚不能读取和回写此筛选器',
  'timeline-open': '尚不能读取和回写此筛选器',
  'sort-custom-open': '尚无选择关键列、标题和多级条件的自定义排序对话框',
  'filter-advanced': '尚无高级筛选条件对话框与文件回写',
  'workbook-statistics': '尚无整本工作簿统计视图',
  'translate': '尚未接入基于选区的翻译操作',
  'sheet-protect': '尚不能读取工作表保护状态，暂不能安全切换',
  'workbook-protect': '尚不能读取工作簿保护状态，暂不能安全切换',
  'allow-edit-ranges-open': '尚不能读取和编辑受保护区域',
  'text-to-columns:2': '尚无文本分列操作与文件回写',
  'text-to-columns:4': '尚无文本分列操作与文件回写',
  'text-to-columns:8': '尚无文本分列操作与文件回写',
  'text-to-columns:1': '尚无文本分列操作与文件回写',
  'flash-fill': '尚不能持久化快速填充生成的修改',
  'remove-duplicates-open': '尚无基于选区的重复值对话框和行删除回写',
  'dv-open': '尚无数据验证对话框与文件回写',
  'consolidate-open': '尚无合并计算对话框与来源范围回写',
  'subtotal-open': '尚无插入并持久化分组汇总行的操作',
  'insert-function-open': '尚无函数目录对话框；可使用自动求和等直接操作',
  'insert-function-open:All': '尚无函数目录对话框；可使用自动求和等直接操作',
  'insert-function-open:Financial': '尚无函数目录对话框；可使用自动求和等直接操作',
  'insert-function-open:Logical': '尚无函数目录对话框；可使用自动求和等直接操作',
  'insert-function-open:Text': '尚无函数目录对话框；可使用自动求和等直接操作',
  'insert-function-open:Date & Time': '尚无函数目录对话框；可使用自动求和等直接操作',
  'insert-function-open:Lookup': '尚无函数目录对话框；可使用自动求和等直接操作',
  'insert-function-open:Math': '尚无函数目录对话框；可使用自动求和等直接操作',
  'normal-view': '当前仅提供普通网格视图',
  'toggle-page-break-preview': '尚无分页预览渲染和视图状态',
  'toggle-formula-bar': '编辑栏由当前预设固定，尚无运行时切换接口',
  'toggle-headings': '尚无表头尺寸和视口状态切换适配',
  'toggle-right-to-left': '文件读写尚未承载从右到左视图状态',
  'toggle-cross-highlight': '尚未实现活动行列突出显示视图',
  'zoom-open': '尚无缩放选择器与已验证的缩放接口',
  'zoom-to-selection': '尚无选区尺寸与视口缩放适配',
  'scale': '固定源经打印对话框设置打印缩放；打印对话框尚未接入',
  'background': '尚无工作表背景图片读取与回写',
  'new-window': '网页编辑器不管理桌面工作簿窗口',
  'arrange-all': '网页编辑器不管理桌面工作簿窗口',
  'split-window': '尚无拆分视口及文件回写',
  'hide-window': '网页编辑器不管理桌面工作簿窗口',
  'switch-window': '网页编辑器不管理桌面工作簿窗口',
}

export function applyWorkbookRibbonCommand(
  command: RibbonCommand,
  workbook: RibbonWorkbook,
  stepDecimals?: (step: 1 | -1) => void,
  rotateSelection?: (value: RotationValue) => void,
  sortRange?: (bounds: RibbonSortBounds, ascending: boolean) => boolean,
  clearSelection?: (kind: 'all' | 'formats') => boolean,
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
  if (name === 'indent-step') {
    // 固定源 ribbon-actions indent-step：每个选中单元格相对自身缩进 ±1 级（混合缩进
    // 保持混合，0–250 级），以 pd 左内边距经 set-range-values 写入网格，可撤销；保存时
    // 由样式差分写回 OOXML alignment@indent。
    const delta = value === 'increase' ? 1 : value === 'decrease' ? -1 : 0
    if (!delta) throw new Error('不支持此缩进操作')
    if (!range.setValues) throw new Error('当前工作簿未接入缩进写入')
    const rows = range.getHeight(), columns = range.getWidth()
    if (rows * columns > 10_000) throw new Error('选区过大，请缩小到 10000 个单元格以内再调整缩进')
    const top = range.getRow(), left = range.getColumn()
    range.setValues(Array.from({ length: rows }, (_, r) => Array.from({ length: columns }, (_, c) => {
      const current = univerPaddingToIndent(sheet.getRange(top + r, left + c).getCellStyleData?.()?.pd) ?? 0
      return { s: { pd: indentToUniverPadding(current + delta) } }
    })))
    return true
  }
  if (name === 'rotate') {
    const rotation = ROTATION_VALUES[command as keyof typeof ROTATION_VALUES]
    if (rotation === undefined) throw new Error('不支持此文字旋转值')
    if (!rotateSelection) throw new Error('当前工作簿未接入文字旋转')
    rotateSelection(rotation); return true
  }
  if (name === 'autofn') {
    const fn = value?.toUpperCase()
    if (!['SUM', 'AVERAGE', 'COUNT', 'MAX', 'MIN'].includes(fn ?? '')) throw new Error('不支持此自动求和函数')
    if (range.getHeight() < 2) throw new Error('请至少选择两行以进行自动求和')
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
    if (range.getHeight() < 2) throw new Error('请至少选择两行以排序')
    if (!sortRange) throw new Error('当前工作簿未接入官方排序命令')
    const startRow = range.getRow(), startColumn = range.getColumn()
    // 官方 sheet.command.sort-range：值/样式/公式随行整体重排；批注在网格内随迁。
    // 含批注来源仍由 main 的结构守卫拦截，直至引擎补移动写回语义。
    if (sortRange({
      startRow, endRow: startRow + range.getHeight() - 1,
      startColumn, endColumn: startColumn + range.getWidth() - 1,
      colIndex: startColumn,
    }, value === 'asc') === false) throw new Error('排序未应用；选区或批注来源受当前限制')
    return true
  }
  if (command === 'clear-formats' || command === 'clear-all') {
    // 固定源 Editing 组语义：清除走官方 Univer 命令（formats = 仅样式重置为默认，
    // all = 值+公式+样式全清；批注/超链接不在 clear-all 范围，另有独立入口）。
    // 保存差分把清除后的“样式缺席”捕获为 styleReset 落盘。
    if (!clearSelection) throw new Error('当前工作簿未接入清除命令')
    if (clearSelection(command === 'clear-all' ? 'all' : 'formats') === false) throw new Error('清除未应用')
    return true
  }
  if (name === 'font-family') {
    if (!value?.trim() || value.length > 100 || /[\x00-\x1f]/.test(value)) throw new Error('字体名称无效')
    range.setFontFamily(value)
    return true
  }
  if (name === 'font-size') {
    const size = Number(value)
    if (!Number.isFinite(size) || size < 1 || size > 400) throw new Error('字号须在 1–400 磅之间')
    range.setFontSize(size)
    return true
  }
  if (name === 'font-color' || name === 'fill') {
    if (!/^#[0-9a-f]{6}$/i.test(value ?? '')) throw new Error('颜色须使用六位十六进制 RGB')
    if (name === 'font-color') range.setFontColor(value!)
    else range.setBackgroundColor(value!)
    return true
  }
  switch (command) {
    case 'bold': { const state = selectedWorkbookFormat(workbook).bold; range.setFontWeight(state.kind === 'value' && state.value ? 'normal' : 'bold'); break }
    case 'italic': { const state = selectedWorkbookFormat(workbook).italic; range.setFontStyle(state.kind === 'value' && state.value ? 'normal' : 'italic'); break }
    case 'underline':
    case 'underline:double':
    case 'strike': applyWorkbookFontDecoration(command, range, selectedWorkbookFormat(workbook)); break
    case 'wrap': range.setWrap(!range.getWrap()); break
    case 'border:all': range.setBorder(BorderType.ALL, BorderStyleTypes.THIN, '#000000'); break
    case 'format:0.00': range.setNumberFormat('0.00'); break
    case 'format:0%': range.setNumberFormat('0%'); break
    case 'format:#,##0.00': range.setNumberFormat('#,##0.00'); break
    case 'decimal-inc':
    case 'decimal-dec':
      if (!stepDecimals) throw new Error('当前工作簿未接入小数位调整')
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
  onCommand: (command: RibbonCommand, target?: NumberFormatTarget) => void,
  view?: {
    rotation(): number | 'mixed' | undefined
    editable(): boolean
    unavailableReason?(): string | undefined
    format?(): WorkbookFormatState
    hasSelection?(): boolean
    noteReason?(command: string): string | undefined
    /// 缩进继承样式不可完整回读时的禁用原因（引擎 indentReadOnlyReason）。
    indentReason?(): string | undefined
    /// 格式刷是否处于单次/锁定状态（aria-pressed 镜像）。
    formatPainterActive?(): boolean
    captureTarget?(): NumberFormatTarget | undefined
    pageSetup?(): WorkbookPageSetupState | undefined
    definedNames?(): readonly string[]
  },
) {
  const tabLabels: Record<RibbonTab, string> = { File: '文件', Home: '开始', Insert: '插入', 'Page Layout': '页面布局', Formulas: '公式', Data: '数据', Review: '审阅', View: '视图', 'Chart Design': '图表设计' }
  container.innerHTML = `
    <header class="workbook-ribbon" aria-label="Excel 功能区">
      <nav class="workbook-ribbon-tabs" role="tablist" aria-label="工作簿工具"></nav>
      <div class="workbook-ribbon-body" role="tabpanel" id="workbook-ribbon-panel"></div>
    </header>`
  const nav = container.querySelector<HTMLElement>('.workbook-ribbon-tabs')!
  const body = container.querySelector<HTMLElement>('.workbook-ribbon-body')!
  let active: RibbonTab = 'Home'

  const stateText = (state: FormatValue<unknown>) => state.kind === 'mixed' ? '混合' : state.kind === 'unavailable' ? '不可判定' : String(state.value)
  const updateSelect = (control: string, state: FormatValue<unknown>, editable: boolean) => {
    const select = body.querySelector<HTMLSelectElement>(`[data-ribbon-control="${control}"]`)
    if (!select) return
    select.querySelectorAll('[data-format-option]').forEach(option => option.remove())
    const value = state.kind === 'value' ? String(state.value) : ''
    if (![...select.options].some(option => option.value === value)) {
      const option = document.createElement('option')
      option.dataset.formatOption = 'true'; option.value = value; option.textContent = stateText(state)
      if (state.kind !== 'value') option.disabled = true
      select.prepend(option)
    }
    select.value = value
    select.dataset.formatState = state.kind
    select.disabled = !editable || state.kind === 'unavailable'
    select.title = state.kind === 'unavailable' ? state.reason : stateText(state)
    select.setAttribute('aria-description', select.title)
  }
  const refreshState = () => {
    if (!view) return
    const rotation = view.rotation(), editable = view.editable(), reason = view.unavailableReason?.()
    const format = view.format?.(), selected = view.hasSelection?.() ?? rotation !== undefined
    for (const button of body.querySelectorAll<HTMLButtonElement>('[data-ribbon-command]')) {
      const id = button.dataset.ribbonCommand!
      if (button.dataset.unavailableReason) continue
      const noteViewAction = ['note-prev', 'note-next', 'note-show-toggle'].includes(id)
      // 打印 is read-only (available like 查找 even while read-only/saved);
      // 撤销/恢复 replay history mutations and follow editability.
      // 复制只读选区（固定源 read-only-safe），只读/已保存时仍可用。
      const readOnlySafe = noteViewAction || id === 'copy'
      button.disabled = id === 'find' || id === 'print' ? false : readOnlySafe ? !selected : id === 'replace' ? !editable : !editable || (!selected && !['insert-sheet', 'toggle-gridlines', 'print-gridlines', 'print-headings', 'name-manager-open', 'undo', 'redo'].includes(id))
      button.title = button.disabled ? !editable && !readOnlySafe ? '当前工作簿不可编辑或正在保存' : '请先选择单元格或区域' : button.textContent ?? ''
      if (id === 'format-painter') button.setAttribute('aria-pressed', String(!!view.formatPainterActive?.()))
      if (id.startsWith('indent-step:') && !button.disabled) {
        const indentReason = view.indentReason?.()
        if (indentReason) { button.disabled = true; button.title = indentReason }
      }
      if (id.startsWith('note-')) {
        const noteReason = view.noteReason?.(id) ?? (!view.noteReason ? '批注来源尚未完成身份读取' : undefined)
        if (noteReason) { button.disabled = true; button.title = noteReason }
      }
      if (format) {
        const property = ({ bold: 'bold', italic: 'italic', underline: 'underline', 'underline:double': 'doubleUnderline', strike: 'strikethrough' } as const)[id as 'bold']
        const state = property ? format[property] : undefined
        if (state) {
          button.dataset.formatState = state.kind
          button.setAttribute('aria-pressed', state.kind === 'mixed' ? 'mixed' : String(state.kind === 'value' && state.value))
          if (state.kind === 'unavailable') { button.disabled = true; button.title = state.reason }
        }
        if (id.startsWith('format:') || id.startsWith('decimal-')) {
          const state = format.numberFormat
          if (state.kind === 'unavailable') { button.disabled = true; button.title = state.reason }
        }
      }
      if (button.disabled) button.setAttribute('aria-description', button.title)
      else button.removeAttribute('aria-description')
    }
    for (const [id, value] of Object.entries(ROTATION_VALUES)) {
      const button = body.querySelector<HTMLButtonElement>(`[data-ribbon-command="${id}"]`)
      if (!button) continue
      button.disabled = !editable || rotation === undefined || !!reason
      const expected = value === 'v' ? 255 : value < 0 ? 90 - value : value
      button.setAttribute('aria-pressed', rotation === 'mixed' ? 'mixed' : String(rotation === expected))
      if (button.disabled) { button.title = editable ? reason ?? '请先选择单元格或区域' : '当前工作簿不可编辑或正在保存'; button.setAttribute('aria-description', button.title) }
      else { button.title = button.textContent ?? ''; button.removeAttribute('aria-description') }
    }
    const pasteSpecial = body.querySelector<HTMLSelectElement>('[data-ribbon-menu="paste-special"]')
    if (pasteSpecial) {
      pasteSpecial.disabled = !editable || !selected
      pasteSpecial.title = !editable ? '当前工作簿不可编辑或正在保存' : !selected ? '请先选择单元格或区域' : '选择性粘贴'
    }
    // Page Layout 下拉与打印开关：状态来自引擎读模型 + 会话内页面设置日志。
    const pageState = view.pageSetup?.()
    const pageOption = (value: string, label: string, disabled = false) => {
      const option = document.createElement('option'); option.value = value; option.textContent = label; option.disabled = disabled; return option
    }
    const fillPageSelect = (selector: string, entries: readonly { value: string; label: string; disabled?: boolean }[], current: string) => {
      const select = body.querySelector<HTMLSelectElement>(selector)
      if (!select) return
      select.replaceChildren(...entries.map(entry => pageOption(entry.value, entry.label, entry.disabled)))
      if (current !== '' && !entries.some(entry => entry.value === current)) select.prepend(pageOption(current, `文件值 ${current}`, true))
      select.value = current
      select.disabled = !editable || !pageState
      select.title = select.disabled ? '当前工作簿不可编辑或正在保存' : select.getAttribute('aria-label') ?? ''
      select.setAttribute('aria-description', select.title)
    }
    fillPageSelect('[data-ribbon-control="page-margins"]',
      pageState?.margins === 'custom'
        ? [{ value: 'custom', label: '自定义（保留文件边距）', disabled: true }, ...PAGE_MARGIN_CHOICES.map(choice => ({ value: choice.value, label: choice.label }))]
        : PAGE_MARGIN_CHOICES.map(choice => ({ value: choice.value, label: choice.label })),
      pageState ? pageState.margins === 'custom' ? 'custom' : pageState.margins : '')
    fillPageSelect('[data-ribbon-control="page-orientation"]',
      [...(pageState?.orientation === undefined ? [{ value: '', label: '按文件保存' }] : []), ...PAGE_ORIENTATION_CHOICES.map(choice => ({ value: choice.value, label: choice.label }))],
      pageState?.orientation ?? '')
    fillPageSelect('[data-ribbon-control="page-paper"]',
      [...(pageState?.paperSize === undefined ? [{ value: '', label: '按文件保存' }] : []), ...PAGE_PAPER_CHOICES.map(choice => ({ value: choice.value, label: choice.label }))],
      pageState?.paperSize === undefined ? '' : String(pageState.paperSize))
    for (const [axis, key] of [['width', 'fitToWidth'], ['height', 'fitToHeight']] as const) {
      fillPageSelect(`[data-ribbon-control="page-fit:${axis}"]`,
        [{ value: '0', label: '自动' }, ...[1, 2, 3, 4, 5].map(pages => ({ value: String(pages), label: `${pages} 页` }))],
        String(pageState?.[key] ?? 0))
    }
    // 页面布局动作下拉依赖页面设置读模型；选择性粘贴下拉由上方剪贴板状态单独管理。
    for (const select of body.querySelectorAll<HTMLSelectElement>('[data-ribbon-menu]:not([data-ribbon-menu="paste-special"])')) {
      select.disabled = !editable || !pageState
      select.title = select.disabled ? '当前工作簿不可编辑或正在保存' : select.getAttribute('aria-label') ?? ''
      select.setAttribute('aria-description', select.title)
    }
    for (const [command, key] of [['print-gridlines', 'printGridlines'], ['print-headings', 'printHeadings']] as const) {
      const button = body.querySelector<HTMLButtonElement>(`[data-ribbon-command="${command}"]`)
      if (!button) continue
      button.disabled = !editable || !pageState
      button.setAttribute('aria-pressed', String(!!pageState?.[key]))
      button.title = button.disabled ? '当前工作簿不可编辑或正在保存' : button.textContent ?? ''
      if (button.disabled) button.setAttribute('aria-description', button.title)
      else button.removeAttribute('aria-description')
    }
    // 用于公式（Formulas ▸ 定义的名称）：已定义名称下拉；无名称时禁用。
    const useSelect = body.querySelector<HTMLSelectElement>('[data-ribbon-control="use-in-formula"]')
    if (useSelect) {
      const names = view.definedNames?.() ?? []
      const placeholder = document.createElement('option')
      placeholder.value = ''
      placeholder.textContent = names.length ? '用于公式…' : '暂无定义名称'
      useSelect.replaceChildren(placeholder, ...names.map(name => {
        const option = document.createElement('option'); option.value = name; option.textContent = name; return option
      }))
      useSelect.disabled = !editable || !selected || names.length === 0
      useSelect.title = useSelect.disabled
        ? names.length === 0 ? '尚无定义名称；可在名称管理器中新建' : editable ? '请先选择单元格' : '当前工作簿不可编辑或正在保存'
        : useSelect.getAttribute('aria-label') ?? ''
      useSelect.setAttribute('aria-description', useSelect.title)
    }
    if (!format) return
    updateSelect('font-family', format.fontFamily, editable)
    updateSelect('font-size', format.fontSize, editable)
    for (const [control, key] of [['font-color', 'fontColor'], ['fill', 'fillColor']] as const) {
      const input = body.querySelector<HTMLInputElement>(`[data-ribbon-control="${control}"]`)
      if (!input) continue
      const state = format[key], wrapper = input.parentElement!
      const color = state.kind === 'value' && /^#[0-9a-f]{6}$/i.test(state.value) ? state.value : undefined
      wrapper.dataset.formatState = state.kind
      wrapper.dataset.formatValue = state.kind === 'value' ? state.value : ''
      input.hidden = !color
      input.disabled = !editable || state.kind === 'unavailable'
      if (color) input.value = color
      input.title = state.kind === 'unavailable' ? state.reason : color ?? (state.kind === 'mixed' ? '混合颜色' : state.kind === 'value' && state.value === 'none' ? '无填充' : '自动颜色')
      input.setAttribute('aria-description', input.title)
      const label = wrapper.querySelector<HTMLElement>('.workbook-ribbon-color-state')!
      label.textContent = input.title
      label.hidden = !!color
      // The picker remains actionable for automatic/no-fill/mixed states without
      // displaying its browser fallback black as a claimed selection color.
      label.tabIndex = !editable || state.kind === 'unavailable' ? -1 : 0
      label.setAttribute('role', 'button')
      label.setAttribute('aria-disabled', String(!editable || state.kind === 'unavailable'))
    }
    const number = body.querySelector<HTMLElement>('[data-ribbon-control="number-format"]')
    if (number) { number.textContent = format.numberFormat.kind === 'value' && format.numberFormat.value === 'General' ? '常规' : stateText(format.numberFormat); number.dataset.formatState = format.numberFormat.kind; number.title = format.numberFormat.kind === 'unavailable' ? format.numberFormat.reason : number.textContent }
  }
  const render = () => {
    nav.replaceChildren(...tabs.map(tab => {
      const button = document.createElement('button')
      button.type = 'button'
      button.id = `workbook-ribbon-tab-${tabs.indexOf(tab)}`
      button.setAttribute('role', 'tab')
      button.setAttribute('aria-controls', 'workbook-ribbon-panel')
      button.setAttribute('aria-selected', String(tab === active))
      button.tabIndex = tab === active ? 0 : -1
      button.dataset.ribbonTab = tab
      button.textContent = tabLabels[tab]
      button.addEventListener('click', () => { active = tab; render(); nav.querySelector<HTMLButtonElement>(`[data-ribbon-tab="${tab}"]`)?.focus() })
      return button
    }))
    body.setAttribute('aria-labelledby', `workbook-ribbon-tab-${tabs.indexOf(active)}`)
    const sections: HTMLElement[] = []
    for (const group of groups[active]) {
      const section = document.createElement('section')
      section.className = 'workbook-ribbon-group'
      const heading = document.createElement('h3')
      heading.textContent = group.title
      section.append(heading)
      if (active === 'Home' && group.title === '字体') {
        for (const [control, label, choices] of [['font-family', '字体', FONT_FAMILIES], ['font-size', '字号', FONT_SIZES]] as const) {
          const select = document.createElement('select')
          select.className = `workbook-ribbon-select${control === 'font-size' ? ' workbook-ribbon-size' : ''}`
          select.setAttribute('aria-label', label); select.dataset.ribbonControl = control
          const unknown = document.createElement('option'); unknown.value = ''; unknown.textContent = '不可判定'; unknown.disabled = true; unknown.dataset.formatOption = 'true'
          select.append(unknown, ...choices.map(value => { const option = document.createElement('option'); option.value = String(value); option.textContent = String(value); return option }))
          select.value = ''
          select.addEventListener('change', () => { if (!select.disabled && select.value) onCommand(`${control}:${select.value}` as RibbonCommand) })
          section.append(select)
        }
        for (const [control, label] of [['font-color', '字体颜色'], ['fill', '填充颜色']] as const) {
          const wrapper = document.createElement('label')
          wrapper.className = 'workbook-ribbon-color'; wrapper.title = label; wrapper.setAttribute('aria-label', label)
          const input = document.createElement('input')
          input.type = 'color'; input.hidden = true; input.dataset.ribbonControl = control; input.setAttribute('aria-label', label)
          input.addEventListener('input', () => { if (!input.disabled) onCommand(`${control}:${input.value}` as RibbonCommand) })
          const status = document.createElement('span'); status.className = 'workbook-ribbon-color-state'; status.textContent = '不可判定'
          const pick = () => { if (!input.disabled) { if (typeof input.showPicker === 'function') input.showPicker(); else input.click() } }
          status.addEventListener('click', event => { event.preventDefault(); pick() })
          status.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); pick() } })
          wrapper.append(input, status); section.append(wrapper)
        }
      }
      if (active === 'Home' && group.title === '剪贴板') {
        // 固定源粘贴分体按钮的下拉：选中后回弹到菜单标题（同页面布局动作下拉）。
        const select = document.createElement('select')
        select.className = 'workbook-ribbon-select'; select.setAttribute('aria-label', '选择性粘贴'); select.dataset.ribbonMenu = 'paste-special'
        const title = document.createElement('option'); title.value = ''; title.textContent = '选择性粘贴'
        select.append(title, ...PASTE_SPECIAL_CHOICES.map(choice => { const option = document.createElement('option'); option.value = choice.value; option.textContent = choice.label; return option }))
        select.addEventListener('change', () => { const value = select.value; select.value = ''; if (value && !select.disabled) onCommand(value as RibbonCommand) })
        section.append(select)
      }
      if (active === 'Home' && group.title === '数字') {
        const number = document.createElement('span'); number.className = 'workbook-ribbon-number-format'; number.dataset.ribbonControl = 'number-format'; number.setAttribute('aria-label', '当前数字格式'); number.textContent = '不可判定'; section.append(number)
      }
      if (active === 'Page Layout' && group.title === '页面设置') {
        // 固定源 MenuSelect 形态：字段下拉直接切换，动作下拉（打印区域/
        // 分页符/顶端标题行）选中后回弹到菜单标题。
        for (const [control, label] of [['page-margins', '页边距'], ['page-orientation', '纸张方向'], ['page-paper', '纸张大小']] as const) {
          const select = document.createElement('select')
          select.className = 'workbook-ribbon-select'; select.setAttribute('aria-label', label); select.dataset.ribbonControl = control
          select.addEventListener('change', () => { if (!select.disabled && select.value) onCommand(`${control}:${select.value}` as RibbonCommand) })
          section.append(select)
        }
        for (const [menu, label, choices] of [['print-area', '打印区域', PRINT_AREA_CHOICES], ['page-breaks', '分页符', PAGE_BREAK_CHOICES], ['print-titles', '打印标题', PRINT_TITLE_CHOICES]] as const) {
          const select = document.createElement('select')
          select.className = 'workbook-ribbon-select'; select.setAttribute('aria-label', label); select.dataset.ribbonMenu = menu
          const title = document.createElement('option'); title.value = ''; title.textContent = label
          select.append(title, ...choices.map(choice => { const option = document.createElement('option'); option.value = choice.value; option.textContent = choice.label; return option }))
          select.addEventListener('change', () => { const value = select.value; select.value = ''; if (value && !select.disabled) onCommand(value as RibbonCommand) })
          section.append(select)
        }
      }
      if (active === 'Page Layout' && group.title === '调整为合适大小') {
        for (const [axis, label] of [['width', '宽度'], ['height', '高度']] as const) {
          const select = document.createElement('select')
          select.className = 'workbook-ribbon-select'; select.setAttribute('aria-label', `调整为${label}`); select.dataset.ribbonControl = `page-fit:${axis}`
          select.addEventListener('change', () => { if (!select.disabled && select.value) onCommand(`page-fit:${axis}:${select.value}` as RibbonCommand) })
          section.append(select)
        }
      }
      if (active === 'Formulas' && group.title === '定义的名称') {
        // 固定源 MenuSelect 形态：Use in Formula 渲染为名称下拉，命令
        // use-in-formula:<name> 由 main 插入活动单元格（选中后回弹）。
        const select = document.createElement('select')
        select.className = 'workbook-ribbon-select'
        select.setAttribute('aria-label', '用于公式')
        select.dataset.ribbonControl = 'use-in-formula'
        select.addEventListener('change', () => {
          const name = select.value
          select.value = ''
          if (name && !select.disabled) onCommand(`use-in-formula:${name}` as RibbonCommand)
        })
        section.append(select)
      }
      for (const item of group.actions) {
        if (active === 'Home' && group.title === '字体' && /^(font-family|font-size|font-color|fill):/.test(item.id)) continue
        if (active === 'Formulas' && item.id === 'use-in-formula') continue
        const button = document.createElement('button')
        button.type = 'button'; button.dataset.ribbonCommand = item.id
        const glyph = COMMAND_GLYPHS[item.id], icon = glyph ? RIBBON_GLYPH_ICONS[glyph] : undefined
        if (icon) {
          const iconHost = document.createElement('span'); iconHost.className = 'workbook-ribbon-icon'; iconHost.setAttribute('aria-hidden', 'true'); iconHost.innerHTML = renderToStaticMarkup(icon)
          const label = document.createElement('span'); label.textContent = item.label; button.append(iconHost, label)
        } else button.textContent = item.label
        if (item.command === undefined || disabledReasons[item.id] !== undefined) {
          const reason = disabledReasons[item.id] ?? `“${item.label}”尚未接入完整的文件读取与回写`
          button.disabled = true; button.dataset.unavailableReason = reason; button.title = reason; button.setAttribute('aria-description', reason)
        } else {
          let target: NumberFormatTarget | undefined
          let captureError: string | undefined
          if (item.command === 'format:custom-open') {
            button.setAttribute('aria-haspopup', 'dialog')
            const capture = () => { try { target = view?.captureTarget?.(); captureError = undefined } catch (error) { target = undefined; captureError = (error as Error).message; button.title = captureError } }
            button.addEventListener('focus', capture); button.addEventListener('pointerdown', capture)
          }
          // 格式刷：固定源按 click detail 区分单击（刷一次）与双击（锁定）。
          button.addEventListener('click', event => { if (!button.disabled && !captureError) { if (item.command === 'format:custom-open') onCommand(item.command, target); else if (item.command === 'format-painter') onCommand(event.detail >= 2 ? 'format-painter:dblclick' : 'format-painter'); else onCommand(item.command!) } })
        }
        section.append(button)
      }
      sections.push(section)
    }
    body.replaceChildren(...sections)
    refreshState()
  }
  const onTabKeyDown = (event: KeyboardEvent) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const index = tabs.indexOf(active)
    active = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]!
    render(); nav.querySelector<HTMLButtonElement>(`[data-ribbon-tab="${active}"]`)?.focus()
  }
  nav.addEventListener('keydown', onTabKeyDown)
  render()
  return { refreshState, dispose() { nav.removeEventListener('keydown', onTabKeyDown); container.replaceChildren() } }
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

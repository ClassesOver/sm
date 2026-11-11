import { createElement, type ComponentType } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { RIBBON_GLYPH_ICONS } from './workbook-vendor/ui/ribbon-icons'
import { IconSuperscript, IconSubscript, IconRotateLeft, IconRotateRight, IconClearFormat, IconIndentInc, IconIndentDec, IconPrintLayout, IconUndo, IconRedo, IconTableProperties, IconAutoFit, IconTextBox, IconEquation, IconSymbol, IconTheme, IconThemeFonts, IconThemeColors, IconHeader, IconZoomIn, IconZoomOut, IconZoom100, IconZoom, IconPageWidth, IconTranslate } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { Bold, Italic, Underline, Strikethrough, Percent, Hash, Baseline, AlignVerticalSpaceAround, createElement as lucideElement } from 'lucide'

// 固定 GenOffice 图形优先；源字体按钮本身为 B/I/U 文本时才用现有 Lucide 轮廓补齐。
const source: Record<string, ComponentType<{size?: number}>> = {
  superscript: IconSuperscript, subscript: IconSubscript, 'rotate:45': IconRotateLeft, 'rotate:-45': IconRotateRight,
  'rotate:90': IconRotateLeft, 'rotate:-90': IconRotateRight, 'rotate:0': IconClearFormat,
  'indent-step:increase': IconIndentInc, 'indent-step:decrease': IconIndentDec,
  print: IconPrintLayout, undo: IconUndo, redo: IconRedo, 'clear-formats': IconClearFormat,
  'format-cells': IconTableProperties, 'format:custom-open': IconTableProperties,
  'autofit-row-height': IconAutoFit, 'autofit-col-width': IconAutoFit,
  'insert-textbox': IconTextBox, 'insert-equation': IconEquation, 'insert-symbol': IconSymbol,
  theme: IconTheme, 'theme-fonts': IconThemeFonts, 'theme-colors': IconThemeColors,
  'header-footer-open': IconHeader, 'zoom-in': IconZoomIn, 'zoom-out': IconZoomOut, 'zoom-reset': IconZoom100,
  'zoom-open': IconZoom, 'zoom-to-selection': IconPageWidth, translate: IconTranslate,
}
const glyphs: Record<string,string> = {
  'forecast-sheet':'📈', 'chart-title':'🗎', 'chart-axis-cat':'↔', 'chart-axis-val':'↕', 'chart-legend':'▤', 'chart-labels':'🏷', 'chart-type-column':'📊', 'chart-type-bar':'▮▬', 'chart-type-line':'📈', 'chart-type-area':'◪', 'chart-type-pie':'◔', 'chart-type-doughnut':'◍', 'chart-select-data':'▦', 'chart-switch-row-col':'⇄', 'chart-format-pane':'🎨', 'chart-delete':'🗑',
  paste:'📋', cut:'✂', copy:'⧉', 'format-painter':'🖌', 'rotate:vertical':'↕',
  'clear-all':'⌫', 'insert-cells':'⊞', 'delete-cells':'⊟', 'row-height-open':'↕', 'col-width-open':'↔',
  'cf-open':'🎨', 'goto-open':'⌖', 'sort-custom-open':'⇅', 'filter-toggle':'▽', 'filter-clear':'⊘', 'filter-reapply':'⟳', 'filter-advanced':'▽',
  'sort:asc':'↑', 'sort:desc':'↓', 'insert-picture':'🖼', 'insert-shape':'◇', 'insert-icons':'✦', 'insert-screenshot':'🖼', 'insert-checkbox':'☑',
  'insert-chart:bar':'▮▬', 'insert-chart:line':'📈', 'insert-chart:area':'◪', 'insert-chart:pie':'◔', 'insert-chart:scatter':'∴', 'insert-chart:radar':'✳', 'insert-chart:doughnut':'◍', 'insert-chart:combo':'𝄜', 'recommended-charts-open':'📊',
  'sparkline:edit':'📈', 'sparkline:line':'📈', 'sparkline:column':'▮▬', 'sparkline:stacked':'▮▬', 'sparkline:delete':'🗑',
  'slicer-open':'▽', 'timeline-open':'🕘', 'link-open':'🔗', 'note-open':'🗨', 'note-delete':'🗑', 'note-prev':'←', 'note-next':'→', 'note-show-toggle':'🗨',
  'theme-effects':'✦', background:'🖼', 'print-scale-open':'⤢', 'toggle-gridlines':'▦', 'print-gridlines':'▦', 'toggle-headings':'▤', 'print-headings':'▤',
  'name-manager-open':'🏷', 'define-name':'🏷', 'trace-precedents':'⇠', 'trace-dependents':'⇢', 'remove-arrows':'✕', 'toggle-show-formulas':'∑', 'error-checking':'⚠', 'watch-window':'👓', 'external-links-panel':'🔗', 'calculate-now':'🧮', 'calculate-sheet':'🧮',
  'refresh-all':'⟳', 'merge-workbooks':'⧉', 'remove-duplicates-open':'⊘', 'dv-open':'✓', 'flash-fill':'⚡', 'data-table-open':'▦', 'goal-seek-open':'⌖', 'consolidate-open':'⇶', 'subtotal-open':'∑',
  'sheet-protect':'🔒', 'workbook-protect':'🔐', 'allow-edit-ranges-open':'🔐', 'freeze-panes':'❄',
  'normal-view':'▦', 'toggle-page-break-preview':'┆', 'toggle-cross-highlight':'⊡', 'toggle-formula-bar':'∑', 'toggle-right-to-left':'⇄', 'workbook-statistics':'🗠',
  'new-window':'🗔', 'arrange-all':'◫', 'split-window':'◫', 'hide-window':'⬚', 'switch-window':'🗔',
}
const fallback: Record<string, Parameters<typeof lucideElement>[0]> = {
  bold: Bold, italic: Italic, underline: Underline, 'underline:double': Underline, strike: Strikethrough,
  'format:0%': Percent, 'format:0.00': Hash, 'format:#,##0.00': Hash,
  'decimal-inc': Baseline, 'decimal-dec': Baseline, 'valign:middle': AlignVerticalSpaceAround,
}
export function workbookCommandIcon(command: string, existingGlyph?: string): string | undefined {
  const component = source[command]
  if (component) return renderToStaticMarkup(createElement(component, {size:18}))
  const glyph = glyphs[command] ?? (command.startsWith('autofn:') || command.startsWith('insert-function-open') ? '∑' : command.startsWith('text-to-columns:') ? '⇶' : command.startsWith('outline-') ? '▤' : existingGlyph)
  if (glyph && RIBBON_GLYPH_ICONS[glyph]) return renderToStaticMarkup(RIBBON_GLYPH_ICONS[glyph])
  const icon = fallback[command]
  return icon ? lucideElement(icon,{width:18,height:18,'stroke-width':1.5,'aria-hidden':'true'}).outerHTML : undefined
}

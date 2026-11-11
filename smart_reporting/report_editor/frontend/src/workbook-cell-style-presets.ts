// 固定源 GenOffice f8c17004 app-constants.ts:232 / ribbon-actions.ts:1345；Apache-2.0。
import { BorderStyleTypes, BorderType } from '@univerjs/core'
import type { FUniver } from '@univerjs/core/lib/facade'
import '@univerjs/sheets/facade'

interface CellStylePatch {
  bold?: boolean
  fontSize?: number
  fontColor?: string
  fillColor?: string
  border?: { type: 'all' | 'top' | 'bottom'; color: string }
}

export const CELL_STYLE_PRESETS: Readonly<Record<string, readonly CellStylePatch[]>> = {
  good: [{ fillColor: '#C6EFCE', fontColor: '#006100' }],
  bad: [{ fillColor: '#FFC7CE', fontColor: '#9C0006' }],
  neutral: [{ fillColor: '#FFEB9C', fontColor: '#9C6500' }],
  input: [
    { fillColor: '#FFCC99', fontColor: '#3F3F76', border: { type: 'all', color: '#7F7F7F' } },
  ],
  output: [
    {
      fillColor: '#F2F2F2',
      fontColor: '#3F3F3F',
      bold: true,
      border: { type: 'all', color: '#3F3F3F' },
    },
  ],
  calculation: [
    {
      fillColor: '#F2F2F2',
      fontColor: '#FA7D00',
      bold: true,
      border: { type: 'all', color: '#7F7F7F' },
    },
  ],
  'warning-text': [{ fontColor: '#FF0000' }],
  title: [{ bold: true, fontSize: 18, fontColor: '#44546A' }],
  'heading-1': [
    {
      bold: true,
      fontSize: 15,
      fontColor: '#44546A',
      border: { type: 'bottom', color: '#4472C4' },
    },
  ],
  'heading-2': [
    {
      bold: true,
      fontSize: 13,
      fontColor: '#44546A',
      border: { type: 'bottom', color: '#8EA9DB' },
    },
  ],
  // Excel's Total is thin-top + double-bottom; the double edge is not in the
  // border command set, so the top rule alone approximates it.
  total: [{ bold: true, border: { type: 'top', color: '#4472C4' } }],
  'accent1-20': [{ fillColor: '#DDEBF7' }],
  'accent1-40': [{ fillColor: '#BDD7EE' }],
  accent1: [{ fillColor: '#4472C4', fontColor: '#FFFFFF' }],
}

export function applyWorkbookCellStyle(runtime: { univerAPI: FUniver }, preset: string): boolean {
  if (!Object.hasOwn(CELL_STYLE_PRESETS, preset)) return false
  const patches = CELL_STYLE_PRESETS[preset]
  const range = runtime.univerAPI.getActiveWorkbook()?.getActiveRange()
  if (!patches || !range) return false
  for (const patch of patches) {
    // 保持源 applyFormatPatchToRange 的属性顺序；不清除未指定属性。
    if (patch.bold !== undefined) range.setFontWeight(patch.bold ? 'bold' : null)
    if (patch.fontSize !== undefined) range.setFontSize(patch.fontSize)
    if (patch.fontColor !== undefined) range.setFontColor(patch.fontColor)
    if (patch.fillColor !== undefined) range.setBackground(patch.fillColor)
    if (patch.border) range.setBorder({ all: BorderType.ALL, top: BorderType.TOP, bottom: BorderType.BOTTOM }[patch.border.type], BorderStyleTypes.THIN, patch.border.color)
  }
  return true
}

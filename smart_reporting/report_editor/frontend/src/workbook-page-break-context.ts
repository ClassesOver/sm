import { shiftFormulaText, shiftPageBreakIndexes, type ShiftSpec } from '@sheets-web/xlsx-engine/structural'
import { PRINT_MARGIN_PRESETS, type SheetPrintSetup, type SheetPrintHeaderFooter } from './workbook-print'

type Patch = Record<string, unknown>
interface Capture { value: unknown; operations: readonly ShiftSpec[] }
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

/** 每个字段保留原始capture；Undo删除后可恢复，绝不原地破坏被删坐标。 */
export function createPageSetupJournal(operations: (sheetId: string) => readonly ShiftSpec[]) {
  const sheets = new Map<string, Map<string, Capture>>()
  const get = (sheetId: string): Patch | undefined => {
    const captures = sheets.get(sheetId)
    if (!captures) return undefined
    const current = operations(sheetId), patch: Patch = {}
    for (const [key, capture] of captures) {
      let prefix = 0
      while (prefix < current.length && prefix < capture.operations.length && same(current[prefix], capture.operations[prefix])) prefix++
      const transforms = [
        ...capture.operations.slice(prefix).reverse().map(spec => ({ ...spec, delta: -spec.delta })),
        ...current.slice(prefix),
      ]
      let value = capture.value
      for (const spec of transforms) {
        if ((key === 'rowBreaks' && spec.axis === 'row' || key === 'colBreaks' && spec.axis === 'column') && !spec.band) value = shiftPageBreakIndexes(value as number[], spec)
        if ((key === 'printArea' || key === 'printTitles') && typeof value === 'string') value = shiftFormulaText(value, spec, true, '')
      }
      patch[key] = value
    }
    return patch
  }
  return {
    get,
    set(sheetId: string, patch: Patch, changedKeys?: readonly string[]) {
      const previous = get(sheetId) ?? {}, captures = sheets.get(sheetId) ?? new Map<string, Capture>()
      for (const [key, value] of Object.entries(patch)) {
        if (same(previous[key], value) && !changedKeys?.includes(key)) continue
        captures.set(key, { value: structuredClone(value), operations: structuredClone(operations(sheetId)) })
      }
      sheets.set(sheetId, captures)
    },
    clear() { sheets.clear() },
  }
}

interface FilePageSetup {
  pageSetup?: { orientation?: 'portrait' | 'landscape'; paperSize?: number; scale?: number; fitToPage?: boolean; fitToWidth?: number; fitToHeight?: number } | undefined
  margins?: { left: number; right: number; top: number; bottom: number; header?: number; footer?: number } | undefined
  headerFooter?: SheetPrintHeaderFooter | undefined
  printGridlines?: boolean | undefined
  printHeadings?: boolean | undefined
  printArea?: string | undefined
  printTitles?: string | undefined
  rowBreaks?: readonly number[] | undefined
  colBreaks?: readonly number[] | undefined
}
/** 与现有File打印相同字段，补足patch.scale；输入file必须是结构重放后的同epoch模型。 */
export function pageBreakPreviewSetup(file: FilePageSetup | undefined, patch: Patch): SheetPrintSetup {
  const before = file?.pageSetup
  const margins = patch.margins as keyof typeof PRINT_MARGIN_PRESETS | undefined
  return {
    orientation: patch.orientation as 'portrait' | 'landscape' ?? before?.orientation ?? 'portrait',
    headerFooter: file?.headerFooter,
    paperSize: patch.paperSize as number ?? before?.paperSize ?? 9,
    scale: patch.scale as number ?? before?.scale ?? 100,
    fitToPage: patch.fitToPage as boolean ?? before?.fitToPage ?? false,
    fitToWidth: patch.fitToWidth as number ?? (before?.fitToPage ? before.fitToWidth ?? 1 : 0),
    fitToHeight: patch.fitToHeight as number ?? (before?.fitToPage ? before.fitToHeight ?? 1 : 0),
    margins: margins && margins in PRINT_MARGIN_PRESETS ? PRINT_MARGIN_PRESETS[margins] : file?.margins ?? PRINT_MARGIN_PRESETS.normal,
    printGridlines: patch.printGridlines as boolean ?? file?.printGridlines ?? false,
    printHeadings: patch.printHeadings as boolean ?? file?.printHeadings ?? false,
    printArea: patch.printArea === undefined ? file?.printArea ?? null : patch.printArea as string | null,
    printTitles: patch.printTitles === undefined ? file?.printTitles ?? null : patch.printTitles as string | null,
    rowBreaks: patch.rowBreaks as number[] ?? file?.rowBreaks ?? [],
    colBreaks: patch.colBreaks as number[] ?? file?.colBreaks ?? [],
  }
}

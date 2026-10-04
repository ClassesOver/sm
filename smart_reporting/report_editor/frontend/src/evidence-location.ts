import { Plugin, PluginKey, TextSelection, type EditorState } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'
import type { TraceTableCellLocation } from './api'
import { findProtocolMarkers } from './protocol'

// 正文中的图片地址可能被手工改成非法 URL；单张解析失败只视为不匹配，不能中断整次定位。
function resolveUrl(value: string, baseUrl: string): string | null {
  try {
    return new URL(value, baseUrl).href
  } catch {
    return null
  }
}

export function findEvidenceChartImage(root: HTMLElement, source: string, baseUrl: string, caption = false): HTMLElement | null {
  const expected = resolveUrl(source, baseUrl)
  if (expected === null) return null
  const images = [...root.querySelectorAll<HTMLImageElement>('img')].filter(image => {
    const value = image.getAttribute('src')
    return value !== null && resolveUrl(value, baseUrl) === expected &&
      !image.closest('.drag-preview')
  })
  if (images.length !== 1) return null
  const block = images[0].closest<HTMLElement>('.milkdown-image-block, p') ?? images[0]
  if (!caption) return block
  const next = block.nextElementSibling
  return next?.matches('p') && /^(图表|图注)[:：]/.test(next.textContent?.trim() ?? '')
    ? next as HTMLElement : null
}

export function findEvidenceTableCell(root: HTMLElement, tableId: string, location: TraceTableCellLocation): HTMLElement | null {
  const markers = [...root.querySelectorAll<HTMLElement>('.report-table-marker')].filter(marker =>
    findProtocolMarkers(marker.textContent ?? '').some(value => value.kind === 'table' && value.value === tableId))
  if (markers.length !== 1 || !Number.isInteger(location.rowIndex) || location.rowIndex < 0 ||
      !Number.isInteger(location.columnIndex) || location.columnIndex < 1) return null
  const block = markers[0].closest('p')
  const next = block?.nextElementSibling
  const tables = next?.matches('table') ? [next as HTMLTableElement]
    : [...next?.querySelectorAll<HTMLTableElement>('table') ?? []]
        .filter(table => !table.closest('.drag-preview, [contenteditable="false"]'))
  if (tables.length !== 1) return null
  const table = tables[0]
  const header = table.rows[0]
  const row = table.rows[location.rowIndex + 1]
  const cell = row?.cells[location.columnIndex]
  if (header?.cells[location.columnIndex]?.textContent?.trim() !== location.columnKey ||
      row?.cells[0]?.textContent?.trim() !== location.rowLabel ||
      cell?.textContent?.trim() !== location.text) return null
  return cell.querySelector<HTMLElement>('p') ?? cell
}

export const evidenceLocationKey = new PluginKey<DecorationSet>('SMART_REPORT_EVIDENCE_LOCATION')

export function createEvidenceLocationPlugin(): Plugin<DecorationSet> {
  return new Plugin<DecorationSet>({
    key: evidenceLocationKey,
    state: {
      init: () => DecorationSet.empty,
      apply: (transaction, previous) => {
        const range = transaction.getMeta(evidenceLocationKey) as { from: number; to: number } | null | undefined
        if (range === null) return DecorationSet.empty
        if (range) return DecorationSet.create(transaction.doc, [
          Decoration.node(range.from, range.to, { class: 'report-located-subject' }),
        ])
        return previous.map(transaction.mapping, transaction.doc)
      },
    },
    props: { decorations: state => evidenceLocationKey.getState(state) ?? DecorationSet.empty },
  })
}

export const evidenceLocationPlugin = $prose(() => createEvidenceLocationPlugin())

export function evidenceLocationTransaction(state: EditorState, position: number) {
  const resolved = state.doc.resolve(position)
  const selection = TextSelection.near(resolved)
  const from = resolved.depth ? resolved.before() : position
  const node = state.doc.nodeAt(from)
  const transaction = state.tr.setSelection(selection).setMeta('addToHistory', false)
  if (node) transaction.setMeta(evidenceLocationKey, { from, to: from + node.nodeSize })
  return transaction
}

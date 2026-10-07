import { Plugin, PluginKey } from '@milkdown/kit/prose/state'
import { Decoration, DecorationSet, type EditorView } from '@milkdown/kit/prose/view'
import { $prose } from '@milkdown/kit/utils'
import type { TraceSources, TraceValidation } from './api'
import { findEvidenceChartImage, findEvidenceTableCell } from './evidence-location'

// 使用原生widget，不把显示标记写入正文。正文变更后等待新一轮精确位置校验。
const key = new PluginKey<DecorationSet>('SMART_REPORT_BODY_SOURCES')
export const bodySourceLinksPlugin = $prose(() => new Plugin<DecorationSet>({
  key,
  state: {
    init: () => DecorationSet.empty,
    apply: (tr, previous) => tr.getMeta(key) ?? (tr.docChanged ? DecorationSet.empty : previous),
  },
  props: { decorations: state => key.getState(state) ?? DecorationSet.empty },
}))

export function updateBodySourceLinks(view: EditorView, root: HTMLElement, sources: TraceSources, result: TraceValidation | null): void {
  const targets = new Map<HTMLElement, Array<{ kind: 'citation' | 'chart'; value: string; state: 'valid' | 'stale' }>>()
  const add = (target: HTMLElement | null, kind: 'citation' | 'chart', value: string, state: 'valid' | 'stale' = 'valid') => {
    if (!target) return
    const refs = targets.get(target) ?? []
    if (!refs.some(ref => ref.kind === kind && ref.value === value)) refs.push({ kind, value, state })
    targets.set(target, refs)
  }
  for (const subject of sources.subjects ?? []) {
    if (subject.subjectKind !== 'table_cell') continue
    const table = result?.tables?.find(item => item.tableId === subject.locator.tableId)
    const location = table?.locations?.find(item => item.rowKey === subject.locator.rowKey && item.columnKey === subject.locator.columnKey)
    if (location && subject.locator.tableId) add(findEvidenceTableCell(root, subject.locator.tableId, location), 'citation', subject.subjectId, location.status)
  }
  for (const chart of result?.charts ?? []) {
    if (chart.status === 'unbound' || !chart.locationSource) continue
    add(findEvidenceChartImage(root, chart.locationSource, document.baseURI), 'chart', chart.chartId, chart.status)
  }
  const decorations: Decoration[] = []
  for (const [target, references] of targets) {
    const position = view.posAtDOM(target, 0)
    const resolved = view.state.doc.resolve(position)
    // 图片块在节点后，表格段落在文本末尾，避免嵌入不可编辑的图片视图。
    const isChart = references[0].kind === 'chart'
    const end = isChart ? position + (view.state.doc.nodeAt(position)?.nodeSize ?? 0) : resolved.end()
    decorations.push(Decoration.widget(end, () => {
      const button = document.createElement('span')
      button.className = 'report-protocol-marker report-citation-marker report-object-source-marker'
      button.contentEditable = 'false'
      button.setAttribute('role', 'button')
      button.tabIndex = 0
      button.dataset.markerKind = references[0].kind
      button.dataset.markerValue = references[0].value
      button.dataset.markerReferences = JSON.stringify(references)
      button.dataset.markerCount = String(references.length)
      const stale = references.some(ref => ref.state === 'stale')
      button.dataset.markerState = stale ? 'stale' : 'valid'
      const title = isChart ? '查看图表来源' : `查看数据来源（${references.length}）`
      button.title = button.ariaLabel = stale ? `${title} · 内容已变化，登记来源待复核` : title
      if (references.length > 1) button.setAttribute('aria-haspopup', 'dialog')
      return button
    }, { side: -1 }))
  }
  view.dispatch(view.state.tr.setMeta(key, DecorationSet.create(view.state.doc, decorations)).setMeta('addToHistory', false))
}

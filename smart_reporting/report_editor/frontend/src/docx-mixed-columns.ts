import type { PageLayout } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/goto'
import type { EditorView } from '@tiptap/pm/view'
import { withMeasuredPaginationSnapshot, slicePaginationSnapshot } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-snapshot'
import type { CurrentDocxPaginationInput } from './docx-measure-current-pagination'
import { columnLayoutSpecs, sectionWidthSpecs, newWidthPassState, widthPassGate, wrapWidthSig, paperWidthPx, pageLeftPx, mirrorMarginSpecs, type WidthPassState } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-sections'
import { setColumnLayout, type ColumnBlockSpec } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/column-layout'
import { LayoutBatch, setPageGaps, gapLedgerOf, pageBorderStyleOf, syncPageBorders, type PageGapSpec } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/pagination-gaps'
import { applyGapLedger, pagePaperEdges, effectiveTopPx, effectiveBottomPx } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination'
import { pageMargins } from './vendor/genoffice-docs/apps/docs/src/renderer/page-margins'
import { lineStartAnchor, nextLineAnchor, createLineRectsCache } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-lines'

const twipsToPx = (twips: number) => (twips / 1440) * 96

export function renderDocxCanvasPageBorders(wrap: HTMLElement, section: CurrentDocxPaginationInput['section'], zoomFactor: number, cuts?: PageLayout['cuts']) {
  const paperWidth = twipsToPx(section.pageWidth)
  syncPageBorders(wrap, pageBorderStyleOf(section), zoomFactor,
    { left: pageLeftPx(section, paperWidth), width: paperWidth }, cuts)
}

/** 源App 5395/5411/5441布局通道：列宽优先，位移相加；source widthPassGate负责窄宽循环钉住。 */
export function mergeDocxColumnSpecs(widths: ColumnBlockSpec[], columns: ColumnBlockSpec[]): ColumnBlockSpec[] {
  const merged = new Map<HTMLElement, ColumnBlockSpec>()
  for (const spec of [...widths, ...columns]) {
    const prev = merged.get(spec.el)
    merged.set(spec.el, prev ? { ...prev, ...spec, dx: prev.dx + spec.dx, dy: prev.dy + spec.dy } : spec)
  }
  return [...merged.values()]
}

/** 同一同步布局桥供正文、Preview、边缘目标使用；DOM变换从不作为下一次测量坐标。 */
export function layoutMixedDocxColumns(view: EditorView, input: CurrentDocxPaginationInput, history: WidthPassState = newWidthPassState()): { converged: boolean; passes: number; layout?: PageLayout } {
  const paperWidth = paperWidthPx(input.sections, input.section)
  let signature = ''
  let layout: PageLayout | undefined
  for (let pass = 0; pass < 8; pass++) {
    const natural = input.pm.classList.contains('measuring-natural')
    input.pm.classList.add('measuring-natural')
    let changed: boolean
    try { changed = withMeasuredPaginationSnapshot(input, measured => {
      const snapshot = slicePaginationSnapshot({ ...input, ...measured })
      const columns = input.colMode === 'mixed' ? columnLayoutSpecs(measured.blocks, snapshot.cuts, measured.live) : []
      const previousColumnSignature = history.sig
      const again = widthPassGate(history, columns)
      const columnShapeChanged = previousColumnSignature !== history.sig
      const widths = sectionWidthSpecs(measured.blocks, measured.live, snapshot.geoms, paperWidth)
      const mirrors = input.mirrorMargins ? mirrorMarginSpecs(measured.blocks, snapshot.cuts, measured.live, input.section, snapshot.cuts.map(cut => cut.pageNo)) : []
      const specs = mergeDocxColumnSpecs(mergeDocxColumnSpecs(widths, mirrors), columns), nextSignature = wrapWidthSig(specs)
      const batch = new LayoutBatch(view)
      const gaps: PageGapSpec[] = []
      const rects = createLineRectsCache()
      snapshot.cuts.slice(1).forEach((cut, index) => {
        const previous = snapshot.cuts[index], nextSec = measured.live[cut.section]?.settings ?? input.section
        const prevSec = measured.live[previous.section]?.settings ?? input.section
        const side = pageMargins(nextSec, cut.pageNo, input.mirrorMargins === true)
        const pad = Math.max(0, Math.round(previous.padPx)), pullUp = Math.max(0, previous.usedPx - previous.physUsedPx)
        const common = { page: index + 1, boundaryY: cut.start, pullUp,
          metrics: { marginTop: effectiveTopPx(nextSec, cut.hf.headerPx), marginBottom: effectiveBottomPx(prevSec, previous.hf.footerPx) + pad,
            marginLeft: side.left / 15, marginRight: side.right / 15,
            pageLeft: pageLeftPx(nextSec, paperWidth), pageWidth: nextSec.pageWidth / 15,
            bodyPad: pad, bodyMarginBottom: effectiveBottomPx(prevSec, previous.hf.footerPx) } }
        const lead = cut.lead
        if (lead.kind === 'block') {
          const el = measured.blocks[lead.block]?.el
          if (el) gaps.push({ ...common, el, suppressLeadMt: cut.leadDropsSpaceBefore, leadMtPx: cut.leadMtPx })
        } else if (lead.kind === 'tail') gaps.push({ ...common, pos: view.state.doc.content.size, kind: 'inline' })
        else {
          const block = measured.blocks[lead.block]
          if (!block?.el) return
          const anchor = lineStartAnchor(block.el, lead.lineOffset ?? 0, measured.factor, rects) ?? nextLineAnchor(block.el, lead.lineOffset ?? 0, measured.factor, rects)
          if (!anchor) return
          try {
            const pos = anchor.node instanceof Element ? anchor.node.parentNode ? view.posAtDOM(anchor.node.parentNode, Array.prototype.indexOf.call(anchor.node.parentNode.childNodes, anchor.node)) : -1 : view.posAtDOM(anchor.node, anchor.charOffset)
            if (pos >= 0) gaps.push({ ...common, pos, kind: lead.kind === 'cell' || lead.kind === 'row' ? 'cut' : 'inline' })
          } catch { /* 源DOM无可映射位置时保留分页事实，后续重排重新定位。 */ }
        }
      })
      if (!natural) input.pm.classList.remove('measuring-natural')
      setPageGaps(view, gaps, undefined, batch)
      setColumnLayout(view, specs, batch)
      batch.commit()
      applyGapLedger(snapshot.cuts, gapLedgerOf(gaps, []))
      const firstSection = measured.live[0]?.settings ?? input.section
      const wrap = (input.pm.closest('.page-wrap') as HTMLElement) ?? input.pm
      renderDocxCanvasPageBorders(wrap, firstSection, measured.factor, snapshot.cuts)
      const last = snapshot.cuts.at(-1)
      if (last) {
        const lastSec = measured.live[last.section]?.settings ?? input.section
        const lastBand = pagePaperEdges(snapshot.cuts, input.canvasTop).filter(edge => edge.gap.kind !== 'cut').at(-1)
        const paperTop = lastBand ? lastBand.gapBottom - effectiveTopPx(lastSec, last.hf.headerPx) : 0
        const paperHeight = paperTop + lastSec.pageHeight / 15
        view.dom.style.height = `${Math.round(paperHeight)}px`
        view.dom.style.minHeight = `${Math.round(paperHeight)}px`
      }
      layout = { blocks: measured.blocks, slices: snapshot.cuts, sections: measured.live, cuts: snapshot.cuts, geoms: snapshot.geoms, hfHeights: snapshot.hfHs, rowSplits: snapshot.rowSplits, carries: [] }
      const remeasure = again || columnShapeChanged || signature !== nextSignature
      signature = nextSignature
      return remeasure
    }) } finally { input.pm.classList.toggle('measuring-natural', natural) }
    if (!changed) return { converged: true, passes: pass + 1, layout }
  }
  return { converged: false, passes: 8, layout }
}

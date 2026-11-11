// 从固定源 PaginationPreview 的 sliceHere 机械抽取；预览与宿主边缘目标复用同一分页规则。
import type { HeaderFooter, HfImage, HfPartInfo, SectionInfo, SectionSettings } from '@genoffice/docx-engine'
import { effectiveHfRefs, sectionGeoms, effectiveTopPx, effectiveBottomPx, singleVariantGeomOf, pageHfStrips, sliceWithLineSplit, buildPageCuts, type BlockBox, type BlockMetaOf, type HfSet, type HfVariant, type PageCut, type SectionGeom, type SectionHfHeights, type RowSplitPatch, type SliceOutputs } from './pagination'
import { hfVariantHeightsPx, sectionHfHeights } from './hf-heights'
import { hfStripGeom } from './editor/hf-dom'
import { measureBlocks, liveSections, assignSections, appendEndnotesBlock, appendFloatSpillBlock, sectionVertical, type PageNoteItem } from './pagination'
import type { PlanOf } from './pagination-plan'
import { FOOTNOTE_SEPARATOR_H } from './line-metrics'

export interface PaginationSnapshotInput {
  section: SectionSettings
  sections: SectionInfo[]
  live: SectionInfo[]
  blocks: BlockBox[]
  flowH: number
  factor: number
  hf: HfSet
  hfParts: Record<string, HfPartInfo>
  colMode: 'none' | 'uniform' | 'mixed'
  colFlow: { cols: number; colWidthPx: number; gapPx: number } | null
  legacyBands?: boolean
  blockMetaOf?: BlockMetaOf
  resolveHf?: (sections: SectionInfo[], sectionIndex: number, kind: 'header' | 'footer', variant: HfVariant) => { value: HeaderFooter | null; images?: HfImage[]; owner?: number }
}

const twipsToPx = (twips: number) => (twips / 1440) * 96

export function slicePaginationSnapshot({ section, sections, live, blocks, flowH, factor, hf, hfParts, colMode, colFlow, legacyBands, blockMetaOf, resolveHf }: PaginationSnapshotInput): { cuts: PageCut[]; geoms: SectionGeom[]; hfHs: SectionHfHeights[]; rowSplits: RowSplitPatch[] } {
  const canvasContentW = twipsToPx(section.pageWidth - section.marginLeft - section.marginRight)
  const splitOut: SliceOutputs = { rowSplits: [], floatSplits: [] }
  if (live.length > 0) {
    // each section's header/footer variant heights → body push-down (matching the canvas)
    const refs = effectiveHfRefs(live)
    const partOf = (i: number, kind: 'header' | 'footer', variant: HfVariant) => {
      const rId = refs[i]?.[kind]?.[variant]
      return rId ? hfParts[rId] : undefined
    }
    const hfHs = sectionHfHeights(
      live,
      resolveHf
        ? (i, kind, variant) => resolveHf(live, i, kind, variant)
        : (i, kind, variant) => {
            const part = partOf(i, kind, variant)
            const value = part
              ? { text: part.text, pageNumber: part.hasPageNumber, paras: part.paras }
              : null
            if (variant !== 'default') return { value, images: part?.images }
            // the parsed set carries the last section's default strips
            const last = i === live.length - 1
            return {
              value: last ? (kind === 'header' ? hf.header : hf.footer) : value,
              images: part?.images?.length
                ? part.images
                : last
                  ? hf.images?.[kind]
                  : undefined,
            }
          },
      { titlePg: hf.titlePg, evenOddHf: hf.evenOddHf, legacyBands },
    )
    const geoms = sectionGeoms(live, hfHs, hf.evenOddHf)
    // when the canvas column layout is inactive, measure as full-width single flow; the geometry drops column flow to match
    if (colMode === 'none') for (const g of geoms) if (g.cols) g.cols = undefined
    const computed = sliceWithLineSplit(blocks, geoms, flowH, factor, blockMetaOf, splitOut)
    const cuts = buildPageCuts(blocks, computed, geoms, hfHs, {
      evenOddHf: hf.evenOddHf,
      titlePgOf:
        live.length > 1
          ? (si) => live[Math.min(si, live.length - 1)].titlePg
          : () => hf.titlePg,
      pageNumberFmtOf: (si) => live[Math.min(si, live.length - 1)]?.pageNumberFmt,
      floatSplits: splitOut.floatSplits,
    })
    return { cuts, geoms, hfHs, rowSplits: splitOut.rowSplits ?? [] }
  }
  const hfPx = hfVariantHeightsPx(
    (kind, variant) => {
      const strips = pageHfStrips(variant, undefined, hf)
      return kind === 'header'
        ? { value: strips.header, images: strips.headerImages }
        : { value: strips.footer, images: strips.footerImages }
    },
    () => canvasContentW,
    hfStripGeom(section, legacyBands),
    hf.titlePg,
    hf.evenOddHf,
  )
  const singleGeom: SectionGeom = {
    contentHeight:
      twipsToPx(section.pageHeight) -
      effectiveTopPx(section, hfPx.headerPx) -
      effectiveBottomPx(section, hfPx.footerPx),
    forceBreak: false,
    ...singleVariantGeomOf(section, hfPx),
    ...(sections[0]?.pageNumberStart !== undefined
      ? { pageNumberStart: sections[0].pageNumberStart }
      : {}),
    ...(colFlow ? { cols: colFlow.cols } : {}),
  }
  const computed = sliceWithLineSplit(
    blocks,
    [singleGeom],
    flowH,
    factor,
    blockMetaOf,
    splitOut,
  )
  const cuts = buildPageCuts(blocks, computed, [singleGeom], [hfPx], {
    evenOddHf: hf.evenOddHf,
    titlePgOf: () => hf.titlePg,
    pageNumberFmtOf: () => sections[0]?.pageNumberFmt,
    floatSplits: splitOut.floatSplits,
  })
  return { cuts, geoms: [singleGeom], hfHs: [hfPx], rowSplits: splitOut.rowSplits ?? [] }
}


export interface PaginationMeasurementInput {
  pm: HTMLElement
  section: SectionSettings
  sections: SectionInfo[]
  canvasTop: number
  colMode: 'none' | 'uniform' | 'mixed'
  blockPlans?: () => PlanOf | undefined
  delSectBreaks?: Set<number>
  endnoteItems?: PageNoteItem[]
  mirrorMargins?: boolean
}

/** 测量期间保持源Preview的zoom/列中和状态；消费者完成后总会恢复。 */
export function withMeasuredPaginationSnapshot<T>({ pm, section, sections, canvasTop, colMode, blockPlans, delSectBreaks, endnoteItems, mirrorMargins }: PaginationMeasurementInput, consume: (snapshot: {
  origin: number
  factor: number
  blocks: BlockBox[]
  floats: ReturnType<typeof measureBlocks>['floats']
  live: SectionInfo[]
  flowH: number
  endnotesTop: number | null
}) => T): T {
    // Measure at zoom 1: CSS zoom rounds every box to device pixels, so dividing
    // zoomed rects by the factor drifts from the zoom-1 clones the pages render
    // (a long table accumulates rows of error — repeated headers overprint the
    // first data row and page cuts land mid-row). Neutralizing the canvas zoom
    // for the snapshot makes measurement and clone layout share one geometry.
    const zoomHost = pm.closest<HTMLElement>('.doc-zoom')
    const savedZoom = zoomHost?.style.zoom ?? ''
    if (zoomHost) zoomHost.style.zoom = '1'
    const factor = 1
    // switch the columned canvas to the single-flow measuring state (uniform: CSS columns
    // off, width = column width; mixed: block translates off), matching engine column-flow
    // coordinates. vAlign documents carry the same visual translates on the canvas
    // (vAlignShiftSpecs) and the preview applies its own vOffset, so they must be
    // neutralized here too or the shifted rects double-apply.
    const measureNeutralize =
      mirrorMargins === true || colMode !== 'none' ||
      section.vAlign === 'center' ||
      section.vAlign === 'bottom' ||
      sections.some(
        (s) =>
          s.settings.pageWidth !== section.pageWidth || s.settings.marginLeft !== section.marginLeft || s.settings.marginRight !== section.marginRight ||
          s.settings.vAlign === 'center' ||
          s.settings.vAlign === 'bottom' ||
          sectionVertical(s.settings),
      )
    if (measureNeutralize) pm.classList.add('measuring-columns')
    try {
      const origin = pm.getBoundingClientRect().top + canvasTop * factor
      const { blocks, totalHeight, floats, sectBreaks } = measureBlocks(
        pm,
        origin,
        factor,
        blockPlans?.(),
      )
      const live = liveSections(sections, blocks, sectBreaks, delSectBreaks)
      if (live.length > 0) assignSections(blocks, live)
      const withEndnotes = appendEndnotesBlock(
        blocks,
        totalHeight,
        endnoteItems ?? [],
        FOOTNOTE_SEPARATOR_H,
      )
      // floating boxes below the flow end still need pages to land on; bottom-
      // margin overhang stays on the page (same allowance as the canvas)
      const lastSec = live.length > 0 ? live[live.length - 1].settings : section
      const flowWithFloats = appendFloatSpillBlock(
        blocks,
        withEndnotes?.totalHeight ?? totalHeight,
        floats,
        lastSec ? twipsToPx(lastSec.marginBottom) : 0,
      )
      const flowH = flowWithFloats ?? withEndnotes?.totalHeight ?? totalHeight
      return consume({ origin, factor, blocks, floats, live, flowH, endnotesTop: withEndnotes?.top ?? null })
    } finally {
      if (measureNeutralize) pm.classList.remove('measuring-columns')
      if (zoomHost) zoomHost.style.zoom = savedZoom
    }
}

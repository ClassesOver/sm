import type { SectionInfo, SectionSettings } from '@genoffice/docx-engine'
import { sectionBidi, sectionColGeom, sectionColumns, paperWidthPx, canvasContentTopPx, effectiveBottomPx } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-sections'
import { hfVariantOf, hfVariantReservedPx } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-hf'
import type { SectionHfHeights } from './vendor/genoffice-docs/apps/docs/src/renderer/pagination-types'

/** 与源 App 共用首页变体及页眉推下规则；测量坐标原点必须等于画布 padding-top。 */
export function applyDocxCanvasHf(pm: HTMLElement, sections: SectionInfo[], fallback: SectionSettings, heights: SectionHfHeights, evenOdd: boolean): number {
  const first = sections[0]
  const reserved = hfVariantReservedPx(heights, hfVariantOf(first?.titlePg, true, evenOdd, first?.pageNumberStart ?? 1))
  const top = canvasContentTopPx(sections, fallback, reserved.headerPx)
  pm.style.paddingTop = `${top}px`
  pm.style.paddingBottom = `${effectiveBottomPx(first?.settings ?? fallback, heights.footerPx)}px`
  return top
}

/** 固定源App.tsx:3897判定；mixed保留事实，尚未接通逐块布局前不能当uniform使用。 */
export function docxColumnFacts(sections: SectionInfo[], fallback: SectionSettings) {
  const section = sections[0]?.settings ?? fallback
  let sourceMode: 'none' | 'uniform' | 'mixed' = 'none'
  if (sections.some(sec => sectionColumns(sec) > 1)) {
    const first = sectionColGeom(sections[0])
    const uniform = !sections.some(sectionBidi)
      && !sections.some((sec, index) => index > 0 && (sec.startType === 'nextColumn' || sec.startType === 'continuous'))
      && sections.every(sec => { const g = sectionColGeom(sec); return g.cols === first.cols && g.cols > 1 && g.equalWidth
        && Math.abs(g.colWidthPx - first.colWidthPx) < .5 && Math.abs(g.gapPx - first.gapPx) < .5 })
    sourceMode = uniform ? 'uniform' : 'mixed'
  }
  const colMode = sourceMode
  const paperWidth = paperWidthPx(sections, fallback)
  const sectionWidths = sections.some(sec => sec.settings.pageWidth !== section.pageWidth || sec.settings.marginLeft !== section.marginLeft || sec.settings.marginRight !== section.marginRight)
  return { section, sourceMode, colMode, paperWidth, sectionWidths, colFlow: colMode === 'uniform' ? sectionColGeom(sections[0]) : null }
}

/** 源uniform CSS的宿主变量；测量class由既有shared measurement同步切换。 */
export function applyDocxCanvasColumns(pm: HTMLElement, facts: ReturnType<typeof docxColumnFacts>) {
  const {section, colFlow} = facts, px = (n: number) => n / 15
  Object.assign(pm.style, {width:`${facts.paperWidth}px`,minHeight:`${px(section.pageHeight)}px`,
    padding:`${px(section.marginTop)}px ${px(section.marginRight)}px ${px(section.marginBottom)}px ${px(section.marginLeft)}px`,boxSizing:'border-box'})
  pm.classList.toggle('native-uniform-columns', !!colFlow)
  pm.style.setProperty('--native-cols',String(colFlow?.cols ?? 1))
  pm.style.setProperty('--native-col-gap',`${colFlow?.gapPx ?? 0}px`)
  pm.style.setProperty('--native-col-measure-width',`${(colFlow?.colWidthPx ?? 0)+px(section.marginLeft+section.marginRight)}px`)
}

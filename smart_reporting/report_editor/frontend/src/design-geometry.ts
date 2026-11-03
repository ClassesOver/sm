import type { CoverBox, CoverRole, DocumentContext, ReportDesign } from './design-types'

export function clampCoverBox(box: CoverBox): CoverBox {
  const round = (value: number) => Math.round(value * 100) / 100
  const width = round(Math.min(210, Math.max(10, box.width)))
  const height = round(Math.min(297, Math.max(5, box.height)))
  return { ...box, width, height, x: round(Math.max(0, Math.min(210 - width, box.x))), y: round(Math.max(0, Math.min(297 - height, box.y))) }
}

export function coverText(design: ReportDesign, context: DocumentContext, role: CoverRole): string {
  const cover = design.cover
  if (cover[role].text !== null) return cover[role].text!
  if (role === 'title') return context.title
  if (role === 'period') return `分析期间：${context.periodLabel}`
  return [cover.showOrganization ? context.organizationName : '', cover.showGeneratedBy ? context.generatedByLabel : '', cover.showDate ? context.generatedDate : ''].filter(Boolean).join('\n')
}

export function applyCoverPreset(design: ReportDesign, preset: 'formal' | 'minimal'): ReportDesign {
  const next = structuredClone(design)
  next.cover.preset = preset
  for (const role of ['title', 'period', 'signature'] as const) {
    Object.assign(next.cover[role], { x: 25, width: 160, align: preset === 'formal' ? 'center' : 'left' })
  }
  Object.assign(next.cover.title, { y: preset === 'formal' ? 65 : 42, height: 65 })
  Object.assign(next.cover.period, { y: preset === 'formal' ? 140 : 122, height: 30 })
  Object.assign(next.cover.signature, { y: 217, height: 55 })
  return next
}

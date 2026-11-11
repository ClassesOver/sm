import type { OpenedPptx } from '@genoffice/pptx-engine'
import { parseTheme } from '../packages/pptx-engine/src/theme.ts'
import { chartColorSchemes } from './pptx-chart-design.ts'

/** 与固定源 deckAccents 一致，读取第一页继承链，失败使用同一默认色。 */
export function inspectChartColorSchemes(opened: OpenedPptx) {
  try {
    const slide = opened.deck.slides[0]
    if (!slide) return chartColorSchemes()
    const chain = opened.archive.resolveSlideChain(slide.path)
    const xml = chain.themePath ? opened.archive.readText(chain.themePath) : null
    const colors = xml ? parseTheme(xml).colors : undefined
    return chartColorSchemes(['accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6'].map(key => colors?.[key]).filter((color): color is string => !!color))
  } catch { return chartColorSchemes() }
}

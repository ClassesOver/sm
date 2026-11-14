import type { RenderSlide } from '@genoffice/pptx-render'
import { initialSequence, type SourceAnimation } from './slides-animation-sequence'
import { previewAnimationItems } from './slides-animation-preview-model'
import { SLIDE_TRANSITIONS } from './slides-transitions'
import type { SlidesShowOptions } from './slides-show'
import type { LinkTargetOp } from './vendor/genoffice/renderer/show-types'

type ModelSlide = { transition?: string; animations?: SourceAnimation[]; elements: Array<{ id: string; name: string; elementLink?: { kind: 'url'; url: string } | { kind: 'slide'; slideIndex: number } | { kind: 'action'; action: string } | null }> }

/** 两个现有只读接口读取同一完整NativeDraft；用实际输出模型的身份/顺序绑定渲染节点。 */
export function slidesShowSnapshot(slides: RenderSlide[], pages: ModelSlide[]): Pick<SlidesShowOptions, 'animations' | 'transitions' | 'shapeKeys' | 'links' | 'warnings'> {
  if (pages.length !== slides.length || pages.some(page => !Array.isArray(page.elements))) throw new Error('放映模型与渲染页面不一致')
  const warnings = new Set<string>()
  const animations = pages.map((page, index) => {
    const ids: string[] = []
    const collect = (nodes: RenderSlide['nodes']) => { for (const node of nodes) { if (!node.decoration) ids.push(node.sourceId); if (node.type === 'group') collect(node.children) } }
    collect(slides[index]!.nodes)
    const source = page.animations ?? [], preview = previewAnimationItems(initialSequence(source), source, ids, true)
    preview.warnings.forEach(message => warnings.add(message)); return preview.items.filter(item => {
      if (!item.effect.startsWith('media')) return true
      if (slides[index]!.nodes.some(node => node.type === 'picture' && node.media && node.sourceId === item.sourceId)) return true
      warnings.add('音视频动画对象不是当前快照中的媒体，本次跳过。'); return false
    })
  })
  const transitions = pages.map(page => {
    const kind = SLIDE_TRANSITIONS.find(kind => kind === page.transition)
    if (!kind && page.transition) warnings.add('当前接口未建模的来源转场保留在文件中，本次不模拟。')
    return kind ?? 'none'
  })
  const shapeKeys = pages.map(page => page.elements.map(element => ({ sourceId: element.id, spid: null, name: element.name })))
  if (transitions.includes('morph')) warnings.add('变形转场按对象名称配对，效果可能与 PowerPoint 有差异。')
  const actions = ['nextslide', 'previousslide', 'firstslide', 'lastslide', 'lastslideviewed', 'endshow']
  const links = pages.map(page => page.elements.flatMap(element => {
    const target = element.elementLink
    if (!target) return []
    let allowed = target.kind === 'slide' ? Number.isInteger(target.slideIndex) && target.slideIndex >= 0 && target.slideIndex < slides.length
      : target.kind === 'action' ? actions.includes(target.action) : false
    if (target.kind === 'url') { try { allowed = ['http:', 'https:', 'mailto:'].includes(new URL(target.url).protocol) && !/[\u0000-\u0020\u007f-\u009f\\]/.test(target.url) } catch {} }
    if (!allowed) { warnings.add('不支持或无效的来源链接不执行；文件中的链接保留。'); return [] }
    return [{ sourceId: element.id, target: target as LinkTargetOp }]
  }))
  warnings.add('屏幕录制、演讲者视图、自动换页和文字内链接尚未验收。')
  return { animations, transitions, shapeKeys, links, warnings: [...warnings] }
}

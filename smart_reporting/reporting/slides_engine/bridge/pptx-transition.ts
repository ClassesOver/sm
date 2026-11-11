/** Native transition adapter: change the visual effect, retain source metadata. */
import { patchSlideTransitionXml } from '../packages/pptx-engine/src/generate.ts'
import type { SlideTransitionKind } from '@genoffice/pptx-engine'
import { splitXmlChildren, xmlSegments } from '../../doc_engine/packages/docx-engine/src/generate.ts'

const effects = new Set(['p:fade', 'p:push', 'p:wipe', 'p:split', 'p:circle', 'p:cover', 'p:pull', 'p:dissolve', 'p:zoom', 'p:random', 'p159:morph'])
function fail(): never { throw new Error('pptx_transition_source_unsupported') }
function parts(xml: string, tag: string) {
  if (/<!--|<!\[CDATA\[|<\?/.test(xml)) fail()
  const open = new RegExp(`^<${tag}\\b(?:"[^"]*"|'[^']*'|[^'">])*>`).exec(xml)?.[0]
  if (!open) fail()
  const selfClosing = open.endsWith('/>')
  if (selfClosing ? open !== xml : !xml.endsWith(`</${tag}>`)) fail()
  const inner = selfClosing ? '' : xml.slice(open.length, -`</${tag}>`.length)
  const children = splitXmlChildren(inner)
  if (inner.replace(/\s/g, '') !== children.map(child => child.xml).join('').replace(/\s/g, '')) fail()
  return { open: open.replace(/\/>$/, '>'), children }
}
function transition(xml: string) {
  const parsed = parts(xml, 'p:transition')
  if (parsed.children.some(child => !effects.has(child.name) && !['p:sndAc', 'p:extLst'].includes(child.name))
    || parsed.children.filter(child => effects.has(child.name)).length > 1
    || ['p:sndAc', 'p:extLst'].some(name => parsed.children.filter(child => child.name === name).length > 1)) fail()
  return parsed
}
function sourceState(suffix: string) {
  if (/<(?!p:)[\w.]+:transition\b/.test(suffix)) fail()
  const segments = xmlSegments(suffix, 'p:transition', 0, suffix.length)
  const alternate = /<(?:[\w.]+:)?AlternateContent\b/.test(suffix)
  if (!segments.length) {
    if (alternate || /<p:transition\b/.test(suffix)) fail()
    return { segments, alternate: false }
  }
  for (const segment of segments) transition(suffix.slice(segment.start, segment.end))
  if (!alternate) { if (segments.length !== 1) fail(); return { segments, alternate: false } }
  // Retain only the pinned Morph compatibility shell, including its per-branch metadata.
  // Arbitrary Choice requirements/extra branches need their own compatibility contract.
  const wrappers = xmlSegments(suffix, 'mc:AlternateContent', 0, suffix.length)
  if (wrappers.length !== 1 || segments.length !== 2 || segments.some(segment => segment.start < wrappers[0]!.start || segment.end > wrappers[0]!.end)) fail()
  const wrapper = parts(suffix.slice(wrappers[0]!.start, wrappers[0]!.end), 'mc:AlternateContent')
  if (wrapper.children.length !== 2 || wrapper.children[0]!.name !== 'mc:Choice' || wrapper.children[1]!.name !== 'mc:Fallback') fail()
  const choice = parts(wrapper.children[0]!.xml, 'mc:Choice'), fallback = parts(wrapper.children[1]!.xml, 'mc:Fallback')
  if (!/\sRequires\s*=\s*(["'])p159\1/.test(choice.open) || !/\sxmlns:p159\s*=\s*(["'])http:\/\/schemas\.microsoft\.com\/office\/powerpoint\/2015\/main\1/.test(choice.open)) fail()
  if ([choice, fallback].some(branch => branch.children.length !== 1 || branch.children[0]!.name !== 'p:transition')) fail()
  return { segments, alternate: true }
}
function sourceKind(suffix: string, source: ReturnType<typeof sourceState>): SlideTransitionKind {
  const first = source.segments[0]
  if (!first) return 'none'
  const effect = transition(suffix.slice(first.start, first.end)).children.find(child => effects.has(child.name))?.name
  return !effect ? 'none' : effect === 'p159:morph' ? 'morph' : effect.slice(2) as SlideTransitionKind
}
export function transitionEditAvailability(suffix: string) {
  try { const source = sourceState(suffix); return { transitionEditSafe: true, transitionEditReason: null, transition: sourceKind(suffix, source) } }
  catch { return { transitionEditSafe: false, transitionEditReason: 'pptx_transition_source_unsupported' } }
}
function effectXml(kind: SlideTransitionKind, fallback = false): string {
  if (kind === 'none') return ''
  const generated = patchSlideTransitionXml('</p:cSld>', kind)
  const segments = xmlSegments(generated, 'p:transition', 0, generated.length)
  const segment = segments[kind === 'morph' && fallback ? 1 : 0]
  if (!segment) fail()
  return transition(generated.slice(segment.start, segment.end)).children.filter(child => effects.has(child.name)).map(child => child.xml).join('')
}
function changedContainer(original: string, effect: string) {
  const { open, children } = transition(original)
  return open + effect + children.filter(child => !effects.has(child.name)).map(child => child.xml).join('') + '</p:transition>'
}
export function patchTransitionPreservingMetadata(suffix: string, kind: SlideTransitionKind): string {
  const source = sourceState(suffix)
  if (!source.segments.length) return patchSlideTransitionXml(suffix, kind)
  if (sourceKind(suffix, source) === kind) return suffix
  if (kind === 'morph' && !source.alternate) {
    const original = source.segments[0]!
    let generated = patchSlideTransitionXml('</p:cSld>', kind).slice('</p:cSld>'.length)
    const segments = xmlSegments(generated, 'p:transition', 0, generated.length)
    for (let index = segments.length - 1; index >= 0; index--) {
      const segment = segments[index]!
      generated = generated.slice(0, segment.start) + changedContainer(suffix.slice(original.start, original.end), effectXml(kind, index === 1)) + generated.slice(segment.end)
    }
    return suffix.slice(0, original.start) + generated + suffix.slice(original.end)
  }
  let result = suffix
  for (let index = source.segments.length - 1; index >= 0; index--) {
    const segment = source.segments[index]!
    result = result.slice(0, segment.start) + changedContainer(suffix.slice(segment.start, segment.end), effectXml(kind, source.alternate && index === 1)) + result.slice(segment.end)
  }
  return result
}

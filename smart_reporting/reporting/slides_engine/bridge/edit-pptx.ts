import { readFile, writeFile } from 'node:fs/promises'
import { addPicture, applyThemeToArchive, elementSpid, getSlideAnimations, getSlideTransition, moveSlide, openPptx, remapDeckColors, savePptx, setSlideAnimations, setSlideTransition, type SlideAnimation, type SlideTransitionKind, type ThemeSpec } from '@genoffice/pptx-engine'
import { auditDeck } from '../packages/pipelines/src/slides/audit-deck.ts'

type TextEdit = {
  slideIndex: number
  elementId: string
  text?: string
  geometry?: { x: number; y: number; width: number; height: number }
}
type Input = {
  action: 'inspect' | 'edit'
  input: string
  output?: string
  edits?: TextEdit[]
  order?: number[]
  theme?: 'executive' | 'clinical' | 'modern'
  images?: {
    slideIndex: number
    bytesBase64: string
    extension: 'png' | 'jpg'
    geometry: { x: number; y: number; width: number; height: number }
    descr?: string
  }[]
  transitions?: { slideIndex: number; kind: SlideTransitionKind }[]
  animations?: { slideIndex: number; elementId: string; effect: SlideAnimation['effect']; trigger: SlideAnimation['trigger'] }[]
}

const themes: Record<NonNullable<Input['theme']>, ThemeSpec> = {
  executive: { name: 'Executive', colors: { dk1: '#183247', lt1: '#F4F6F8', dk2: '#566773', lt2: '#D5DEDF', accent1: '#147D75', accent2: '#307C8A', accent3: '#718B49', accent4: '#C45A3C', accent5: '#6C7180', accent6: '#8A6D3B', hlink: '#0563C1', folHlink: '#954F72' } },
  clinical: { name: 'Clinical', colors: { dk1: '#173B36', lt1: '#F5F8F7', dk2: '#5B706A', lt2: '#D9E5E1', accent1: '#287F70', accent2: '#4D8B78', accent3: '#6E9B88', accent4: '#B47A46', accent5: '#66818A', accent6: '#8E9B63', hlink: '#0563C1', folHlink: '#954F72' } },
  modern: { name: 'Modern', colors: { dk1: '#293846', lt1: '#F7F7F4', dk2: '#5F6B70', lt2: '#E1E3DF', accent1: '#C45A3C', accent2: '#3B8490', accent3: '#79864A', accent4: '#A66A87', accent5: '#4F6E87', accent6: '#AD8848', hlink: '#0563C1', folHlink: '#954F72' } },
}

const requestPath = process.argv[2]
if (!requestPath) throw new Error('input JSON path required')
const request = JSON.parse(await readFile(requestPath, 'utf8')) as Input
const opened = await openPptx(new Uint8Array(await readFile(request.input)))

const textOf = (element: (typeof opened.deck.slides)[number]['elements'][number]) => {
  if (element.type !== 'text' && element.type !== 'shape') return ''
  return (element.text?.paragraphs ?? []).map((paragraph) =>
    paragraph.runs.map((run) => run.text).join(''),
  ).join('\n')
}

if (request.action === 'inspect') {
  process.stdout.write(JSON.stringify({
    size: opened.deck.size,
    slides: opened.deck.slides.map((slide, slideIndex) => ({
      slideIndex,
      transition: getSlideTransition(slide),
      animations: getSlideAnimations(slide).map(({ spid, effect, trigger, durationMs, delayMs, presetXml, preset }) => ({
        spid,
        elementId: slide.elements.find((element) => elementSpid(element) === spid)?.id ?? '',
        effect,
        trigger,
        durationMs,
        delayMs,
        ...(presetXml ? { presetXml } : {}),
        ...(preset ? { preset } : {}),
      })),
      elements: slide.elements.map((element) => ({
        id: element.id,
        type: element.type,
        name: element.name ?? '',
        text: textOf(element),
        editable: element.type === 'text' || element.type === 'shape',
        geometry: {
          x: element.transform.offset.x / 9525,
          y: element.transform.offset.y / 9525,
          width: element.transform.offset.cx / 9525,
          height: element.transform.offset.cy / 9525,
        },
      })),
    })),
  }))
} else {
  if (request.theme && !Object.hasOwn(themes, request.theme)) throw new Error('theme_invalid')
  for (const edit of request.edits ?? []) {
    if (!Number.isInteger(edit.slideIndex) || edit.slideIndex < 0 || edit.slideIndex >= opened.deck.slides.length) {
      throw new Error('slide_index_invalid')
    }
    const element = opened.deck.slides[edit.slideIndex]!.elements.find((candidate) => candidate.id === edit.elementId)
    if (!element || (element.type !== 'text' && element.type !== 'shape')) throw new Error('element_not_editable')
    if (edit.text !== undefined) {
      if (!element.text?.paragraphs.length || !element.text.paragraphs[0]!.runs.length) throw new Error('element_text_missing')
      const runs = element.text.paragraphs[0]!.runs
      runs[0]!.text = edit.text
      for (const run of runs.slice(1)) run.text = ''
      element.dirty = true
    }
    if (edit.geometry) {
      const { x, y, width, height } = edit.geometry
      element.transform.offset = {
        x: Math.round(x * 9525),
        y: Math.round(y * 9525),
        cx: Math.round(width * 9525),
        cy: Math.round(height * 9525),
      }
      element.dirtyTransform = true
    }
  }
  for (const image of request.images ?? []) {
    if (!Number.isInteger(image.slideIndex) || image.slideIndex < 0 || image.slideIndex >= opened.deck.slides.length) {
      throw new Error('image_slide_index_invalid')
    }
    const slide = opened.deck.slides[image.slideIndex]!
    const content = Buffer.from(image.bytesBase64, 'base64')
    if (content.toString('base64') !== image.bytesBase64 || !['png', 'jpg'].includes(image.extension)) {
      throw new Error('image_asset_invalid')
    }
    const { x, y, width, height } = image.geometry
    const added = addPicture(opened, slide, {
      bytes: new Uint8Array(content),
      ext: image.extension,
      offset: { x: Math.round(x * 9525), y: Math.round(y * 9525), cx: Math.round(width * 9525), cy: Math.round(height * 9525) },
      name: 'AI 生成配图',
      descr: image.descr,
    })
    if (!added) throw new Error('image_format_unsupported')
  }
  for (const transition of request.transitions ?? []) {
    if (!Number.isInteger(transition.slideIndex) || transition.slideIndex < 0 || transition.slideIndex >= opened.deck.slides.length) {
      throw new Error('transition_slide_index_invalid')
    }
    setSlideTransition(opened.deck.slides[transition.slideIndex]!, transition.kind)
  }
  for (const animation of request.animations ?? []) {
    const slide = opened.deck.slides[animation.slideIndex]
    const element = slide?.elements.find((candidate) => candidate.id === animation.elementId)
    const spid = element ? elementSpid(element) : null
    if (!slide || spid === null || (element!.type !== 'text' && element!.type !== 'shape')) {
      throw new Error('animation_target_invalid')
    }
    const existing = getSlideAnimations(slide)
    if (existing.some((item) => item.spid === spid && item.effect === animation.effect)) continue
    setSlideAnimations(slide, [...existing, {
      spid,
      effect: animation.effect,
      trigger: animation.trigger,
      durationMs: 500,
      delayMs: 0,
    }])
  }
  if (request.order) {
    if (request.order.length !== opened.deck.slides.length || new Set(request.order).size !== request.order.length || request.order.some((n) => !Number.isInteger(n) || n < 0 || n >= request.order!.length)) {
      throw new Error('slide_order_invalid')
    }
    const originalPaths = [...opened.deck.slides]
    const desired = request.order.map((index) => originalPaths[index]!.path)
    for (let target = 0; target < desired.length; target++) {
      const current = opened.deck.slides.findIndex((slide) => slide.path === desired[target])
      if (current !== target) moveSlide(opened, current, target)
    }
  }
  if (request.theme) {
    const spec = themes[request.theme]
    applyThemeToArchive(opened, spec)
    remapDeckColors(opened, spec)
  }
  if (!request.output) throw new Error('output_path_required')
  const bytes = await savePptx(opened)
  const audit = await auditDeck(bytes)
  await writeFile(request.output, bytes)
  process.stdout.write(JSON.stringify({
    slideCount: opened.deck.slides.length,
    issues: audit.flatMap((page) => page.issues.map((message) => ({ page: page.slide + 1, message }))),
  }))
}

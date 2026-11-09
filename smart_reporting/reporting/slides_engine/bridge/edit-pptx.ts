import { patchTransitionPreservingMetadata, transitionEditAvailability } from './pptx-transition.ts'
import { XMLParser } from 'fast-xml-parser'
import { patchSlideTransitionXml } from '../packages/pptx-engine/src/generate.ts'
import { readFile, writeFile } from 'node:fs/promises'
import shapePresets from './shape-presets.json' with { type: 'json' }
import { addElement, addPicture, addTable, applyThemeToArchive, deleteElement, elementSpid, getSlideAnimations, getSlideTransition, deleteSlide, duplicateSlide, insertBlankSlide, insertSlideWithLayout, resetSlideLayout, listMasterParts, listSlideLayouts, moveSlide, openPptx, remapDeckColors, savePptx, setElementFont, setElementParagraphFormat, setSlideAnimations, setSlideBackground, setSlideLayout, setSlideSize, setSlideTransition, type SlideAnimation, type SlideTransitionKind, type ThemeSpec } from '@genoffice/pptx-engine'
import { applyEditParagraphs } from '../packages/pptx-ops/src/edit-text.ts'
import { auditDeck } from '../packages/pipelines/src/slides/audit-deck.ts'

type TextEdit = {
  slideIndex: number
  elementId: string
  text?: string
  geometry?: { x: number; y: number; width: number; height: number }
} & { fontSizePt?: number; fontFamily?: string; color?: string; bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean }
type Geometry = { x: number; y: number; width: number; height: number }
type TextBox = {
  slideIndex: number
  text: string
  geometry: Geometry
  fontSize?: number
  fontFamily?: string
  color?: string
  bold?: boolean
  rotation?: number
}
type Input = {
  action: 'inspect' | 'edit'
  input: string
  output?: string
  edits?: TextEdit[]
  order?: number[]
  /** 固定源 onAddSlide → addBlankSlide：每项新建一张空白页，沿用 layoutFrom 来源页的版式；新页索引为 来源页数 + k。 */
  newSlides?: ({ layoutFrom: number } | { duplicateOf: number } | { withLayout: string })[]
  /** 固定源 Insert ▸ Shapes（onPickShape）：预设形状，几何为 96dpi 像素；线条为 1pt 黑色连接符，其他为出厂填充色。 */
  shapes?: { slideIndex: number; kind: string; geometry: { x: number; y: number; width: number; height: number } }[]
  /** 固定源 Insert ▸ Table（insertTable + table-insert.ts）：行列数；位置按固定源规格由幻灯片尺寸计算。 */
  tables?: { slideIndex: number; rows: number; cols: number }[]
  /** 固定源 onResetLayout（resetSlideLayout）：占位符去掉显式位置，回到版式继承；最先执行，同批其他修改叠加其上。 */
  resetLayouts?: number[]
  /** 固定源缩略图删除（deleteSlide）：删除的来源页索引；同批不得再引用这些页。order 只列保留页。 */
  deletedSlides?: number[]
  theme?: 'executive' | 'clinical' | 'modern'
  slideSize?: { cx: number; cy: number }
  images?: {
    slideIndex: number
    bytesBase64: string
    extension: 'png' | 'jpg'
    geometry: { x: number; y: number; width: number; height: number }
    descr?: string
  }[]
  transitions?: { slideIndex: number; kind: SlideTransitionKind }[]
  animations?: {
    slideIndex: number
    elementId: string
    effect: SlideAnimation['effect']
    trigger: SlideAnimation['trigger']
    durationMs?: number
    delayMs?: number
    direction?: SlideAnimation['direction']
    append?: boolean
  }[]
  slideLayouts?: { slideIndex: number; layoutPath: string }[]
  backgrounds?: { slideIndex: number; color: string }[]
  textBoxes?: TextBox[]
  deletions?: { slideIndex: number; elementId: string }[]
  paragraphFormatting?: {
    slideIndex: number
    elementId: string
    bullet?: 'char' | 'number' | 'none'
    bulletChar?: string
    bulletFont?: string
    numType?: string
    startAt?: number
    bulletHangEmu?: number
    bulletSizePct?: number
    bulletColor?: string
    rtl?: boolean
    indentDelta?: 1 | -1
    align?: 'left' | 'center' | 'right' | 'justify'
    lineSpacingPct?: number
    spaceBeforePt?: number
    spaceAfterPt?: number
  }[]
}

const numberingTypes = ['arabicPeriod', 'arabicParenR', 'romanUcPeriod', 'alphaUcPeriod', 'alphaLcParenR', 'alphaLcPeriod', 'romanLcPeriod', 'circleNumDbPlain', 'ea1ChsPeriod']
const maxParagraphEmu = 51206400 // ECMA-376 ST_TextMargin/ST_TextIndent, 56 inches.
const colorPattern = /^#[0-9a-fA-F]{6}$/
const deletableTypes = new Set(['text', 'shape', 'picture'])
const validSlideIndex = (value: unknown, count: number): value is number =>
  Number.isInteger(value) && (value as number) >= 0 && (value as number) < count
const validGeometry = (value: Geometry | undefined) => !!value &&
  [value.x, value.y, value.width, value.height].every((item) => Number.isFinite(item) && item >= 0 && item <= 100000) &&
  value.width > 0 && value.height > 0

const themes: Record<NonNullable<Input['theme']>, ThemeSpec> = {
  executive: { name: 'Executive', colors: { dk1: '#183247', lt1: '#F4F6F8', dk2: '#566773', lt2: '#D5DEDF', accent1: '#147D75', accent2: '#307C8A', accent3: '#718B49', accent4: '#C45A3C', accent5: '#6C7180', accent6: '#8A6D3B', hlink: '#0563C1', folHlink: '#954F72' } },
  clinical: { name: 'Clinical', colors: { dk1: '#173B36', lt1: '#F5F8F7', dk2: '#5B706A', lt2: '#D9E5E1', accent1: '#287F70', accent2: '#4D8B78', accent3: '#6E9B88', accent4: '#B47A46', accent5: '#66818A', accent6: '#8E9B63', hlink: '#0563C1', folHlink: '#954F72' } },
  modern: { name: 'Modern', colors: { dk1: '#293846', lt1: '#F7F7F4', dk2: '#5F6B70', lt2: '#E1E3DF', accent1: '#C45A3C', accent2: '#3B8490', accent3: '#79864A', accent4: '#A66A87', accent5: '#4F6E87', accent6: '#AD8848', hlink: '#0563C1', folHlink: '#954F72' } },
}

const requestPath = process.argv[2]
if (!requestPath) throw new Error('input JSON path required')
const request = JSON.parse(await readFile(requestPath, 'utf8')) as Input
const opened = await openPptx(new Uint8Array(await readFile(request.input)))
const layouts = listSlideLayouts(opened.archive)

const textOf = (element: (typeof opened.deck.slides)[number]['elements'][number]) => {
  if (element.type !== 'text' && element.type !== 'shape') return ''
  return (element.text?.paragraphs ?? []).map((paragraph) =>
    paragraph.runs.map((run) => run.text).join(''),
  ).join('\n')
}

const transitionParser = new XMLParser({ preserveOrder: true, ignoreAttributes: false, processEntities: false })
function transitionApplyAllState(slide: (typeof opened.deck.slides)[number]) {
  const unsafe = { transitionApplyAllSafe: false, transitionApplyAllReason: 'pptx_transition_additional_settings' }
  try {
  const suffix = slide.bodySuffix
  if (/<(?:[\w.]+:)?AlternateContent\b/.test(suffix)) return unsafe
  if (/<(?!p:)[\w.]+:transition\b/.test(suffix)) return unsafe
  const blocks = suffix.match(/<p:transition\b[^>]*\/>|<p:transition\b[^>]*>[\s\S]*?<\/p:transition>/g) ?? []
  if (!blocks.length) return /<p:transition\b/.test(suffix) ? unsafe : { transitionApplyAllSafe: true, transitionApplyAllReason: null }
  // AlternateContent or repeated containers need a separate preservation contract.
  if (blocks.length !== 1 || /<!--|<!\[CDATA\[|<\?/.test(blocks[0]!)) return unsafe
  const parsed = transitionParser.parse(blocks[0]!)?.[0]
  const attributes = parsed?.[':@'] ?? {}
  if (Object.keys(attributes).some(key => key !== '@_advTm') || (attributes['@_advTm'] !== undefined && (!/^\d+$/.test(String(attributes['@_advTm'])) || !Number.isSafeInteger(Number(attributes['@_advTm'])) || Number(attributes['@_advTm']) > 4294967295))) return unsafe
  const effect = parsed?.['p:transition'] ?? []
  const kind = getSlideTransition(slide)
  if (kind === 'none') return effect.length ? unsafe : { transitionApplyAllSafe: true, transitionApplyAllReason: null }
  const canonical = patchSlideTransitionXml('</p:cSld>', kind).match(/<p:transition\b[^>]*>[\s\S]*?<\/p:transition>/)?.[0]
  const expected = canonical ? transitionParser.parse(canonical)?.[0]?.['p:transition'] : undefined
  if (effect.length !== 1 || !expected || expected.length !== 1) return unsafe
  const name = Object.keys(effect[0]).find(key => key !== ':@')
  const expectedName = Object.keys(expected[0]).find(key => key !== ':@')
  if (name !== expectedName || !name || effect[0][name]?.length) return unsafe
  const effectAttributes = effect[0][':@'] ?? {}
  // Only a generic kind or the pinned writer's default variant is modeled.
  if (Object.keys(effectAttributes).length && JSON.stringify(effectAttributes) !== JSON.stringify(expected[0][':@'] ?? {})) return unsafe
  return { transitionApplyAllSafe: true, transitionApplyAllReason: null }
  } catch { return unsafe }
}

if (request.action === 'inspect') {
  process.stdout.write(JSON.stringify({
    size: opened.deck.size,
    masterParts: listMasterParts(opened.archive),
    layouts,
    slides: opened.deck.slides.map((slide, slideIndex) => ({
      slideIndex,
      background: slide.background?.type === 'solid' ? slide.background.color : null,
      ...opened.archive.resolveSlideChain(slide.path),
      transition: getSlideTransition(slide),
      ...transitionApplyAllState(slide),
      ...transitionEditAvailability(slide.bodySuffix),
      animations: getSlideAnimations(slide).map(({ spid, effect, trigger, durationMs, delayMs, direction, presetXml, preset }) => ({
        spid,
        elementId: slide.elements.find((element) => elementSpid(element) === spid)?.id ?? '',
        effect,
        trigger,
        durationMs,
        delayMs,
        ...(direction ? { direction } : {}),
        ...(presetXml ? { presetXml } : {}),
        ...(preset ? { preset } : {}),
      })),
      elements: slide.elements.map((element) => ({
        id: element.id,
        type: element.type,
        name: element.name ?? '',
        text: textOf(element),
        ...(element.type === 'text' || element.type === 'shape' ? (() => {
          const paragraphs = element.text?.paragraphs ?? []
          const run = paragraphs[0]?.runs[0]
          return {
            paragraphLists: paragraphs.map((paragraph) => ({
              bulletKind: paragraph.bullet?.type ?? null,
              bulletChar: paragraph.bullet?.char ?? null,
              bulletFont: paragraph.bullet?.font ?? null,
              numType: paragraph.bullet?.numType ?? null,
              startAt: paragraph.bullet?.startAt ?? null,
              bulletSizePct: paragraph.bullet?.sizePct ?? null,
              bulletSizePt: paragraph.bullet?.sizePt ?? null,
              bulletColor: paragraph.bullet?.color ?? null,
              level: paragraph.level ?? null,
              rtl: paragraph.rtl ?? null,
              marLEmu: paragraph.marL ?? null,
              indentEmu: paragraph.indent ?? null,
              hasExplicitHangingIndent: Boolean(paragraph.pPrExplicit?.marL && paragraph.indent != null && paragraph.indent < 0),
            })),
            paragraphAlignments: paragraphs.map((paragraph) => paragraph.align ?? null),
            paragraphFormatting: paragraphs.map((paragraph) => ({
              align: paragraph.align ?? null,
              lineSpacingPct: paragraph.lineHeight ?? null,
              lineSpacingPt: paragraph.lineExact ?? null,
              spaceBeforePt: paragraph.spaceBefore ?? null,
              spaceAfterPt: paragraph.spaceAfter ?? null,
              spaceBeforePct: paragraph.spaceBeforePct ?? null,
              spaceAfterPct: paragraph.spaceAfterPct ?? null,
            })),
            ...(run ? { textStyle: {
            fontSizePt: run.fontSize ?? null,
            fontFamily: run.fontFamily ?? null,
            color: run.color ?? null,
            bold: run.bold ?? null,
            italic: run.italic ?? null,
            underline: run.underline ?? null,
            strike: run.strike ?? null,
            } } : {}),
          }
        })() : {}),
        editable: element.type === 'text' || element.type === 'shape',
        deletable: deletableTypes.has(element.type),
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
  // 页面引用在重排前固定；背景和新增文本框在主题之后写入，避免显式颜色被主题重映射。
  const originalSlides = [...opened.deck.slides]
  const slideCount = originalSlides.length
  // 新建页最先创建（副本因此复制已保存内容），逐个追加到末尾：来源页索引与新页编号（来源页数 + k）均不变；
  // 之后所有按索引的步骤只接受来源页，order（长度 = 来源页数 + 新页数）决定最终位置。
  const newSlideSource = (item: unknown) => item && typeof item === 'object' ? ('duplicateOf' in item ? (item as { duplicateOf: unknown }).duplicateOf : (item as { layoutFrom?: unknown }).layoutFrom) : undefined
  const newSlides = request.newSlides ?? []
  if (!Array.isArray(newSlides) || newSlides.length > 50) throw new Error('new_slides_invalid')
  for (const item of newSlides) {
    const keys = item && typeof item === 'object' ? Object.keys(item) : []
    if (keys.length === 1 && keys[0] === 'withLayout') {
      // 固定源 onAddSlideWithLayout：按所选版式生成占位符；插在末尾，来源页索引不变。
      const layoutPath = (item as { withLayout: unknown }).withLayout
      if (typeof layoutPath !== 'string' || !layouts.some(layout => layout.path === layoutPath)) throw new Error('new_slide_layout_invalid')
      if (!insertSlideWithLayout(opened, opened.deck.slides.length - 1, layoutPath)) throw new Error('new_slide_insert_failed')
      continue
    }
    const source = newSlideSource(item)
    if (keys.length !== 1 || !['layoutFrom', 'duplicateOf'].includes(keys[0]!) || !validSlideIndex(source, slideCount)) throw new Error('new_slide_source_invalid')
    const created = keys[0] === 'duplicateOf' ? duplicateSlide(opened, source) : insertBlankSlide(opened, source)
    if (!created) throw new Error('new_slide_insert_failed')
    const last = opened.deck.slides.length - 1
    if (source + 1 !== last) moveSlide(opened, source + 1, last)
  }
  const resetLayouts = request.resetLayouts ?? []
  if (!Array.isArray(resetLayouts) || new Set(resetLayouts).size !== resetLayouts.length || resetLayouts.some(index => !validSlideIndex(index, slideCount))) throw new Error('reset_layouts_invalid')
  for (const index of resetLayouts) {
    const reset = resetSlideLayout(opened, index)
    if (!reset) throw new Error('reset_layout_failed')
    originalSlides[index] = reset
  }
  // addTable 会重建页面模型，因此放在其他页面修改之前；几何同固定源 tableInsertSpec：宽 2/3 居中、顶部 10.5%、行高 29.2pt。
  const tables = request.tables ?? []
  if (!Array.isArray(tables) || tables.length > 100) throw new Error('tables_invalid')
  for (const table of tables) {
    if (!table || typeof table !== 'object' || Object.keys(table).some(key => !['slideIndex', 'rows', 'cols'].includes(key)) || !validSlideIndex(table.slideIndex, slideCount)
      || !Number.isInteger(table.rows) || !Number.isInteger(table.cols) || table.rows < 1 || table.cols < 1 || table.rows > 75 || table.cols > 75) throw new Error('table_invalid')
    const { cx, cy } = opened.deck.size, rowHeightEmu = Math.round(29.2 * 12700), width = Math.round(cx * 2 / 3)
    const added = addTable(opened, table.slideIndex, { rows: table.rows, cols: table.cols, offset: { x: Math.round((cx - width) / 2), y: Math.round(cy * 0.105), cx: width, cy: table.rows * rowHeightEmu }, rowHeightsEmu: Array(table.rows).fill(rowHeightEmu) })
    if (!added) throw new Error('table_insert_failed')
    originalSlides[table.slideIndex] = added.slide
  }
  if (request.paragraphFormatting !== undefined && (!Array.isArray(request.paragraphFormatting) || request.paragraphFormatting.length > 500)) {
    throw new Error('paragraph_format_invalid')
  }
  const paragraphFields = ['align', 'lineSpacingPct', 'spaceBeforePt', 'spaceAfterPt', 'bullet', 'bulletChar', 'bulletFont', 'numType', 'startAt', 'bulletHangEmu', 'bulletSizePct', 'bulletColor', 'rtl', 'indentDelta']
  for (const format of request.paragraphFormatting ?? []) {
    if (!format || typeof format !== 'object' || Array.isArray(format) ||
      Object.keys(format).some(key => !['slideIndex', 'elementId', ...paragraphFields].includes(key)) ||
      !paragraphFields.some(key => Object.hasOwn(format, key)) ||
      !validSlideIndex(format.slideIndex, slideCount) || typeof format.elementId !== 'string' || !format.elementId ||
      (Object.hasOwn(format, 'align') && !['left', 'center', 'right', 'justify'].includes(format.align!)) ||
      (Object.hasOwn(format, 'lineSpacingPct') && ![100, 115, 150, 200, 250, 300].includes(format.lineSpacingPct!)) ||
      (['spaceBeforePt', 'spaceAfterPt'] as const).some(key => Object.hasOwn(format, key) &&
        (typeof format[key] !== 'number' || !Number.isFinite(format[key]) || format[key]! < 0 || format[key]! > 500)) ||
      (Object.hasOwn(format, 'bullet') && !['char', 'number', 'none'].includes(format.bullet!)) ||
      (Object.hasOwn(format, 'bulletChar') && (typeof format.bulletChar !== 'string' || [...format.bulletChar].length !== 1 || /[\u0000-\u001f\u007f-\u009f\ud800-\udfff\ufffe\uffff]/u.test(format.bulletChar))) ||
      (Object.hasOwn(format, 'bulletFont') && (typeof format.bulletFont !== 'string' || !format.bulletFont.trim() || [...format.bulletFont].length > 200 || /[\u0000-\u001f\u007f-\u009f\ud800-\udfff\ufffe\uffff]/u.test(format.bulletFont))) ||
      (Object.hasOwn(format, 'numType') && !numberingTypes.includes(format.numType!)) ||
      (Object.hasOwn(format, 'startAt') && (!Number.isInteger(format.startAt) || format.startAt! < 1 || format.startAt! > 32767)) ||
      (Object.hasOwn(format, 'bulletHangEmu') && (!Number.isInteger(format.bulletHangEmu) || format.bulletHangEmu! < 0 || format.bulletHangEmu! > maxParagraphEmu)) ||
      (Object.hasOwn(format, 'bulletSizePct') && ![75, 90, 100, 125, 150].includes(format.bulletSizePct!)) ||
      (Object.hasOwn(format, 'bulletColor') && (typeof format.bulletColor !== 'string' || !colorPattern.test(format.bulletColor))) ||
      (Object.hasOwn(format, 'rtl') && typeof format.rtl !== 'boolean') ||
      (Object.hasOwn(format, 'indentDelta') && ![-1, 1].includes(format.indentDelta!)) ||
      (format.bullet === 'none' && ['bulletChar', 'bulletFont', 'numType', 'startAt', 'bulletHangEmu', 'bulletSizePct', 'bulletColor'].some(key => Object.hasOwn(format, key))) ||
      (format.bullet === 'char' && ['numType', 'startAt'].some(key => Object.hasOwn(format, key))) ||
      (['bulletChar', 'bulletFont'].some(key => Object.hasOwn(format, key)) && format.bullet !== 'char')) {
      throw new Error('paragraph_format_invalid')
    }
  }
  const deletedSlides = request.deletedSlides ?? []
  if (!Array.isArray(deletedSlides) || new Set(deletedSlides).size !== deletedSlides.length || deletedSlides.some(index => !validSlideIndex(index, slideCount))) throw new Error('deleted_slides_invalid')
  if (deletedSlides.length && !request.order) throw new Error('deleted_slides_require_order')
  const removedSlides = new Set(deletedSlides)
  const slideRecords: ({ slideIndex: number }[] | undefined)[] = [request.edits, request.images, request.transitions, request.animations, request.slideLayouts, request.backgrounds, request.textBoxes, request.deletions, request.paragraphFormatting, request.shapes, request.tables, (request.resetLayouts ?? []).map(slideIndex => ({ slideIndex }))]
  if (slideRecords.some(records => (records ?? []).some(record => removedSlides.has(record.slideIndex))) || (request.newSlides ?? []).some(item => removedSlides.has(newSlideSource(item) as number))) throw new Error('deleted_slide_has_pending_edits')
  const deletions = request.deletions ?? []
  const deleted = new Set<string>()
  for (const deletion of deletions) {
    if (!validSlideIndex(deletion.slideIndex, slideCount)) throw new Error('delete_slide_index_invalid')
    const element = originalSlides[deletion.slideIndex]!.elements.find((candidate) => candidate.id === deletion.elementId)
    if (!element || !deletableTypes.has(element.type)) throw new Error('delete_target_invalid')
    const key = `${deletion.slideIndex}:${deletion.elementId}`
    if (deleted.has(key)) throw new Error('delete_target_duplicated')
    deleted.add(key)
  }
  const touchesDeleted = (slideIndex: number, elementId: string) => deleted.has(`${slideIndex}:${elementId}`)
  if ((request.edits ?? []).some((edit) => touchesDeleted(edit.slideIndex, edit.elementId)) ||
    (request.animations ?? []).some((item) => touchesDeleted(item.slideIndex, item.elementId)) ||
    (request.paragraphFormatting ?? []).some((item) => touchesDeleted(item.slideIndex, item.elementId))) {
    throw new Error('delete_target_has_pending_edits')
  }
  for (const background of request.backgrounds ?? []) {
    if (!validSlideIndex(background.slideIndex, slideCount)) throw new Error('background_slide_index_invalid')
    if (typeof background.color !== 'string' || !colorPattern.test(background.color)) throw new Error('background_color_invalid')
  }
  if ((request.shapes ?? []).length > 500) throw new Error('shapes_invalid')
  for (const shape of request.shapes ?? []) {
    if (!shape || typeof shape !== 'object' || Object.keys(shape).some(key => !['slideIndex', 'kind', 'geometry'].includes(key)) || !validSlideIndex(shape.slideIndex, slideCount) || typeof shape.kind !== 'string' || !shapePresets.presets.includes(shape.kind) || !validGeometry(shape.geometry)) throw new Error('shape_invalid')
  }
  for (const box of request.textBoxes ?? []) {
    if (!validSlideIndex(box.slideIndex, slideCount)) throw new Error('textbox_slide_index_invalid')
    if (typeof box.text !== 'string' || box.text.length > 20000) throw new Error('textbox_text_invalid')
    if (!validGeometry(box.geometry)) throw new Error('textbox_geometry_invalid')
    if (box.fontSize !== undefined && (!Number.isFinite(box.fontSize) || box.fontSize < 1 || box.fontSize > 400)) throw new Error('textbox_font_invalid')
    if (box.fontFamily !== undefined && (typeof box.fontFamily !== 'string' || !box.fontFamily.trim() || box.fontFamily.length > 200)) throw new Error('textbox_font_invalid')
    if (box.color !== undefined && (typeof box.color !== 'string' || !colorPattern.test(box.color))) throw new Error('textbox_color_invalid')
    if (box.bold !== undefined && typeof box.bold !== 'boolean') throw new Error('textbox_font_invalid')
    if (box.rotation !== undefined && (!Number.isFinite(box.rotation) || Math.abs(box.rotation) > 360)) throw new Error('textbox_rotation_invalid')
  }
  for (const edit of request.edits ?? []) {
    if (Object.keys(edit).some(key => !['slideIndex', 'elementId', 'text', 'geometry', 'fontSizePt', 'fontFamily', 'color', 'bold', 'italic', 'underline', 'strike'].includes(key))) {
      throw new Error('element_edit_invalid')
    }
    if (edit.fontSizePt !== undefined && (!Number.isFinite(edit.fontSizePt) || edit.fontSizePt < 1 || edit.fontSizePt > 400)) throw new Error('text_format_font_invalid')
    if (edit.fontFamily !== undefined && (typeof edit.fontFamily !== 'string' || !edit.fontFamily.trim() || edit.fontFamily.length > 200 || /[\x00-\x1f]/.test(edit.fontFamily))) throw new Error('text_format_font_invalid')
    if (edit.color !== undefined && (typeof edit.color !== 'string' || !colorPattern.test(edit.color))) throw new Error('text_format_color_invalid')
    if (['bold', 'italic', 'underline', 'strike'].some(key => edit[key as keyof TextEdit] !== undefined && typeof edit[key as keyof TextEdit] !== 'boolean')) throw new Error('text_format_font_invalid')
    if (!Number.isInteger(edit.slideIndex) || edit.slideIndex < 0 || edit.slideIndex >= opened.deck.slides.length) {
      throw new Error('slide_index_invalid')
    }
    const element = opened.deck.slides[edit.slideIndex]!.elements.find((candidate) => candidate.id === edit.elementId)
    if (!element || (element.type !== 'text' && element.type !== 'shape')) throw new Error('element_not_editable')
    if (edit.text !== undefined) {
      if (!element.text?.paragraphs.length) throw new Error('element_text_missing')
      element.text.paragraphs = applyEditParagraphs(
        element.text.paragraphs,
        edit.text.split(/\r?\n/).map((text) => ({ runs: [{ text }] })),
      )
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
    if (!Number.isInteger(image.slideIndex) || image.slideIndex < 0 || image.slideIndex >= slideCount) {
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
    if (!Number.isInteger(transition.slideIndex) || transition.slideIndex < 0 || transition.slideIndex >= slideCount) {
      throw new Error('transition_slide_index_invalid')
    }
    const slide = opened.deck.slides[transition.slideIndex]!
    const preserved = patchTransitionPreservingMetadata(slide.bodySuffix, transition.kind)
    if (preserved !== slide.bodySuffix) {
      // Keep the pinned operation's dirty/save hook, then install preserved source XML.
      setSlideTransition(slide, transition.kind)
      slide.bodySuffix = preserved
    }
  }
  for (const animation of request.animations ?? []) {
    const durationMs = animation.durationMs ?? 500
    const delayMs = animation.delayMs ?? 0
    if (!Number.isFinite(durationMs) || durationMs < 0 || !Number.isFinite(delayMs) || delayMs < 0) {
      throw new Error('animation_timing_invalid')
    }
    if (animation.direction !== undefined && (
      !['top', 'bottom', 'left', 'right'].includes(animation.direction) ||
      !['flyIn', 'flyOut', 'wipe', 'wipeOut'].includes(animation.effect)
    )) throw new Error('animation_direction_invalid')
    const slide = opened.deck.slides[animation.slideIndex]
    const element = slide?.elements.find((candidate) => candidate.id === animation.elementId)
    const spid = element ? elementSpid(element) : null
    if (!slide || spid === null || (element!.type !== 'text' && element!.type !== 'shape')) {
      throw new Error('animation_target_invalid')
    }
    const existing = getSlideAnimations(slide)
    const index = animation.append ? -1 : existing.findIndex((item) => item.spid === spid && item.effect === animation.effect)
    const updated: SlideAnimation = {
      ...(index >= 0 ? existing[index] : {}),
      spid,
      effect: animation.effect,
      trigger: animation.trigger,
      durationMs,
      delayMs,
      ...(animation.direction !== undefined ? { direction: animation.direction } : {}),
    }
    if (index >= 0) existing[index] = updated
    else existing.push(updated)
    setSlideAnimations(slide, existing)
  }
  for (const deletion of deletions) {
    if (!deleteElement(opened, originalSlides[deletion.slideIndex]!, deletion.elementId)) throw new Error('delete_target_invalid')
  }
  for (const selection of request.slideLayouts ?? []) {
    if (!Number.isInteger(selection.slideIndex) || selection.slideIndex < 0 || selection.slideIndex >= slideCount) {
      throw new Error('layout_slide_index_invalid')
    }
    if (!layouts.some((layout) => layout.path === selection.layoutPath)) {
      throw new Error('layout_path_invalid')
    }
    const laidOut = setSlideLayout(opened, selection.slideIndex, selection.layoutPath)
    if (!laidOut) throw new Error('layout_apply_failed')
    // Layout materialization replaces the slide model; later edits must target
    // that live object while retaining the request's original slide indices.
    originalSlides[selection.slideIndex] = laidOut
  }
  if (newSlides.length && !request.order) throw new Error('new_slides_require_order')
  // 原始编号 = 来源页 + 新建页；删除按部件路径执行，order 用原始编号列出全部保留页。
  const originalPaths = opened.deck.slides.map((slide) => slide.path)
  if (deletedSlides.length >= originalPaths.length) throw new Error('deleted_slides_all')
  for (const index of deletedSlides) {
    const current = opened.deck.slides.findIndex((slide) => slide.path === originalPaths[index])
    if (current < 0 || !deleteSlide(opened, current)) throw new Error('slide_delete_failed')
  }
  if (request.order) {
    if (request.order.length !== opened.deck.slides.length || new Set(request.order).size !== request.order.length || request.order.some((n) => !Number.isInteger(n) || n < 0 || n >= originalPaths.length || removedSlides.has(n))) {
      throw new Error('slide_order_invalid')
    }
    const desired = request.order.map((index) => originalPaths[index]!)
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
  for (const edit of request.edits ?? []) {
    const { fontSizePt, fontFamily, color, bold, italic, underline, strike } = edit
    if ([fontSizePt, fontFamily, color, bold, italic, underline, strike].some(value => value !== undefined)) {
      if (!setElementFont(originalSlides[edit.slideIndex]!, edit.elementId, {
        ...(fontSizePt !== undefined ? { fontSizePt } : {}),
        ...(fontFamily !== undefined ? { fontFamily } : {}),
        ...(color !== undefined ? { color: color.toUpperCase() } : {}),
        ...(bold !== undefined ? { bold } : {}),
        ...(italic !== undefined ? { italic } : {}),
        ...(underline !== undefined ? { underline } : {}),
        ...(strike !== undefined ? { strike } : {}),
      })) throw new Error('text_format_target_invalid')
    }
  }
  for (const format of request.paragraphFormatting ?? []) {
    const { slideIndex, elementId, ...patch } = format
    const slide = originalSlides[slideIndex]
    const element = slide?.elements.find(candidate => candidate.id === elementId)
    if (!slide || !element || (element.type !== 'text' && element.type !== 'shape') || !element.text ||
      !setElementParagraphFormat(slide, elementId, patch)) throw new Error('paragraph_format_target_invalid')
    // Validate every ordered command so a later opposite indent cannot hide overflow.
    if (element.text?.paragraphs.some(paragraph =>
        (paragraph.marL != null && (paragraph.marL < 0 || paragraph.marL > maxParagraphEmu)) ||
        (paragraph.indent != null && Math.abs(paragraph.indent) > maxParagraphEmu))) {
      throw new Error('paragraph_indent_out_of_range')
    }
  }
  for (const background of request.backgrounds ?? []) {
    setSlideBackground(opened, originalSlides[background.slideIndex]!, background.color.toUpperCase())
  }
  for (const shape of request.shapes ?? []) {
    const { x, y, width, height } = shape.geometry
    const line = shapePresets.lines.includes(shape.kind)
    addElement(originalSlides[shape.slideIndex]!, {
      kind: shape.kind,
      offset: { x: Math.round(x * 9525), y: Math.round(y * 9525), cx: Math.round(width * 9525), cy: Math.round(height * 9525) },
      ...(line ? { stroke: { color: '#000000', widthEmu: 12700 } } : { fillColor: '#C43E1C' }),
    })
  }
  for (const box of request.textBoxes ?? []) {
    const { x, y, width, height } = box.geometry
    const element = addElement(originalSlides[box.slideIndex]!, {
      kind: 'textbox',
      offset: { x: Math.round(x * 9525), y: Math.round(y * 9525), cx: Math.round(width * 9525), cy: Math.round(height * 9525) },
      paragraphs: box.text.split(/\r?\n/).map((text) => ({ runs: [{
        text,
        fontSize: box.fontSize ?? 18,
        ...(box.fontFamily ? { fontFamily: box.fontFamily } : {}),
        color: (box.color ?? '#000000').toUpperCase(),
        ...(box.bold ? { bold: true } : {}),
      }] })),
      bodyPr: { autoFit: 'shrink' },
    })
    if (box.rotation) {
      element.transform.rot = Math.round(box.rotation * 60000)
      element.dirtyTransform = true
    }
  }
  if (request.slideSize) {
    const { cx, cy } = request.slideSize
    if (Object.keys(request.slideSize).length !== 2
      || ![cx, cy].every(value => Number.isInteger(value) && value >= 914400 && value <= 51206400)) {
      throw new Error('slide_size_invalid')
    }
    // Draft coordinates refer to the original canvas. Resize after all edits;
    // setSlideSize materializes slides and must not invalidate pending targets.
    if ((opened.deck.size.cx !== cx || opened.deck.size.cy !== cy) && !setSlideSize(opened, cx, cy)) {
      throw new Error('slide_size_apply_failed')
    }
  }
  if (!request.output) throw new Error('output_path_required')
  const bytes = await savePptx(opened)
  await writeFile(request.output, bytes)
  let issues: { page: number; message: string }[]
  try {
    const audit = await auditDeck(bytes)
    issues = audit.flatMap((page) => page.issues.map((message) => ({ page: page.slide + 1, message })))
  } catch (error) {
    issues = [{ page: 0, message: `PPTX layout audit failed: ${error instanceof Error ? error.message : String(error)}` }]
  }
  process.stdout.write(JSON.stringify({
    slideCount: opened.deck.slides.length,
    issues,
  }))
}

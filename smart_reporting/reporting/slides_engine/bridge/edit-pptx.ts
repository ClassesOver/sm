import { readFile, writeFile } from 'node:fs/promises'
import {
  addElement, deleteElement, openPptx, savePptx, setElementFill,
  setElementFont, setElementParagraphFormat, setSlideBackground, strokePatchToModel,
  type OpenedPptx, type SlideElement, type TextElement, type Paragraph,
} from '@genoffice/pptx-engine'
import { auditDeck } from '../packages/pipelines/src/slides/audit-deck.ts'

type Operation = Record<string, unknown> & { op: string; slide: number }
type Issue = { code: string; message: string; details?: unknown }
const editableShapes = new Set(['rect', 'roundRect', 'ellipse', 'line'])
const geometryFields = ['x', 'y', 'width', 'height', 'rotation']
const textFields = ['text', 'fontSize', 'fontFamily', 'color', 'bold', 'lineSpacing']
const updateFields = [...geometryFields, ...textFields, 'fill']
const imageMime: Record<string, string> = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
  gif: 'image/gif', webp: 'image/webp' }

function fail(code: string): never { throw new Error(code) }
function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}
function isEditable(element: SlideElement): boolean {
  return element.type === 'picture'
    ? !element.media && !element.model3d && !!imageMime[element.mediaRef.split('.').pop()?.toLowerCase() ?? '']
    : (element.type === 'text' || element.type === 'shape') && !element.customGeometry &&
      (!element.presetGeometry || editableShapes.has(element.presetGeometry))
}
function plainText(element: TextElement): string {
  return element.text?.paragraphs.map((paragraph) => paragraph.runs.map((run) => run.text).join('')).join('\n') ?? ''
}

function inspect(opened: OpenedPptx) {
  const scale = 1280 / opened.deck.size.cx
  return {
    width: 1280,
    height: opened.deck.size.cy * scale,
    fontScale: 12700 * scale,
    slides: opened.deck.slides.map((slide, index) => ({
      index,
      title: slide.elements.filter((element): element is TextElement =>
        element.type === 'text' || element.type === 'shape').map(plainText).find((value) => value.trim()) ?? `第 ${index + 1} 页`,
      background: slide.background?.type === 'solid' ? slide.background.color : '#FFFFFF',
      elements: [...(slide.decorations ?? []).map((element) => ({ element, decoration: true })),
        ...slide.elements.map((element) => ({ element, decoration: false }))].map(({ element, decoration }, elementIndex): Record<string, unknown> => {
        const { x, y, cx, cy } = element.transform.offset
        const base = {
          id: decoration ? `decoration:${elementIndex}:${element.id}` : element.id,
          x: x * scale, y: y * scale, width: cx * scale,
          height: cy * scale, rotation: element.transform.rot / 60000,
          editable: !decoration && isEditable(element),
        }
        if (element.type === 'picture') {
          const bytes = opened.archive.readBytes(element.mediaRef)
          const extension = element.mediaRef.split('.').pop()?.toLowerCase()
          const mime = imageMime[extension ?? '']
          if (bytes && mime) return { ...base, kind: 'image', imageDataUrl: `data:${mime};base64,${Buffer.from(bytes).toString('base64')}` }
        }
        if ((element.type !== 'text' && element.type !== 'shape') || !isEditable(element)) {
          return { ...base, editable: false, kind: 'shape', shape: 'unsupported',
            text: `${element.name || element.type}（只读保留）`, fill: '#EDF0F3', color: '#566773' }
        }
        const paragraph = element.text?.paragraphs[0]
        const run = paragraph?.runs.find((item) => item.text) ?? paragraph?.runs[0]
        const text = plainText(element)
        const fill = element.presetGeometry === 'line' ? element.stroke?.fill : element.fill
        return { ...base, kind: text || element.type === 'text' ? 'text' : 'shape',
          shape: element.presetGeometry ?? 'rect', text,
          ...(run?.fontSize !== undefined ? { fontSize: run.fontSize } : {}),
          ...(run?.fontFamily ? { fontFamily: run.fontFamily } : {}),
          color: element.presetGeometry === 'line' && fill?.type === 'solid' ? fill.color : run?.color ?? '#000000',
          bold: run?.bold ?? false,
          ...(fill?.type === 'solid' ? { fill: fill.color } : {}),
          lineSpacing: paragraph?.lineHeight !== undefined ? paragraph.lineHeight / 100 : 1,
        }
      }),
    })),
  }
}

function validate(operation: unknown, opened: OpenedPptx): asserts operation is Operation {
  if (!operation || typeof operation !== 'object' || Array.isArray(operation)) fail('pptx_operation_invalid')
  const item = operation as Operation
  const allowed: Record<string, string[]> = {
    update: ['op', 'slide', 'id', ...updateFields],
    addText: ['op', 'slide', ...geometryFields, ...textFields],
    delete: ['op', 'slide', 'id'], background: ['op', 'slide', 'color'],
  }
  if (!Object.hasOwn(allowed, item.op)) fail('pptx_operation_unknown')
  if (Object.keys(item).some((key) => !allowed[item.op]!.includes(key))) fail('pptx_operation_field_unknown')
  if (!Number.isInteger(item.slide) || item.slide < 0 || item.slide >= opened.deck.slides.length) fail('pptx_slide_invalid')
  if (item.op === 'update' || item.op === 'delete') {
    if (typeof item.id !== 'string' || !item.id) fail('pptx_element_invalid')
    const element = opened.deck.slides[item.slide]!.elements.find((value) => value.id === item.id)
    if (!element || !isEditable(element)) fail('pptx_element_invalid')
    if (item.op === 'update' && element.type === 'picture' &&
      [...textFields, 'fill'].some((key) => Object.hasOwn(item, key))) fail('pptx_element_field_invalid')
  }
  const required = item.op === 'addText' ? ['text', 'x', 'y', 'width', 'height']
    : item.op === 'background' ? ['color'] : []
  if (required.some((key) => !Object.hasOwn(item, key))) fail('pptx_operation_field_missing')
  for (const key of geometryFields) {
    if (!Object.hasOwn(item, key)) continue
    const value = item[key]
    if (!isNumber(value) || Math.abs(value) > 100000 ||
      ((key === 'width' || key === 'height') && value <= 0)) fail('pptx_geometry_invalid')
  }
  for (const key of ['color', 'fill']) {
    if (Object.hasOwn(item, key) && (typeof item[key] !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(item[key] as string))) fail('pptx_color_invalid')
  }
  if (Object.hasOwn(item, 'text') && (typeof item.text !== 'string' || item.text.length > 100000)) fail('pptx_text_invalid')
  if (Object.hasOwn(item, 'fontFamily') && (typeof item.fontFamily !== 'string' || !item.fontFamily.trim() || item.fontFamily.length > 200)) fail('pptx_font_invalid')
  if (Object.hasOwn(item, 'fontSize') && (!isNumber(item.fontSize) || item.fontSize < 1 || item.fontSize > 400)) fail('pptx_font_invalid')
  if (Object.hasOwn(item, 'bold') && typeof item.bold !== 'boolean') fail('pptx_font_invalid')
  if (Object.hasOwn(item, 'lineSpacing') && (!isNumber(item.lineSpacing) || item.lineSpacing < 1 || item.lineSpacing > 3)) fail('pptx_line_spacing_invalid')
}

function updateText(element: TextElement, value: string) {
  const previous = element.text?.paragraphs ?? []
  // 替换文本沿用对应段落的首个 run 样式；未改文本时保留原来的富文本。
  const paragraphs: Paragraph[] = value.split('\n').map((line, index) => {
    const original = previous[index] ?? previous[0]
    const run = { ...(original?.runs[0] ?? {}), text: line }
    delete run.rawXml
    delete run.paraMark
    return { ...original, runs: [run] }
  })
  element.text = { ...element.text, paragraphs }
  element.textMoved = true
  element.dirty = true
}

function apply(opened: OpenedPptx, item: Operation) {
  const slide = opened.deck.slides[item.slide]!
  const emu = opened.deck.size.cx / 1280
  if (item.op === 'background') {
    setSlideBackground(opened, slide, item.color as string)
    return
  }
  if (item.op === 'delete') {
    if (!deleteElement(opened, slide, item.id as string)) fail('pptx_element_invalid')
    return
  }
  const element = item.op === 'addText'
    ? addElement(slide, { kind: 'textbox',
      offset: { x: Math.round((item.x as number) * emu), y: Math.round((item.y as number) * emu),
        cx: Math.round((item.width as number) * emu), cy: Math.round((item.height as number) * emu) },
      paragraphs: [{ runs: [{ text: '', fontSize: 18, fontFamily: 'Arial', color: '#000000' }] }],
      bodyPr: { autoFit: 'shrink', insetsEmu: { l: 0, t: 0, r: 0, b: 0 } },
    })
    : slide.elements.find((value) => value.id === item.id)!
  const offset = element.transform.offset
  for (const [key, target] of [['x', 'x'], ['y', 'y'], ['width', 'cx'], ['height', 'cy']] as const) {
    if (Object.hasOwn(item, key)) {
      offset[target] = Math.round((item[key] as number) * emu)
      element.dirtyTransform = true
    }
  }
  if (Object.hasOwn(item, 'rotation')) {
    element.transform.rot = Math.round((item.rotation as number) * 60000)
    element.dirtyTransform = true
  }
  if (element.type === 'text' || element.type === 'shape') {
    if (Object.hasOwn(item, 'text')) updateText(element, item.text as string)
    if (['fontSize', 'fontFamily', 'color', 'bold', 'lineSpacing'].some((key) => Object.hasOwn(item, key)) && !element.text?.paragraphs.length) {
      updateText(element, '')
    }
    const font = {
      ...(Object.hasOwn(item, 'fontSize') ? { fontSizePt: item.fontSize as number } : {}),
      ...(Object.hasOwn(item, 'fontFamily') ? { fontFamily: item.fontFamily as string } : {}),
      ...(Object.hasOwn(item, 'color') ? { color: item.color as string } : {}),
      ...(Object.hasOwn(item, 'bold') ? { bold: item.bold as boolean } : {}),
    }
    if (Object.keys(font).length) setElementFont(slide, element.id, font)
    if (Object.hasOwn(item, 'lineSpacing')) setElementParagraphFormat(slide, element.id, { lineSpacingPct: (item.lineSpacing as number) * 100 })
    if (Object.hasOwn(item, 'fill')) {
      if (element.presetGeometry === 'line') {
        element.stroke = { ...element.stroke, ...strokePatchToModel({
          color: item.fill as string, widthEmu: element.stroke?.width ?? 12700,
        }) }
        element.dirtyStroke = true
      } else setElementFill(opened, slide, element.id, item.fill as string)
    }
  }
}

const inputPath = process.argv[2]
if (!inputPath) throw new Error('input JSON path required')
const input = JSON.parse(await readFile(inputPath, 'utf8'))
try {
  let opened: OpenedPptx
  try { opened = await openPptx(new Uint8Array(await readFile(input.input))) }
  catch { fail('pptx_input_invalid') }
  if (input.mode === 'inspect') {
    await writeFile(input.receipt, JSON.stringify(inspect(opened)))
  } else {
    if (input.mode !== 'edit' || !Array.isArray(input.operations) || input.operations.length > 1000) fail('pptx_operations_invalid')
    // 在临时内存中依序校验和修改；任何无效操作都不会生成新文件。
    for (const operation of input.operations) {
      validate(operation, opened)
      apply(opened, operation)
    }
    const bytes = await savePptx(opened)
    await writeFile(input.output, bytes)
    let issues: Issue[] = []
    try {
      issues = (await auditDeck(bytes)).flatMap((page) => page.issues.map((message) => ({
        code: 'pptx_layout_warning', message, details: { slide: page.slide },
      })))
    } catch {
      issues.push({ code: 'pptx_audit_failed', message: '幻灯片验收未完成，已保留可下载的 PPTX。' })
    }
    await writeFile(input.receipt, JSON.stringify({ ok: issues.length === 0, issues }))
  }
} catch (error) {
  const message = error instanceof Error ? error.message : ''
  if (!/^pptx_[a-z_]+$/.test(message)) throw error
  await writeFile(input.receipt, JSON.stringify({ error: message }))
}

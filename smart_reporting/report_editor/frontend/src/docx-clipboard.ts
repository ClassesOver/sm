import {richPasteControls} from './docx-rich-paste'
/**
 * Word Home 剪贴板组的 DOCX 接线。对照固定源 genoffice-source-full f8c17004：
 * - Ribbon.tsx:3611 剪贴板组（paste 分体主按钮 + source/merge/text/picture 菜单、cut/copy、格式刷）
 * - paste-actions.ts readClipboardPayload 的剪贴板读取路径（read() 失败回退 readText()）
 * - paste-actions.ts pastePayload 的图片优先级：显式 picture 模式；或无 html 且
 *   无有效文本时的位图兜底（OS 剪贴板常在 image/png 旁附带空 text/plain）
 * - insertImageFromDataUrl（ribbon-tabs.tsx:399）的格式白名单与 620px 宽度缩放
 * - Ribbon.tsx:2234 clipboard()：cut/copy 走 document.execCommand，不越权访问剪贴板 API
 * - Ribbon.tsx:451-478 PAINTER_* 白名单与 applyPainterFormat:496 的 unset→set 语义
 *
 * 与原版的差异（保存协议限制，均为有意收敛）：
 * - 富文本粘贴通过结构化 pasteRichContent 保存，源格式、合并格式和仅文本可从原上下文重放。
 * - 图片粘贴映射为 insertParagraphImage（media part + 关系 + 内联 drawing 的
 *   严格后端操作）；仅 png/jpeg，≤8MB，与格式刷同属协议内收敛。
 * - 格式刷段落属性只保留保存协议可组合的字段（对齐、缩进、段距、行距）；
 *   样式切换、底纹、边框、列表身份与同段其他改动互斥，不纳入刷子。
 * - 格式刷字符格式只拾取 run 上的直接标记（协议不支持从样式解析有效格式），
 *   docTextStyle 只保留 sizeHalfPoints/color/font 三个可写字段。
 * - 刷子作用粒度为整段（与高亮/底纹等 Home 命令一致的整段协议）。
 */
import type { Editor } from '@tiptap/core'
import type { Node as PmNode } from '@tiptap/pm/model'
import { Fragment, Slice } from '@tiptap/pm/model'
import { DOCX_PASTE_IMAGE_MIMES, DOCX_PASTE_IMAGE_MAX_BYTES, DOCX_PASTE_IMAGE_MAX_EDGE_PX } from './docx-operations'

export type DocxPasteMode = 'source' | 'merge' | 'text' | 'picture'

/** 格式刷传递的字符标记（Ribbon.tsx:451 PAINTER_MARK_TYPES 去掉 docTextStyle 整体透传） */
const PAINTER_MARK_TYPES = ['bold', 'italic', 'underline', 'strike'] as const
/** docTextStyle 里保存协议可写的字段；rawRPr/vertAlign/highlight/styleId 等不跨段落扩散 */
const PAINTER_TEXT_STYLE_KEYS = ['sizeHalfPoints', 'color', 'font'] as const
/** 格式刷传递的段落属性（Ribbon.tsx:457 PAINTER_PARA_KEYS 中保存协议可组合的子集） */
const PAINTER_PARA_KEYS = ['align', 'indentLeft', 'indentRight', 'spaceBefore', 'spaceAfter', 'lineSpacing'] as const
const PARAGRAPH_TYPES = ['docParagraph', 'docHeading', 'docListItem']
const SUPPORTED_ALIGN = ['left', 'center', 'right', 'justify']
const SUPPORTED_LINE_SPACING = [1, 1.15, 1.5, 2, 2.5, 3]

const MAX_PASTE_CHARS = 200000
const MAX_PASTE_PARAGRAPHS = 400
/** 允许 \n 换行；\t 等其余 C0 控制符与 DEL 一律拒绝 */
const PASTE_CONTROL_CHARS = /[\u0000-\u0009\u000b\u000c\u000e-\u001f\u007f]/u

export interface DocxPainterFormat {
  marks: Array<{ type: string; attrs: Record<string, unknown> }>
  /** 源段落的协议内段落属性；null 表示光标不在可刷段落或不携带段落格式 */
  block: Record<string, unknown> | null
}

const isIntInRange = (value: unknown, min: number, max: number) =>
  Number.isInteger(Number(value)) && Number(value) >= min && Number(value) <= max

/** Ribbon.tsx:1991 pickUpFormat 的协议内收敛版：光标拾取 $head 标记，选区拾取首个文字 run。 */
export function docxPainterPickUp(editor: Editor): DocxPainterFormat | null {
  if (!editor.isEditable) return null
  const { state } = editor
  const { $from, $to, $head, from, to, empty } = state.selection
  const picked: Array<{ type: { name: string }; attrs: Record<string, unknown> }> = []
  if (empty) picked.push(...$head.marks())
  else {
    let found = false
    state.doc.nodesBetween(from, to, node => {
      if (found) return false
      if (node.isText) { found = true; picked.push(...node.marks); return false }
      return true
    })
  }
  // Ribbon.tsx:2023 ¶ 标记规则：光标拾取或跨段选择携带段落格式，段内部分选择只刷字符格式
  const coversWholeParagraph = !empty && $from.parent.isTextblock && $from.sameParent($to)
    && $from.parentOffset === 0 && $to.parentOffset === $to.parent.content.size
  const includesParaMark = empty || !$from.sameParent($to) || coversWholeParagraph
  const marks: DocxPainterFormat['marks'] = []
  for (const mark of picked) {
    if ((PAINTER_MARK_TYPES as readonly string[]).includes(mark.type.name)) marks.push({ type: mark.type.name, attrs: {} })
    else if (mark.type.name === 'docTextStyle' || mark.type.name === 'textStyle') {
      const attrs: Record<string, unknown> = {}
      for (const key of PAINTER_TEXT_STYLE_KEYS) if (mark.attrs?.[key] != null) attrs[key] = mark.attrs[key]
      if (Object.keys(attrs).length) marks.push({ type: 'docTextStyle', attrs })
    }
  }
  let block: Record<string, unknown> | null = null
  if (includesParaMark && PARAGRAPH_TYPES.includes($from.parent.type.name)) {
    const attrs: Record<string, unknown> = {}
    for (const key of PAINTER_PARA_KEYS) {
      const value = $from.parent.attrs[key]
      if (value == null) continue
      if (key === 'align' && !SUPPORTED_ALIGN.includes(String(value))) continue
      if (key === 'indentLeft' && !(isIntInRange(value, 0, 14400) && Number(value) % 720 === 0)) continue
      if (key === 'indentRight' && !isIntInRange(value, -14400, 14400)) continue
      if ((key === 'spaceBefore' || key === 'spaceAfter') && !isIntInRange(value, 0, 14400)) continue
      // 精确/最小行距不可写：仅当源段落本身是倍数行距时才拾取（docx-operations.ts:246）
      if (key === 'lineSpacing' && !(SUPPORTED_LINE_SPACING.includes(Number(value)) && $from.parent.attrs.lineRule == null && $from.parent.attrs.lineRawTwips == null)) continue
      attrs[key] = value
    }
    if (Object.keys(attrs).length) block = attrs
  }
  if (!marks.length && !block) return null
  return { marks, block }
}

/** Ribbon.tsx:496 applyPainterFormat 的协议内收敛版：对选区覆盖的每个正文段落整段应用。 */
export function docxPainterApply(editor: Editor, fmt: DocxPainterFormat): void {
  if (!editor.isEditable) throw new Error('当前文档不可编辑')
  const { state } = editor
  const { from, to } = state.selection
  const targets: Array<{ node: PmNode; pos: number }> = []
  state.doc.nodesBetween(from, to, (node, pos) => {
    if (PARAGRAPH_TYPES.includes(node.type.name)) { targets.push({ node, pos }); return false }
    return true
  })
  if (!targets.length) throw new Error('请先选择正文段落')
  const tr = state.tr
  for (const { node, pos } of targets) {
    const blockAttrs: Record<string, unknown> = {}
    if (fmt.block) {
      // 列表缩进只能走编号级别（docx-operations.ts:258），刷子不把缩进带到列表段
      const skipIndent = node.type.name === 'docListItem'
      for (const [key, value] of Object.entries(fmt.block)) {
        if (skipIndent && (key === 'indentLeft' || key === 'indentRight')) continue
        if (value === node.attrs[key]) continue
        blockAttrs[key] = value
      }
      // 与行距/段距菜单一致：写回显式值时清掉自动标记（setParagraphSpacing 回放同款）
      if ('spaceBefore' in blockAttrs && node.attrs.spaceBeforeAuto != null) blockAttrs.spaceBeforeAuto = null
      if ('spaceAfter' in blockAttrs && node.attrs.spaceAfterAuto != null) blockAttrs.spaceAfterAuto = null
      if ('lineSpacing' in blockAttrs) { blockAttrs.lineRule = null; blockAttrs.lineRawTwips = null }
    }
    if (Object.keys(blockAttrs).length) tr.setNodeMarkup(pos, undefined, { ...node.attrs, ...blockAttrs })
    if (fmt.marks.length && node.content.size) {
      const start = pos + 1, end = pos + 1 + node.content.size
      // 先剥四类字符标记再补拾取到的（applyPainterFormat 的 unset→set 语义；
      // docTextStyle 不整体摘除，避免协议禁止的清色/清字体）
      for (const name of PAINTER_MARK_TYPES) {
        const type = state.schema.marks[name]
        if (type) tr.removeMark(start, end, type)
      }
      for (const mark of fmt.marks) {
        if ((PAINTER_MARK_TYPES as readonly string[]).includes(mark.type)) {
          const type = state.schema.marks[mark.type]
          if (type) tr.addMark(start, end, type.create())
          continue
        }
        const type = state.schema.marks.docTextStyle
        if (!type) continue
        // docTextStyle 逐 run 合并：保留目标 run 未被拾取的其他可写字段
        state.doc.nodesBetween(start, end, (child, childPos) => {
          if (!child.isText) return true
          const runStart = Math.max(start, childPos), runEnd = Math.min(end, childPos + child.nodeSize)
          if (runEnd <= runStart) return true
          const existing = child.marks.find(item => item.type === type)
          tr.addMark(runStart, runEnd, type.create({ ...existing?.attrs, ...mark.attrs }))
          return false
        })
      }
    }
  }
  if (!tr.docChanged) return
  editor.view.dispatch(tr.scrollIntoView())
}

export interface DocxPainterController {
  click(): void
  doubleClick(): void
  active(): boolean
  dispose(): void
}

/**
 * Ribbon.tsx:2093-2108 的单击刷一次/双击锁定（Esc 解除）交互。
 * 应用时机与原版一致：拖选后松开应用选区；原位单击应用点击处的段落。
 */
export function createDocxPainter(editor: Editor, options: { report: (error: unknown) => void; onChange: () => void }): DocxPainterController {
  let format: DocxPainterFormat | null = null
  let locked = false
  let downAt: { x: number; y: number } | null = null
  let selecting = false
  const press: boolean[] = []
  let idle = { from: 0, to: 0 }
  const change = () => options.onChange()
  const arm = (isLocked: boolean) => {
    try {
      const picked = docxPainterPickUp(editor)
      if (!picked) throw new Error('光标处没有可拾取的格式')
      format = picked
      locked = isLocked
      idle = { from: editor.state.selection.from, to: editor.state.selection.to }
    } catch (error) { options.report(error) }
    change()
  }
  const disarm = () => {
    if (!format) return
    format = null
    locked = false
    change()
  }
  const applyRange = (from: number, to: number) => {
    if (!format || !editor.isEditable) return
    try {
      editor.commands.setTextSelection({ from, to })
      docxPainterApply(editor, format)
    } catch (error) { options.report(error) }
    if (!locked) { disarm(); return }
    // 锁定模式：本次笔划结束后的选区成为新的"空闲"基线，下一次移动再次触发
    idle = { from: editor.state.selection.from, to: editor.state.selection.to }
  }
  const onMouseDown = (event: MouseEvent) => {
    if (!editor.view.dom.contains(event.target as globalThis.Node)) return
    selecting = true
    downAt = { x: event.clientX, y: event.clientY }
  }
  const onMouseUp = (event: MouseEvent) => {
    if (!selecting) return
    selecting = false
    const pressAt = downAt
    downAt = null
    if (!format || !pressAt) return
    const dist = Math.abs(event.clientX - pressAt.x) + Math.abs(event.clientY - pressAt.y)
    requestAnimationFrame(() => {
      if (!format || !editor.isEditable) return
      const { from, to } = editor.state.selection
      if (from !== to && (from !== idle.from || to !== idle.to)) { applyRange(from, to); return }
      if (dist >= 5) return
      // 原位单击刷整段（协议按整段映射，见文件头差异说明）
      const hit = editor.view.posAtCoords({ left: pressAt.x, top: pressAt.y })
      if (!hit) return
      const $pos = editor.state.doc.resolve(hit.pos)
      for (let depth = $pos.depth; depth > 0; depth--) {
        const node = $pos.node(depth)
        if (PARAGRAPH_TYPES.includes(node.type.name)) { applyRange($pos.start(depth), $pos.end(depth)); return }
      }
    })
  }
  const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') disarm() }
  window.addEventListener('mousedown', onMouseDown)
  window.addEventListener('mouseup', onMouseUp)
  window.addEventListener('keydown', onKeyDown, true)
  return {
    click() {
      press.push(format != null)
      if (press.length > 2) press.shift()
      if (format) disarm()
      else arm(false)
    },
    doubleClick() {
      const wasOn = press[0] ?? format != null
      press.length = 0
      if (wasOn) disarm()
      else arm(true)
    },
    active: () => format != null,
    dispose() {
      window.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('mouseup', onMouseUp)
      window.removeEventListener('keydown', onKeyDown, true)
    },
  }
}

/** paste-actions.ts readClipboardPayload 的协议内收敛版：text/html/image 三通道。 */
export async function readClipboardPayload(): Promise<{ text: string | null; html: string | null; image: Blob | null }> {
  const clipboard = navigator.clipboard
  if (!clipboard || typeof clipboard.readText !== 'function') throw new Error('当前浏览器不支持剪贴板读取（需要在 HTTPS 或 localhost 安全上下文中使用）')
  let html: string | null = null
  let image: Blob | null = null
  if (typeof clipboard.read === 'function') {
    try {
      for (const item of await clipboard.read()) {
        if (!html && item.types.includes('text/html')) html = await (await item.getType('text/html')).text()
        const imageType = item.types.find((type: string) => type.startsWith('image/'))
        if (!image && imageType) image = await item.getType(imageType)
      }
    } catch { /* read 权限不足或不可用时按纯文本继续 */ }
  }
  try { return { text: await clipboard.readText(), html, image } }
  catch (error) {
    if (error instanceof DOMException && error.name === 'NotAllowedError') throw new Error('浏览器拒绝了剪贴板读取权限：请点击文档区域后重试，或在浏览器设置中允许此站点访问剪贴板')
    throw new Error(`无法读取剪贴板：${error instanceof Error ? error.message : String(error)}`)
  }
}

/** paste-actions.ts htmlText 的等价实现：富文本剪贴板没有纯文本层时的兜底提取 */
function htmlToText(html: string): string {
  try {
    const body = new DOMParser().parseFromString(html, 'text/html').body
    for (const block of body.querySelectorAll('p,div,li,tr,h1,h2,h3,h4,h5,h6,br')) block.after(body.ownerDocument.createTextNode('\n'))
    return (body.textContent ?? '').replace(/\n{2,}/g, '\n').trim()
  } catch { return '' }
}

/** 固定源 ribbon-tabs.tsx:339 MAX_IMAGE_WIDTH_PX：US Letter 96dpi 内容宽 */
const MAX_IMAGE_WIDTH_PX = 620

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => typeof reader.result === 'string' && reader.result.startsWith('data:')
      ? resolve(reader.result) : reject(new Error('粘贴图片读取失败'))
    reader.onerror = () => reject(new Error('粘贴图片读取失败'))
    reader.readAsDataURL(blob)
  })
}

function imageSizeOf(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight })
    img.onerror = () => reject(new Error('粘贴图片无法解码'))
    img.src = dataUrl
  })
}

/**
 * 插入粘贴图片（insertPictureAtSelection 的协议内收敛版）：图片成为独立
 * 图片段落（docProtected/genImage）。段中插入时把被拆出的右半段恢复为新
 * 段落（extensions.ts:1440 split-twin 同规），避免出现重复的 docxIndex 锚点；
 * 插在文档末尾时补一个空段落承接光标（Word 粘贴图片后的行为）。
 */
function insertDocxPastedImage(editor: Editor, payload: { dataUrl: string; base64: string; mime: string; widthPx: number; heightPx: number }): void {
  const schema = editor.state.schema
  const nodeType = schema.nodes.docProtected
  if (!nodeType) throw new Error('文档结构不支持图片粘贴')
  const imageNode = nodeType.create({
    docxIndex: null, blockType: 'image', label: '图片（粘贴）',
    imageDataUrl: payload.dataUrl, imageWidthPx: payload.widthPx, imageHeightPx: payload.heightPx,
    genImage: { base64: payload.base64, mime: payload.mime, widthPx: payload.widthPx, heightPx: payload.heightPx },
  })
  const { state } = editor
  const { $from, empty } = state.selection
  const paragraphType = schema.nodes.docParagraph
  const topLevelTextblock = $from.depth >= 1 && $from.node(1).isTextblock ? $from : null
  if (!topLevelTextblock || !empty || !paragraphType) {
    // 非文本光标（对象选区等）：交给 PM 原生替换，由 filterTransaction 校验结果
    const tr = state.tr.replaceSelectionWith(imageNode)
    if (!tr.docChanged) throw new Error('文档结构不支持图片粘贴')
    editor.view.dispatch(tr.scrollIntoView())
    if (!editor.state.doc.eq(tr.doc)) throw new Error('图片插入未被接受，请检查当前位置的保存限制')
    return
  }
  const tr = state.tr
  const before = topLevelTextblock.before(1), after = topLevelTextblock.after(1)
  if (topLevelTextblock.parent.content.size === 0) {
    // 空段落：图片插在该段之前，原段落锚点原样保留
    tr.insert(before, imageNode)
  } else if (topLevelTextblock.parentOffset === 0) {
    tr.insert(before, imageNode)
  } else if (topLevelTextblock.parentOffset === topLevelTextblock.parent.content.size) {
    tr.insert(after, imageNode)
    // 图片落在文档末尾时补一个新段落承接光标（Word 粘贴图片后的行为）
    if (after === state.doc.content.size) tr.insert(after + imageNode.nodeSize, paragraphType.create({ docxIndex: null }))
  } else {
    // 段中插入：显式拆段（split 把原 docxIndex 复制给两半）。拆分后右半段起点
    // 恒为 at+1（左半 = parentOffset 内容 + 2 个边界标记）；图片插在边界处，
    // 右半段恢复为新段落（extensions.ts:1440 split-twin 同规），避免重复锚点。
    // setNodeMarkup 整体替换 attrs，必须从原段 attrs 全量展开。
    const at = topLevelTextblock.pos
    tr.split(at)
    tr.insert(at + 1, imageNode)
    tr.setNodeMarkup(at + 1 + imageNode.nodeSize, undefined,
      { ...topLevelTextblock.parent.attrs, docxIndex: null })
  }
  if (!tr.docChanged) throw new Error('文档结构不支持图片粘贴')
  editor.view.dispatch(tr.scrollIntoView())
  if (!editor.state.doc.eq(tr.doc)) throw new Error('图片插入未被接受，请检查当前位置的保存限制')
}

export function docxPictureUnavailable(editor: Editor, editable: boolean): string | undefined {
  if (!editable || !editor.isEditable || editor.isDestroyed) return '当前文档不可编辑或正在保存'
  const { $from, empty } = editor.state.selection
  if ($from.depth !== 1 || !$from.parent.isTextblock || !empty) return '请将光标放在正文段落中插入图片'
  return undefined
}

/** 文件选择与剪贴板共用图片解码和写回；读取期间的编辑/选区变化不得改变插入目标。 */
export async function insertDocxImageFile(editor: Editor, image: Blob, target = { doc: editor.state.doc, selection: editor.state.selection }): Promise<void> {
  let changed = false
  const validate = () => {
    if (editor.isDestroyed || !editor.isEditable) throw new Error('当前文档不可编辑或正在保存')
    if (changed || editor.state.doc !== target.doc || !editor.state.selection.eq(target.selection)) throw new Error('图片读取期间文档、光标或编辑状态已变化，请重新选择图片')
    const { $from } = editor.state.selection
    for (let depth = $from.depth; depth > 0; depth--) {
      const name = $from.node(depth).type.name
      if (name === 'docTableCell' || name === 'docTableHeader') throw new Error('表格单元格内暂不支持粘贴图片；请把光标放到正文段落')
    }
  }
  validate()
  if (!(DOCX_PASTE_IMAGE_MIMES as readonly string[]).includes(image.type)) throw new Error('仅支持粘贴 PNG 或 JPEG 图片')
  if (image.size > DOCX_PASTE_IMAGE_MAX_BYTES) throw new Error('粘贴图片超过 8MB 大小上限')
  const observe = () => { changed ||= editor.isDestroyed || !editor.isEditable || editor.state.doc !== target.doc || !editor.state.selection.eq(target.selection) }
  editor.on('transaction', observe); editor.on('update', observe); editor.on('destroy', observe)
  let dataUrl: string, natural: { width: number; height: number }
  try {
    dataUrl = await blobToDataUrl(image)
    natural = await imageSizeOf(dataUrl)
  } finally {
    editor.off('transaction', observe); editor.off('update', observe); editor.off('destroy', observe)
  }
  validate()
  if (!Number.isFinite(natural.width) || !Number.isFinite(natural.height) || natural.width < 1 || natural.height < 1) throw new Error('粘贴图片无法解码')
  const scale = Math.min(1, MAX_IMAGE_WIDTH_PX / natural.width)
  const widthPx = Math.max(1, Math.round(natural.width * scale)), heightPx = Math.max(1, Math.round(natural.height * scale))
  if (heightPx > DOCX_PASTE_IMAGE_MAX_EDGE_PX) throw new Error('图片的显示尺寸超出可保存范围')
  insertDocxPastedImage(editor, { dataUrl, base64: dataUrl.slice(dataUrl.indexOf(',') + 1), mime: image.type, widthPx, heightPx })
}

/**
 * Ribbon.tsx:3636 pasteAs + paste-actions.ts pastePayload 的协议内收敛版：
 * 文本经严格校验后按 PM 原生粘贴路径写入（进入 filterTransaction 前），由
 * docxOperations 映射为 replaceParagraph/insertParagraph；富文本明确拒绝；
 * 图片（显式 picture 模式，或无 html 且无有效文本时的位图兜底）映射为
 * insertParagraphImage。
 */
export async function docxClipboardPaste(editor: Editor, mode?: DocxPasteMode): Promise<void> {
  if (!editor.isEditable) throw new Error('当前文档不可编辑')
  const target = { doc: editor.state.doc, selection: editor.state.selection }
  const { text, html, image } = await readClipboardPayload()
  if (html && mode !== 'picture' && mode !== 'text') {
    const controls=richPasteControls(editor)
    if(!controls)throw new Error('当前编辑器没有原生富文本粘贴能力')
    if(!editor.state.doc.eq(target.doc)||!editor.state.selection.eq(target.selection))throw new Error('读取剪贴板期间选区已变化，请重新粘贴')
    controls.paste({html,text},mode);return
  }
  const plain = text || (html ? htmlToText(html) : '')
  const normalized = plain.replace(/\r\n?/g, '\n')
  // 图片优先级对照 paste-actions.ts:125：picture 模式直接粘贴位图；默认粘贴
  // 只在无 html 且无有效文本时兜底（OS 剪贴板常在 image/png 旁带空 text/plain）。
  if (mode === 'picture' || (mode !== 'text' && image && !html && !plain.trim())) {
    if (!image) throw new Error('剪贴板中没有图片')
    await insertDocxImageFile(editor, image, target)
    return
  }
  if (!normalized.trim()) throw new Error('剪贴板为空或没有可粘贴的文本')
  if (normalized.length > MAX_PASTE_CHARS) throw new Error(`粘贴文本超过长度上限（${MAX_PASTE_CHARS} 字符），请分批粘贴`)
  if (PASTE_CONTROL_CHARS.test(normalized)) throw new Error('粘贴文本包含制表符或其他控制字符，暂不支持；请先在来源中替换为空格或换行')
  const paragraphs = normalized.split('\n')
  if (paragraphs.length > MAX_PASTE_PARAGRAPHS) throw new Error(`粘贴文本超过段落上限（${MAX_PASTE_PARAGRAPHS} 段），请分批粘贴`)
  const schema = editor.state.schema
  const nodeType = schema.nodes.docParagraph
  if (!nodeType) throw new Error('文档结构不支持粘贴')
  const blocks = paragraphs.map(line => nodeType.create(null, line ? schema.text(line) : undefined))
  const tr = editor.state.tr
    .replaceSelection(new Slice(Fragment.from(blocks), 1, 1))
    .setMeta('paste', true)
    .setMeta('uiEvent', 'paste')
  editor.view.dispatch(tr.scrollIntoView())
}

/** Ribbon.tsx:2234 clipboard()：document.execCommand 路径，不越权访问剪贴板 API */
function execClipboardCommand(editor: Editor, action: 'copy' | 'cut', label: string, chord: string): void {
  if (typeof document.execCommand !== 'function') throw new Error(`当前浏览器不支持剪贴板${label}命令`)
  editor.commands.focus()
  let ok = false
  try { ok = document.execCommand(action) } catch { ok = false }
  if (!ok) throw new Error(`浏览器拒绝了剪贴板${label}权限，请重试或改用键盘 ${chord}`)
}

export function docxClipboardCopy(editor: Editor): void {
  if (editor.state.selection.empty) throw new Error('请先选择要复制的内容')
  execClipboardCommand(editor, 'copy', '复制', 'Ctrl+C')
}

export function docxClipboardCut(editor: Editor): void {
  if (!editor.isEditable) throw new Error('当前文档不可编辑')
  if (editor.state.selection.empty) throw new Error('请先选择要剪切的内容')
  execClipboardCommand(editor, 'cut', '剪切', 'Ctrl+X')
}

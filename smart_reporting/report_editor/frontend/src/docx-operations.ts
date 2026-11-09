import { highlightMap, paragraphHighlight, safeDocxHighlight, withoutHighlight } from './docx-highlight'
import { docxBorderAttrs, paragraphBorders, safeDocxBorderSpec } from './docx-borders'
import { safeDocxShading } from './docx-shading'
import { paragraphVerticalAlign, withoutVerticalAlign, verticalAlignMap } from './docx-vertical'
import { TABLE_KINDS, projectDocxTable, tableIntent } from './docx-tables'
import { newTableMatchesProjection, newTableNodeCells, newTableSize, projectNewDocxTable } from './docx-new-table'
import { coverGroupMatchesProjection, coverGroupParas, isCoverEndNode, projectCoverNodes } from './docx-cover-page'
import type { Schema } from '@tiptap/pm/model'
import type { NativeOperation } from './native-draft'
import type { SectionSettings } from '@genoffice/docx-engine'
export interface DocxCellAnchor { cellId: string; expectedObjectSha256: string; editable: boolean }
import { safeParagraphStyle, type DocxStyleInfo } from './docx-styles'
import { restoredDocxHeaderFooterOperations } from './docx-hf'
export interface DocxAnchor { docxIndex: number; blockId: string; expectedObjectSha256: string; editable: boolean; deletable?: boolean; paragraphStyleEditable?: boolean; paragraphStyleReadOnlyReason?: string | null; links?: { from: number; to: number; href: string }[]; cells?: DocxCellAnchor[][]; structureEditable?: boolean; structureReadOnlyReason?: string | null; tableWidthsTwips?: number[]; tableHeaderCount?: number }
export interface DocxPmNode { type: string; attrs?: Record<string, unknown>; text?: string; marks?: { type: string; attrs?: Record<string, unknown> }[]; content?: DocxPmNode[] }
export interface DocxSectionAnchor { sectionId: string; expectedSectionSha256: string; settings: SectionSettings }
type SectionValues = Partial<Pick<SectionSettings, 'orientation' | 'pageWidth' | 'pageHeight' | 'marginTop' | 'marginRight' | 'marginBottom' | 'marginLeft' | 'columns' | 'headerDist' | 'footerDist'>>
export function restoredDocxSectionOperation(operations: NativeOperation[], section?: DocxSectionAnchor) {
  let values: SectionValues | undefined
  const numericLimits: Record<string, [number, number]> = { pageWidth: [1440, 31680], pageHeight: [1440, 31680],
    marginTop: [0, 14400], marginRight: [0, 14400], marginBottom: [0, 14400], marginLeft: [0, 14400], columns: [1, 3], headerDist: [0, 31680], footerDist: [0, 31680] }
  for (const operation of operations) {
    if (operation.kind !== 'setSectionLayout') continue
    if (!section || operation.sectionId !== section.sectionId || operation.expectedSectionSha256 !== section.expectedSectionSha256) throw new Error('草稿页面设置的节身份与当前来源不一致')
    const patch = operation.values
    if (Object.keys(operation).some(key => !['kind', 'sectionId', 'expectedSectionSha256', 'values'].includes(key))
      || !patch || typeof patch !== 'object' || Array.isArray(patch) || !Object.keys(patch).length) throw new Error('草稿页面设置无效')
    for (const [key, value] of Object.entries(patch)) {
      if (key === 'orientation') { if (value !== 'portrait' && value !== 'landscape') throw new Error('草稿纸张方向无效') }
      else {
        const limit = numericLimits[key]
        if (!limit || typeof value !== 'number' || !Number.isInteger(value) || value < limit[0] || value > limit[1]) throw new Error('草稿页面设置数值无效')
      }
    }
    values = { ...values, ...patch }
  }
  if (!values || !section) return undefined
  const settings = { ...section.settings, ...values }
  if (settings.marginLeft + settings.marginRight >= settings.pageWidth || settings.marginTop + settings.marginBottom >= settings.pageHeight) throw new Error('草稿页边距超出纸张大小')
  return { kind: 'setSectionLayout', sectionId: section.sectionId, expectedSectionSha256: section.expectedSectionSha256, values }
}
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const textOf = (node: DocxPmNode): string => node.text ?? (node.type === 'docHardBreak' ? '\n' : (node.content ?? []).map(textOf).join(''))
const paragraph = (node: DocxPmNode) => ['docParagraph', 'docHeading', 'docListItem'].includes(node.type)
const idOf = (node: DocxPmNode) => node.attrs?.docxIndex
const baseOp = (a: DocxAnchor) => ({ blockId: a.blockId, expectedObjectSha256: a.expectedObjectSha256 })
const withoutAlignment = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => key !== 'align'))
const withoutIndent = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !['indentLeft', 'indentRight'].includes(key)))
const paragraphSpacingKeys = ['spaceBefore', 'spaceAfter', 'lineSpacing', 'lineRule', 'lineRawTwips', 'spaceBeforeAuto', 'spaceAfterAuto']
const withoutParagraphSpacing = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !paragraphSpacingKeys.includes(key)))
const withoutParagraphShading = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !['shadingFill', 'shadingClear'].includes(key)))
const withoutParagraphBorders = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !['borders', 'borderLines'].includes(key)))
const withoutPageBreakBefore = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => key !== 'pageBreakBefore'))
const withoutList = (attrs: DocxPmNode['attrs']) => Object.fromEntries(Object.entries(attrs ?? {}).filter(([key]) => !['kind', 'numId', 'ilvl'].includes(key)))
const listOf = (node: DocxPmNode) => node.type === 'docListItem' ? { kind: node.attrs?.kind, numId: node.attrs?.numId, ilvl: node.attrs?.ilvl } : null
function structure(node: DocxPmNode, marks = true): unknown {
  const content: unknown[] = []
  for (const child of node.content ?? []) {
    if (child.type === 'text' && !marks) continue
    const shape = structure(child, marks)
    if (child.type === 'text' && content.length && same(content[content.length - 1], shape)) continue
    content.push(shape)
  }
  return { type: node.type, attrs: node.attrs, marks: marks ? node.marks : undefined, content }
}
const plainTyping = (run: DocxPmNode) => (run.marks ?? []).every(mark => mark.type === 'textStyle' && Object.values(mark.attrs ?? {}).every(value => value == null || value === false))
/** 单元格只改文字：段落结构与属性不变；有文字的段落保持 run 格式，空段落（如新建表格的空格子）只允许新增普通文字。 */
function cellTextEditOnly(cell: DocxPmNode, changed: DocxPmNode): boolean {
  if (!same(structure(cell, false), structure(changed, false))) return false
  return (cell.content ?? []).every((left, index) => {
    const right = changed.content![index]
    if (same(structure(left), structure(right))) return true
    return !(left.content ?? []).some(run => run.type === 'text') && (right.content ?? []).every(run => run.type !== 'text' || plainTyping(run))
  })
}
function markSequence(node: DocxPmNode): unknown[] {
  const result: unknown[] = []
  for (const run of node.content ?? []) if (run.type === 'text') {
    const marks = run.marks ?? []
    if (!result.length || !same(result[result.length - 1], marks)) result.push(marks)
  }
  return result
}
export function safeDocxLink(value: unknown): string {
  if (typeof value !== 'string') throw new Error('请输入有效的链接地址')
  const href = value.trim()
  if (!href || href.length > 4096 || /[\s\u0000-\u001f\u007f]/u.test(href)) throw new Error('链接地址不能包含空白或控制字符')
  let url: URL
  try { url = new URL(href) } catch { throw new Error('仅支持完整的 http、https 或 mailto 链接') }
  if (!['http:', 'https:', 'mailto:'].includes(url.protocol) || (url.protocol !== 'mailto:' && !/^https?:\/\//i.test(href)) || url.username || url.password
    || (url.protocol === 'mailto:' && (!url.pathname || url.pathname.startsWith('//')))) throw new Error('仅支持安全的 http、https 或 mailto 链接')
  return href
}
export function validDocxLinkRange(text: string, from: unknown, to: unknown): boolean {
  const boundary = (at: number) => !(at > 0 && at < text.length && /[\uD800-\uDBFF]/.test(text[at - 1]) && /[\uDC00-\uDFFF]/.test(text[at]))
  return typeof from === 'number' && typeof to === 'number' && Number.isInteger(from) && Number.isInteger(to)
    && from >= 0 && to > from && to <= text.length && boundary(from) && boundary(to)
}
const withoutLinks = (node: DocxPmNode): DocxPmNode => ({ ...node, content: node.content?.map(run => ({ ...run, marks: (run.marks ?? []).filter(mark => mark.type !== 'link') })) })
/** 保存协议开放的粘贴图片格式（引擎 NewImage 另支持 gif，粘贴不开放） */
export const DOCX_PASTE_IMAGE_MIMES = ['image/png', 'image/jpeg'] as const
export const DOCX_PASTE_IMAGE_MAX_BYTES = 8 * 1024 * 1024
export const DOCX_PASTE_IMAGE_MAX_EDGE_PX = 10000
export interface DocxPastedImage { mime: (typeof DOCX_PASTE_IMAGE_MIMES)[number]; base64: string; widthPx: number; heightPx: number }
const CANONICAL_BASE64 = /^[A-Za-z0-9+/]+={0,2}$/
/** 新插入粘贴图片节点（docProtected/genImage）的协议内载荷；null = 非图片新增节点。 */
export function pastedDocxImage(node: DocxPmNode): DocxPastedImage | null {
  if (node.type !== 'docProtected' || node.attrs?.blockType !== 'image') return null
  const gen = node.attrs.genImage as Record<string, unknown> | null | undefined
  if (!gen || typeof gen !== 'object' || Array.isArray(gen)) throw new Error('新增图片缺少可保存的图片数据')
  if (Object.keys(gen).some(key => !['mime', 'base64', 'widthPx', 'heightPx'].includes(key))) throw new Error('新增图片数据包含不支持的字段')
  if (!(DOCX_PASTE_IMAGE_MIMES as readonly string[]).includes(String(gen.mime))) throw new Error('仅支持粘贴 PNG 或 JPEG 图片')
  const base64 = gen.base64
  if (typeof base64 !== 'string' || !base64.length || base64.length % 4 !== 0 || !CANONICAL_BASE64.test(base64)
    || base64.length > Math.ceil(DOCX_PASTE_IMAGE_MAX_BYTES / 3) * 4) throw new Error('粘贴图片数据无效或超过 8MB 大小上限')
  let rawLength = 0
  try { rawLength = atob(base64).length } catch { throw new Error('粘贴图片数据不是有效的 base64') }
  if (rawLength < 1 || rawLength > DOCX_PASTE_IMAGE_MAX_BYTES) throw new Error('粘贴图片超过 8MB 大小上限')
  for (const key of ['widthPx', 'heightPx'] as const) {
    const value = gen[key]
    if (!Number.isInteger(Number(value)) || Number(value) < 1 || Number(value) > DOCX_PASTE_IMAGE_MAX_EDGE_PX) throw new Error('粘贴图片的显示尺寸超出可保存范围')
  }
  return { mime: gen.mime as DocxPastedImage['mime'], base64, widthPx: Number(gen.widthPx), heightPx: Number(gen.heightPx) }
}
function draftImagePayload(value: unknown): DocxPastedImage {
  const gen = value
  if (!gen || typeof gen !== 'object' || Array.isArray(gen)) throw new Error('草稿图片粘贴数据无效')
  return pastedDocxImage({ type: 'docProtected', attrs: { blockType: 'image', genImage: gen } })
    ?? (() => { throw new Error('草稿图片粘贴数据无效') })()
}
function linkMap(node: DocxPmNode): (string | null)[] {
  return (node.content ?? []).flatMap(run => Array.from({ length: textOf(run).length }, () => {
    const marks = (run.marks ?? []).filter(mark => mark.type === 'link')
    if (marks.length > 1) throw new Error('链接标记无效')
    return marks.length ? safeDocxLink(marks[0].attrs?.href) : null
  }))
}
function linkMetadata(node: DocxPmNode) {
  return (node.content ?? []).flatMap(run => Array.from({ length: textOf(run).length }, () => {
    const attrs = run.marks?.find(mark => mark.type === 'link')?.attrs
    return attrs ? { tooltip: attrs.tooltip ?? null, plain: attrs.plain ?? false } : undefined
  }))
}
function compatibleLinkGroups(node: DocxPmNode) {
  let previous: Record<string, unknown> | undefined
  for (const run of node.content ?? []) {
    const link = run.marks?.find(mark => mark.type === 'link')?.attrs
    if (link && previous && link.href === previous.href && !(link.rId && previous.rId && link.rId !== previous.rId)) {
      if ((link.tooltip ?? '') !== (previous.tooltip ?? '')) throw new Error('相邻同地址链接的提示不同，暂不支持此链接修改')
      previous = { ...previous, rId: previous.rId ?? link.rId }
    } else previous = link
  }
}
/** Split only targeted text; keep every unrelated mark and link attribute unchanged. */
function applyLink(node: DocxPmNode, from: number, to: number, href: string | null) {
  if ((node.content ?? []).some(run => run.type !== 'text')) throw new Error('含复杂内联对象的段落暂不支持链接修改')
  let offset = 0
  node.content = (node.content ?? []).flatMap(run => {
    const start = offset, end = offset += (run.text ?? '').length
    const cuts = [start, ...[from, to].filter(at => at > start && at < end), end].sort((a, b) => a - b)
    return cuts.slice(0, -1).map((at, index) => {
      const next = { ...run, text: run.text!.slice(at - start, cuts[index + 1] - start) }
      if (at >= from && at < to) next.marks = [...(run.marks ?? []).filter(mark => mark.type !== 'link'), ...(href === null ? [] : [{ type: 'link', attrs: { ...run.marks?.find(mark => mark.type === 'link')?.attrs, href, rId: null } }])]
      return next
    })
  })
  compatibleLinkGroups(node)
}
function styleOf(node: DocxPmNode): Record<string, unknown> {
  const runs = (node.content ?? []).filter(child => child.type === 'text')
  if (!runs.length) throw new Error('空段落暂不支持样式修改')
  const styles = runs.map(run => {
    const style: Record<string, unknown> = { bold: false, italic: false, underline: false, strike: false }
    for (const mark of run.marks ?? []) {
      if (['bold', 'italic', 'underline', 'strike'].includes(mark.type)) style[mark.type] = true
      else if (mark.type === 'textStyle' || mark.type === 'docTextStyle') for (const [key, value] of Object.entries(mark.attrs ?? {})) {
        if (value == null || value === false) continue
        if (key === 'color') style.color = String(value).replace(/^#/, '')
        else if (key === 'sizeHalfPoints' || key === 'fontSize') style.fontSize = key === 'sizeHalfPoints' ? Number(value) / 2 : Number(value)
        else if (key === 'font' || key === 'fontFamily') style.fontFamily = value
        else throw new Error('此文字样式暂不支持保存')
      }
      else throw new Error('此文字样式暂不支持保存')
    }
    return style
  })
  if (!styles.every(style => same(style, styles[0]))) throw new Error('暂不支持同段落内局部样式修改，请选择整个段落')
  return styles[0]
}
/** 原始XML和资源路径从不进入保存协议；变化仅映射为后端允许操作。 */
export function docxOperations(original: DocxPmNode, current: DocxPmNode, anchors: DocxAnchor[], sectionOperation?: NativeOperation, schema?: Schema, styles?: Map<string, DocxStyleInfo>, headerFooterOperations?: NativeOperation[]): NativeOperation[] {
  const before = original.content ?? [], after = current.content ?? []
  const byIndex = new Map(anchors.map(anchor => [anchor.docxIndex, anchor]))
  const retained = after.filter(node => idOf(node) != null)
  const positions = retained.map(node => before.findIndex(item => idOf(item) === idOf(node)))
  if (positions.some(index => index < 0) || new Set(retained.map(idOf)).size !== retained.length) throw new Error('文档锚点无效')
  if (positions.some((value, index) => index > 0 && value <= positions[index - 1])) throw new Error('暂不支持改变原对象顺序')
  const ops: NativeOperation[] = []
  for (let index = 0; index < after.length; index++) {
    const node = after[index]
    if (idOf(node) != null) continue
    const pastedImage = pastedDocxImage(node)
    if (pastedImage) {
      // 粘贴图片与 insertParagraph 同锚点语义：贴在最近的可编辑正文段前/后。
      const next = after.slice(index + 1).find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const previous = [...after.slice(0, index)].reverse().find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const fallback = before.find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const target = next ?? previous ?? fallback
      if (!target) throw new Error('新增图片没有可编辑的锚点段落')
      ops.push({ kind: 'insertParagraphImage', ...baseOp(byIndex.get(Number(idOf(target)))!), position: next || !previous ? 'before' : 'after', image: pastedImage })
      continue
    }
    if (node.attrs?.nativeCoverPage != null) {
      // 新增封面（docx-cover-page.ts）：必须位于文档开头，首段至分页结束段为一组，
      // 按首段携带的预设规格 + 当前各段文字重算投影并完全一致。
      if (!schema) throw new Error('新增封面需要编辑器结构信息')
      const end = after.findIndex((item, at) => at >= index && isCoverEndNode(item))
      if (index !== 0 || end < 0 || after.slice(index, end + 1).some(item => idOf(item) != null)) throw new Error('封面结构已改变，请删除后重新插入')
      const group = after.slice(index, end + 1)
      let paras: ReturnType<typeof coverGroupParas>
      try { paras = coverGroupParas(group) } catch { throw new Error('封面结构已改变，请删除后重新插入') }
      if (!coverGroupMatchesProjection(group, projectCoverNodes(paras, schema))) throw new Error('封面保存前只能修改占位文字；格式或段落修改请先保存')
      const target = after.slice(end + 1).find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      if (!target) throw new Error('封面后没有可编辑的锚点段落')
      ops.push({ kind: 'insertCoverPage', ...baseOp(byIndex.get(Number(idOf(target)))!), position: 'before', paras })
      index = end
      continue
    }
    if (node.type === 'docTable') {
      // 新增表格（docx-new-table.ts）：必须仍是按行列意图确定性投影出的空表。
      if (!schema) throw new Error('新增表格需要编辑器结构信息')
      let size: { rows: number; cols: number }
      try { size = newTableSize(node.attrs?.nativeTableInsert) } catch { throw new Error('只支持通过“插入表格”新建的表格；粘贴或复制的表格暂不支持保存') }
      const cells = newTableNodeCells(node)
      const typed = cells.some(row => row.some(text => text !== ''))
      let expected: DocxPmNode | undefined
      try { expected = projectNewDocxTable(size, schema, cells) } catch { expected = undefined }
      if (!expected || !newTableMatchesProjection(node, expected)) throw new Error('新增表格保存前只能输入纯文字；格式或布局修改请先保存')
      const next = after.slice(index + 1).find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const previous = [...after.slice(0, index)].reverse().find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const fallback = before.find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
      const target = next ?? previous ?? fallback
      if (!target) throw new Error('新增表格没有可编辑的锚点段落')
      ops.push({ kind: 'insertTable', ...baseOp(byIndex.get(Number(idOf(target)))!), position: next || !previous ? 'before' : 'after', rows: size.rows, cols: size.cols, ...(typed ? { cells } : {}) })
      continue
    }
    if (node.attrs?.styleId != null) throw new Error('新增段落请保存后再修改段落样式')
    if (node.attrs?.align != null) throw new Error('新增段落请保存后再修改对齐方式')
    if (node.attrs?.indentLeft != null) throw new Error('新增段落请保存后再修改缩进')
    if (node.type !== 'docParagraph' || (node.content ?? []).some(child => child.type !== 'text' || (child.marks ?? []).some(mark => mark.type !== 'textStyle' || Object.values(mark.attrs ?? {}).some(value => value != null && value !== false)))) throw new Error('新增段落暂只支持普通文字，请保存后再修改样式')
    const next = after.slice(index + 1).find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
    const previous = [...after.slice(0, index)].reverse().find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
    const fallback = before.find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
    const target = next ?? previous ?? fallback
    if (!target) throw new Error('新增段落没有可编辑的锚点')
    ops.push({ kind: 'insertParagraph', ...baseOp(byIndex.get(Number(idOf(target)))!), position: next || !previous ? 'before' : 'after', text: textOf(node), ...(node.attrs?.pageBreakBefore === true ? { pageBreakBefore: true } : {}) })
  }
  for (const node of before) {
    const anchor = byIndex.get(Number(idOf(node)))
    if (!anchor) throw new Error('文档锚点无效')
    const edited = after.find(item => idOf(item) === idOf(node))
    if (edited && same(node, edited) && ['spaceBefore', 'spaceAfter'].every(key => Object.is(node.attrs?.[key], edited.attrs?.[key]))) continue
    if (!edited) {
      // deletable：可编辑段落，或仅含图库封面隐藏书签的封面段（整段删除/替换已保存封面）。
      if (!(anchor.deletable ?? anchor.editable) || !paragraph(node)) throw new Error('只读对象不能删除')
      ops.push({ kind: 'deleteParagraph', ...baseOp(anchor) }); continue
    }
    if (node.type === 'docTable' && edited.type === 'docTable') {
      if (edited.attrs?.nativeTableStructure) {
        const intent = tableIntent(edited.attrs.nativeTableStructure)
        if (!same(edited, projectDocxTable(node, anchor, intent, schema))) throw new Error('表格结构修改后请先保存；同表文字、格式或第二次结构修改不能混用')
        ops.push({ ...baseOp(anchor), ...intent }); continue
      }
      if (!same(node.attrs, edited.attrs) || node.content?.length !== edited.content?.length) throw new Error('暂不支持修改表格布局')
      for (let row = 0; row < (node.content?.length ?? 0); row++) {
        const left = node.content![row], right = edited.content![row]
        if (!same(left.attrs, right.attrs) || left.content?.length !== right.content?.length) throw new Error('暂不支持修改表格布局')
        for (let col = 0; col < (left.content?.length ?? 0); col++) {
          const cell = left.content![col], changed = right.content![col]
          if (same(cell, changed)) continue
          const cellAnchor = anchor.cells?.[row]?.[col]
          if (!cellAnchor?.editable) throw new Error('只读单元格不能修改')
          if (!cellTextEditOnly(cell, changed)) throw new Error('暂不支持修改单元格结构或样式')
          ops.push({ kind: 'replaceCellText', blockId: anchor.blockId, cellId: cellAnchor.cellId, expectedObjectSha256: cellAnchor.expectedObjectSha256, text: (changed.content ?? []).map(textOf).join('\n') })
        }
      }
      continue
    }
    if (!same(node.attrs?.styleId ?? null, edited.attrs?.styleId ?? null)) {
      if (!(anchor.paragraphStyleEditable ?? anchor.editable) || node.type !== 'docParagraph' || edited.type !== 'docParagraph' || anchor.paragraphStyleEditable === false) throw new Error('此来源段落暂不支持切换样式')
      safeParagraphStyle(styles, edited.attrs?.styleId)
      const sourceStyle = node.attrs?.styleId ?? [...(styles?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
      if (sourceStyle != null) safeParagraphStyle(styles, sourceStyle)
      if (!same(node, { ...edited, attrs: { ...edited.attrs, styleId: node.attrs?.styleId } })) throw new Error('段落样式修改请先保存；同段文字和格式不能混用')
      ops.push({ kind: 'setParagraphStyle', ...baseOp(anchor), styleId: edited.attrs!.styleId })
      continue
    }
    if (!anchor.editable) throw new Error('只读对象不能修改')
    const beforeList = listOf(node), afterList = listOf(edited)
    const listLevelChanged = node.type === 'docListItem' && edited.type === 'docListItem'
      && beforeList?.kind === afterList?.kind && beforeList?.numId === afterList?.numId && beforeList?.ilvl !== afterList?.ilvl
    const listChanged = !same(beforeList, afterList) && !listLevelChanged
    if (listChanged) {
      if (!['docParagraph', 'docListItem'].includes(node.type) || !['docParagraph', 'docListItem'].includes(edited.type)) throw new Error('暂不支持标题转换列表')
      const list = edited.type === 'docListItem' ? edited.attrs?.kind : 'none'
      if (!['none', 'bullet', 'ordered'].includes(String(list)) || (list !== 'none' && (edited.attrs?.numId !== `native-${list}` || edited.attrs?.ilvl !== 0))) throw new Error('此列表定义或级别暂不支持保存')
      ops.push({ kind: 'setParagraphList', ...baseOp(anchor), list })
    }
    if (listLevelChanged) {
      const ilvl = edited.attrs?.ilvl
      if (typeof ilvl !== 'number' || !Number.isInteger(ilvl) || ilvl < 0 || ilvl > 8) throw new Error('此列表级别暂不支持保存')
      ops.push({ kind: 'setParagraphListLevel', ...baseOp(anchor), ilvl })
    }
    const originalAttrs = node.type === 'docListItem' ? withoutList(node.attrs) : node.attrs
    const editedAttrs = edited.type === 'docListItem' ? withoutList(edited.attrs) : edited.attrs
    if ((!listChanged && node.type !== edited.type) || !same(withoutPageBreakBefore(withoutParagraphBorders(withoutParagraphShading(withoutParagraphSpacing(withoutIndent(withoutAlignment(originalAttrs)))))), withoutPageBreakBefore(withoutParagraphBorders(withoutParagraphShading(withoutParagraphSpacing(withoutIndent(withoutAlignment(editedAttrs)))))))) throw new Error('暂不支持改变段落布局')
    const pageBreakChanged = !!node.attrs?.pageBreakBefore !== !!edited.attrs?.pageBreakBefore
    if (pageBreakChanged) {
      // 固定源 page-break.ts：分页符 = 段落 pageBreakBefore；与底纹同规走原 XML 最小修改，
      // 不能与同段其他改动混存（段中插入分页的拆分段由 insertParagraph 携带分页）。
      if (!same(node, { ...edited, attrs: { ...edited.attrs, pageBreakBefore: node.attrs?.pageBreakBefore ?? false } })) throw new Error('分页符修改请先保存；同段文字和格式不能混用')
      ops.push({ kind: 'setParagraphPageBreakBefore', ...baseOp(anchor), value: !!edited.attrs?.pageBreakBefore })
    }
    const shadingChanged = !same(node.attrs?.shadingFill ?? null, edited.attrs?.shadingFill ?? null) || !same(node.attrs?.shadingClear ?? null, edited.attrs?.shadingClear ?? null)
    if (shadingChanged) {
      // 与段落样式同规：底纹走原 XML 最小修改，不能与同段其他改动混存。
      if (!same(node, { ...edited, attrs: { ...edited.attrs, shadingFill: node.attrs?.shadingFill ?? null, shadingClear: node.attrs?.shadingClear ?? null } })) throw new Error('段落底纹修改请先保存；同段文字和格式不能混用')
      const shading = safeDocxShading(edited.attrs?.shadingClear === true ? 'auto' : edited.attrs?.shadingFill ?? 'none')
      ops.push({ kind: 'setParagraphShading', ...baseOp(anchor), fill: shading.fill, clear: shading.clear })
    }
    const bordersChanged = !same(node.attrs?.borders ?? null, edited.attrs?.borders ?? null) || !same(node.attrs?.borderLines ?? null, edited.attrs?.borderLines ?? null)
    if (bordersChanged) {
      // 与底纹同规：边框走原 XML 最小修改，不能与同段其他改动混存。
      if (!same(node, { ...edited, attrs: { ...edited.attrs, borders: node.attrs?.borders ?? null, borderLines: node.attrs?.borderLines ?? null } })) throw new Error('段落边框修改请先保存；同段文字和格式不能混用')
      ops.push({ kind: 'setParagraphBorders', ...baseOp(anchor), borders: safeDocxBorderSpec(paragraphBorders(edited)) })
    }
    const changedSpacing: Record<string, number> = {}
    for (const key of ['spaceBefore', 'spaceAfter'] as const) if (!Object.is(node.attrs?.[key], edited.attrs?.[key])
      || !same(node.attrs?.[`${key}Auto`] ?? null, edited.attrs?.[`${key}Auto`] ?? null)) {
      const value = edited.attrs?.[key]
      if (typeof value !== 'number' || !Number.isFinite(value) || !Number.isInteger(value) || value < 0 || value > 14400) throw new Error('此段前/段后间距暂不支持保存')
      changedSpacing[key] = value
    }
    if (!same(node.attrs?.lineSpacing, edited.attrs?.lineSpacing) || !same(node.attrs?.lineRule, edited.attrs?.lineRule) || !same(node.attrs?.lineRawTwips, edited.attrs?.lineRawTwips)) {
      const value = edited.attrs?.lineSpacing
      if (typeof value !== 'number' || ![1, 1.15, 1.5, 2, 2.5, 3].includes(value)) throw new Error('此行距暂不支持保存')
      if (edited.attrs?.lineRule != null || edited.attrs?.lineRawTwips != null) throw new Error('精确行距和至少行距暂不支持保存')
      changedSpacing.lineSpacing = value
    }
    for (const [autoKey, valueKey] of [['spaceBeforeAuto', 'spaceBefore'], ['spaceAfterAuto', 'spaceAfter']] as const) {
      if ((valueKey in changedSpacing && edited.attrs?.[autoKey] != null) || (!same(node.attrs?.[autoKey], edited.attrs?.[autoKey]) && !(valueKey in changedSpacing))) throw new Error('自动段前/段后间距暂不支持保存')
    }
    if (Object.keys(changedSpacing).length) ops.push({ kind: 'setParagraphSpacing', ...baseOp(anchor), ...changedSpacing })
    if (!same(node.attrs?.indentLeft, edited.attrs?.indentLeft)) {
      const twips = edited.attrs?.indentLeft ?? 0
      if (!Number.isInteger(twips) || Number(twips) < 0 || Number(twips) > 14400 || Number(twips) % 720 !== 0 || edited.type === 'docListItem') throw new Error('此段落缩进暂不支持保存')
      ops.push({ kind: 'setParagraphIndent', ...baseOp(anchor), twips })
    }
    if (!same(node.attrs?.indentRight, edited.attrs?.indentRight)) {
      const twips = edited.attrs?.indentRight ?? 0
      if (!Number.isInteger(twips) || Number(twips) < -14400 || Number(twips) > 14400) throw new Error('此段落右缩进值无效')
      ops.push({ kind: 'setParagraphRightIndent', ...baseOp(anchor), twips })
    }
    if (!same(node.attrs?.align, edited.attrs?.align)) {
      const alignment = edited.attrs?.align ?? (edited.attrs?.bidi === true || edited.attrs?.bidiInferred === true ? 'right' : 'left')
      if (!['left', 'center', 'right', 'justify'].includes(String(alignment))) throw new Error('此段落对齐方式暂不支持保存')
      ops.push({ kind: 'setParagraphAlignment', ...baseOp(anchor), alignment })
    }
    if (!same(structure(node, false), structure({ ...edited, type: node.type, attrs: node.attrs }, false))) throw new Error('暂不支持改变段落结构')
    const oldLinks = linkMap(node), newLinks = linkMap(edited), textChanged = textOf(node) !== textOf(edited)
    if (textChanged && oldLinks.some(Boolean)) throw new Error('含已有链接的段落请先单独修改链接；文字编辑暂不支持保留原链接元数据')
    if (textChanged) ops.push({ kind: 'replaceParagraph', ...baseOp(anchor), text: textOf(edited) })
    const beforeMetadata = textChanged ? [] : linkMetadata(node), afterMetadata = linkMetadata(edited)
    if (afterMetadata.some((metadata, index) => metadata && !same(metadata, beforeMetadata[index] ?? { tooltip: null, plain: false }))) throw new Error('暂不支持修改链接提示或显示属性')
    const comparison = textChanged ? newLinks.map(() => null) : oldLinks
    const linkedPreview = textChanged ? withoutLinks(edited) : structuredClone(node)
    for (let from = 0; from < newLinks.length;) {
      if (newLinks[from] === comparison[from]) { from++; continue }
      const href = newLinks[from]
      let to = from + 1
      while (to < newLinks.length && newLinks[to] === href && newLinks[to] !== comparison[to]) to++
      if (!validDocxLinkRange(textOf(edited), from, to)) throw new Error('链接范围不能拆开 Unicode 字符')
      if ((edited.content ?? []).some(run => run.type !== 'text')) throw new Error('含复杂内联对象的段落暂不支持链接修改')
      applyLink(linkedPreview, from, to, href)
      ops.push({ kind: 'setParagraphLink', ...baseOp(anchor), from, to, href })
      from = to
    }
    const oldVertical = paragraphVerticalAlign(node), newVertical = paragraphVerticalAlign(edited)
    if (textOf(edited) && ((oldVertical !== newVertical && !(textOf(node) === '' && newVertical === 'baseline'))
      || (oldVertical === undefined && newVertical === undefined && !same(verticalAlignMap(node), verticalAlignMap(edited))))) {
      if (!newVertical) throw new Error('暂不支持局部上下标修改，请选择整个段落')
      ops.push({ kind: 'setParagraphVerticalAlign', ...baseOp(anchor), value: newVertical })
    }
    const oldHighlight = paragraphHighlight(node), newHighlight = paragraphHighlight(edited)
    if (textOf(edited) && ((oldHighlight ?? null) !== (newHighlight ?? null) || (!textChanged && !same(highlightMap(node), highlightMap(edited))))) {
      if (newHighlight == null) throw new Error('暂不支持局部高亮修改或移除覆盖；请选择整段并使用无颜色')
      ops.push({ kind: 'formatParagraph', ...baseOp(anchor), style: { highlight: safeDocxHighlight(newHighlight) } })
    }
    if ((edited.content ?? []).some(child => child.type === 'text') && !same(markSequence(withoutHighlight(withoutVerticalAlign(withoutLinks(node)))), markSequence(withoutHighlight(withoutVerticalAlign(withoutLinks(edited)))))) {
      const old = (node.content ?? []).some(child => child.type === 'text') ? styleOf(withoutHighlight(withoutVerticalAlign(withoutLinks(node)))) : { bold: false, italic: false, underline: false, strike: false }, next = styleOf(withoutHighlight(withoutVerticalAlign(withoutLinks(edited))))
      if (['color', 'fontFamily', 'fontSize'].some(key => key in old && !(key in next))) throw new Error('暂不支持清除段落字体、字号或颜色')
      const changed = Object.fromEntries(Object.entries(next).filter(([key, value]) => !same(value, old[key])))
      if (Object.keys(changed).length) ops.push({ kind: 'formatParagraph', ...baseOp(anchor), style: changed })
    }
  }
  if (sectionOperation) ops.push(sectionOperation)
  if (headerFooterOperations?.length) ops.push(...headerFooterOperations)
  if (ops.length > 500) throw new Error('操作超过 500 条，请分批保存')
  return ops
}

/** 从原文件恢复草稿，保持原 docxIndex 和对象身份。 */
export function replayDocxOperations(original: DocxPmNode, operations: NativeOperation[], anchors: DocxAnchor[], section?: DocxSectionAnchor, schema?: Schema, styles?: Map<string, DocxStyleInfo>, headerFooters?: { anchor?: { sectionId: string; expectedSectionSha256: string }; model?: import('./docx-hf').DocxHeadersFootersModel }): DocxPmNode {
  restoredDocxSectionOperation(operations, section)
  if (headerFooters) restoredDocxHeaderFooterOperations(operations, headerFooters.anchor, headerFooters.model)
  const result = structuredClone(original), originalNodes = new Map((result.content ?? []).map(node => [Number(idOf(node)), node]))
  const byId = new Map(anchors.map(anchor => [anchor.blockId, anchor])), afterCounts = new Map<string, number>()
  const replaceText = (node: DocxPmNode, value: string) => {
    let remaining = Array.from(value)
    const runs = (node.content ?? []).filter(child => child.type === 'text')
    if (!runs.length) { node.content = value ? [{ type: 'text', text: value }] : []; return }
    runs.forEach((run, index) => { run.text = remaining.splice(0, index === runs.length - 1 ? remaining.length : Array.from(run.text ?? '').length).join('') })
    node.content = node.content?.filter(child => child.type !== 'text' || child.text)
  }
  const structural = new Set<string>()
  for (const operation of operations) if (TABLE_KINDS.includes(operation.kind as any)) {
    const id = String(operation.blockId)
    if (structural.has(id) || operations.some(other => other !== operation && other.blockId === id)) throw new Error('同表草稿不能混合文字或多次结构操作')
    structural.add(id)
  }
  for (const operation of operations) {
    if (operation.kind === 'setSectionLayout' || operation.kind === 'setHeaderFooter') continue
    const anchor = byId.get(String(operation.blockId)), node = anchor && originalNodes.get(anchor.docxIndex)
    if (!anchor || !node) throw new Error('草稿对象不属于当前 Word 文件')
    if (operation.kind === 'setParagraphStyle') {
      if (!(anchor.paragraphStyleEditable ?? anchor.editable) || node.type !== 'docParagraph' || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'styleId'].includes(key))
        || operations.some(other => other.blockId === operation.blockId && other.kind !== 'setParagraphStyle')) throw new Error('草稿段落样式字段或来源身份无效')
      safeParagraphStyle(styles, operation.styleId)
      const sourceStyle = node.attrs?.styleId ?? [...(styles?.values() ?? [])].find(style => style.type === 'paragraph' && style.isDefault)?.styleId
      if (sourceStyle != null) safeParagraphStyle(styles, sourceStyle)
      node.attrs = { ...node.attrs, styleId: operation.styleId }
    }
    else if (operation.kind === 'setParagraphShading') {
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'fill', 'clear'].includes(key))
        || (typeof operation.fill !== 'string' && operation.fill !== null)
        || (typeof operation.fill === 'string' && !/^[0-9a-f]{6}$/.test(operation.fill))
        || typeof operation.clear !== 'boolean'
        || operations.some(other => other.blockId === operation.blockId && other !== operation)) throw new Error('草稿段落底纹字段或来源身份无效')
      node.attrs = { ...node.attrs, shadingFill: operation.fill, shadingClear: operation.clear ? true : null }
    }
    else if (operation.kind === 'setParagraphPageBreakBefore') {
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'value'].includes(key))
        || typeof operation.value !== 'boolean'
        || operations.some(other => other.blockId === operation.blockId && other !== operation && other.kind !== 'insertParagraph' && other.kind !== 'insertParagraphImage')) throw new Error('草稿分页符字段或来源身份无效')
      node.attrs = { ...node.attrs, pageBreakBefore: operation.value }
    }
    else if (operation.kind === 'setParagraphBorders') {
      let borders: ReturnType<typeof safeDocxBorderSpec>
      try { borders = safeDocxBorderSpec(operation.borders) } catch { throw new Error('草稿段落边框字段或来源身份无效') }
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'borders'].includes(key))
        || node.attrs?.borderReset || node.attrs?.borderPad
        || operations.some(other => other.blockId === operation.blockId && other !== operation)) throw new Error('草稿段落边框字段或来源身份无效')
      node.attrs = { ...node.attrs, ...docxBorderAttrs(borders) }
    }
    else if (TABLE_KINDS.includes(operation.kind as any)) {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'index'].includes(key)) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('草稿表格身份或字段无效')
      const projected = projectDocxTable(node, anchor, { kind: operation.kind, index: operation.index }, schema)
      Object.assign(node, projected)
    }
    else if (operation.kind === 'setParagraphLink') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'from', 'to', 'href'].includes(key))) throw new Error('草稿链接包含不支持的字段')
      if (!anchor.editable || operation.expectedObjectSha256 !== anchor.expectedObjectSha256 || !paragraph(node)
        || !validDocxLinkRange(textOf(node), operation.from, operation.to)) throw new Error('草稿链接范围或对象身份无效')
      const href = operation.href === null ? null : safeDocxLink(operation.href)
      applyLink(node, Number(operation.from), Number(operation.to), href)
    }
    else if (operation.kind === 'setParagraphVerticalAlign') {
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'value'].includes(key))
        || !['baseline', 'superscript', 'subscript'].includes(String(operation.value)) || !(node.content ?? []).some(run => run.type === 'text' && !!run.text)) throw new Error('草稿上下标字段或来源身份无效')
      for (const run of node.content ?? []) {
        if (run.type !== 'text') continue
        const marks = run.marks ?? []
        const old = marks.find(mark => ['docTextStyle', 'textStyle'].includes(mark.type))
        const changed = { type: old?.type ?? 'docTextStyle', attrs: { ...old?.attrs, vertAlign: operation.value === 'baseline' ? null : operation.value } }
        run.marks = old ? marks.map(mark => mark === old ? changed : mark) : [...marks, changed]
      }
    }
    else if (operation.kind === 'replaceParagraph') replaceText(node, String(operation.text))
    else if (operation.kind === 'setParagraphIndent') {
      const twips = operation.twips
      if (!Number.isInteger(twips) || Number(twips) < 0 || Number(twips) > 14400 || Number(twips) % 720 !== 0) throw new Error('草稿段落缩进无效')
      node.attrs = { ...node.attrs, indentLeft: twips || null }
    }
    else if (operation.kind === 'setParagraphRightIndent') {
      const twips = operation.twips
      if (!Number.isInteger(twips) || Number(twips) < -14400 || Number(twips) > 14400) throw new Error('草稿右缩进值无效')
      node.attrs = { ...node.attrs, indentRight: twips || null }
    }
    else if (operation.kind === 'setParagraphList') {
      const list = operation.list
      if (!['none', 'bullet', 'ordered'].includes(String(list))) throw new Error('草稿列表类型无效')
      node.type = list === 'none' ? 'docParagraph' : 'docListItem'
      node.attrs = { ...withoutList(node.attrs), ...(list === 'none' ? {} : { kind: list, numId: `native-${list}`, ilvl: 0 }) }
    }
    else if (operation.kind === 'setParagraphListLevel') {
      const ilvl = operation.ilvl
      if (!Number.isInteger(ilvl) || Number(ilvl) < 0 || Number(ilvl) > 8 || node.type !== 'docListItem') throw new Error('草稿列表级别无效')
      node.attrs = { ...node.attrs, ilvl: Number(ilvl) }
    }
    else if (operation.kind === 'setParagraphAlignment') {
      if (!['left', 'center', 'right', 'justify'].includes(String(operation.alignment))) throw new Error('草稿段落对齐方式无效')
      node.attrs = { ...node.attrs, align: operation.alignment }
    }
    else if (operation.kind === 'setParagraphSpacing') {
      const values = operation as Record<string, unknown>
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(values).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'spaceBefore', 'spaceAfter', 'lineSpacing'].includes(key))) throw new Error('草稿段落间距字段或来源身份无效')
      if (!['spaceBefore', 'spaceAfter', 'lineSpacing'].some(key => values[key] !== undefined)) throw new Error('草稿段落间距无效')
      for (const key of ['spaceBefore', 'spaceAfter']) if (values[key] !== undefined && (typeof values[key] !== 'number' || !Number.isFinite(values[key]) || !Number.isInteger(values[key]) || (values[key] as number) < 0 || (values[key] as number) > 14400)) throw new Error('草稿段落间距无效')
      if (values.lineSpacing !== undefined && (typeof values.lineSpacing !== 'number' || ![1, 1.15, 1.5, 2, 2.5, 3].includes(values.lineSpacing as number))) throw new Error('草稿行距无效')
      node.attrs = { ...node.attrs,
        ...(values.spaceBefore !== undefined ? { spaceBefore: values.spaceBefore, spaceBeforeAuto: null } : {}),
        ...(values.spaceAfter !== undefined ? { spaceAfter: values.spaceAfter, spaceAfterAuto: null } : {}),
        ...(values.lineSpacing !== undefined ? { lineSpacing: values.lineSpacing, lineRule: null, lineRawTwips: null } : {}),
      }
    }
    else if (operation.kind === 'deleteParagraph') result.content = result.content?.filter(item => item !== node)
    else if (operation.kind === 'insertParagraph') {
      const index = result.content!.indexOf(node)
      if (index < 0) throw new Error('草稿插入锚点已删除')
      const offset = operation.position === 'after' ? (afterCounts.get(anchor.blockId) ?? 0) + 1 : 0
      if (operation.pageBreakBefore !== undefined && operation.pageBreakBefore !== true) throw new Error('草稿新增段落分页字段无效')
      result.content!.splice(index + offset, 0, { type: 'docParagraph', attrs: { ...node.attrs, docxIndex: null, pageBreakBefore: operation.pageBreakBefore === true }, ...(operation.text ? { content: [{ type: 'text', text: String(operation.text) }] } : {}) })
      if (operation.position === 'after') afterCounts.set(anchor.blockId, offset)
    }
    else if (operation.kind === 'insertCoverPage') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'position', 'paras'].includes(key)) || operation.position !== 'before'
        || !anchor.editable || operation.expectedObjectSha256 !== anchor.expectedObjectSha256 || !schema) throw new Error('草稿封面字段或来源身份无效')
      let cover: DocxPmNode[]
      try { cover = projectCoverNodes(operation.paras as never, schema) } catch { throw new Error('草稿封面字段或来源身份无效') }
      if (result.content!.indexOf(node) < 0) throw new Error('草稿插入锚点已删除')
      result.content!.splice(0, 0, ...cover)
    }
    else if (operation.kind === 'insertTable') {
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'position', 'rows', 'cols', 'cells'].includes(key))
        || (operation.position !== 'before' && operation.position !== 'after')
        || !anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256 || !schema) throw new Error('草稿新增表格字段或来源身份无效')
      let table: DocxPmNode
      try { table = projectNewDocxTable({ rows: operation.rows, cols: operation.cols }, schema, operation.cells === undefined ? undefined : operation.cells as string[][]) } catch { throw new Error('草稿新增表格字段或来源身份无效') }
      const index = result.content!.indexOf(node)
      if (index < 0) throw new Error('草稿插入锚点已删除')
      const offset = operation.position === 'after' ? (afterCounts.get(anchor.blockId) ?? 0) + 1 : 0
      result.content!.splice(index + offset, 0, table)
      if (operation.position === 'after') afterCounts.set(anchor.blockId, offset)
    }
    else if (operation.kind === 'insertParagraphImage') {
      // 与 insertParagraph 同回放语义；图片以 docProtected/genImage 形态回到草稿，
      // 与前端粘贴时创建的节点完全一致（filterTransaction/replay 一致性）。
      if (Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'position', 'image'].includes(key))
        || (operation.position !== 'before' && operation.position !== 'after')
        || !anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256) throw new Error('草稿图片粘贴字段或来源身份无效')
      const image = draftImagePayload(operation.image)
      const index = result.content!.indexOf(node)
      if (index < 0) throw new Error('草稿插入锚点已删除')
      const offset = operation.position === 'after' ? (afterCounts.get(anchor.blockId) ?? 0) + 1 : 0
      result.content!.splice(index + offset, 0, {
        type: 'docProtected',
        attrs: { docxIndex: null, blockType: 'image', label: '图片（粘贴）',
          imageDataUrl: `data:${image.mime};base64,${image.base64}`,
          imageWidthPx: image.widthPx, imageHeightPx: image.heightPx,
          genImage: { base64: image.base64, mime: image.mime, widthPx: image.widthPx, heightPx: image.heightPx } },
      })
      if (operation.position === 'after') afterCounts.set(anchor.blockId, offset)
    } else if (operation.kind === 'formatParagraph') {
      const style = operation.style as Record<string, unknown>
      if (!anchor.editable || !paragraph(node) || operation.expectedObjectSha256 !== anchor.expectedObjectSha256
        || Object.keys(operation).some(key => !['kind', 'blockId', 'expectedObjectSha256', 'style'].includes(key))
        || !style || typeof style !== 'object' || Array.isArray(style) || !Object.keys(style).length
        || Object.keys(style).some(key => !['bold', 'italic', 'underline', 'strike', 'fontSize', 'fontFamily', 'color', 'highlight'].includes(key))) throw new Error('草稿文字格式字段或来源身份无效')
      for (const key of ['bold', 'italic', 'underline', 'strike']) if (key in style && typeof style[key] !== 'boolean') throw new Error('草稿文字格式无效')
      if ('fontSize' in style && (typeof style.fontSize !== 'number' || !Number.isFinite(style.fontSize) || style.fontSize < 1 || style.fontSize > 200 || !Number.isInteger(style.fontSize * 2))) throw new Error('草稿字号无效')
      if ('fontFamily' in style && (typeof style.fontFamily !== 'string' || !style.fontFamily.trim() || style.fontFamily.length > 128 || /[\x00-\x1f]/.test(style.fontFamily))) throw new Error('草稿字体无效')
      if ('color' in style && (typeof style.color !== 'string' || !/^[a-f\d]{6}$/i.test(style.color))) throw new Error('草稿字体颜色无效')
      if ('highlight' in style) {
        safeDocxHighlight(style.highlight)
        if (!(node.content ?? []).some(run => run.type === 'text' && !!run.text) || (node.content ?? []).some(run => run.type !== 'text')) throw new Error('草稿高亮要求非空正文段落')
      }
      for (const run of node.content ?? []) {
        if (run.type !== 'text') continue
        run.marks = [...(run.marks ?? [])]
        for (const key of ['bold', 'italic', 'underline', 'strike']) if (key in style) {
          run.marks = run.marks.filter(mark => mark.type !== key)
          if (style[key]) run.marks.push({ type: key })
        }
        for (const [key, attr] of Object.entries({ color: 'color', fontSize: 'sizeHalfPoints', fontFamily: 'font', highlight: 'highlight' })) if (key in style) {
          let mark = run.marks.find(item => item.type === 'docTextStyle' || item.type === 'textStyle')
          if (!mark) { mark = { type: 'docTextStyle', attrs: {} }; run.marks.push(mark) }
          mark.attrs = { ...mark.attrs, [attr]: key === 'fontSize' ? Number(style[key]) * 2 : style[key] }
        }
      }
    } else if (operation.kind === 'replaceCellText') {
      const position = anchor.cells?.flatMap((row, r) => row.map((cell, c) => ({ ...cell, r, c }))).find(cell => cell.cellId === operation.cellId)
      const cell = position && node.content?.[position.r].content?.[position.c]
      if (!cell?.content?.length) throw new Error('草稿单元格身份无效')
      replaceText(cell.content[0], String(operation.text))
      for (const paragraph of cell.content.slice(1)) replaceText(paragraph, '')
    } else throw new Error('Word 草稿包含不支持的操作')
  }
  return result
}

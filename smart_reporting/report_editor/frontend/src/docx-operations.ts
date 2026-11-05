import type { NativeOperation } from './native-draft'
import type { SectionSettings } from '@genoffice/docx-engine'
export interface DocxCellAnchor { cellId: string; expectedObjectSha256: string; editable: boolean }
export interface DocxAnchor { docxIndex: number; blockId: string; expectedObjectSha256: string; editable: boolean; cells?: DocxCellAnchor[][] }
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
function markSequence(node: DocxPmNode): unknown[] {
  const result: unknown[] = []
  for (const run of node.content ?? []) if (run.type === 'text') {
    const marks = run.marks ?? []
    if (!result.length || !same(result[result.length - 1], marks)) result.push(marks)
  }
  return result
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
export function docxOperations(original: DocxPmNode, current: DocxPmNode, anchors: DocxAnchor[], sectionOperation?: NativeOperation): NativeOperation[] {
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
    if (node.attrs?.align != null) throw new Error('新增段落请保存后再修改对齐方式')
    if (node.attrs?.indentLeft != null) throw new Error('新增段落请保存后再修改缩进')
    if (node.type !== 'docParagraph' || (node.content ?? []).some(child => child.type !== 'text' || (child.marks ?? []).some(mark => mark.type !== 'textStyle' || Object.values(mark.attrs ?? {}).some(value => value != null && value !== false)))) throw new Error('新增段落暂只支持普通文字，请保存后再修改样式')
    const next = after.slice(index + 1).find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
    const previous = [...after.slice(0, index)].reverse().find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
    const fallback = before.find(item => idOf(item) != null && byIndex.get(Number(idOf(item)))?.editable)
    const target = next ?? previous ?? fallback
    if (!target) throw new Error('新增段落没有可编辑的锚点')
    ops.push({ kind: 'insertParagraph', ...baseOp(byIndex.get(Number(idOf(target)))!), position: next || !previous ? 'before' : 'after', text: textOf(node) })
  }
  for (const node of before) {
    const anchor = byIndex.get(Number(idOf(node)))
    if (!anchor) throw new Error('文档锚点无效')
    const edited = after.find(item => idOf(item) === idOf(node))
    if (edited && same(node, edited)) continue
    if (!edited) {
      if (!anchor.editable || !paragraph(node)) throw new Error('只读对象不能删除')
      ops.push({ kind: 'deleteParagraph', ...baseOp(anchor) }); continue
    }
    if (node.type === 'docTable' && edited.type === 'docTable') {
      if (!same(node.attrs, edited.attrs) || node.content?.length !== edited.content?.length) throw new Error('暂不支持修改表格布局')
      for (let row = 0; row < (node.content?.length ?? 0); row++) {
        const left = node.content![row], right = edited.content![row]
        if (!same(left.attrs, right.attrs) || left.content?.length !== right.content?.length) throw new Error('暂不支持修改表格布局')
        for (let col = 0; col < (left.content?.length ?? 0); col++) {
          const cell = left.content![col], changed = right.content![col]
          if (same(cell, changed)) continue
          const cellAnchor = anchor.cells?.[row]?.[col]
          if (!cellAnchor?.editable) throw new Error('只读单元格不能修改')
          if (!same(structure(cell), structure(changed))) throw new Error('暂不支持修改单元格结构或样式')
          ops.push({ kind: 'replaceCellText', blockId: anchor.blockId, cellId: cellAnchor.cellId, expectedObjectSha256: cellAnchor.expectedObjectSha256, text: (changed.content ?? []).map(textOf).join('\n') })
        }
      }
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
    if ((!listChanged && node.type !== edited.type) || !same(withoutParagraphSpacing(withoutIndent(withoutAlignment(originalAttrs))), withoutParagraphSpacing(withoutIndent(withoutAlignment(editedAttrs))))) throw new Error('暂不支持改变段落布局')
    const changedSpacing: Record<string, number> = {}
    for (const key of ['spaceBefore', 'spaceAfter'] as const) if (!same(node.attrs?.[key], edited.attrs?.[key])) {
      const value = edited.attrs?.[key] ?? 0
      if (typeof value !== 'number' || !Number.isInteger(value) || ![0, 240].includes(value)) throw new Error('此段前/段后间距暂不支持保存')
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
    if (textOf(node) !== textOf(edited)) ops.push({ kind: 'replaceParagraph', ...baseOp(anchor), text: textOf(edited) })
    if ((edited.content ?? []).some(child => child.type === 'text') && !same(markSequence(node), markSequence(edited))) {
      const old = (node.content ?? []).some(child => child.type === 'text') ? styleOf(node) : { bold: false, italic: false, underline: false, strike: false }, next = styleOf(edited)
      if (['color', 'fontFamily', 'fontSize'].some(key => key in old && !(key in next))) throw new Error('暂不支持清除段落字体、字号或颜色')
      const changed = Object.fromEntries(Object.entries(next).filter(([key, value]) => !same(value, old[key])))
      if (Object.keys(changed).length) ops.push({ kind: 'formatParagraph', ...baseOp(anchor), style: changed })
    }
  }
  if (sectionOperation) ops.push(sectionOperation)
  if (ops.length > 500) throw new Error('操作超过 500 条，请分批保存')
  return ops
}

/** 从原文件恢复草稿，保持原 docxIndex 和对象身份。 */
export function replayDocxOperations(original: DocxPmNode, operations: NativeOperation[], anchors: DocxAnchor[], section?: DocxSectionAnchor): DocxPmNode {
  restoredDocxSectionOperation(operations, section)
  const result = structuredClone(original), originalNodes = new Map((result.content ?? []).map(node => [Number(idOf(node)), node]))
  const byId = new Map(anchors.map(anchor => [anchor.blockId, anchor])), afterCounts = new Map<string, number>()
  const replaceText = (node: DocxPmNode, value: string) => {
    let remaining = Array.from(value)
    const runs = (node.content ?? []).filter(child => child.type === 'text')
    if (!runs.length) { node.content = value ? [{ type: 'text', text: value }] : []; return }
    runs.forEach((run, index) => { run.text = remaining.splice(0, index === runs.length - 1 ? remaining.length : Array.from(run.text ?? '').length).join('') })
    node.content = node.content?.filter(child => child.type !== 'text' || child.text)
  }
  for (const operation of operations) {
    if (operation.kind === 'setSectionLayout') continue
    const anchor = byId.get(String(operation.blockId)), node = anchor && originalNodes.get(anchor.docxIndex)
    if (!anchor || !node) throw new Error('草稿对象不属于当前 Word 文件')
    if (operation.kind === 'replaceParagraph') replaceText(node, String(operation.text))
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
      if (!['spaceBefore', 'spaceAfter', 'lineSpacing'].some(key => values[key] !== undefined)) throw new Error('草稿段落间距无效')
      for (const key of ['spaceBefore', 'spaceAfter']) if (values[key] !== undefined && (typeof values[key] !== 'number' || !Number.isInteger(values[key]) || ![0, 240].includes(values[key] as number))) throw new Error('草稿段落间距无效')
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
      result.content!.splice(index + offset, 0, { type: 'docParagraph', attrs: { ...node.attrs, docxIndex: null }, ...(operation.text ? { content: [{ type: 'text', text: String(operation.text) }] } : {}) })
      if (operation.position === 'after') afterCounts.set(anchor.blockId, offset)
    } else if (operation.kind === 'formatParagraph') {
      const style = operation.style as Record<string, unknown>
      for (const run of node.content ?? []) {
        if (run.type !== 'text') continue
        run.marks = [...(run.marks ?? [])]
        for (const key of ['bold', 'italic', 'underline', 'strike']) if (key in style) {
          run.marks = run.marks.filter(mark => mark.type !== key)
          if (style[key]) run.marks.push({ type: key })
        }
        for (const [key, attr] of Object.entries({ color: 'color', fontSize: 'sizeHalfPoints', fontFamily: 'font' })) if (key in style) {
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

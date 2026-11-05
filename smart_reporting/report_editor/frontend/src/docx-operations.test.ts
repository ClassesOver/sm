import { describe, expect, it } from 'vitest'
import { docxOperations, replayDocxOperations, type DocxAnchor } from './docx-operations'

const para = (id: number | null, text: string) => ({ type: 'docParagraph', attrs: { docxIndex: id }, content: text ? [{ type: 'text', text }] : [] })
const anchors: DocxAnchor[] = [{ docxIndex: 0, blockId: 'a', expectedObjectSha256: 'hash-a', editable: true }, { docxIndex: 1, blockId: 'b', expectedObjectSha256: 'hash-b', editable: false }]
const base = { type: 'doc', content: [para(0, '原文'), para(1, '复杂对象')] }

describe('DOCX snapshots to allowed operations', () => {
  it('binds replacement to original server anchor and never emits XML', () => {
    const next = structuredClone(base); next.content[0] = para(0, '新文')
    expect(docxOperations(base, next, anchors)).toEqual([{ kind: 'replaceParagraph', blockId: 'a', expectedObjectSha256: 'hash-a', text: '新文' }])
    expect(docxOperations(base, base, anchors)).toEqual([])
  })
  it('rejects readonly edits, reordered anchors and forged identities', () => {
    const next = structuredClone(base); next.content[1] = para(1, '不应修改')
    expect(() => docxOperations(base, next, anchors)).toThrow(/只读/)
    expect(() => docxOperations(base, { type: 'doc', content: [...base.content].reverse() }, anchors)).toThrow(/顺序/)
    expect(() => docxOperations(base, { type: 'doc', content: [para(9, '伪造')] }, anchors)).toThrow(/锚点/)
  })
  it('supports inserted and deleted paragraphs without touching protected blocks', () => {
    const next = { type: 'doc', content: [para(null, '新增'), base.content[1]] }
    expect(docxOperations(base, next, anchors)).toEqual([
      { kind: 'insertParagraph', blockId: 'a', expectedObjectSha256: 'hash-a', position: 'before', text: '新增' },
      { kind: 'deleteParagraph', blockId: 'a', expectedObjectSha256: 'hash-a' },
    ])
  })
  it('allows basic uniform paragraph marks and rejects XML/layout mutations', () => {
    const next = structuredClone(base) as any
    next.content[0].content[0].marks = [{ type: 'bold' }]
    expect(docxOperations(base, next, anchors)).toEqual([{ kind: 'formatParagraph', blockId: 'a', expectedObjectSha256: 'hash-a', style: { bold: true } }])
    next.content[0].attrs.rawPPr = '<w:evil/>'
    expect(() => docxOperations(base, next, anchors)).toThrow(/布局/)
  })
  it('maps only editable table cells and preserves their structure', () => {
    const cell = (text: string) => ({ type: 'docTableCell', content: [para(null, text)] })
    const original = { type: 'doc', content: [{ type: 'docTable', attrs: { docxIndex: 4 }, content: [{ type: 'docTableRow', content: [cell('旧值'), cell('保留')] }] }] }
    const tableAnchors = [{ docxIndex: 4, blockId: 'table', expectedObjectSha256: 'table-hash', editable: false, cells: [[{ cellId: 'c1', expectedObjectSha256: 'c1hash', editable: true }, { cellId: 'c2', expectedObjectSha256: 'c2hash', editable: false }]] }]
    const changed = structuredClone(original); changed.content[0].content[0].content[0] = cell('新值')
    expect(docxOperations(original, changed, tableAnchors)).toEqual([{ kind: 'replaceCellText', blockId: 'table', cellId: 'c1', expectedObjectSha256: 'c1hash', text: '新值' }])
    changed.content[0].content[0].content[1] = cell('不能改')
    expect(() => docxOperations(original, changed, tableAnchors)).toThrow(/只读/)
  })
  it('keeps strict table writeback limited to anchored cell text', () => {
    const cell = (text: string, fill: string | null = null) => ({ type: 'docTableCell', attrs: { fill }, content: [para(null, text)] })
    const original = { type: 'doc', content: [{ type: 'docTable', attrs: { docxIndex: 4, tblStyleId: 'TableGrid' }, content: [{ type: 'docTableRow', content: [cell('旧值')] }] }] }
    const tableAnchors = [{ docxIndex: 4, blockId: 'table', expectedObjectSha256: 'table-hash', editable: false, cells: [[{ cellId: 'cell-a', expectedObjectSha256: 'cell-hash', editable: true }]] }]
    const textChange = structuredClone(original)
    textChange.content[0].content[0].content[0] = cell('新值')
    expect(docxOperations(original, textChange, tableAnchors)).toEqual([
      { kind: 'replaceCellText', blockId: 'table', cellId: 'cell-a', expectedObjectSha256: 'cell-hash', text: '新值' },
    ])
    const styleChange = structuredClone(original)
    styleChange.content[0].attrs.tblStyleId = 'OtherStyle'
    expect(() => docxOperations(original, styleChange, tableAnchors)).toThrow(/表格布局/)
    const cellStyleChange = structuredClone(original)
    cellStyleChange.content[0].content[0].content[0] = cell('旧值', 'FF0000')
    expect(() => docxOperations(original, cellStyleChange, tableAnchors)).toThrow(/单元格结构或样式/)
  })
})


it('recovers stable source identities through replacement, formatting, insertion and deletion', () => {
  const operations = [
    { kind: 'insertParagraph', blockId: 'a', expectedObjectSha256: 'hash-a', position: 'before', text: '前插' },
    { kind: 'replaceParagraph', blockId: 'a', expectedObjectSha256: 'hash-a', text: '新文' },
    { kind: 'formatParagraph', blockId: 'a', expectedObjectSha256: 'hash-a', style: { bold: true } },
  ]
  const recovered = replayDocxOperations(base, operations, anchors)
  expect(docxOperations(base, recovered, anchors)).toEqual(operations)
  expect(base.content[0].content[0].text).toBe('原文')
})
it('allows clearing editable paragraph text while retaining its identity', () => {
  const next = structuredClone(base); next.content[0] = para(0, '')
  expect(docxOperations(base, next, anchors)).toEqual([{ kind: 'replaceParagraph', blockId: 'a', expectedObjectSha256: 'hash-a', text: '' }])
})
it('keeps inserted paragraph order when replaying multiple after operations', () => {
  const operations = ['一', '二'].map(text => ({ kind: 'insertParagraph', blockId: 'a', expectedObjectSha256: 'hash-a', position: 'after', text }))
  const recovered = replayDocxOperations(base, operations, anchors)
  expect(recovered.content?.map(node => node.content?.[0]?.text)).toEqual(['原文', '一', '二', '复杂对象'])
  expect(docxOperations(base, recovered, anchors)).toEqual(operations)
})

it('rejects unsaveable styles on new paragraphs instead of silently dropping them', () => {
  const inserted = { ...para(null, '新增'), content: [{ type: 'text', text: '新增', marks: [{ type: 'bold' }] }] }
  expect(() => docxOperations(base, { type: 'doc', content: [inserted, ...base.content] }, anchors)).toThrow(/普通文字/)
})

it('rejects hyperlink mark changes until an anchored hyperlink operation exists', () => {
  const original = { type: 'doc', content: [{ ...para(0, '链接文字'), content: [{ type: 'text', text: '链接文字' }] }] }
  const current = structuredClone(original) as any
  current.content[0].content[0].marks = [{ type: 'link', attrs: { href: 'https://example.test/path', rId: null } }]
  expect(() => docxOperations(original, current, anchors)).toThrow(/文字样式暂不支持保存/)
})

it.each(['left', 'center', 'right', 'justify'])('emits and replays anchored %s paragraph alignment without allowing other layout changes', alignment => {
  const original = { type: 'doc', content: [{ ...para(0, '正文'), attrs: { docxIndex: 0, align: 'center', indentLeft: 20 } }] }
  const current = structuredClone(original)
  current.content[0].attrs.align = alignment
  const operations = alignment === 'center' ? [] : [{ kind: 'setParagraphAlignment', blockId: 'a', expectedObjectSha256: 'hash-a', alignment }]
  expect(docxOperations(original, current, anchors)).toEqual(operations)
  expect(docxOperations(original, replayDocxOperations(original, operations, anchors), anchors)).toEqual(operations)
  current.content[0].attrs.indentLeft = 40
  expect(() => docxOperations(original, current, anchors)).toThrow(/缩进/)
})

it('resolves the upstream start alignment against paragraph direction and rejects unsupported alignments', () => {
  for (const [bidi, alignment] of [[false, 'left'], [true, 'right']] as const) {
    const original = { type: 'doc', content: [{ ...para(0, '正文'), attrs: { docxIndex: 0, align: 'center', bidi } }] }
    const current = structuredClone(original) as any
    current.content[0].attrs.align = null
    expect(docxOperations(original, current, anchors)).toEqual([{ kind: 'setParagraphAlignment', blockId: 'a', expectedObjectSha256: 'hash-a', alignment }])
    current.content[0].attrs.align = 'distribute'
    expect(() => docxOperations(original, current, anchors)).toThrow(/对齐/)
  }
})

it('rejects alignment on unsaved paragraphs and invalid replay values instead of dropping them', () => {
  const inserted = { ...para(null, '新增'), attrs: { docxIndex: null, align: 'center' } }
  expect(() => docxOperations(base, { type: 'doc', content: [inserted, ...base.content] }, anchors)).toThrow(/保存后再修改对齐/)
  expect(() => replayDocxOperations(base, [{ kind: 'setParagraphAlignment', blockId: 'a', alignment: 'distribute' }], anchors)).toThrow(/对齐方式无效/)
})

it.each(['bullet', 'ordered'])('binds %s list toggles to source anchors and replays without accepting numbering XML', kind => {
  const current = structuredClone(base) as any
  current.content[0] = { ...current.content[0], type: 'docListItem', attrs: { docxIndex: 0, kind, numId: `native-${kind}`, ilvl: 0 } }
  const operations = [{ kind: 'setParagraphList', blockId: 'a', expectedObjectSha256: 'hash-a', list: kind }]
  expect(docxOperations(base, current, anchors)).toEqual(operations)
  expect(docxOperations(base, replayDocxOperations(base, operations, anchors), anchors)).toEqual(operations)
  const plain = { type: 'doc', content: [para(0, '原文'), base.content[1]] }
  expect(docxOperations(current, plain, anchors)).toEqual([{ ...operations[0], list: 'none' }])
  current.content[0].attrs.numId = '<w:evil/>'
  expect(() => docxOperations(base, current, anchors)).toThrow(/列表/)
})

it('keeps heading, nested list level, readonly block and unrelated paragraph attributes outside list writeback', () => {
  const list = { type: 'docListItem', attrs: { docxIndex: 0, kind: 'bullet', numId: 'native-bullet', ilvl: 0 }, content: [{ type: 'text', text: '原文' }] }
  expect(() => docxOperations({ type: 'doc', content: [{ ...base.content[0], type: 'docHeading' }, base.content[1]] }, { type: 'doc', content: [list, base.content[1]] }, anchors)).toThrow(/标题/)
  const nested = { type: 'doc', content: [{ ...list, attrs: { ...list.attrs, ilvl: 1 } }, base.content[1]] }
  const levelOp = [{ kind: 'setParagraphListLevel', blockId: 'a', expectedObjectSha256: 'hash-a', ilvl: 1 }]
  expect(docxOperations({ type: 'doc', content: [list, base.content[1]] }, nested, anchors)).toEqual(levelOp)
  expect(docxOperations({ type: 'doc', content: [list, base.content[1]] }, replayDocxOperations({ type: 'doc', content: [list, base.content[1]] }, levelOp, anchors), anchors)).toEqual(levelOp)
  expect(() => docxOperations(base, { type: 'doc', content: [{ ...list, attrs: { ...list.attrs, ilvl: 9 } }, base.content[1]] }, anchors)).toThrow(/列表/)
  expect(() => docxOperations({ type: 'doc', content: [list, base.content[1]] }, { type: 'doc', content: [{ ...list, attrs: { ...list.attrs, ilvl: '1' } }, base.content[1]] }, anchors)).toThrow(/列表/)
  expect(() => docxOperations(base, { type: 'doc', content: [base.content[0], { ...list, attrs: { ...list.attrs, docxIndex: 1 } }] }, anchors)).toThrow(/只读/)
  expect(() => docxOperations(base, { type: 'doc', content: [{ ...base.content[0], attrs: { docxIndex: 0, kind: 'forged' } }, base.content[1]] }, anchors)).toThrow(/布局/)
})

it('carries an anchored section layout and validates its source identity before paragraph replay', () => {
  const section = { kind: 'setSectionLayout', sectionId: 'section-a', expectedSectionSha256: 'section-hash', values: { orientation: 'landscape', columns: 2 } }
  const source = { sectionId: 'section-a', expectedSectionSha256: 'section-hash', settings: { orientation: 'portrait' as const,
    pageWidth: 12240, pageHeight: 15840, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1, pageBorder: false } }
  const operations = docxOperations(base, base, anchors, section)
  expect(operations).toEqual([section])
  expect(docxOperations(base, replayDocxOperations(base, operations, anchors, source), anchors, section)).toEqual(operations)
  expect(() => replayDocxOperations(base, operations, anchors)).toThrow(/节身份/)
})

it('maps only source line-spacing presets and 12 pt before/after toggles to an anchored operation', () => {
  const original = { type: 'doc', content: [{ ...para(0, '行距正文'), attrs: { docxIndex: 0, spaceBefore: 0, spaceAfter: 120, lineSpacing: 1.5, lineRule: null, lineRawTwips: null } }] }
  const current = structuredClone(original) as any
  current.content[0].attrs.spaceBefore = 240
  current.content[0].attrs.spaceAfter = 0
  current.content[0].attrs.lineSpacing = 2
  current.content[0].attrs.lineRule = null
  current.content[0].attrs.lineRawTwips = null
  const operations = [{ kind: 'setParagraphSpacing', blockId: 'a', expectedObjectSha256: 'hash-a', spaceBefore: 240, spaceAfter: 0, lineSpacing: 2 }]
  expect(docxOperations(original, current, anchors)).toEqual(operations)
  expect(docxOperations(original, replayDocxOperations(original, operations, anchors), anchors)).toEqual(operations)
  current.content[0].attrs.lineSpacing = 1.2
  expect(() => docxOperations(original, current, anchors)).toThrow(/行距/)
})

it('reapplies an unchanged line-spacing preset while clearing its original raw rule', () => {
  const original = { type: 'doc', content: [{ ...para(0, '行距正文'), attrs: { docxIndex: 0, lineSpacing: 2, lineRule: 'auto', lineRawTwips: 480 } }] }
  const current = structuredClone(original) as any
  current.content[0].attrs.lineRule = null
  current.content[0].attrs.lineRawTwips = null
  const operations = [{ kind: 'setParagraphSpacing', blockId: 'a', expectedObjectSha256: 'hash-a', lineSpacing: 2 }]
  expect(docxOperations(original, current, anchors)).toEqual(operations)
  expect(docxOperations(original, replayDocxOperations(original, operations, anchors), anchors)).toEqual(operations)
})

it('rejects non-cleared raw line rules and automatic spacing alongside source spacing edits', () => {
  const original = { type: 'doc', content: [para(0, '行距正文')] }
  const line = structuredClone(original) as any
  line.content[0].attrs = { docxIndex: 0, lineSpacing: 2, lineRule: 'exact', lineRawTwips: 480 }
  expect(() => docxOperations(original, line, anchors)).toThrow(/行距/)
  const auto = structuredClone(original) as any
  auto.content[0].attrs = { docxIndex: 0, spaceBefore: 240, spaceBeforeAuto: true }
  expect(() => docxOperations(original, auto, anchors)).toThrow(/自动段前/)
  const originalAuto = structuredClone(original) as any
  originalAuto.content[0].attrs = { docxIndex: 0, spaceBefore: 0, spaceBeforeAuto: true }
  expect(() => docxOperations(originalAuto, auto, anchors)).toThrow(/自动段前/)
})

it.each([0, 720, 1440])('writes and replays an anchored %s-twip paragraph indent and rejects unrelated attrs', twips => {
  const original = { type: 'doc', content: [{ ...para(0, '正文'), attrs: { docxIndex: 0, indentLeft: 300, indentRight: 180 } }] }
  const current = structuredClone(original) as any
  current.content[0].attrs.indentLeft = twips || null
  const operations = [{ kind: 'setParagraphIndent', blockId: 'a', expectedObjectSha256: 'hash-a', twips }]
  expect(docxOperations(original, current, anchors)).toEqual(operations)
  expect(docxOperations(original, replayDocxOperations(original, operations, anchors), anchors)).toEqual(operations)
  current.content[0].attrs.indentFirstLine = 360
  expect(() => docxOperations(original, current, anchors)).toThrow(/布局/)
})

it.each([0, -360, 720])('writes and replays an anchored %s-twip right paragraph indent', twips => {
  const original = { type: 'doc', content: [{ ...para(0, '正文'), attrs: { docxIndex: 0, indentLeft: 360, indentRight: 180 } }] }
  const current = structuredClone(original) as any
  current.content[0].attrs.indentRight = twips || null
  const operations = [{ kind: 'setParagraphRightIndent', blockId: 'a', expectedObjectSha256: 'hash-a', twips }]
  expect(docxOperations(original, current, anchors)).toEqual(operations)
  expect(docxOperations(original, replayDocxOperations(original, operations, anchors), anchors)).toEqual(operations)
  current.content[0].attrs.indentRight = 14401
  expect(() => docxOperations(original, current, anchors)).toThrow(/右缩进/)
})

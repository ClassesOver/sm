import { describe, expect, it } from 'vitest'
import { docxOperations, replayDocxOperations, safeDocxLink, docxPageBorderSectionOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'

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
  it('lets an empty saved cell gain plain typed text but not formatted runs or new paragraphs', () => {
    const empty = { type: 'docTableCell', content: [{ type: 'docParagraph', attrs: { docxIndex: null } }] }
    const original = { type: 'doc', content: [{ type: 'docTable', attrs: { docxIndex: 4 }, content: [{ type: 'docTableRow', content: [empty] }] }] }
    const tableAnchors = [{ docxIndex: 4, blockId: 'table', expectedObjectSha256: 'table-hash', editable: false, cells: [[{ cellId: 'c1', expectedObjectSha256: 'c1hash', editable: true }]] }]
    const typed = (marks?: unknown[]) => { const next = structuredClone(original) as any; next.content[0].content[0].content[0].content[0].content = [{ type: 'text', text: '后填', ...(marks ? { marks } : {}) }]; return next }
    expect(docxOperations(original, typed(), tableAnchors)).toEqual([{ kind: 'replaceCellText', blockId: 'table', cellId: 'c1', expectedObjectSha256: 'c1hash', text: '后填' }])
    expect(docxOperations(original, typed([{ type: 'textStyle', attrs: { color: null } }]), tableAnchors)[0]).toMatchObject({ text: '后填' })
    expect(() => docxOperations(original, typed([{ type: 'bold' }]), tableAnchors)).toThrow(/结构或样式/)
    const split = typed(); split.content[0].content[0].content[0].content.push({ type: 'docParagraph', attrs: { docxIndex: null } })
    expect(() => docxOperations(original, split, tableAnchors)).toThrow(/结构或样式/)
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
    expect(() => docxOperations(original, cellStyleChange, tableAnchors)).toThrow(/单元格底纹来源或草稿无效/)
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

const linkMark = (href: string, extra = {}) => ({ type: 'link', attrs: { href, rId: null, tooltip: null, plain: false, ...extra } })
it('diffs selected links across mixed styled runs and replays without flattening', () => {
  const original: DocxPmNode = { type: 'doc', content: [{ ...para(0, ''), content: [
    { type: 'text', text: 'A😀', marks: [{ type: 'bold' }] },
    { type: 'text', text: 'BC', marks: [{ type: 'italic' }] },
    { type: 'text', text: 'keep', marks: [linkMark('https://keep.test', { tooltip: 'retain me', plain: true, rId: 'rId7' })] },
  ] }] }
  const operations = [{ kind: 'setParagraphLink', blockId: 'a', expectedObjectSha256: 'hash-a', from: 1, to: 4, href: 'https://new.test' }]
  const replayed = replayDocxOperations(original, operations, anchors)
  expect(docxOperations(original, replayed, anchors)).toEqual(operations)
  expect(replayed.content![0].content!.at(-1)).toEqual(original.content![0].content!.at(-1))
  expect(replayed.content![0].content!.slice(0, -1).flatMap(run => (run.marks ?? []).filter(mark => mark.type !== 'link')).map(mark => mark.type)).toEqual(['bold', 'bold', 'italic', 'italic'])
  const removed = replayDocxOperations(replayed, [{ ...operations[0], href: null }], anchors)
  expect(docxOperations(original, removed, anchors)).toEqual([])
  expect(() => replayDocxOperations(original, [{ ...operations[0], from: 2 }], anchors)).toThrow(/范围/)
  expect(() => replayDocxOperations(original, [{ ...operations[0], expectedObjectSha256: 'forged' }], anchors)).toThrow(/身份/)
})
it('retains targeted link metadata on href edits and refuses unsupported metadata or linked text edits', () => {
  const original: DocxPmNode = { type: 'doc', content: [{ ...para(0, ''), content: [
    { type: 'text', text: 'target', marks: [linkMark('https://old.test', { tooltip: 'explanation', plain: true, rId: 'rId4' })] },
  ] }] }
  const op = { kind: 'setParagraphLink', blockId: 'a', expectedObjectSha256: 'hash-a', from: 0, to: 6, href: 'mailto:a@example.test' }
  const replayed = replayDocxOperations(original, [op], anchors)
  expect(replayed.content![0].content![0].marks![0].attrs).toMatchObject({ tooltip: 'explanation', plain: true, rId: null, href: op.href })
  expect(docxOperations(original, replayed, anchors)).toEqual([op])
  const textChanged = structuredClone(replayed); textChanged.content![0].content![0].text = 'changed'
  expect(() => docxOperations(original, textChanged, anchors)).toThrow(/原链接元数据/)
  replayed.content![0].content![0].marks![0].attrs!.tooltip = 'forged'
  expect(() => docxOperations(original, replayed, anchors)).toThrow(/提示/)
})
it('composes replacement before newly selected links and recovers the draft', () => {
  const original = { type: 'doc', content: [para(0, 'old')] }
  const current = { type: 'doc', content: [{ ...para(0, ''), content: [
    { type: 'text', text: 'new ' }, { type: 'text', text: '😀 link', marks: [linkMark('https://example.test')] },
  ] }] }
  const operations = docxOperations(original, current, anchors)
  expect(operations.map(op => op.kind)).toEqual(['replaceParagraph', 'setParagraphLink'])
  expect(operations[1]).toMatchObject({ from: 4, to: 11 })
  expect(docxOperations(original, replayDocxOperations(original, operations, anchors), anchors)).toEqual(operations)
})
it.each(['javascript:alert(1)', 'https:example.test', 'http://user:password@example.test', 'mailto://example.test', 'https://ex ample.test', 'https://example.test/\u00a0x', 'file:///etc/passwd'])('rejects unsupported link %s', href => {
  expect(() => safeDocxLink(href)).toThrow()
})
it.each(['https://example.test/a', 'http://example.test', 'mailto:a@example.test', '\u00a0https://example.test\u00a0'])('accepts backend-compatible link %s', href => {
  expect(safeDocxLink(href)).toBe(href.trim())
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
  expect(() => replayDocxOperations(base, [{ kind: 'setParagraphAlignment', blockId: 'a', expectedObjectSha256: 'hash-a', alignment: 'distribute' }], anchors)).toThrow(/对齐方式无效/)
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

it('applies page borders to selected sections atomically while preserving each section layout draft', () => {
  const sections = ['a', 'b'].map(id => ({ sectionId: `section-${id}`, expectedSectionSha256: `hash-${id}`, settings: {
    orientation: 'portrait' as const, pageWidth: 12240, pageHeight: 15840, marginTop: 1440, marginRight: 1440,
    marginBottom: 1440, marginLeft: 1440, columns: 1, pageBorder: false,
  } }))
  const existing = [{ kind: 'setSectionLayout', sectionId: 'section-b', expectedSectionSha256: 'hash-b', values: { marginLeft: 900 } }]
  const props = { offsetFrom: 'text' as const, spacePt: 8, widthPt: 2, sides: { top: { val: 'double', widthPt: 2, spacePt: 8, color: '008000' } } }
  const changed = docxPageBorderSectionOperations(existing, sections, [0, 1], props)
  expect(changed).toEqual([
    { kind: 'setSectionLayout', sectionId: 'section-a', expectedSectionSha256: 'hash-a', values: { pageBorder: true, pageBorderProps: props } },
    { kind: 'setSectionLayout', sectionId: 'section-b', expectedSectionSha256: 'hash-b', values: { marginLeft: 900, pageBorder: true, pageBorderProps: props } },
  ])
  expect(docxPageBorderSectionOperations(changed, sections, [1], null)[1]).toEqual({
    kind: 'setSectionLayout', sectionId: 'section-b', expectedSectionSha256: 'hash-b',
    values: { marginLeft: 900, pageBorder: false, pageBorderProps: null },
  })
  expect(() => docxPageBorderSectionOperations(existing, sections, [0, 2], props)).toThrow(/节身份/)
  expect(existing).toEqual([{ kind: 'setSectionLayout', sectionId: 'section-b', expectedSectionSha256: 'hash-b', values: { marginLeft: 900 } }])
})

it('maps arbitrary paragraph before/after values to source-bound spacing and replays explicit zero', () => {
  const original = { type: 'doc', content: [{ ...para(0, '任意间距'), attrs: { docxIndex: 0, spaceBefore: null, spaceAfter: null, spaceBeforeAuto: null, spaceAfterAuto: null } }] }
  const current = structuredClone(original) as any
  current.content[0].attrs.spaceBefore = 735
  current.content[0].attrs.spaceAfter = 0
  const operation = { kind: 'setParagraphSpacing', blockId: 'a', expectedObjectSha256: 'hash-a', spaceBefore: 735, spaceAfter: 0 }
  expect(docxOperations(original, current, anchors)).toEqual([operation])
  expect(docxOperations(original, replayDocxOperations(original, [operation], anchors), anchors)).toEqual([operation])
  for (const invalid of [-1, 14401, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
    current.content[0].attrs.spaceBefore = invalid
    expect(() => docxOperations(original, current, anchors)).toThrow(/间距/)
  }
  expect(() => replayDocxOperations(original, [{ ...operation, expectedObjectSha256: 'foreign' }], anchors)).toThrow(/身份/)
  expect(() => replayDocxOperations(original, [{ ...operation, tooltip: 'unexpected' }], anchors)).toThrow(/字段/)
})

it('reapplies an unchanged literal spacing value to clear automatic source formatting', () => {
  const original = { type: 'doc', content: [{ ...para(0, '自动间距'), attrs: { docxIndex: 0, spaceBefore: 240, spaceBeforeAuto: true } }] }
  const current = structuredClone(original) as any
  current.content[0].attrs.spaceBeforeAuto = null
  const operation = { kind: 'setParagraphSpacing', blockId: 'a', expectedObjectSha256: 'hash-a', spaceBefore: 240 }
  expect(docxOperations(original, current, anchors)).toEqual([operation])
  expect(docxOperations(original, replayDocxOperations(original, [operation], anchors), anchors)).toEqual([operation])
})

it('maps source line-spacing multiples and arbitrary before/after spacing to anchored operations', () => {
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
  expect(docxOperations(original, current, anchors)).toEqual([{ ...operations[0], lineSpacing: 1.2 }])
  current.content[0].attrs.lineSpacing = 1.234
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
  expect(docxOperations(original, current, anchors)).toEqual([...operations, { kind: 'setParagraphSpecialIndent', blockId: 'a', expectedObjectSha256: 'hash-a', twips: 360 }])
  current.content[0].attrs.keepLines = true
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

it('rejects adjacent tooltip-incompatible link groups before save and during draft replay', () => {
  const original: DocxPmNode = { type: 'doc', content: [{ ...para(0, ''), content: [
    { type: 'text', text: 'first', marks: [linkMark('https://first.test', { tooltip: 'first title', rId: 'rId1' })] },
    { type: 'text', text: 'second', marks: [linkMark('https://second.test', { tooltip: 'second title', rId: 'rId2' })] },
  ] }] }
  const current = structuredClone(original)
  current.content![0].content![0].marks![0].attrs!.href = 'https://second.test'
  current.content![0].content![0].marks![0].attrs!.rId = null
  expect(() => docxOperations(original, current, anchors)).toThrow(/相邻同地址链接的提示不同/)
  expect(() => replayDocxOperations(original, [{ kind: 'setParagraphLink', blockId: 'a', expectedObjectSha256: 'hash-a', from: 0, to: 5, href: 'https://second.test' }], anchors)).toThrow(/相邻同地址链接的提示不同/)
})

it('rejects unknown hyperlink draft fields before they can disappear in a later diff', () => {
  const original = { type: 'doc', content: [para(0, 'source text')] }
  const operation = { kind: 'setParagraphLink', blockId: 'a', expectedObjectSha256: 'hash-a', from: 0, to: 6, href: 'https://example.test', tooltip: 'unsupported draft semantics' }
  expect(() => replayDocxOperations(original, [operation], anchors)).toThrow(/草稿链接包含不支持的字段/)
  expect(original.content[0].content[0]).toEqual({ type: 'text', text: 'source text' })
})

const imageNode = (overrides: Record<string, unknown> = {}) => ({
  type: 'docProtected',
  attrs: { docxIndex: null, blockType: 'image', label: '图片（粘贴）',
    imageDataUrl: 'data:image/png;base64,QUJD', imageWidthPx: 3, imageHeightPx: 2,
    genImage: { mime: 'image/png', base64: 'QUJD', widthPx: 3, heightPx: 2 }, ...overrides },
})

describe('粘贴图片 insertParagraphImage（docProtected/genImage 的协议内映射）', () => {
  it('新增图片映射为最近可编辑锚点的 insertParagraphImage，携带完整图片载荷', () => {
    const next = { type: 'doc', content: [imageNode(), para(0, '原文'), para(1, '复杂对象')] }
    expect(docxOperations(base, next as never, anchors)).toEqual([
      { kind: 'insertParagraphImage', blockId: 'a', expectedObjectSha256: 'hash-a', position: 'before',
        image: { mime: 'image/png', base64: 'QUJD', widthPx: 3, heightPx: 2 } },
    ])
  })

  it('锚点前后各有可编辑段时贴在后段之前（与 insertParagraph 的 before/after 语义一致）', () => {
    const doc = { type: 'doc', content: [para(0, '原文'), imageNode(), para(1, '复杂对象')] }
    const editableBoth = [{ ...anchors[0] }, { ...anchors[1], editable: true }]
    expect(docxOperations(base as never, doc as never, editableBoth)).toEqual([
      { kind: 'insertParagraphImage', blockId: 'b', expectedObjectSha256: 'hash-b', position: 'before',
        image: { mime: 'image/png', base64: 'QUJD', widthPx: 3, heightPx: 2 } },
    ])
  })

  it('只读锚点或无锚点时拒绝并说明', () => {
    expect(() => docxOperations(base, { type: 'doc', content: [imageNode()] } as never, [anchors[1]])).toThrow(/锚点/)
    expect(() => docxOperations(base, { type: 'doc', content: [imageNode()] } as never, [])).toThrow(/锚点/)
  })

  it.each([
    [{ ...imageNode(), attrs: { blockType: 'image', docxIndex: null, genImage: { mime: 'image/gif', base64: 'QUJD', widthPx: 3, heightPx: 2 } } }, 'PNG 或 JPEG'],
    [{ ...imageNode(), attrs: { blockType: 'image', docxIndex: null, genImage: { mime: 'image/png', base64: 'QUJ', widthPx: 3, heightPx: 2 } } }, '数据无效'],
    [{ ...imageNode(), attrs: { blockType: 'image', docxIndex: null, genImage: { mime: 'image/png', base64: 'QUJD', widthPx: 0, heightPx: 2 } } }, '尺寸'],
    [{ ...imageNode(), attrs: { blockType: 'image', docxIndex: null, genImage: { mime: 'image/png', base64: 'QUJD', widthPx: 3, heightPx: 2, extra: 1 } } }, '不支持的字段'],
    [{ type: 'docProtected', attrs: { docxIndex: null, blockType: 'image' } }, '图片数据'],
  ])('严格拒绝越界载荷：%j', (node, reason) => {
    expect(() => docxOperations(base, { type: 'doc', content: [node, para(0, '原文')] } as never, anchors)).toThrow(new RegExp(reason))
  })

  it('回放 insertParagraphImage 恢复相同的 docProtected 节点并保持 diff 幂等', () => {
    const operations = [{ kind: 'insertParagraphImage', blockId: 'a', expectedObjectSha256: 'hash-a', position: 'after',
      image: { mime: 'image/jpeg', base64: 'QUJD', widthPx: 620, heightPx: 480 } }]
    const recovered = replayDocxOperations(base, operations as never, anchors)
    expect(recovered.content?.map(node => node.type)).toEqual(['docParagraph', 'docProtected', 'docParagraph'])
    const image = recovered.content![1]
    expect(image.attrs!).toMatchObject({ docxIndex: null, blockType: 'image', imageWidthPx: 620, imageHeightPx: 480 })
    expect(image.attrs!.genImage).toEqual({ mime: 'image/jpeg', base64: 'QUJD', widthPx: 620, heightPx: 480 })
    expect(image.attrs!.imageDataUrl).toBe('data:image/jpeg;base64,QUJD')
    expect(docxOperations(base, recovered, anchors)).toEqual(operations)
  })

  it('回放拒绝伪造身份、越界尺寸和未知字段', () => {
    const valid = { kind: 'insertParagraphImage', blockId: 'a', expectedObjectSha256: 'hash-a', position: 'before', image: { mime: 'image/png', base64: 'QUJD', widthPx: 3, heightPx: 2 } }
    expect(() => replayDocxOperations(base, [{ ...valid, expectedObjectSha256: 'forged' }], anchors)).toThrow(/身份/)
    expect(() => replayDocxOperations(base, [{ ...valid, image: { ...valid.image, widthPx: 20001 } }], anchors)).toThrow(/数据无效|尺寸/)
    expect(() => replayDocxOperations(base, [{ ...valid, position: 'middle' }], anchors)).toThrow(/字段或来源身份/)
    expect(() => replayDocxOperations(base, [{ ...valid, note: 'x' }], anchors)).toThrow(/字段或来源身份/)
  })
})

it('toggles a list on a paragraph carrying the null local cover-page marker (dropped by docListItem)', () => {
  const original = { type: 'doc', content: [{ ...para(0, '原文'), attrs: { docxIndex: 0, nativeCoverPage: null, align: 'center' } }, base.content[1]] }
  const current = structuredClone(original) as any
  current.content[0] = { ...current.content[0], type: 'docListItem', attrs: { docxIndex: 0, align: 'center', kind: 'bullet', numId: 'native-bullet', ilvl: 0 } }
  expect(docxOperations(original, current, anchors)).toEqual([{ kind: 'setParagraphList', blockId: 'a', expectedObjectSha256: 'hash-a', list: 'bullet' }])
})

it('serializes and restores native GIF image payload without raster conversion',()=>{
 const gif='R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==',image={mime:'image/gif',base64:gif,widthPx:1,heightPx:1}
 const next={type:'doc',content:[para(0,'原文'),imageNode({genImage:image,imageDataUrl:'data:image/gif;base64,'+gif,imageWidthPx:1,imageHeightPx:1}),para(1,'复杂对象')]}
 const ops=docxOperations(base,next as DocxPmNode,anchors)
 expect(ops[0]).toMatchObject({kind:'insertParagraphImage',image})
 const restored=replayDocxOperations(base,ops,anchors)
 expect(docxOperations(base,restored,anchors)).toEqual(ops)
 expect(restored.content?.find(n=>n.attrs?.genImage)?.attrs?.imageDataUrl).toBe('data:image/gif;base64,'+gif)
})

it('preserves mixed inserted picture/paragraph order before a retained protected image',()=>{
 const protectedImage={type:'docProtected',attrs:{docxIndex:1,blockType:'image',label:'original image'}}
 const original={type:'doc',content:[para(0,'LEFT RIGHT'),protectedImage,para(2,'tail')]}
 const bindings=[{docxIndex:0,blockId:'left',expectedObjectSha256:'left',editable:true},{docxIndex:1,blockId:'image',expectedObjectSha256:'image',editable:false},{docxIndex:2,blockId:'tail',expectedObjectSha256:'tail',editable:true}]
 const current={type:'doc',content:[para(0,'LEFT '),imageNode(),para(null,'RIGHT'),protectedImage,para(2,'tail')]}
 const operations=docxOperations(original,current,bindings)
 expect(operations.filter(o=>o.kind.startsWith('insert'))).toEqual([expect.objectContaining({kind:'insertParagraphImage',blockId:'left',position:'after'}),expect.objectContaining({kind:'insertParagraph',blockId:'left',position:'after'})])
 const restored=replayDocxOperations(original,operations,bindings)
 const order=(doc:DocxPmNode)=>doc.content?.map(n=>n.attrs?.genImage?'new image':n.attrs?.blockType==='image'?'original image':n.content?.map(c=>c.text??'').join(''))
 expect(order(restored)).toEqual(order(current))
})

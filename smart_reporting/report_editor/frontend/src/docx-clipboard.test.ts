import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Editor, Mark, Node } from '@tiptap/core'
import { docxOperations, type DocxAnchor } from './docx-operations'
import {
  createDocxPainter, docxClipboardCopy, docxClipboardCut, docxClipboardPaste,
  docxPainterApply, docxPainterPickUp,
} from './docx-clipboard'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+', renderHTML: () => ['div', 0] })
const Paragraph = Node.create({
  name: 'docParagraph', group: 'block', content: 'inline*',
  addAttributes: () => ({
    docxIndex: { default: null }, align: { default: null }, indentLeft: { default: null }, indentRight: { default: null },
    spaceBefore: { default: null }, spaceAfter: { default: null }, spaceBeforeAuto: { default: null }, spaceAfterAuto: { default: null },
    lineSpacing: { default: null }, lineRule: { default: null }, lineRawTwips: { default: null },
  }),
  renderHTML: () => ['p', 0],
})
const ListItem = Paragraph.extend({
  name: 'docListItem',
  addAttributes() {
    return { ...this.parent?.(), kind: { default: 'bullet' }, numId: { default: null }, ilvl: { default: 0 } }
  },
  renderHTML: () => ['div', 0],
})
const Text = Node.create({ name: 'text', group: 'inline', renderHTML: ({ node }) => ['span', {}, node.text ?? ''] })
const simpleMark = (name: string) => Mark.create({ name, renderHTML: () => ['span', { [`data-${name}`]: '' }, 0] })
const TextStyle = Mark.create({
  name: 'docTextStyle',
  addAttributes: () => ({ font: { default: null }, sizeHalfPoints: { default: null }, color: { default: null }, vertAlign: { default: null }, highlight: { default: null }, rawRPr: { default: null } }),
  renderHTML: ({ HTMLAttributes }) => ['span', { ...HTMLAttributes, 'data-style': '' }, 0],
})

const editableAnchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'hash-0', editable: true }
const readOnlyAnchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'hash-0', editable: false }

function makeEditor(content: unknown) {
  const host = document.createElement('div')
  document.body.append(host)
  return new Editor({ element: host, extensions: [Doc, Paragraph, ListItem, Text, simpleMark('bold'), simpleMark('italic'), simpleMark('underline'), simpleMark('strike'), TextStyle], content: content as never })
}

/** 第三个参数是文字 run 的 marks 数组 */
const paragraphJson = (text: string, attrs: Record<string, unknown> = { docxIndex: 0 }, marks?: unknown[]) => ({
  type: 'docParagraph', attrs, ...(text ? { content: [{ type: 'text', text, ...(marks ? { marks } : {}) }] } : {}),
})

let originalRaf: typeof requestAnimationFrame | undefined
const fakeRect = () => ({ width: 0, height: 0, top: 0, left: 0, bottom: 0, right: 0, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
beforeEach(() => {
  originalRaf = globalThis.requestAnimationFrame
  // jsdom 的 rAF 是异步的：格式刷的 mouseup→rAF 应用路径需要同步触发
  globalThis.requestAnimationFrame = ((cb: FrameRequestCallback) => { cb(0); return 0 }) as typeof requestAnimationFrame
  // jsdom 缺少几何 API：cut/copy 的 focus() 与格式刷的 posAtCoords 需要
  Element.prototype.getClientRects = () => [] as unknown as DOMRectList
  Element.prototype.getBoundingClientRect = fakeRect
  ;(Range.prototype as unknown as Record<string, unknown>).getClientRects = () => []
  ;(Range.prototype as unknown as Record<string, unknown>).getBoundingClientRect = fakeRect
  document.elementFromPoint = () => null
})
afterEach(() => {
  globalThis.requestAnimationFrame = originalRaf as typeof requestAnimationFrame
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

describe('格式刷捕获（固定源 Ribbon.tsx:1991 pickUpFormat 的协议内收敛）', () => {
  it('光标拾取字符标记与整段协议内属性，并丢弃不可写字段', () => {
    const attrs = { docxIndex: 0, align: 'center', indentLeft: 720, indentRight: 360, spaceBefore: 20000, lineSpacing: 2, lineRule: 'exact' }
    const marks = [
      { type: 'bold' },
      { type: 'docTextStyle', attrs: { color: 'FF0000', sizeHalfPoints: 24, font: 'Arial', vertAlign: 'superscript', highlight: 'yellow', rawRPr: { keep: true } } },
    ]
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文', attrs, marks)] })
    editor.commands.setTextSelection(2)
    const picked = docxPainterPickUp(editor)!
    // vertAlign/highlight/rawRPr 不跨段落扩散；indentRight 360 在右缩进协议范围内可拾取
    expect(picked.marks).toEqual([{ type: 'bold', attrs: {} }, { type: 'docTextStyle', attrs: { color: 'FF0000', sizeHalfPoints: 24, font: 'Arial' } }])
    // spaceBefore 20000 超上限、精确行距（lineRule exact）不可拾取
    expect(picked.block).toEqual({ align: 'center', indentLeft: 720, indentRight: 360 })
    editor.destroy()
  })

  it('段内部分选择只拾取字符格式，整段选择携带段落格式', () => {
    const content = { type: 'doc', content: [paragraphJson('报告正文', { docxIndex: 0, align: 'center' }, [{ type: 'bold' }])] }
    const partial = makeEditor(content)
    partial.commands.setTextSelection({ from: 2, to: 4 })
    expect(docxPainterPickUp(partial)!.block).toBeNull()
    expect(docxPainterPickUp(partial)!.marks).toEqual([{ type: 'bold', attrs: {} }])
    partial.destroy()
    const whole = makeEditor(content)
    whole.commands.setTextSelection({ from: 1, to: 5 })
    expect(docxPainterPickUp(whole)!.block).toEqual({ align: 'center' })
    whole.destroy()
  })

  it('光标处没有可拾取格式时返回 null', () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    editor.commands.setTextSelection(2)
    expect(docxPainterPickUp(editor)).toBeNull()
    editor.destroy()
  })
})

describe('格式刷应用与协议映射（applyPainterFormat:496 的整段收敛）', () => {
  it('把源段落格式刷到目标段并映射为 setParagraphIndent + setParagraphAlignment + formatParagraph', () => {
    const editor = makeEditor({ type: 'doc', content: [
      paragraphJson('源段落', { docxIndex: 0, align: 'center', indentLeft: 720 }, [{ type: 'bold' }, { type: 'docTextStyle', attrs: { color: 'FF0000' } }]),
      paragraphJson('目标段落', { docxIndex: 1 }),
    ] })
    const original = editor.getJSON() as never
    editor.commands.setTextSelection(2)
    const source = docxPainterPickUp(editor)!
    expect(source.block).toEqual({ align: 'center', indentLeft: 720 })
    editor.commands.setTextSelection({ from: 5, to: 7 })
    docxPainterApply(editor, source)
    const operations = docxOperations(original, editor.getJSON() as never, [editableAnchor, { ...editableAnchor, docxIndex: 1, blockId: 'block-1' }])
    expect(operations).toContainEqual({ kind: 'setParagraphIndent', blockId: 'block-1', expectedObjectSha256: 'hash-0', twips: 720 })
    expect(operations).toContainEqual({ kind: 'setParagraphAlignment', blockId: 'block-1', expectedObjectSha256: 'hash-0', alignment: 'center' })
    expect(operations).toContainEqual({ kind: 'formatParagraph', blockId: 'block-1', expectedObjectSha256: 'hash-0', style: { bold: true, color: 'FF0000' } })
    editor.destroy()
  })

  it('行距刷到目标段时清除精确行距字段并映射为 setParagraphSpacing', () => {
    const editor = makeEditor({ type: 'doc', content: [
      paragraphJson('源段落', { docxIndex: 0, lineSpacing: 1.5 }),
      paragraphJson('目标段落', { docxIndex: 1, lineSpacing: 2, lineRule: 'exact', lineRawTwips: 480 }),
    ] })
    const original = editor.getJSON() as never
    editor.commands.setTextSelection(2)
    const source = docxPainterPickUp(editor)!
    editor.commands.setTextSelection({ from: 5, to: 7 })
    docxPainterApply(editor, source)
    const edited = (editor.getJSON() as { content: { attrs: Record<string, unknown> }[] }).content[1].attrs
    expect(edited.lineRule).toBeNull()
    expect(edited.lineRawTwips).toBeNull()
    expect(docxOperations(original, editor.getJSON() as never, [editableAnchor, { ...editableAnchor, docxIndex: 1, blockId: 'block-1' }])).toEqual([
      { kind: 'setParagraphSpacing', blockId: 'block-1', expectedObjectSha256: 'hash-0', lineSpacing: 1.5 },
    ])
    editor.destroy()
  })

  it('列表段跳过缩进刷写，避免协议拒绝（缩进只能走编号级别）', () => {
    const editor = makeEditor({ type: 'doc', content: [
      paragraphJson('源段落', { docxIndex: 0, align: 'left', indentLeft: 720 }),
      { ...paragraphJson('列表项', { docxIndex: 1, align: 'center', indentLeft: 720, kind: 'bullet', numId: 'native-bullet', ilvl: 0 }), type: 'docListItem' },
    ] })
    editor.commands.setTextSelection(2)
    const source = docxPainterPickUp(editor)!
    editor.commands.setTextSelection({ from: 5, to: 8 })
    docxPainterApply(editor, source)
    const edited = (editor.getJSON() as { content: { attrs: Record<string, unknown> }[] }).content[1].attrs
    expect(edited.align).toBe('left')
    expect(edited.indentLeft).toBe(720)
    editor.destroy()
  })

  it('越界拒绝：只读锚点被协议拒绝，不可编辑拒绝应用', () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const original = editor.getJSON() as never
    editor.commands.setTextSelection({ from: 1, to: 5 })
    docxPainterApply(editor, { marks: [{ type: 'bold', attrs: {} }], block: null })
    // 守卫（filterTransaction → docxOperations）对只读锚点的原子拒绝
    expect(() => docxOperations(original, editor.getJSON() as never, [readOnlyAnchor])).toThrow('只读对象不能修改')
    editor.setEditable(false)
    editor.commands.setTextSelection({ from: 1, to: 5 })
    expect(() => docxPainterApply(editor, { marks: [], block: { align: 'center' } })).toThrow('当前文档不可编辑')
    editor.destroy()
  })
})

describe('格式刷交互（单击一次/双击锁定/Esc 解除，Ribbon.tsx:2093-2108）', () => {
  const content = { type: 'doc', content: [
    paragraphJson('源段落', { docxIndex: 0, align: 'center' }, [{ type: 'bold' }]),
    paragraphJson('目标段落', { docxIndex: 1 }),
  ] }

  it('单击武装后拖选应用并自动解除', () => {
    const editor = makeEditor(content)
    const report = vi.fn()
    const painter = createDocxPainter(editor, { report, onChange: () => {} })
    editor.commands.setTextSelection(2)
    painter.click()
    expect(painter.active()).toBe(true)
    editor.view.dom.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: 100, clientY: 100 }))
    editor.commands.setTextSelection({ from: 5, to: 7 })
    window.dispatchEvent(new MouseEvent('mouseup', { clientX: 300, clientY: 100 }))
    expect(painter.active()).toBe(false)
    expect((editor.getJSON() as { content: { content?: { marks?: unknown[] }[] }[] }).content[1].content?.[0].marks).toEqual([{ type: 'bold' }])
    expect(report).not.toHaveBeenCalled()
    painter.dispose()
    editor.destroy()
  })

  it('双击锁定：应用后保持武装，Esc 解除', () => {
    const editor = makeEditor(content)
    const painter = createDocxPainter(editor, { report: vi.fn(), onChange: () => {} })
    editor.commands.setTextSelection(2)
    // 真实双击序列：click → click → dblclick
    painter.click(); painter.click(); painter.doubleClick()
    expect(painter.active()).toBe(true)
    editor.view.dom.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: 100, clientY: 100 }))
    editor.commands.setTextSelection({ from: 5, to: 7 })
    window.dispatchEvent(new MouseEvent('mouseup', { clientX: 400, clientY: 100 }))
    expect(painter.active()).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(painter.active()).toBe(false)
    painter.dispose()
    editor.destroy()
  })

  it('武装中的选区未移动时不误刷源选区', () => {
    const editor = makeEditor(content)
    const painter = createDocxPainter(editor, { report: vi.fn(), onChange: () => {} })
    editor.commands.setTextSelection(2)
    painter.click()
    editor.view.dom.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: 100, clientY: 100 }))
    window.dispatchEvent(new MouseEvent('mouseup', { clientX: 100, clientY: 100 }))
    // 光标仍在源段落且选区未变化：不应用
    expect((editor.getJSON() as { content: { content?: { marks?: unknown[] }[] }[] }).content[0].content?.[0].marks).toEqual([{ type: 'bold' }])
    painter.dispose()
    editor.destroy()
  })

  it('无可拾取格式时报告原因且不武装，可再次尝试', () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const report = vi.fn()
    const painter = createDocxPainter(editor, { report, onChange: () => {} })
    editor.commands.setTextSelection(2)
    painter.click()
    expect(painter.active()).toBe(false)
    expect(report).toHaveBeenCalledWith(expect.objectContaining({ message: '光标处没有可拾取的格式' }))
    painter.click()
    expect(painter.active()).toBe(false)
    painter.dispose()
    editor.destroy()
  })
})

describe('粘贴协议（paste-actions.ts 读取路径 + replaceParagraph 类协议严格校验）', () => {
  function stubClipboard(impl: { readText?: () => Promise<string>; read?: () => unknown[] }) {
    const clipboard: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(impl)) clipboard[key] = value
    Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true })
  }

  afterEach(() => {
    Reflect.deleteProperty(navigator as unknown as Record<string, unknown>, 'clipboard')
  })

  it('纯文本粘贴经 replaceParagraph/insertParagraph 映射', async () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const original = editor.getJSON() as never
    stubClipboard({ readText: async () => '摘 要\n第二段' })
    editor.commands.setTextSelection(2)
    await docxClipboardPaste(editor)
    const json = editor.getJSON() as { content: { content?: { text?: string }[] }[] }
    expect(json.content[0].content?.map(run => run.text).join('')).toBe('报摘 要')
    expect(json.content[1].content?.map(run => run.text).join('')).toBe('第二段告正文')
    expect(docxOperations(original, editor.getJSON() as never, [editableAnchor])).toEqual([
      { kind: 'insertParagraph', blockId: 'block-0', expectedObjectSha256: 'hash-0', position: 'after', text: '第二段告正文' },
      { kind: 'replaceParagraph', blockId: 'block-0', expectedObjectSha256: 'hash-0', text: '报摘 要' },
    ])
    editor.destroy()
  })

  it.each([
    ['bad\ttext', '控制字符'],
    ['bad\u0007bell', '控制字符'],
    ['a'.repeat(200001), '长度上限'],
    [Array(401).fill('段').join('\n'), '段落上限'],
  ])('边界拒绝：%j', async (text, reason) => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const before = editor.getJSON()
    stubClipboard({ readText: async () => text })
    editor.commands.setTextSelection(2)
    await expect(docxClipboardPaste(editor)).rejects.toThrow(reason)
    expect(editor.getJSON()).toEqual(before)
    editor.destroy()
  })

  it('富文本剪贴板在默认与保留源格式模式下明确拒绝，仅保留文本放行', async () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    stubClipboard({
      readText: async () => '富文本里的文字',
      read: () => [{ types: ['text/html', 'text/plain'], getType: async (type: string) => ({ text: async () => (type === 'text/html' ? '<b>富文本里的文字</b>' : '富文本里的文字') }) }],
    })
    editor.commands.setTextSelection(2)
    await expect(docxClipboardPaste(editor)).rejects.toThrow('无法精确映射到 DOCX 保存协议')
    await expect(docxClipboardPaste(editor, 'source')).rejects.toThrow('无法精确映射到 DOCX 保存协议')
    await expect(docxClipboardPaste(editor, 'merge')).rejects.toThrow('无法精确映射到 DOCX 保存协议')
    await docxClipboardPaste(editor, 'text')
    expect((editor.getJSON() as { content: { content?: { text?: string }[] }[] }).content[0].content?.map(run => run.text).join('')).toBe('报富文本里的文字告正文')
    editor.destroy()
  })

  it('浏览器权限失败给出准确提示且授权后可重试', async () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const before = editor.getJSON()
    stubClipboard({ readText: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) })
    editor.commands.setTextSelection(2)
    await expect(docxClipboardPaste(editor)).rejects.toThrow('浏览器拒绝了剪贴板读取权限')
    expect(editor.getJSON()).toEqual(before)
    stubClipboard({ readText: async () => '重试文本' })
    await docxClipboardPaste(editor)
    expect((editor.getJSON() as { content: { content?: { text?: string }[] }[] }).content[0].content?.map(run => run.text).join('')).toBe('报重试文本告正文')
    editor.destroy()
  })

  it('空剪贴板拒绝', async () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    stubClipboard({ readText: async () => '' })
    await expect(docxClipboardPaste(editor)).rejects.toThrow('剪贴板为空')
    editor.destroy()
  })
})

describe('剪切与复制（Ribbon.tsx:2234 clipboard() 的 execCommand 路径）', () => {
  afterEach(() => { delete (document as unknown as Record<string, unknown>).execCommand })

  it('复制调用 document.execCommand("copy")', () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const exec = vi.fn(() => true)
    document.execCommand = exec as unknown as typeof document.execCommand
    editor.commands.setTextSelection({ from: 1, to: 5 })
    docxClipboardCopy(editor)
    expect(exec).toHaveBeenCalledWith('copy')
    editor.destroy()
  })

  it('剪切调用 document.execCommand("cut")', () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const exec = vi.fn(() => true)
    document.execCommand = exec as unknown as typeof document.execCommand
    editor.commands.setTextSelection({ from: 1, to: 5 })
    docxClipboardCut(editor)
    expect(exec).toHaveBeenCalledWith('cut')
    editor.destroy()
  })

  it('execCommand 失败时给出权限提示', () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    document.execCommand = () => false
    editor.commands.setTextSelection({ from: 1, to: 5 })
    expect(() => docxClipboardCopy(editor)).toThrow('浏览器拒绝了剪贴板复制权限')
    expect(() => docxClipboardCut(editor)).toThrow('浏览器拒绝了剪贴板剪切权限')
    editor.destroy()
  })

  it('空选区拒绝复制/剪切，不可编辑拒绝剪切', () => {
    const editor = makeEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    document.execCommand = () => true
    editor.commands.setTextSelection(2)
    expect(() => docxClipboardCopy(editor)).toThrow('请先选择要复制的内容')
    expect(() => docxClipboardCut(editor)).toThrow('请先选择要剪切的内容')
    editor.setEditable(false)
    editor.commands.setTextSelection({ from: 1, to: 5 })
    expect(() => docxClipboardCut(editor)).toThrow('当前文档不可编辑')
    editor.destroy()
  })
})

const DocProtected = Node.create({
  name: 'docProtected', group: 'block', atom: true,
  addAttributes: () => ({
    docxIndex: { default: null }, blockType: { default: 'passthrough' }, label: { default: '' },
    imageDataUrl: { default: null }, imageWidthPx: { default: null }, imageHeightPx: { default: null },
    genImage: { default: null },
  }),
  renderHTML: () => ['div', 0],
})

/** 粘贴图片的 1x1 透明 PNG；1240x960 供缩放断言使用 */
const PNG_BYTES = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='), ch => ch.charCodeAt(0))
const makeImageBlob = (type = 'image/png') => new Blob([PNG_BYTES], { type })

function stubImage(natural = { width: 1240, height: 960 }) {
  class FakeImage {
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    naturalWidth = natural.width
    naturalHeight = natural.height
    set src(_value: string) { queueMicrotask(() => this.onload?.()) }
  }
  ;(globalThis as unknown as Record<string, unknown>).Image = FakeImage
}

describe('图片粘贴（paste-actions.ts 图片通道 + insertParagraphImage 协议映射）', () => {
  const imageAnchor: DocxAnchor = { docxIndex: 0, blockId: 'block-0', expectedObjectSha256: 'hash-0', editable: true }

  function stubImageClipboard(blob: Blob | null, text = '') {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
      readText: async () => text,
      read: async () => blob ? [{ types: [blob.type], getType: async () => blob }] : [],
    } })
  }

  afterEach(() => {
    Reflect.deleteProperty(navigator as unknown as Record<string, unknown>, 'clipboard')
    Reflect.deleteProperty(globalThis as unknown as Record<string, unknown>, 'Image')
  })

  function imageEditor(content: unknown) {
    const host = document.createElement('div')
    document.body.append(host)
    return new Editor({ element: host, extensions: [Doc, Paragraph, DocProtected, Text], content: content as never })
  }

  it('纯位图剪贴板默认粘贴：图片成为独立图片段，段中插入把右半段恢复为新段落', async () => {
    stubImage()
    const editor = imageEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const original = editor.getJSON() as never
    stubImageClipboard(makeImageBlob())
    editor.commands.setTextSelection(2)
    await docxClipboardPaste(editor)
    const json = editor.getJSON() as { content: { type: string; attrs?: Record<string, unknown>; content?: { text?: string }[] }[] }
    expect(json.content[0].content?.map(run => run.text).join('')).toBe('报')
    expect(json.content[1].type).toBe('docProtected')
    expect(json.content[1].attrs).toMatchObject({ docxIndex: null, blockType: 'image', imageWidthPx: 620, imageHeightPx: 480 })
    expect(json.content[1].attrs?.genImage).toEqual({ mime: 'image/png', widthPx: 620, heightPx: 480, base64: expect.any(String) })
    expect(json.content[2].content?.map(run => run.text).join('')).toBe('告正文')
    expect(json.content[2].attrs?.docxIndex).toBeNull()
    expect(docxOperations(original, editor.getJSON() as never, [imageAnchor])).toEqual([
      expect.objectContaining({ kind: 'insertParagraphImage', position: 'after' }),
      { kind: 'insertParagraph', blockId: 'block-0', expectedObjectSha256: 'hash-0', position: 'after', text: '告正文' },
      { kind: 'replaceParagraph', blockId: 'block-0', expectedObjectSha256: 'hash-0', text: '报' },
    ])
    editor.destroy()
  })

  it('1240x960 位图按固定源 620px 内容宽缩放并保持纵横比', async () => {
    stubImage()
    const editor = imageEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    stubImageClipboard(makeImageBlob())
    editor.commands.setTextSelection(2)
    await docxClipboardPaste(editor)
    const attrs = (editor.getJSON() as { content: { attrs?: Record<string, unknown> }[] }).content[1].attrs!
    expect(attrs.imageWidthPx).toBe(620)
    expect(attrs.imageHeightPx).toBe(480)
    editor.destroy()
  })

  it('picture 模式忽略文本直接粘贴图片；text 模式不粘贴图片', async () => {
    stubImage()
    const editor = imageEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    stubImageClipboard(makeImageBlob(), '旁边的文字')
    editor.commands.setTextSelection(2)
    await docxClipboardPaste(editor, 'picture')
    expect((editor.getJSON() as { content: { type: string }[] }).content[1].type).toBe('docProtected')
    editor.destroy()
    const textEditor = imageEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    stubImageClipboard(makeImageBlob(), '纯文字')
    textEditor.commands.setTextSelection(2)
    await docxClipboardPaste(textEditor, 'text')
    const json = textEditor.getJSON() as { content: { type: string }[] }
    expect(json.content.every(node => node.type !== 'docProtected')).toBe(true)
    expect(JSON.stringify(json)).toContain('纯文字')
    textEditor.destroy()
  })

  it('非 png/jpeg 位图与超出 8MB 的图片拒绝', async () => {
    stubImage()
    const editor = imageEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const before = editor.getJSON()
    stubImageClipboard(makeImageBlob('image/webp'))
    await expect(docxClipboardPaste(editor)).rejects.toThrow('PNG 或 JPEG')
    stubImageClipboard(new Blob([new Uint8Array(8 * 1024 * 1024 + 1)], { type: 'image/png' }))
    await expect(docxClipboardPaste(editor)).rejects.toThrow('8MB')
    expect(editor.getJSON()).toEqual(before)
    editor.destroy()
  })

  it('表格单元格内拒绝粘贴图片并说明原因', async () => {
    stubImage()
    // 单元格内容模型（extensions.ts:3342）不含 docProtected：用同名最小节点复现深度父链
    const CellParagraph = Paragraph.extend({ name: 'docParagraph' })
    const Cell = Node.create({ name: 'docTableCell', group: 'block', content: 'docParagraph+', isolating: true, renderHTML: () => ['td', 0] })
    const cellHost = document.createElement('div')
    document.body.append(cellHost)
    const cellEditor = new Editor({ element: cellHost, extensions: [Doc, Cell, CellParagraph, Text], content: { type: 'doc', content: [{ type: 'docTableCell', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 } }] }] } as never })
    stubImageClipboard(makeImageBlob())
    cellEditor.commands.setTextSelection(2)
    await expect(docxClipboardPaste(cellEditor)).rejects.toThrow('表格单元格内暂不支持粘贴图片')
    cellEditor.destroy()
  })

  it('空段落光标：图片贴在段落前，原段落锚点保留', async () => {
    stubImage()
    const editor = imageEditor({ type: 'doc', content: [paragraphJson('')] })
    const original = editor.getJSON() as never
    stubImageClipboard(makeImageBlob())
    editor.commands.setTextSelection(1)
    await docxClipboardPaste(editor)
    const json = editor.getJSON() as { content: { type: string; attrs?: Record<string, unknown> }[] }
    expect(json.content.map(node => node.type)).toEqual(['docProtected', 'docParagraph'])
    expect(json.content[1].attrs?.docxIndex).toBe(0)
    expect(docxOperations(original, editor.getJSON() as never, [imageAnchor])).toEqual([
      expect.objectContaining({ kind: 'insertParagraphImage', position: 'before' }),
    ])
    editor.destroy()
  })

  it('段尾光标：图片贴在段落之后，无需拆段', async () => {
    stubImage()
    const editor = imageEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    const original = editor.getJSON() as never
    stubImageClipboard(makeImageBlob())
    editor.commands.setTextSelection(5)
    await docxClipboardPaste(editor)
    const json = editor.getJSON() as { content: { type: string; attrs?: Record<string, unknown> }[] }
    expect(json.content[0].type).toBe('docParagraph')
    expect(json.content[1].type).toBe('docProtected')
    expect(docxOperations(original, editor.getJSON() as never, [imageAnchor])).toEqual([
      expect.objectContaining({ kind: 'insertParagraphImage', position: 'after' }),
      { kind: 'insertParagraph', blockId: 'block-0', expectedObjectSha256: 'hash-0', position: 'after', text: '' },
    ])
    editor.destroy()
  })

  it('剪贴板没有图片时 picture 模式拒绝', async () => {
    stubImage()
    const editor = imageEditor({ type: 'doc', content: [paragraphJson('报告正文')] })
    stubImageClipboard(null)
    await expect(docxClipboardPaste(editor, 'picture')).rejects.toThrow('没有图片')
    editor.destroy()
  })
})

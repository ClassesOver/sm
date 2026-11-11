import { Extension, type Editor } from '@tiptap/core'
import { Fragment, type Schema } from '@tiptap/pm/model'
import { closeHistory } from '@tiptap/pm/history'
import type { parseDocx } from '@genoffice/docx-engine'
import {
  docxTocEntries, docxTocRegion, docxTocSource, docxTocXml, isDocxTocOperation, readDocxTocOperation,
  type TocKind, type TocOperation,
} from '../../../reporting/doc_engine/bridge/docx-toc-core'
import type { DocxAnchor, DocxPmNode } from './docx-operations'
import type { NativeOperation } from './native-draft'

export { isDocxTocOperation }
export const NativeDocxToc = Extension.create({
  name: 'nativeDocxToc',
  addGlobalAttributes: () => [{ types: ['doc'], attributes: { nativeTocOperation: { default: null, rendered: false } } }],
})
const batchError = '目录需要单独保存。请先保存当前修改，再操作目录。'
export function assertDocxTocBatch(operations: readonly NativeOperation[]) {
  if (operations.some(isDocxTocOperation) && operations.length !== 1) throw new Error(batchError)
}
export type DocxTocControls = { reason: (kind: TocKind) => string | null; run: (kind: TocKind) => void }

type TocAnchor = Pick<DocxAnchor, 'docxIndex' | 'blockId' | 'expectedObjectSha256'>
export function createDocxToc(parsed: Awaited<ReturnType<typeof parseDocx>>, anchors: readonly TocAnchor[]) {
  const raw = docxTocSource(parsed), entries = docxTocEntries(parsed), region = docxTocRegion(parsed, raw)
  const byId = new Map(anchors.map(anchor => [anchor.blockId, anchor])), byIndex = new Map(anchors.map(anchor => [anchor.docxIndex, anchor]))
  const blocks = new Map(parsed.blocks.map(block => [block.docxIndex, block]))
  const byBlock = (anchor: TocAnchor) => ({ blockId: anchor.blockId, expectedObjectSha256: anchor.expectedObjectSha256 })
  const eligible = (index: number, position: 'before' | 'after') => {
    const block = blocks.get(index)
    return raw.paragraphs.has(index) && !!block && ['heading', 'paragraph', 'listItem'].includes(block.type)
      && (position === 'before' || !/<w:sectPr\b/.test(block.originalXml ?? ''))
  }
  const requireAvailable = () => {
    if (!raw.safe) throw new Error('当前文档来源暂不支持目录编辑。')
    if (!entries.length) throw new Error('没有可用于目录的标题，请先应用标题样式并保存。')
  }
  const plan = (doc: DocxPmNode, value: unknown, schema: Schema) => {
    requireAvailable()
    const operation = readDocxTocOperation(value), anchor = byId.get(operation.blockId)
    if (!anchor || anchor.expectedObjectSha256 !== operation.expectedObjectSha256) throw new Error('目录锚点不属于当前 Word 文件。')
    const body = doc.content ?? [], i = body.findIndex(node => node.attrs?.docxIndex === anchor.docxIndex)
    let from = i, to = i, keepPageBreak = false
    if (i < 0) throw new Error('目录锚点已变化。')
    if (operation.kind === 'insertToc') {
      if (!eligible(anchor.docxIndex, operation.position)) throw new Error('请选择普通正文或标题段落作为目录插入位置。')
      if (operation.position === 'after') from = to = i + 1
    } else {
      if (!region.indices || region.indices[0] !== anchor.docxIndex
        || region.indices.some((index, offset) => body[i + offset]?.attrs?.docxIndex !== index)) throw new Error('现有目录的范围已变化。')
      to = i + region.indices.length
      keepPageBreak = region.keepPageBreak
    }
    const nodes = docxTocXml(entries, keepPageBreak).map((genXml, index) => schema.nodeFromJSON({
      type: 'docProtected',
      attrs: { docxIndex: null, blockType: 'passthrough', label: index === entries.length ? '分页符' : '目录',
        genXml, fieldDisplay: index === entries.length ? { kind: 'pageBreak' }
          : { kind: 'tocLine', left: entries[index]!.text, right: '', level: entries[index]!.level } },
    }))
    return { operation, from, to, nodes }
  }
  const controls = (editor: Editor, pending: () => readonly NativeOperation[], reportError: (error: unknown) => void): DocxTocControls => {
    const intent = (kind: TocKind): TocOperation => {
      if (!editor.isEditable) throw new Error('当前文档不可编辑或正在保存。')
      if (pending().length) throw new Error(batchError)
      requireAvailable()
      if (kind === 'updateToc') {
        const first = region.indices && byIndex.get(region.indices[0]!)
        if (!first) throw new Error(region.reason === 'missing' ? '没有可更新的自动目录。' : '现有目录格式暂不支持更新。')
        return { kind, ...byBlock(first) }
      }
      const { empty, $from } = editor.state.selection
      if (!empty || $from.depth !== 1 || ($from.parentOffset !== 0 && $from.parentOffset !== $from.parent.content.size)) {
        throw new Error('请把光标放在正文或标题段落的开头或结尾。')
      }
      const position = $from.parentOffset === 0 ? 'before' : 'after'
      const anchor = byIndex.get($from.parent.attrs.docxIndex)
      if (!anchor || !eligible(anchor.docxIndex, position)) throw new Error('请选择普通正文或标题段落作为目录插入位置。')
      return { kind, ...byBlock(anchor), position }
    }
    return {
      reason(kind) { try { intent(kind); return null } catch (error) { return (error as Error).message } },
      run(kind) {
        try {
          const { from, to, nodes, operation } = plan(editor.getJSON(), intent(kind), editor.schema)
          const { doc, tr } = editor.state
          let start = 0, end = 0
          doc.forEach((node, _offset, index) => { if (index < from) start += node.nodeSize; if (index < to) end += node.nodeSize })
          editor.view.dispatch(closeHistory(tr.replaceWith(start, end, Fragment.fromArray(nodes)).setDocAttribute('nativeTocOperation', operation)))
          editor.view.focus()
        } catch (error) { reportError(error) }
      },
    }
  }
  return { plan, controls }
}
type DocxToc = ReturnType<typeof createDocxToc>

/** Strip only the exact projected TOC; ordinary mutation collection checks the rest of the document. */
export function normalizeDocxToc(baseline: DocxPmNode, current: DocxPmNode, source: DocxToc, schema: Schema) {
  const value = current.attrs?.nativeTocOperation
  if (value == null) return { current, operations: [] as NativeOperation[] }
  const { from, to, nodes, operation } = source.plan(baseline, value, schema)
  const actual = current.content ?? [], generated = nodes.map(node => node.toJSON())
  if (JSON.stringify(actual.slice(from, from + nodes.length)) !== JSON.stringify(generated)) throw new Error('目录结构已变化，请撤销后重新操作。')
  return {
    current: { ...current, attrs: { ...current.attrs, nativeTocOperation: baseline.attrs?.nativeTocOperation ?? null },
      content: [...actual.slice(0, from), ...(baseline.content ?? []).slice(from, to), ...actual.slice(from + nodes.length)] },
    operations: [operation],
  }
}
export function replayDocxToc(doc: DocxPmNode, operations: NativeOperation[], source: DocxToc, schema: Schema): DocxPmNode {
  assertDocxTocBatch(operations)
  const value = operations.find(isDocxTocOperation)
  if (!value) return doc
  const { operation, from, to, nodes } = source.plan(doc, value, schema), body = doc.content ?? []
  return { ...doc, attrs: { ...doc.attrs, nativeTocOperation: operation },
    content: [...body.slice(0, from), ...nodes.map(node => node.toJSON()), ...body.slice(to)] }
}

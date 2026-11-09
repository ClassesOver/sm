/** Native adaptation of pinned GenOffice CommentsPanel/note-threads read semantics.
 * Provenance and differences: genoffice-pdf-comments-source.json. No reply write support.
 */
import type { NativeOperation } from './native-draft'
import type { PdfPageIdentity } from './pdf-operations'
import { parsePdfDate } from './genoffice-pdf-comment-date'
export interface CommentAnnotation { id: string; annotationType: number; subtype?: string; hidden?: boolean; replyType?: string; inReplyTo?: string | null; contentsObj?: { str: string }; titleObj?: { str: string }; creationDate?: string | null; modificationDate?: string | null }
export interface CommentNode { key: string; pageId: string; pageNo: number; contents: string; author: string; timeMs: number | null; cardId: string | null; pendingIndex?: number; readonly: boolean; issue?: string; replies: CommentNode[] }
export interface CommentTarget { node: CommentNode; snapshot: string; document: object }
export class PdfAnnotationCache {
  private entries = new WeakMap<object, Map<number, Promise<CommentAnnotation[]>>>()
  get(document: { getPage(n: number): Promise<{ getAnnotations(): Promise<any[]> }> }, index: number): Promise<CommentAnnotation[]> {
    let pages = this.entries.get(document)
    if (!pages) { pages = new Map(); this.entries.set(document, pages) }
    let result = pages.get(index)
    if (!result) {
      result = document.getPage(index + 1).then(page => page.getAnnotations()).then(items => { if (!Array.isArray(items) || items.some(item => !item || typeof item !== 'object')) throw new Error('pdf_annotations_unreadable'); return items })
      pages.set(index, result)
      const cached = pages
      void result.catch(() => { if (cached.get(index) === result) cached.delete(index) })
    }
    return result
  }
  evict(document: object, index: number) { this.entries.get(document)?.delete(index) }
  clear() { this.entries = new WeakMap() }
}
const byTime = (a: CommentNode, b: CommentNode) => (a.timeMs ?? Number.MAX_SAFE_INTEGER) - (b.timeMs ?? Number.MAX_SAFE_INTEGER)
export function flattenComments(root: CommentNode): { node: CommentNode; depth: number }[] {
  const stack = [{ node: root, depth: 0 }], result: { node: CommentNode; depth: number }[] = []
  while (stack.length) { const current = stack.pop()!; result.push(current); for (const reply of [...current.node.replies].reverse()) stack.push({ node: reply, depth: current.depth + 1 }) }
  return result
}
export function filterComments(roots: CommentNode[], query: string) {
  const q = query.trim().toLowerCase()
  return roots.filter(root => !q || flattenComments(root).some(({ node }) => [node.contents, node.author].some(text => text.toLowerCase().includes(q))))
    .sort((a, b) => a.pageNo - b.pageNo || byTime(a, b))
}
export function projectPageComments(raw: CommentAnnotation[], page: PdfPageIdentity, pageNo: number, operations: NativeOperation[], preview: boolean): CommentNode[] {
  const nodes: CommentNode[] = [], references = new Map<string, CommentNode[]>(), parents = new Map<CommentNode, string>(), nodeRefs = new Map<CommentNode, string>()
  const nativeRefs = new Map<string, NonNullable<PdfPageIdentity['notes']>>()
  for (const note of page.notes ?? []) if (note.sourceRef) { const list = nativeRefs.get(note.sourceRef) ?? []; list.push(note); nativeRefs.set(note.sourceRef, list) }
  let cardIndex = -1
  for (const [index, item] of raw.entries()) {
    if (item.subtype === 'Text' && item.contentsObj?.str) cardIndex++
    if (item.annotationType !== 1 || item.hidden || item.replyType === 'Group') continue
    const matches = nativeRefs.get(item.id) ?? []
    const native = !preview && matches.length === 1 ? matches[0] : undefined
    if (native && operations.some(op => op.kind === 'removeNote' && op.pageId === page.pageId && op.annotationId === native.annotationId)) continue
    const edit = native && operations.find(op => op.kind === 'editNote' && op.pageId === page.pageId && op.annotationId === native.annotationId)
    const node: CommentNode = { key: `${page.pageId}:saved:${item.id}:${index}`, pageId: page.pageId, pageNo, contents: edit ? String(edit.contents) : native?.contents ?? (typeof item.contentsObj?.str === 'string' ? item.contentsObj.str : ''), author: typeof item.titleObj?.str === 'string' ? item.titleObj.str : '', timeMs: parsePdfDate(typeof item.creationDate === 'string' ? item.creationDate : null) ?? parsePdfDate(typeof item.modificationDate === 'string' ? item.modificationDate : null), cardId: native?.annotationId ?? (preview || !page.notesReadSafe ? item.subtype === 'Text' && item.contentsObj?.str ? `readonly:${cardIndex}` : null : null), readonly: preview || !native?.editable, replies: [] }
    nodes.push(node); nodeRefs.set(node, item.id)
    const list = references.get(item.id) ?? []; list.push(node); references.set(item.id, list)
    if (item.inReplyTo) parents.set(node, item.inReplyTo)
    if (!node.cardId) node.issue = '无法唯一匹配便签卡片，仅可定位到所在页'
  }
  const parentOf = new Map<CommentNode, CommentNode>()
  for (const node of nodes) {
    const own = references.get(nodeRefs.get(node)!)
    if (own && own.length > 1) { node.issue = '重复引用，按独立只读项展示'; node.readonly = true; node.cardId = null; continue }
    const parentRef = parents.get(node), candidates = parentRef ? references.get(parentRef) : undefined
    if (parentRef && candidates?.length === 1 && candidates[0] !== node) parentOf.set(node, candidates[0])
    else if (parentRef) { node.issue = '回复关系缺失或歧义，按只读根条目展示'; node.readonly = true }
  }
  // Detach one edge in each cycle; no recursion and no note is hidden.
  const done = new Set<CommentNode>()
  for (const seed of nodes) {
    const path: CommentNode[] = [], local = new Set<CommentNode>(); let node: CommentNode | undefined = seed
    while (node && !done.has(node)) {
      if (local.has(node)) { parentOf.delete(node); node.issue = '回复关系成环，按只读根条目展示'; node.readonly = true; break }
      local.add(node); path.push(node); node = parentOf.get(node)
    }
    for (const current of path) done.add(current)
  }
  const roots: CommentNode[] = []
  for (const node of nodes) { const parent = parentOf.get(node); if (parent) parent.replies.push(node); else roots.push(node) }
  for (const node of nodes) { node.replies.sort(byTime); if (parentOf.has(node) || node.replies.length) node.readonly = true }
  if (!preview) for (const [index, op] of operations.entries()) if (op.kind === 'addTextAnnotation' && op.pageId === page.pageId) roots.push({ key: `${page.pageId}:pending:${index}`, pageId: page.pageId, pageNo, contents: String(op.text), author: '', timeMs: typeof op.createdMs === 'number' ? op.createdMs : null, cardId: null, pendingIndex: index, readonly: false, replies: [] })
  return roots
}

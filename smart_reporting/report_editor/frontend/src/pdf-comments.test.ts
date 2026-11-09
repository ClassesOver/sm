import { expect, it } from 'vitest'
import { PdfAnnotationCache, projectPageComments, filterComments, flattenComments, type CommentAnnotation } from './pdf-comments'
const page = { pageId: 'source:0', index: 0, rotation: 0, cropBox: { x: 0, y: 0, width: 400, height: 500 }, mediaBox: { x: 0, y: 0, width: 400, height: 500 }, notesReadSafe: true, notes: [{ sourceRef: '10R', annotationId: 'native0', expectedAnnotationSha256: 'hash', contents: 'original', editable: true, removable: true, removalReason: null }] }
const a = (id: string, text: string, extra: Partial<CommentAnnotation> = {}): CommentAnnotation => ({ id, annotationType: 1, subtype: 'Text', contentsObj: { str: text }, ...extra })
it('maps only exact full-generation unique refs, and overlays pending edits/deletes without changing raw source', () => {
  const raw = [a('10R', 'original'), a('10R2', 'other generation')]
  const edited = projectPageComments(raw, page, 2, [{ kind: 'editNote', pageId: page.pageId, annotationId: 'native0', contents: 'changed' }], false)
  expect(edited[0]).toMatchObject({ cardId: 'native0', contents: 'changed', pageNo: 2, readonly: false })
  expect(edited[1]).toMatchObject({ cardId: null, readonly: true })
  expect(projectPageComments(raw, page, 2, [{ kind: 'removeNote', pageId: page.pageId, annotationId: 'native0' }], false)).toHaveLength(1)
  expect(raw[0].contentsObj?.str).toBe('original')
})
it('builds nested replies, preserves orphan/cyclic/duplicate notes and never matches contents/geometry as identity', () => {
  const raw = [a('10R', 'root'), a('11R', 'reply', { inReplyTo: '10R' }), a('12R', 'nested', { inReplyTo: '11R' }), a('13R', 'orphan', { inReplyTo: 'missing' }), a('20R', 'cycle1', { inReplyTo: '21R' }), a('21R', 'cycle2', { inReplyTo: '20R' }), a('30R', 'same'), a('30R', 'same')]
  const roots = projectPageComments(raw, page, 1, [], false)
  expect(roots.flatMap(flattenComments)).toHaveLength(8)
  expect(roots[0].replies[0].replies[0].contents).toBe('nested')
  expect(roots.filter(node => node.contents === 'same').every(node => node.readonly && !node.cardId)).toBe(true)
  expect(roots.find(node => node.contents === 'orphan')?.issue).toMatch(/缺失/)
})
it('filters reply bodies/authors and sorts display-page then source time with unknown dates last', () => {
  const first = projectPageComments([a('11R', 'late', { creationDate: 'D:20260102000000Z' }), a('12R', 'unknown'), a('13R', 'early', { modificationDate: 'D:20260101000000Z' }), a('14R', 'needle', { inReplyTo: '11R', titleObj: { str: 'Alice' } })], page, 2, [], false)
  const second = projectPageComments([a('20R', 'page one')], { ...page, pageId: 'source:1' }, 1, [], false)
  expect(filterComments([...first, ...second], '').map(node => node.contents)).toEqual(['page one', 'early', 'late', 'unknown'])
  expect(filterComments(first, ' ALICE ').map(node => node.contents)).toEqual(['late'])
  expect(filterComments(first, 'needle')).toHaveLength(1)
})
it('keeps hidden/group annotations out of source panel and preview card ordinals exact, with no mutation identities', () => {
  const raw = [a('hidden', 'hidden', { hidden: true }), a('group', 'group', { replyType: 'Group' }), a('10R', 'actual output')]
  const preview = projectPageComments(raw, page, 1, [{ kind: 'addTextAnnotation', pageId: page.pageId, text: 'pending' }], true)
  expect(preview).toHaveLength(1); expect(preview[0]).toMatchObject({ cardId: 'readonly:2', contents: 'actual output', readonly: true })
  const original = projectPageComments([], page, 1, [{ kind: 'addTextAnnotation', pageId: page.pageId, text: 'pending', createdMs: 0 }], false)
  expect(original[0]).toMatchObject({ pendingIndex: 0, contents: 'pending', timeMs: 0 })
})
it('walks a deep reply chain without recursive filter/count overflow', () => {
  const raw = Array.from({ length: 12000 }, (_, i) => a(`${i}R`, i === 11999 ? 'last' : 'node', i ? { inReplyTo: `${i - 1}R` } : {}))
  const roots = projectPageComments(raw, { ...page, notes: [] }, 1, [], false)
  expect(roots).toHaveLength(1); expect(flattenComments(roots[0])).toHaveLength(12000)
  expect(filterComments(roots, 'last')).toHaveLength(1)
})
it('caches in-flight and successful reads per document, evicts failures for retry, and separates previews', async () => {
  let calls = 0, fail = true
  const doc = { getPage: async () => ({ getAnnotations: async () => { calls++; if (fail) throw Error('bad page'); return [a('10R', 'ok')] } }) }
  const cache = new PdfAnnotationCache(), pending = cache.get(doc, 0)
  expect(cache.get(doc, 0)).toBe(pending); await expect(pending).rejects.toThrow()
  fail = false; expect(await cache.get(doc, 0)).toHaveLength(1); await cache.get(doc, 0); expect(calls).toBe(2)
  await cache.get({ ...doc }, 0); expect(calls).toBe(3)
  cache.clear(); await cache.get(doc, 0); expect(calls).toBe(4)
})
it('rejects malformed page replies for retry instead of reporting an empty complete document', async () => {
  let result: unknown = null
  const doc = { getPage: async () => ({ getAnnotations: async () => result as any[] }) }, cache = new PdfAnnotationCache()
  await expect(cache.get(doc, 0)).rejects.toThrow(/unreadable/)
  result = [a('10R', 'recovered')]; expect((await cache.get(doc, 0))[0].contentsObj?.str).toBe('recovered')
})

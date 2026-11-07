import { describe, expect, it, vi } from 'vitest'
import { NativeDraft, nativeDraftKey, type NativeDraftIdentity } from './native-draft'

const identity: NativeDraftIdentity = { documentId: 'doc-1', revision: 2, sourceSha256: 'a'.repeat(64), scope: { database: 'db', companyId: 'co', userId: 'u', threadId: 't' } }
const operation = (text: string) => ({ kind: 'replaceParagraph', blockId: 'block', expectedObjectSha256: 'b'.repeat(64), text })
function storage() {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
}

describe('native drafts', () => {
  it('copies operations and supports undo/redo without external mutation', () => {
    const draft = new NativeDraft(identity, storage(), () => 'request')
    const ops = [operation('first')]
    draft.setOperations(ops)
    ops[0].text = 'mutated outside'
    draft.setOperations([operation('second')])
    draft.undo()
    expect(draft.operations).toEqual([operation('first')])
    draft.redo()
    expect(draft.operations).toEqual([operation('second')])
    draft.undo()
    draft.setOperations([operation('third')])
    expect(draft.canRedo).toBe(false)
    draft.operations[0].text = 'external'
    expect(draft.operations).toEqual([operation('third')])
  })

  it('restores only the same scope, document, revision and source digest', () => {
    const store = storage()
    new NativeDraft(identity, store).setOperations([operation('draft')])
    expect(new NativeDraft(identity, store).operations).toEqual([operation('draft')])
    for (const changed of [
      { ...identity, documentId: 'another' }, { ...identity, revision: 3 },
      { ...identity, sourceSha256: 'c'.repeat(64) },
      ...Object.keys(identity.scope).map(key => ({ ...identity, scope: { ...identity.scope, [key]: 'foreign' } })),
    ]) expect(new NativeDraft(changed, store).operations).toEqual([])
    const key = nativeDraftKey(identity)
    const payload = JSON.parse(store.getItem(key)!)
    payload.identity.sourceSha256 = 'f'.repeat(64)
    store.setItem(key, JSON.stringify(payload))
    expect(new NativeDraft(identity, store).operations).toEqual([])
  })

  it('keeps a stable request on failure/reload and locks every mutation during save', () => {
    const store = storage()
    let sequence = 0
    const draft = new NativeDraft(identity, store, () => `request-${++sequence}`)
    draft.setOperations([operation('draft')])
    const first = draft.beginSave({ note: 'review' })
    expect(first).toMatchObject({ requestId: 'request-1', expectedSha256: identity.sourceSha256, operations: [operation('draft')], note: 'review' })
    expect(() => draft.setOperations([])).toThrow(/保存/)
    expect(() => draft.undo()).toThrow(/保存/)
    expect(() => draft.redo()).toThrow(/保存/)
    expect(() => draft.beginSave()).toThrow(/保存/)
    draft.saveFailed()
    expect(draft.operations).toEqual([operation('draft')])
    expect(draft.beginSave({ note: 'review' })).toEqual(first)
    const recovered = new NativeDraft(identity, store, () => 'new-id')
    expect(recovered.saving).toBe(false)
    expect(recovered.beginSave({ note: 'review' })).toEqual(first)
    recovered.saveFailed()
    recovered.setOperations([operation('changed')])
    expect(recovered.beginSave({ note: 'review' }).requestId).toBe('new-id')
  })

  it('keeps unregistered results retryable but ends editing after a saved revision', () => {
    const store = storage()
    const draft = new NativeDraft(identity, store, () => 'request')
    draft.setOperations([operation('draft')])
    const request = draft.beginSave()
    draft.saveCompleted({ revision: 3, revisionRegistered: false })
    expect(draft.beginSave()).toEqual(request)
    draft.saveCompleted({ revision: 3, revisionRegistered: true })
    expect(draft.closed).toBe(true)
    expect(draft.dirty).toBe(false)
    expect(() => draft.setOperations([])).toThrow(/修订/)
    expect(store.getItem(nativeDraftKey(identity))).toBeNull()
  })

  it('rejects malformed restores and unsafe operation payloads without erasing current edits', () => {
    const store = storage()
    store.setItem(nativeDraftKey(identity), '{broken')
    const draft = new NativeDraft(identity, store)
    expect(draft.operations).toEqual([])
    draft.setOperations([operation('safe')])
    expect(() => draft.setOperations(Array.from({ length: 501 }, () => operation('bad')))).toThrow()
    expect(() => draft.setOperations([{ kind: 'rotatePage', delta: NaN }])).toThrow()
    expect(draft.operations).toEqual([operation('safe')])
  })

  it('does not expose mutable file identity or reuse a request for another export mode', () => {
    let sequence = 0
    const original = structuredClone(identity)
    const draft = new NativeDraft(original, storage(), () => `request-${++sequence}`)
    original.scope.companyId = 'changed'
    draft.identity.sourceSha256 = 'f'.repeat(64)
    draft.identity.scope.companyId = 'changed-again'
    expect(draft.identity).toEqual(identity)
    expect(draft.beginSave().requestId).toBe('request-1')
    draft.saveFailed()
    expect(draft.beginSave({ action: 'export' }).requestId).toBe('request-2')
  })

  it('storage quota failure does not discard live operations', () => {
    const store = { getItem: () => null, setItem: () => { throw new Error('quota') }, removeItem: () => undefined }
    const draft = new NativeDraft(identity, store)
    draft.setOperations([operation('safe')])
    expect(draft.operations).toEqual([operation('safe')])
    expect(draft.persistenceError).toBeTruthy()
  })
})

it('文字预览确认摘要参与保存幂等身份，确认改变不得复用旧requestId', () => {
  const identity={documentId:'confirm',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}}
  const draft=new NativeDraft(identity,localStorage,vi.fn().mockReturnValueOnce('first').mockReturnValueOnce('second'))
  draft.setOperations([{kind:'replaceText',newText:'修改'}])
  const first=draft.beginSave({confirmedPreviewDigest:'b'.repeat(64)})
  draft.saveFailed()
  const same=draft.beginSave({confirmedPreviewDigest:'b'.repeat(64)})
  expect(same.requestId).toBe(first.requestId)
  draft.saveFailed()
  const changed=draft.beginSave({confirmedPreviewDigest:'c'.repeat(64)})
  expect(changed.requestId).not.toBe(first.requestId)
  expect(changed.confirmedPreviewDigest).toBe('c'.repeat(64))
})

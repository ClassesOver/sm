import { expect, it } from 'vitest'
import { applyDocxCommentTextIntent, assertDocxCommentTextBatch, commentTextOperationsOf, editDocxCommentTextOperations,
  normalizeDocxCommentText, projectedDocxCommentTexts, replayDocxCommentText, verifiedDocxCommentTextModel, type DocxCommentTextModel } from './docx-comment-text'
import type { DocxPmNode } from './docx-operations'

const sourceId = 'c'.repeat(64), targetId = 'd'.repeat(64)
const target = { sourceId, targetId, expectedCommentsSha256: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64),
  originalCommentId: '7', ordinal: 0, author: 'Alice', date: null, initials: 'A', text: 'Original 😀', relationshipIds: [], editableText: true, readOnlyReason: null }
const model: DocxCommentTextModel = { sourceSha256: 'e'.repeat(64), sourceId, commentReadOnlyReason: null, commentTargets: [target] }
const baseline = (): DocxPmNode => ({ type: 'doc', attrs: { title: 'Untouched' }, content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'Body' }] }] })

it('projects only source-authorized comment text and reverts an edit to baseline as no operation', () => {
  const changed = editDocxCommentTextOperations(model, [], targetId, 'Edited 😀')
  expect(changed).toEqual([{ kind: 'editCommentText', sourceId, targetId, expectedCommentsSha256: 'a'.repeat(64), expectedObjectSha256: 'b'.repeat(64), text: 'Edited 😀' }])
  expect(projectedDocxCommentTexts(model, changed)[0]).toMatchObject({ text: 'Edited 😀', pending: true, editableText: true })
  expect(editDocxCommentTextOperations(model, changed, targetId, 'Original 😀')).toEqual([])
})

it.each(['foreign-source', 'foreign-target', 'stale-part', 'stale-object', 'readonly', 'extra-field', 'duplicate'])('rejects %s comment edit identity before projection', fault => {
  const invalid = fault === 'foreign-source' ? { kind: 'editCommentText', sourceId: 'f'.repeat(64), targetId, expectedCommentsSha256: target.expectedCommentsSha256, expectedObjectSha256: target.expectedObjectSha256, text: 'x' }
    : fault === 'foreign-target' ? { kind: 'editCommentText', sourceId, targetId: 'f'.repeat(64), expectedCommentsSha256: target.expectedCommentsSha256, expectedObjectSha256: target.expectedObjectSha256, text: 'x' }
    : fault === 'stale-part' ? { kind: 'editCommentText', sourceId: target.sourceId, targetId: target.targetId, expectedCommentsSha256: '0'.repeat(64), expectedObjectSha256: target.expectedObjectSha256, text: 'x' }
    : fault === 'stale-object' ? { kind: 'editCommentText', sourceId: target.sourceId, targetId: target.targetId, expectedCommentsSha256: target.expectedCommentsSha256, expectedObjectSha256: '0'.repeat(64), text: 'x' }
    : fault === 'extra-field' ? { kind: 'editCommentText', sourceId: target.sourceId, targetId: target.targetId, expectedCommentsSha256: target.expectedCommentsSha256, expectedObjectSha256: target.expectedObjectSha256, text: 'x', author: 'forged' }
    : { kind: 'editCommentText', sourceId: target.sourceId, targetId: target.targetId, expectedCommentsSha256: target.expectedCommentsSha256, expectedObjectSha256: target.expectedObjectSha256, text: 'x' }
  const source = fault === 'readonly' ? { ...model, commentTargets: [{ ...target, editableText: false, readOnlyReason: 'unsupported comment structure' }] } : model
  expect(() => projectedDocxCommentTexts(source, fault === 'duplicate' ? [invalid, invalid] : [invalid])).toThrow()
})

it('stores comment intent on the document root, preserves body edits, and restores through undoable document state', () => {
  const original = baseline(), operations = editDocxCommentTextOperations(model, [], targetId, 'Edited')
  const projected = replayDocxCommentText(original, operations, model)
  expect(projected.content).toEqual(original.content)
  expect(commentTextOperationsOf(projected, model)).toEqual(operations)
  const normalized = normalizeDocxCommentText(original, projected, model)
  expect(normalized.operations).toEqual(operations)
  expect(normalized.current).toEqual(original)
  const applied = applyDocxCommentTextIntent(projected, [], model)
  expect(commentTextOperationsOf(applied)).toEqual([])
})

it('rejects mixed operation batches and malformed doc-level recovery intents', () => {
  expect(() => assertDocxCommentTextBatch([{ kind: 'editCommentText' }, { kind: 'replaceParagraph' }])).toThrow()
  expect(() => assertDocxCommentTextBatch(Array.from({ length: 201 }, (_, index) => ({ kind: 'editCommentText', targetId: String(index) })))).toThrow()
  const forged = baseline(); forged.attrs = { ...forged.attrs, nativeCommentTextOperations: [{ ...editDocxCommentTextOperations(model, [], targetId, 'Edited')[0], text: 'bad\rvalue' }] }
  expect(() => normalizeDocxCommentText(baseline(), forged, model)).toThrow()
  expect(() => normalizeDocxCommentText(baseline(), { ...baseline(), content: [{ type: 'docParagraph', attrs: { nativeCommentTextOperations: [] } }] }, model)).toThrow()
})

it('rejects recovered edits for a globally readonly manifest even when its target claims editability', () => {
  const operations = editDocxCommentTextOperations(model, [], targetId, 'Edited')
  const blocked = { ...model, commentReadOnlyReason: '受保护的批注来源' }
  expect(() => projectedDocxCommentTexts(blocked, operations)).toThrow()
  expect(() => replayDocxCommentText(baseline(), operations, blocked)).toThrow()
  expect(() => editDocxCommentTextOperations(blocked, [], targetId, 'Edited')).toThrow()
  expect(projectedDocxCommentTexts(blocked, [])).toHaveLength(1)
})

it('uses parser metadata only to restrict existing server targets and refuses changed paragraph counts', () => {
  const parsed = [{ id: '7', author: 'Alice', text: 'Original 😀', initials: 'A' }]
  expect(verifiedDocxCommentTextModel(model, model.sourceSha256, parsed).commentTargets[0].editableText).toBe(true)
  expect(verifiedDocxCommentTextModel(model, model.sourceSha256, [{ ...parsed[0], text: 'Foreign' }]).commentTargets[0]).toMatchObject({ editableText: false, readOnlyReason: expect.stringContaining('显示与服务端来源不一致') })
  expect(verifiedDocxCommentTextModel(model, model.sourceSha256, [...parsed, ...parsed]).commentTargets[0].editableText).toBe(false)
  expect(() => verifiedDocxCommentTextModel(model, 'f'.repeat(64), parsed)).toThrow()
  expect(() => editDocxCommentTextOperations(model, [], targetId, 'New\nparagraph')).toThrow()
})

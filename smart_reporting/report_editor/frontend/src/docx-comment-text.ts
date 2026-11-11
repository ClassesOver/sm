import type { DocxPmNode } from './docx-operations'

export interface DocxCommentTextTarget {
  sourceId: string; targetId: string; expectedCommentsSha256: string; expectedObjectSha256: string
  originalCommentId: string; ordinal: number; author: string; date: string | null; initials: string | null
  text: string; relationshipIds: string[]; editableText: boolean; readOnlyReason: string | null
}
export interface DocxCommentTextModel {
  sourceSha256: string; sourceId: string | null; commentTargets: DocxCommentTextTarget[]; commentReadOnlyReason: string | null
}
export type DocxCommentTextOperation = {
  kind: 'editCommentText'; sourceId: string; targetId: string; expectedCommentsSha256: string; expectedObjectSha256: string; text: string
}
export type DocxCommentTextEntry = DocxCommentTextTarget & { pending: boolean }
const intentKey = 'nativeCommentTextOperations'
const operationKeys = ['expectedCommentsSha256', 'expectedObjectSha256', 'kind', 'sourceId', 'targetId', 'text'].sort()
const clone = <T>(value: T): T => structuredClone(value)
function fail(): never { throw new Error('批注文字草稿与当前服务端来源不一致或包含不支持的修改') }
const sha256 = (value: unknown): value is string => typeof value === 'string' && /^[a-f\d]{64}$/.test(value)
function validText(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > 65536 || value.includes('\r')) return false
  for (const character of value) {
    const code = character.codePointAt(0)!
    if (!(code === 9 || code === 10 || code >= 32 && code <= 0xd7ff || code >= 0xe000 && code <= 0xfffd || code >= 0x10000 && code <= 0x10ffff)) return false
  }
  return true
}
function checkedModel(model: DocxCommentTextModel, expectedSourceSha256?: string): DocxCommentTextModel {
  if (!model || typeof model !== 'object' || !sha256(model.sourceSha256) || expectedSourceSha256 && model.sourceSha256 !== expectedSourceSha256
    || !(model.sourceId === null || sha256(model.sourceId)) || !Array.isArray(model.commentTargets) || model.commentTargets.length > 10000
    || !(model.commentReadOnlyReason === null || typeof model.commentReadOnlyReason === 'string')) fail()
  const targets = new Set<string>()
  for (const target of model.commentTargets) {
    if (!target || typeof target !== 'object' || !sha256(target.sourceId) || target.sourceId !== model.sourceId || !sha256(target.targetId)
      || !sha256(target.expectedCommentsSha256) || !sha256(target.expectedObjectSha256) || typeof target.originalCommentId !== 'string'
      || !Number.isSafeInteger(target.ordinal) || target.ordinal < 0 || typeof target.author !== 'string'
      || !(target.date === null || typeof target.date === 'string') || !(target.initials === null || typeof target.initials === 'string')
      || typeof target.text !== 'string' || !Array.isArray(target.relationshipIds) || !target.relationshipIds.every(id => typeof id === 'string')
      || typeof target.editableText !== 'boolean' || !(target.readOnlyReason === null || typeof target.readOnlyReason === 'string')
      || targets.has(target.targetId)) fail()
    targets.add(target.targetId)
  }
  if (model.sourceId === null && model.commentTargets.length) fail()
  return model
}
function validateOperations(value: unknown, model: DocxCommentTextModel): DocxCommentTextOperation[] {
  checkedModel(model)
  if (!Array.isArray(value) || value.length > 200) fail()
  const seen = new Set<string>()
  return value.map(raw => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).sort().join('\0') !== operationKeys.join('\0')) fail()
    const op = raw as Record<string, unknown>, target = model.commentTargets.find(item => item.targetId === op.targetId)
    if (op.kind !== 'editCommentText' || typeof op.targetId !== 'string' || seen.has(op.targetId) || model.commentReadOnlyReason || !target?.editableText
      || op.sourceId !== target.sourceId || op.expectedCommentsSha256 !== target.expectedCommentsSha256
      || op.expectedObjectSha256 !== target.expectedObjectSha256 || !validText(op.text) || op.text.split('\n').length !== target.text.split('\n').length) fail()
    seen.add(op.targetId)
    return clone(op) as unknown as DocxCommentTextOperation
  })
}
export function commentTextOperationsOf(doc: DocxPmNode, model?: DocxCommentTextModel): DocxCommentTextOperation[] {
  const value = doc.attrs?.[intentKey]
  if (value === undefined || value === null) return []
  if (!model) fail()
  return validateOperations(value, model)
}
export function projectedDocxCommentTexts(model: DocxCommentTextModel, operations: readonly unknown[]): DocxCommentTextEntry[] {
  checkedModel(model)
  const valid = validateOperations(operations, model), byTarget = new Map(valid.map(operation => [operation.targetId, operation]))
  return model.commentTargets.map(target => ({ ...clone(target), text: byTarget.get(target.targetId)?.text ?? target.text, pending: byTarget.has(target.targetId) }))
}
export function editDocxCommentTextOperations(model: DocxCommentTextModel, operations: readonly DocxCommentTextOperation[], targetId: string, text: string): DocxCommentTextOperation[] {
  const current = validateOperations(operations, model), target = model.commentTargets.find(item => item.targetId === targetId)
  if (model.commentReadOnlyReason || !target?.editableText || !validText(text) || text.split('\n').length !== target.text.split('\n').length) fail()
  const index = current.findIndex(operation => operation.targetId === targetId), next = current.filter(operation => operation.targetId !== targetId)
  if (text !== target.text) {
    const operation: DocxCommentTextOperation = { kind: 'editCommentText', sourceId: target.sourceId, targetId: target.targetId,
      expectedCommentsSha256: target.expectedCommentsSha256, expectedObjectSha256: target.expectedObjectSha256, text }
    if (index < 0) next.push(operation); else next.splice(index, 0, operation)
  }
  return next
}
export function applyDocxCommentTextIntent(current: DocxPmNode, operations: readonly unknown[], model: DocxCommentTextModel): DocxPmNode {
  const result = clone(current), valid = validateOperations(operations, model)
  result.attrs = { ...result.attrs }
  if (valid.length) result.attrs[intentKey] = clone(valid)
  else delete result.attrs[intentKey]
  if (!Object.keys(result.attrs).length) delete result.attrs
  return result
}
export function replayDocxCommentText(doc: DocxPmNode, operations: readonly unknown[], model: DocxCommentTextModel): DocxPmNode {
  return applyDocxCommentTextIntent(doc, operations, model)
}
export function normalizeDocxCommentText(baseline: DocxPmNode, live: DocxPmNode, model: DocxCommentTextModel) {
  const current = clone(live), operations = commentTextOperationsOf(current, model)
  const visit = (node: DocxPmNode, root: boolean) => {
    if (!root && Object.hasOwn(node.attrs ?? {}, intentKey)) fail()
    node.content?.forEach(child => visit(child, false))
  }
  visit(current, true)
  current.attrs = { ...current.attrs }
  delete current.attrs[intentKey]
  if (!Object.keys(current.attrs).length) delete current.attrs
  if (baseline.attrs?.[intentKey] != null) fail()
  return { current, operations }
}
export function assertDocxCommentTextBatch(operations: readonly { kind?: unknown }[]): void {
  const comments = operations.filter(operation => operation?.kind === 'editCommentText')
  if (comments.length && comments.length !== operations.length) throw new Error('批注修改必须独立保存，请先保存或撤销正文及其他修改')
  if (comments.length > 200 || new TextEncoder().encode(JSON.stringify(operations)).length > 12 * 1024 * 1024) fail()
}

/** 服务端清单才授予编辑能力；浏览器解析只核对显示，不从 comment id 反推授权。 */
export function verifiedDocxCommentTextModel(value: DocxCommentTextModel, expectedSourceSha256: string, parsed: readonly { id: string; author: string; text: string; date?: string; initials?: string }[]): DocxCommentTextModel {
  const model = clone(checkedModel(value, expectedSourceSha256))
  for (const target of model.commentTargets) {
    const matches = parsed.filter(comment => comment.id === target.originalCommentId), actual = matches[0]
    if (matches.length !== 1 || parsed[target.ordinal] !== actual || actual.author !== target.author || actual.text !== target.text
      || (actual.date ?? null) !== target.date || (actual.initials ?? null) !== target.initials) {
      target.editableText = false; target.readOnlyReason = '批注显示与服务端来源不一致，仅可查看原文'
    }
  }
  return model
}

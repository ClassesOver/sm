import { expect, it, vi } from 'vitest'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft } from './native-draft'

const identity = { documentId: 'show-transport', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }
const context = { context: { ...identity, format: 'pptx', sourceFile: { sha256: identity.sourceSha256 } } } as never
const fixture = () => {
  const draft = new NativeDraft(identity, { getItem: () => null, setItem() {}, removeItem() {} })
  draft.setOperations([{ kind: 'editSlides', order: [1, 0], transitions: [{ slideIndex: 1, kind: 'push' }] }])
  const result = { sourceSha256: identity.sourceSha256, draftSha256: 'b'.repeat(64), model: { slides: [] } }
  const api = { preview: vi.fn().mockResolvedValue(result), save: vi.fn(), renderTree: vi.fn() }
  return { draft, result, api, transport: createNativeOfficeTransport({ api: api as never, context, draft }) }
}

it('真实native传输允许放映只读preview，完整转发来源身份和快照，不保存或修改草稿', async () => {
  const { draft, result, api, transport } = fixture(), before = JSON.stringify(draft.operations)
  const body = { expectedSha256: identity.sourceSha256, operations: draft.operations }
  expect(await transport.slides('preview', { method: 'POST', body: JSON.stringify(body) })).toEqual(result)
  expect(api.preview).toHaveBeenCalledExactlyOnceWith(body)
  expect(api.save).not.toHaveBeenCalled(); expect(api.renderTree).not.toHaveBeenCalled()
  expect(JSON.stringify(draft.operations)).toBe(before); expect(draft.closed).toBe(false)
})

it('preview拒绝失配来源身份，不委托API也不修改草稿', async () => {
  const { draft, api, transport } = fixture(), before = JSON.stringify(draft.operations)
  await expect(transport.slides('preview', { method: 'POST', body: JSON.stringify({ expectedSha256: 'f'.repeat(64), operations: [] }) })).rejects.toThrow('来源已变化')
  expect(api.preview).not.toHaveBeenCalled(); expect(JSON.stringify(draft.operations)).toBe(before)
})

it('preview要求完整operations数组，拒绝缺省或错误形状，不扩展其他操作白名单', async () => {
  const { api, transport } = fixture()
  for (const operations of [undefined, {}, 'operations']) await expect(transport.slides('preview', { method: 'POST', body: JSON.stringify({ expectedSha256: identity.sourceSha256, operations }) })).rejects.toThrow('完整草稿')
  await expect(transport.slides('not-preview', { method: 'POST', body: JSON.stringify({ expectedSha256: identity.sourceSha256, operations: [] }) })).rejects.toThrow('未开放')
  expect(api.preview).not.toHaveBeenCalled()
})

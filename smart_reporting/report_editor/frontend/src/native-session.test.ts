import { describe, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { NativeDraft } from './native-draft'
import { bindNativeSession } from './native-session'

function fixture() {
  document.body.innerHTML = '<main id="app"></main>'
  localStorage.clear()
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'docx')
  const draft = new NativeDraft({ documentId: 'doc', revision: 1, sourceSha256: 'a'.repeat(64),
    scope: { database: 'db', companyId: 'c', userId: 'u', threadId: 't' } }, localStorage, () => 'request')
  draft.setOperations([{ kind: 'replaceParagraph', text: '修改' }])
  const result = { documentId: 'doc', revision: 2, parentRevision: 1, revisionRegistered: true,
    artifacts: { word: { downloadUrl: 'http://localhost/download' } },
    validation: { ok: false, issues: [{ code: 'native_review_pending', message: '尚未重新核验' }] } }
  const api = { save: vi.fn().mockResolvedValue(result), export: vi.fn().mockResolvedValue(result) }
  const view = { setSaving: vi.fn() }
  const navigate = vi.fn()
  const controller = bindNativeSession(shell, { draft, api, format: 'docx', view, navigate })
  return { shell, draft, api, result, view, navigate, controller }
}

describe('native save session', () => {
  it('keeps failed saves and retries the same request identity', async () => {
    const f = fixture()
    f.api.save.mockRejectedValueOnce(new Error('网络不可用'))
    await f.controller.save('save')
    expect(f.draft.dirty).toBe(true)
    expect(f.shell.statusLabel.textContent).toContain('网络不可用')
    await f.controller.save('save')
    expect(f.api.save.mock.calls[0][0].requestId).toBe(f.api.save.mock.calls[1][0].requestId)
    expect(f.view.setSaving.mock.calls).toEqual([[true], [false], [true], [false]])
    f.controller.dispose()
  })

  it('keeps unregistered results retryable and displays specific warnings and downloads', async () => {
    const f = fixture()
    f.api.save.mockResolvedValue({ ...f.result, revisionRegistered: false })
    await f.controller.save('save')
    expect(f.draft.closed).toBe(false)
    expect(f.draft.operations).toHaveLength(1)
    expect(document.body.textContent).toContain('尚未重新核验')
    expect(document.querySelector<HTMLAnchorElement>('.native-delivery a')?.href).toBe('http://localhost/download')
    expect(f.navigate).not.toHaveBeenCalled()
    f.controller.dispose()
  })

  it('locks the old snapshot and keeps warnings visible before opening the new revision', async () => {
    const f = fixture()
    f.api.save.mockResolvedValue({ ...f.result, editor: { openUrl: 'http://localhost/revision-2' } })
    await f.controller.save('save')
    expect(f.draft.closed).toBe(true)
    expect(f.shell.save.disabled).toBe(true)
    expect(f.navigate).not.toHaveBeenCalled()
    document.querySelector<HTMLAnchorElement>('.native-next-revision')!.click()
    expect(f.navigate).toHaveBeenCalledWith('http://localhost/revision-2')
    f.controller.dispose()
  })

  it('exports the current unsaved snapshot and retains identities without download URLs', async () => {
    const f = fixture()
    f.api.export.mockResolvedValue({ ...f.result, artifacts: { word: { sha256: 'b'.repeat(64) } } })
    await f.controller.save('export')
    expect(f.api.export.mock.calls[0][0].operations).toEqual(f.draft.operations)
    expect(f.api.save).not.toHaveBeenCalled()
    expect(f.shell.save.disabled).toBe(true)
    expect(document.querySelector('.native-delivery a')).toBeNull()
    expect(f.navigate).not.toHaveBeenCalled()
    f.controller.dispose()
  })
})

it('只读会话更新和直接调用保存均保持关闭，不发送请求', async () => {
  const f = fixture()
  f.controller.dispose()
  const controller = bindNativeSession(f.shell, {draft:f.draft,api:f.api,format:'docx',view:f.view,editingEnabled:false})
  controller.update()
  expect(f.shell.save.disabled).toBe(true)
  await controller.save('save')
  expect(f.api.save).not.toHaveBeenCalled()
  controller.dispose()
})

it('flushes pending edits before snapshot confirmation and includes them in the save request', async () => {
  const f = fixture(); f.controller.dispose()
  const operation = { kind: 'setHeaderFooter', text: '未失焦的页眉' }
  const view = { ...f.view,
    flushPendingEdits: vi.fn(() => f.draft.setOperations([...f.draft.operations, operation])),
    prepareSave: vi.fn(async () => { expect(f.draft.operations).toContainEqual(operation); return {} }),
  }
  const controller = bindNativeSession(f.shell, { draft: f.draft, api: f.api, format: 'docx', view })
  await controller.save('save')
  expect(f.api.save).toHaveBeenCalledOnce()
  expect(f.api.save.mock.calls[0][0].operations).toContainEqual(operation)
  expect(view.flushPendingEdits).toHaveBeenCalledOnce()
  controller.dispose()
})

it('still rejects edits made during asynchronous confirmation after flushing', async () => {
  const f = fixture(); f.controller.dispose()
  const view = { ...f.view, flushPendingEdits: vi.fn(), prepareSave: vi.fn(async () => {
    f.draft.setOperations([{ kind: 'replaceParagraph', text: '确认期间变化' }]); return {}
  }) }
  const controller = bindNativeSession(f.shell, { draft: f.draft, api: f.api, format: 'docx', view })
  await controller.save('save')
  expect(f.api.save).not.toHaveBeenCalled()
  expect(f.shell.statusLabel.textContent).toContain('草稿已变化')
  expect(f.draft.dirty).toBe(true)
  controller.dispose()
})

it('保存前必须完成文字修改确认，拒绝确认时草稿保留且不发送保存', async()=>{
  const f=fixture();f.controller.dispose()
  const view={...f.view,prepareSave:vi.fn().mockRejectedValueOnce(new Error('请确认跳过项')).mockResolvedValue({confirmedPreviewDigest:'b'.repeat(64)})}
  const controller=bindNativeSession(f.shell,{draft:f.draft,api:f.api,format:'pdf',view})
  await controller.save('save')
  expect(f.api.save).not.toHaveBeenCalled();expect(f.draft.dirty).toBe(true)
  expect(f.shell.statusLabel.textContent).toContain('请确认跳过项')
  await controller.save('save')
  expect(f.api.save.mock.calls[0][0].confirmedPreviewDigest).toBe('b'.repeat(64))
  controller.dispose()
})

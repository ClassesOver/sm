import { expect, it, vi } from 'vitest'
import type { WorkbookModel } from '@sheets-web/xlsx-engine'
import { mountWorkbookThreads } from './workbook-threaded-comments-host'

vi.mock('./workbook-threaded-comment-marker', () => ({
  installThreadedCommentAffordances: () => ({ dispose() {} }),
}))

it('routes Review commands through the existing thread pane and legacy note operations', async () => {
  const scroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
  const host = document.createElement('div')
  document.body.append(host)
  let row = 0, editable = true
  const notes = [{ row: 1, col: 0 }, { row: 3, col: 0 }]
  const sheet = {
    getSheetId: () => 'sheet-0',
    getNotes: () => notes,
    getSelection: () => ({ getActiveRange: () => ({ getRow: () => row, getColumn: () => 0 }) }),
  }
  const api = {
    getActiveWorkbook: () => ({ getActiveSheet: () => sheet }),
    Event: { ActiveSheetChanged: 'active-sheet-changed' },
    addEvent: () => ({ dispose() {} }),
    executeCommand: vi.fn(async () => true),
    syncExecuteCommand: vi.fn(() => true),
  }
  const commit = vi.fn(async () => {}), error = vi.fn()
  const jump = vi.fn((_sheet: string, nextRow: number) => { row = nextRow })
  const model = { sheets: [{ threads: { threads: [{
    id: 'thread', author: '作者', row: 3, column: 0, dT: '', done: false, text: '线程正文', replies: [],
  }] } }] } as unknown as WorkbookModel
  const view = mountWorkbookThreads(host, {
    runtime: { univerAPI: api } as never, actor: { personId: 'actor', author: '作者' },
    editable: () => editable, model, jump, commit, error,
  })
  try {
    view.run('comment-new')
    await vi.waitFor(() => expect(host.querySelector('textarea[placeholder="开始对话"]')).not.toBeNull())
    expect(commit).not.toHaveBeenCalled()
    view.run('comment-next')
    expect(jump).toHaveBeenLastCalledWith('sheet-0', 1, 0)
    expect(api.executeCommand).toHaveBeenCalledWith('sheet.operation.add-note-popup')
    expect(view.reason('comment-new')).toContain('已有注释')
    view.run('comment-delete')
    expect(api.syncExecuteCommand).toHaveBeenCalledWith('sheet.command.delete-note')
    view.run('comment-next')
    expect(jump).toHaveBeenLastCalledWith('sheet-0', 3, 0)
    await vi.waitFor(() => expect(host.textContent).toContain('线程正文'))
    editable = false
    expect(view.reason('comment-delete')).toContain('不可编辑')
    expect(view.reason('comment-prev')).toBeUndefined()
    editable = true
    view.run('comment-delete')
    expect(commit).toHaveBeenCalledWith('sheet-0', 3, 0, null)
    view.run('comments-pane-toggle')
    await vi.waitFor(() => expect(host.querySelector('.threaded-comments-pane')).toBeNull())
    expect(error).not.toHaveBeenCalled()
  } finally {
    view.dispose(); host.remove()
    if (scroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', scroll)
    else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
  }
})

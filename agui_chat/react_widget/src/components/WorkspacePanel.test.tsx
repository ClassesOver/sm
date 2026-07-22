import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChatRuntime } from '../runtime/ChatRuntime'
import type { WorkspaceEntry, WorkspaceReference } from '../types'
import { WorkspacePanel } from './WorkspacePanel'

vi.mock('@file-viewer/react-full', () => ({
  FileViewer: ({ url, filename, type }: { url: string; filename: string; type: string }) => {
    if (filename === '查看器失败.txt') throw new Error('viewer failed')
    return <div data-testid="file-viewer" data-url={url} data-filename={filename} data-type={type} />
  }
}))

function entry(name: string, overrides: Partial<WorkspaceEntry> = {}): WorkspaceEntry {
  return {
    path: name,
    name,
    isDirectory: false,
    size: 100,
    mimeType: 'text/plain',
    modifiedAt: '2026-07-20T08:00:00+08:00',
    ...overrides
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function runtimeWith(overrides: Record<string, unknown> = {}): ChatRuntime {
  return {
    listWorkspace: vi.fn(async () => []),
    subscribeWorkspace: vi.fn(() => () => undefined),
    readWorkspaceFile: vi.fn(async () => ({ blob: new Blob(['content'], { type: 'text/plain' }), mimeType: 'text/plain' })),
    downloadWorkspaceFile: vi.fn(async () => undefined),
    deleteWorkspaceEntry: vi.fn(async () => undefined),
    ...overrides
  } as unknown as ChatRuntime
}

function renderPanel(runtime: ChatRuntime, references: WorkspaceReference[] = [], overrides: Partial<React.ComponentProps<typeof WorkspacePanel>> = {}) {
  const props = {
    runtime,
    threadId: 'thread-1',
    references,
    onToggleReference: vi.fn(),
    onDeleted: vi.fn(),
    onClose: vi.fn(),
    ...overrides
  }
  return { ...render(<WorkspacePanel {...props} />), props }
}

function listedNames(): string[] {
  return screen.getAllByRole('listitem').map((item) => item.getAttribute('data-entry-name') || '')
}

let createObjectURL: ReturnType<typeof vi.fn>
let revokeObjectURL: ReturnType<typeof vi.fn>

beforeEach(() => {
  let objectUrlId = 0
  createObjectURL = vi.fn(() => `blob:workspace-${++objectUrlId}`)
  revokeObjectURL = vi.fn()
  Object.defineProperties(URL, {
    createObjectURL: { configurable: true, value: createObjectURL },
    revokeObjectURL: { configurable: true, value: revokeObjectURL }
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('workspace browsing', () => {
  it('searches the current directory, clears the query, and distinguishes no matches', async () => {
    const runtime = runtimeWith({
      listWorkspace: vi.fn(async () => [entry('合同说明.PDF', { mimeType: 'application/pdf' }), entry('预算.xlsx')])
    })
    renderPanel(runtime)

    expect(await screen.findByText('当前结果 2 项')).toBeTruthy()
    fireEvent.change(screen.getByRole('textbox', { name: '搜索当前目录' }), { target: { value: '合同说明.pdf' } })
    expect(screen.getByText('当前结果 1 项')).toBeTruthy()
    expect(screen.getByText('合同说明.PDF')).toBeTruthy()

    fireEvent.change(screen.getByRole('textbox', { name: '搜索当前目录' }), { target: { value: '不存在' } })
    expect(screen.getByText('没有匹配结果，请尝试其他名称。')).toBeTruthy()
    expect(screen.getByText('当前结果 0 项')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '清空搜索' }))
    expect(screen.getByText('当前结果 2 项')).toBeTruthy()
  })

  it('sorts by name, modified time, and size while keeping directories first', async () => {
    const entries = [
      entry('folder', { isDirectory: true, size: 9999, mimeType: false }),
      entry('large.txt', { size: 300, modifiedAt: '2026-07-19T08:00:00+08:00' }),
      entry('small.txt', { size: 10, modifiedAt: '2026-07-18T08:00:00+08:00' }),
      entry('bad.txt', { size: 20, modifiedAt: 'not-a-date' })
    ]
    renderPanel(runtimeWith({ listWorkspace: vi.fn(async () => entries) }))
    await screen.findByText('当前结果 4 项')

    expect(listedNames()).toEqual(['folder', 'bad.txt', 'large.txt', 'small.txt'])
    fireEvent.click(screen.getByRole('button', { name: '切换为降序' }))
    expect(listedNames()[0]).toBe('folder')
    expect(listedNames().slice(1)).toEqual(['small.txt', 'large.txt', 'bad.txt'])

    fireEvent.change(screen.getByRole('combobox', { name: '排序方式' }), { target: { value: 'size' } })
    expect(listedNames()).toEqual(['folder', 'large.txt', 'bad.txt', 'small.txt'])
    fireEvent.click(screen.getByRole('button', { name: '切换为升序' }))
    expect(listedNames()).toEqual(['folder', 'small.txt', 'bad.txt', 'large.txt'])

    fireEvent.change(screen.getByRole('combobox', { name: '排序方式' }), { target: { value: 'modifiedAt' } })
    expect(listedNames()).toEqual(['folder', 'small.txt', 'large.txt', 'bad.txt'])
    expect(screen.getByText('时间未知')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '切换为降序' }))
    expect(listedNames()).toEqual(['folder', 'large.txt', 'small.txt', 'bad.txt'])
  })

  it('shows the initial skeleton and preserves entries when a refresh fails', async () => {
    const initial = deferred<WorkspaceEntry[]>()
    const refresh = deferred<WorkspaceEntry[]>()
    const listWorkspace = vi.fn()
      .mockReturnValueOnce(initial.promise)
      .mockReturnValueOnce(refresh.promise)
      .mockResolvedValueOnce([entry('现有.txt')])
    renderPanel(runtimeWith({ listWorkspace }))

    expect(screen.getByRole('status', { name: '正在加载工作区' })).toBeTruthy()
    await act(async () => initial.resolve([entry('现有.txt')]))
    expect(await screen.findByText('现有.txt')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '刷新工作区' }))
    expect(screen.getByText('现有.txt')).toBeTruthy()
    expect(screen.getByText('正在刷新…')).toBeTruthy()
    await act(async () => refresh.reject(new Error('刷新失败，请稍后重试。')))
    expect((await screen.findByRole('alert')).textContent).toContain('刷新失败，请稍后重试。')
    expect(screen.getByText('现有.txt')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(listWorkspace).toHaveBeenCalledTimes(3))
    expect(screen.getByText('现有.txt')).toBeTruthy()
  })

  it('retries an initial load failure and then shows an empty directory', async () => {
    const listWorkspace = vi.fn()
      .mockRejectedValueOnce(new Error('无法读取工作区。'))
      .mockResolvedValueOnce([])
    renderPanel(runtimeWith({ listWorkspace }))

    expect((await screen.findByRole('alert')).textContent).toContain('无法读取工作区。')
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('当前目录为空。')).toBeTruthy()
  })

  it('refreshes the current directory after a host export changes the workspace', async () => {
    let workspaceListener: ((path: string) => void) | undefined
    const listWorkspace = vi.fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([entry('exports', { isDirectory: true })])
    const runtime = runtimeWith({
      listWorkspace,
      subscribeWorkspace: vi.fn((listener: (path: string) => void) => {
        workspaceListener = listener
        return () => undefined
      })
    })
    renderPanel(runtime)

    expect(await screen.findByText('当前目录为空。')).toBeTruthy()
    act(() => workspaceListener?.('exports/report.csv'))
    expect(await screen.findByText('exports')).toBeTruthy()
    expect(listWorkspace).toHaveBeenLastCalledWith('')
  })
})

describe('workspace preview', () => {
  it('passes a Blob URL to the shared viewer and releases it on close and unmount', async () => {
    const files = [entry('甲.txt'), entry('乙.pdf', { mimeType: 'application/pdf' })]
    const runtime = runtimeWith({ listWorkspace: vi.fn(async () => files) })
    const view = renderPanel(runtime)
    await screen.findByText('甲.txt')

    fireEvent.click(screen.getByRole('button', { name: '预览 甲.txt' }))
    expect(screen.getByText('正在读取文件预览…')).toBeTruthy()
    expect(await screen.findByTestId('file-viewer')).toMatchObject({
      dataset: { url: 'blob:workspace-1', filename: '甲.txt', type: 'txt' }
    })
    fireEvent.click(screen.getByRole('button', { name: '关闭预览' }))
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:workspace-1')

    fireEvent.click(screen.getByRole('button', { name: '预览 乙.pdf' }))
    expect((await screen.findByTestId('file-viewer')).getAttribute('data-url')).toBe('blob:workspace-2')
    view.unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:workspace-2')
  })

  it('only displays the last selection when file reads complete out of order', async () => {
    const first = deferred<{ blob: Blob; mimeType: string }>()
    const second = deferred<{ blob: Blob; mimeType: string }>()
    const readWorkspaceFile = vi.fn((path: string) => path === '甲.txt' ? first.promise : second.promise)
    renderPanel(runtimeWith({
      listWorkspace: vi.fn(async () => [entry('甲.txt'), entry('乙.txt')]),
      readWorkspaceFile
    }))
    await screen.findByText('甲.txt')

    fireEvent.click(screen.getByRole('button', { name: '预览 甲.txt' }))
    fireEvent.click(screen.getByRole('button', { name: '关闭预览' }))
    fireEvent.click(screen.getByRole('button', { name: '预览 乙.txt' }))
    await act(async () => second.resolve({ blob: new Blob(['second']), mimeType: 'text/plain' }))
    expect((await screen.findByTestId('file-viewer')).getAttribute('data-filename')).toBe('乙.txt')
    await act(async () => first.resolve({ blob: new Blob(['first']), mimeType: 'text/plain' }))
    expect(screen.getByTestId('file-viewer').getAttribute('data-filename')).toBe('乙.txt')
    expect(createObjectURL).toHaveBeenCalledTimes(1)
  })

  it('offers download fallback for unsupported formats and failed reads', async () => {
    const runtime = runtimeWith({
      listWorkspace: vi.fn(async () => [entry('模型.bin', { mimeType: 'application/octet-stream' }), entry('损坏.txt')]),
      readWorkspaceFile: vi.fn(async (path: string) => {
        if (path === '损坏.txt') throw new Error('文件暂时无法读取。')
        return { blob: new Blob(['binary']), mimeType: 'application/octet-stream' }
      })
    })
    renderPanel(runtime)
    await screen.findByText('模型.bin')

    fireEvent.click(screen.getByRole('button', { name: '预览 模型.bin' }))
    expect(await screen.findByText('此格式暂不支持在线预览，请下载后查看。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '下载文件' }))
    expect(runtime.downloadWorkspaceFile).toHaveBeenCalledWith('模型.bin')

    fireEvent.click(screen.getByRole('button', { name: '关闭预览' }))
    fireEvent.click(screen.getByRole('button', { name: '预览 损坏.txt' }))
    expect(await screen.findByText('文件暂时无法读取。')).toBeTruthy()
    expect(screen.getByRole('button', { name: '下载文件' })).toBeTruthy()
  })

  it('offers download fallback when the shared viewer fails', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const failed = entry('查看器失败.txt')
    const runtime = runtimeWith({ listWorkspace: vi.fn(async () => [failed]) })
    renderPanel(runtime)
    await screen.findByText(failed.name)

    fireEvent.click(screen.getByRole('button', { name: `预览 ${failed.name}` }))
    expect(await screen.findByText('文件查看器加载失败，请下载后查看。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '下载文件' }))
    expect(runtime.downloadWorkspaceFile).toHaveBeenCalledWith(failed.path)
    consoleError.mockRestore()
  })
})

describe('workspace references and deletion', () => {
  it('shows selected state, supports directory references, and reports the five-item limit', async () => {
    const existing = entry('已选.txt')
    const directory = entry('资料', { isDirectory: true, mimeType: false })
    const candidate = entry('待选.txt')
    const references = [existing, ...Array.from({ length: 4 }, (_, index) => entry(`引用-${index}.txt`))]
      .map((item) => ({ id: `workspace:${item.path}`, path: item.path, name: item.name, isDirectory: item.isDirectory }))
    const onToggleReference = vi.fn()
    const firstView = renderPanel(runtimeWith({ listWorkspace: vi.fn(async () => [existing, directory, candidate]) }), references, { onToggleReference })
    await screen.findByText('已选引用 5/5')

    expect(screen.getByRole('button', { name: '移除对话 已选.txt' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: '移除对话 已选.txt' }))
    expect(onToggleReference).toHaveBeenCalledWith(existing)
    fireEvent.click(screen.getByRole('button', { name: '加入对话 待选.txt' }))
    expect((await screen.findByRole('status')).textContent).toContain('工作区引用最多 5 个')
    expect(onToggleReference).not.toHaveBeenCalledWith(candidate)

    firstView.unmount()
    const view = renderPanel(runtimeWith({ listWorkspace: vi.fn(async () => [directory]) }), [], { onToggleReference })
    fireEvent.click(await screen.findByRole('button', { name: '加入对话 资料' }))
    expect(onToggleReference).toHaveBeenCalledWith(directory)
    view.unmount()
  })

  it('keeps full-path confirmation, prevents duplicate deletion, and retries after failure', async () => {
    const target = entry('合同/待删.txt', { name: '待删.txt' })
    const firstDelete = deferred<void>()
    const deleteWorkspaceEntry = vi.fn()
      .mockReturnValueOnce(firstDelete.promise)
      .mockResolvedValueOnce(undefined)
    const onDeleted = vi.fn()
    renderPanel(runtimeWith({ listWorkspace: vi.fn(async () => [target]), deleteWorkspaceEntry }), [], { onDeleted })
    await screen.findByText('待删.txt')

    fireEvent.click(screen.getByRole('button', { name: '删除 待删.txt' }))
    expect(screen.getByText('删除“合同/待删.txt”？')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认' }))
    expect((screen.getByRole('button', { name: '删除中…' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: '删除中…' }))
    expect(deleteWorkspaceEntry).toHaveBeenCalledTimes(1)

    await act(async () => firstDelete.reject(new Error('删除被拒绝。')))
    expect((await screen.findByRole('alert')).textContent).toContain('删除被拒绝。')
    expect(screen.getByText('删除“合同/待删.txt”？')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(target))
    expect(deleteWorkspaceEntry).toHaveBeenCalledTimes(2)
  })

  it('closes a related preview and releases its URL after successful deletion', async () => {
    const target = entry('待删.txt')
    const onDeleted = vi.fn()
    renderPanel(runtimeWith({ listWorkspace: vi.fn(async () => [target]) }), [], { onDeleted })
    await screen.findByText('待删.txt')
    fireEvent.click(screen.getByRole('button', { name: '删除 待删.txt' }))
    fireEvent.click(screen.getByRole('button', { name: '预览 待删.txt' }))
    await screen.findByTestId('file-viewer')
    fireEvent.click(screen.getByRole('button', { name: '确认' }))

    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(target))
    expect(screen.queryByTestId('file-viewer')).toBeNull()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:workspace-1')
  })
})

import { describe, expect, it } from 'vitest'
import type { WorkspaceEntry } from '../types'
import {
  getVisibleWorkspaceEntries,
  workspaceEntryContains,
  workspaceErrorMessage
} from './workspaceEntryModel'

const entries: WorkspaceEntry[] = [
  { path: '文件10.txt', name: '文件10.txt', isDirectory: false, size: 10, mimeType: 'text/plain', modifiedAt: '2026-07-02T00:00:00Z' },
  { path: '目录', name: '目录', isDirectory: true, size: 0, mimeType: '', modifiedAt: '' },
  { path: '文件2.txt', name: '文件2.txt', isDirectory: false, size: 20, mimeType: 'text/plain', modifiedAt: '2026-07-01T00:00:00Z' }
]

describe('工作区条目模型', () => {
  it('过滤当前目录并按自然名称排序且目录始终优先', () => {
    expect(getVisibleWorkspaceEntries(entries, '文件', 'name', 'asc').map((entry) => entry.name)).toEqual([
      '文件2.txt', '文件10.txt'
    ])
    expect(getVisibleWorkspaceEntries(entries, '', 'name', 'desc').map((entry) => entry.name)).toEqual([
      '目录', '文件10.txt', '文件2.txt'
    ])
  })

  it('支持大小和修改时间排序', () => {
    expect(getVisibleWorkspaceEntries(entries, '', 'size', 'asc').map((entry) => entry.name)).toEqual([
      '目录', '文件10.txt', '文件2.txt'
    ])
    expect(getVisibleWorkspaceEntries(entries, '', 'modifiedAt', 'desc').map((entry) => entry.name)).toEqual([
      '目录', '文件10.txt', '文件2.txt'
    ])
  })

  it('按目录边界判断包含关系', () => {
    expect(workspaceEntryContains(entries[1], '目录/合同/甲.pdf')).toBe(true)
    expect(workspaceEntryContains(entries[1], '目录外/甲.pdf')).toBe(false)
    expect(workspaceEntryContains(entries[0], entries[0].path)).toBe(true)
    expect(workspaceEntryContains(entries[0], `${entries[0].path}/子项`)).toBe(false)
  })

  it('优先使用异常消息并保留回退文案', () => {
    expect(workspaceErrorMessage(new Error('读取失败'), '默认错误')).toBe('读取失败')
    expect(workspaceErrorMessage('失败', '默认错误')).toBe('默认错误')
  })
})

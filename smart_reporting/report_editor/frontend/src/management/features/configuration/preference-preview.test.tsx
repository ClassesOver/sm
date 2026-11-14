import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PreferencePreview } from './preference-preview'

let root: Root
const fetcher = vi.fn()
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', fetcher)
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); fetcher.mockReset() })
async function mount(format = 'md', version = 3, disabled = false, showSettings = false) {
  await act(async () => root.render(<PreferencePreview format={format} version={version} csrf="test-csrf" disabled={disabled} showSettings={showSettings}><input aria-label="设置输入" defaultValue="保留输入" /></PreferencePreview>))
}
const button = () => [...document.querySelectorAll('button')].find(element => element.textContent === '预览已保存草稿')!
const result = { format: 'md', draftVersion: 3, contentHash: 'test', generatedDate: '2026-11-12',
  artifact: { filename: 'preview.md', mediaType: 'text/markdown', size: 6, sha256: 'test', base64: btoa('<b>old preview</b>') }, pdf: null, pages: [], issues: [], scope: '固定样例' }
it('按需请求保存版本，Markdown 作为文本显示', async () => {
  fetcher.mockResolvedValue(new Response(JSON.stringify(result)))
  await mount()
  expect(fetcher).not.toHaveBeenCalled()
  await act(async () => button().click())
  expect(fetcher.mock.calls[0][0]).toBe('/management/api/v1/configuration/preferences/preview/md')
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ expectedVersion: 3 })
  expect(document.querySelector('pre')?.textContent).toBe('<b>old preview</b>')
  expect(document.querySelector('pre b')).toBeNull()
})
it('格式切换后不展示之前未完成请求的旧预览', async () => {
  let finish!: (response: Response) => void
  fetcher.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  await mount(); await act(async () => button().click())
  await mount('xlsx', 3)
  await act(async () => finish(new Response(JSON.stringify(result))))
  expect(document.body.textContent).not.toContain('old preview')
  expect(document.querySelector('pre')).toBeNull()
})
it('未保存修改时禁用预览入口', async () => {
  await mount('md', 3, true)
  await act(async () => button().click())
  expect(fetcher).not.toHaveBeenCalled()
})

it('预览嵌入工作区，切换视图保留设置输入，不创建抽屉', async () => {
  await mount()
  expect(document.querySelector('[aria-label="真实样例预览"]')).not.toBeNull()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  const input = document.querySelector('input[aria-label="设置输入"]') as HTMLInputElement
  input.value = '尚未保存'
  const toggle = document.querySelector<HTMLButtonElement>('button[aria-label="预览"]')!
  await act(async () => toggle.click())
  expect(document.querySelector('[data-preference-view="preview"]')).not.toBeNull()
  expect(input.value).toBe('尚未保存')
  expect(fetcher).not.toHaveBeenCalled()
})
it('未保存修改时保留已生成样例并明确标注保存版本', async () => {
  fetcher.mockResolvedValue(new Response(JSON.stringify(result)))
  await mount(); await act(async () => button().click())
  await mount('md', 3, true)
  expect(document.querySelector('pre')?.textContent).toBe('<b>old preview</b>')
  expect(document.body.textContent).toContain('预览对应已保存草稿，尚未包含当前修改。')
})

it('保留原生分页诊断告警并展示可读取的 PPTX 样例', async () => {
  fetcher.mockResolvedValue(new Response(JSON.stringify({ ...result, format: 'pptx', artifact: {
    ...result.artifact, filename: 'preview.pptx', mediaType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' },
    issues: [{ page: 2, message: '文本超出幻灯片边界。' }] })))
  await mount('pptx')
  await act(async () => button().click())
  expect(document.body.textContent).toContain('第2页存在版面提示，请查看实际样例。')
  expect(document.body.textContent).not.toContain('Text overflow')
  expect([...document.querySelectorAll('button')].some(item => item.textContent === '读取原生样例')).toBe(true)
  expect(document.body.textContent).not.toContain('服务器响应格式异常')
})

it('字段校验失败后返回设置视图，避免错误字段被隐藏', async () => {
  await mount()
  await act(async () => document.querySelector<HTMLButtonElement>('button[aria-label="预览"]')!.click())
  await mount('md', 3, true, true)
  expect(document.querySelector('[data-preference-view="settings"]')).not.toBeNull()
})
it('保存版本变化清除旧样例，防止把旧效果误认为最新草稿', async () => {
  fetcher.mockResolvedValue(new Response(JSON.stringify(result)))
  await mount(); await act(async () => button().click())
  await mount('md', 4)
  expect(document.querySelector('pre')).toBeNull()
  expect(fetcher).toHaveBeenCalledTimes(1)
})

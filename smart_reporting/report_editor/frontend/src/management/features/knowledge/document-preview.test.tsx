import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { BusinessDocumentPreview } from './document-preview'
let root: Root, client: QueryClient
const fetcher = vi.fn(), close = vi.fn(), scope = { database: 'warehouse', companyId: 'a' }
const fragment = { text: '执行额合计÷预算额合计，不能平均各组比率。', locator: { kind: 'text_lines', lineStart: 1, lineEnd: 1, page: null, paragraph: null, table: null, row: null, column: null } }
const detail = { documentId: 'rules', revisions: [{ revision: 2, metadata: { title: '新版制度' }, originalHash: 'new-hash', reviewStatus: 'approved', ingestionStatus: 'ready', parseReceipt: { originalHash: 'new-hash', fragments: [{ ...fragment, text: '新版文本不应显示' }] } },
 { revision: 1, metadata: { title: '预算管理制度' }, originalHash: 'old-hash', reviewStatus: 'approved', ingestionStatus: 'ready', parseReceipt: { originalHash: 'old-hash', fragments: [fragment] } }] }
beforeEach(() => {
 Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
 vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
 vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
 vi.stubGlobal('fetch', fetcher); fetcher.mockResolvedValue(new Response(JSON.stringify(detail)))
 client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); vi.unstubAllGlobals(); fetcher.mockReset(); close.mockReset() })
async function until(check: () => void) { for (let i = 0; i < 60; i++) { await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)) }); try { check(); return } catch {} } check() }
async function mount() { await act(async () => root.render(<QueryClientProvider client={client}><BusinessDocumentPreview scope={scope} documentId="rules" revision={1} onClose={close} /></QueryClientProvider>)) }
it('shows only the explicitly selected revision and its real text location', async () => {
 await mount(); await until(() => expect(document.body.textContent).toContain(fragment.text))
 expect(document.body.textContent).toContain('第1–1行'); expect(document.body.textContent).not.toContain('新版文本不应显示')
 expect(document.body.textContent).toContain('解析片段')
 expect(fetcher.mock.calls[0][0]).toContain('/business-documents/rules?scopeDatabase=warehouse&companyId=a')
})
it('does not expose fragments from a revoked exact revision', async () => {
 fetcher.mockResolvedValue(new Response(JSON.stringify({ ...detail, revisions: [{ ...detail.revisions[1], reviewStatus: 'revoked' }] })))
 await mount(); await until(() => expect(document.body.textContent).toContain('修订已撤销'))
 expect(document.body.textContent).not.toContain(fragment.text)
})
it('rejects a parse receipt with another original identity', async () => {
 fetcher.mockResolvedValue(new Response(JSON.stringify({ ...detail, revisions: [{ ...detail.revisions[1], originalHash: 'different' }] })))
 await mount(); await until(() => expect(document.body.textContent).toContain('解析与原件身份不一致'))
 expect(document.body.textContent).not.toContain(fragment.text)
})
it('rejects another document identity instead of falling back to a matching revision', async () => {
 fetcher.mockResolvedValue(new Response(JSON.stringify({ ...detail, documentId: 'foreign' })))
 await mount(); await until(() => expect(document.body.textContent).toContain('未找到所选原件的精确修订'))
 expect(document.body.textContent).not.toContain(fragment.text)
})
it('does not fall back to a newer revision when the exact revision is absent', async () => {
 fetcher.mockResolvedValue(new Response(JSON.stringify({ ...detail, revisions: [detail.revisions[0]] })))
 await mount(); await until(() => expect(document.body.textContent).toContain('未找到所选原件的精确修订'))
 expect(document.body.textContent).not.toContain('新版文本不应显示')
})
it('limits initial fragment display and loads more only by explicit action', async () => {
 const fragments = Array.from({ length: 21 }, (_, index) => ({ ...fragment, text: '原文片段编号' + (index + 1) + '。' }))
 fetcher.mockResolvedValue(new Response(JSON.stringify({ ...detail, revisions: [{ ...detail.revisions[1], parseReceipt: { originalHash: 'old-hash', fragments } }] })))
 await mount(); await until(() => expect(document.body.textContent).toContain('原文片段编号20。'))
 expect(document.body.textContent).not.toContain('原文片段编号21。')
 await act(async () => [...document.querySelectorAll('button')].find(button => button.textContent?.replaceAll(' ', '') === '显示更多解析片段')!.click())
 expect(document.body.textContent).toContain('原文片段编号21。')
})
it('allows inspection of parsed pending material only in explicit management review mode', async () => {
 fetcher.mockResolvedValue(new Response(JSON.stringify({ ...detail, revisions: [{ ...detail.revisions[1], reviewStatus: 'pending', ingestionStatus: 'parsed' }] })))
 await act(async () => root.render(<QueryClientProvider client={client}><BusinessDocumentPreview scope={scope} documentId="rules" revision={1} reviewMode onClose={close} /></QueryClientProvider>))
 await until(() => expect(document.body.textContent).toContain(fragment.text))
 expect(document.body.textContent).toContain('尚未作为已发布制度依据')
})

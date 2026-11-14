import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { webcrypto } from 'node:crypto'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setUnauthorized } from '../../api/http'
import { PreferenceReportVerification, reportVerificationTarget, verifiedReportArtifactBytes } from './preference-report-verification'

let root: Root
const fetcher = vi.fn(), unauthorized = vi.fn(), created = vi.fn(() => 'blob:verified-report'), revoked = vi.fn()
const hash = 'a'.repeat(64), binding = 'b'.repeat(64), token = 't'.repeat(43)
const editor = '/reports/v1/editor/report-1/2', api = editor + '/api/preference-verification'
const recordList = '/management/api/v1/configuration/preferences/report-verification/results?expectedVersion=3&expectedHash=' + hash
const unavailable = { status: 'incomplete', availability: 'unavailable', artifact: null, pdf: null,
  readback: { status: 'unavailable' }, issues: [{ code: 'native_input_unavailable', message: '此格式缺少正式原生输入。' }] }
const result = () => ({ draftVersion: 3, contentHash: hash, status: 'failed', canApply: false,
  report: { reportId: 'report-1', revision: 2 }, bindingHash: binding, bindingValid: true,
  formats: { md: { ...unavailable }, xlsx: { ...unavailable }, pptx: { ...unavailable }, pdf: { ...unavailable },
    word: { ...unavailable, status: 'failed', availability: 'available', issues: [{ code: 'readback_failed', message: '分页回读不一致。' }] } },
  issues: [{ code: 'report_validation_failed', message: '材料验收未通过，仍可读取已授权产物。' }] })
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
function respond(value: unknown = result(), records: unknown[] = []) {
  fetcher.mockImplementation(async (url: string, options: RequestInit) => {
    if (url.startsWith('/management/api/v1/configuration/preferences/report-verification/results?')) return json(records)
    if (url === '/management/api/v1/configuration/preferences/report-verification') return json({ handoffToken: token, expiresAt: '2026-11-13T12:00:00Z' })
    if (url === api && options.method === 'GET') return json({ csrfToken: 'editor-csrf' })
    if (url === api && options.method === 'POST') return json({ reportId: 'report-1', revision: 2 })
    if (url === '/management/api/v1/configuration/preferences/report-verification/run') return json(value)
    throw new Error('unexpected request: ' + url)
  })
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('fetch', fetcher); vi.stubGlobal('crypto', webcrypto)
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: created })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revoked })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  setUnauthorized(unauthorized)
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); setUnauthorized(undefined); vi.unstubAllGlobals(); vi.restoreAllMocks();
  fetcher.mockReset(); unauthorized.mockReset(); created.mockClear(); revoked.mockClear() })
async function mount({ format = 'word', version = 3, contentHash = hash, disabled = false } = {}) {
  await act(async () => root.render(<PreferenceReportVerification format={format} version={version} contentHash={contentHash} csrf="admin-csrf" disabled={disabled} />))
}
const button = (label: string) => document.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!
async function open() {
  await act(async () => button('实际报告验收').click())
  await vi.waitFor(() => expect(document.querySelector('[role="dialog"]')).not.toBeNull())
  await vi.waitFor(() => expect(document.querySelector('[aria-label="已保存验收记录"]')).not.toBeNull())
  await vi.waitFor(() => expect(document.querySelector('[aria-label="已保存验收记录"]')?.textContent || '')
    .not.toContain('正在读取已保存记录'))
}
async function fill(value = editor) {
  const field = document.querySelector<HTMLInputElement>('input[aria-label="已打开的报告修订地址"]')!
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, value); field.dispatchEvent(new Event('input', { bubbles: true })) })
}
async function run(value = editor) { await open(); await fill(value); await act(async () => button('关联并验收报告').click()) }

it('仅按需打开对话框，提示当前浏览器完整报告权限且不把验收当作应用', async () => {
  await mount(); expect(document.querySelector('[role="dialog"]')).toBeNull(); expect(fetcher).not.toHaveBeenCalled()
  respond(); await open(); expect(document.body.textContent).toContain('先在当前浏览器打开具有完整编辑权限的报告')
  expect(document.body.textContent).toContain('不等于应用批准'); expect(fetcher.mock.calls.map(call => call[0])).toEqual([recordList])
})

it.each(['https://foreign.example/reports/v1/editor/report-1/2', '/reports/v1/editor/open/123', '/reports/v1/editor/assets/123',
  '/reports/v1/native/report-1/2', editor + '?session=secret', editor + '#fragment', editor + '/api/document',
  '/reports/v1/editor/report-1/0', '/reports/v1/editor/report-1/02', '/reports/v1/editor/%2e%2e/2',
  '/reports/v1/editor/report%2fother/2', '//evil.example/reports/v1/editor/report-1/2',
  'javascript:alert(1)', '/reports/v1/editor/a/../report-1/2'])('在创建挑战前拒绝非精确或不安全报告URL：%s', async value => {
  respond(); await mount(); await run(value)
  expect(fetcher.mock.calls.map(call => call[0])).toEqual([recordList]); expect(document.body.textContent).toContain('同源报告修订地址')
})

it('同源绝对地址与单段编码报告身份可精确解析', () => {
  expect(reportVerificationTarget(location.origin + editor)).toMatchObject({ reportId: 'report-1', revision: 2, api })
  expect(reportVerificationTarget('/reports/v1/editor/report%3A1/2')).toMatchObject({ reportId: 'report:1', revision: 2 })
})

it('四阶段分别使用限定管理路径与实际报告路径，报告错误不会登出管理会话', async () => {
  respond(); await mount(); await run(location.origin + editor)
  expect(fetcher.mock.calls.map(call => call[0])).toEqual([recordList, '/management/api/v1/configuration/preferences/report-verification', api, api,
    '/management/api/v1/configuration/preferences/report-verification/run'])
  const [, create, bootstrap, confirm, execute] = fetcher.mock.calls.map(call => call[1])
  expect(JSON.parse(create.body)).toEqual({ expectedVersion: 3, expectedHash: hash })
  expect(bootstrap).toMatchObject({ method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
  expect(bootstrap.body).toBeUndefined()
  expect(confirm).toMatchObject({ method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json', 'x-csrf-token': 'editor-csrf' } })
  expect(JSON.parse(confirm.body)).toEqual({ handoffToken: token })
  expect(JSON.parse(execute.body)).toEqual({ expectedVersion: 3, expectedHash: hash, handoffToken: token })
  expect(unauthorized).not.toHaveBeenCalled()
  expect(location.href).not.toContain(token); expect(localStorage.length).toBe(0)
  expect(document.body.textContent).toContain('分页回读不一致。'); expect(document.body.textContent).toContain('材料验收未通过')
  expect(document.body.textContent).not.toContain(token); expect(document.body.textContent).not.toContain('应用成功')
})

it.each([401, 403])('报告侧%s detail错误保留管理登录，并给出具体原因', async status => {
  respond(); const previous = fetcher.getMockImplementation()!
  fetcher.mockImplementation((url, options) => url === api ? Promise.resolve(json({ detail: { code: 'report_editor_session_invalid', message: '请重新打开此报告修订。' } }, status)) : previous(url, options))
  await mount(); await run(); expect(document.body.textContent).toContain('请重新打开此报告修订。'); expect(unauthorized).not.toHaveBeenCalled()
  expect(fetcher.mock.calls).toHaveLength(3)
})

it.each(['version', 'hash', 'report'])('拒绝%s不匹配响应，不保留旧证据', async mismatch => {
  const value = result(); if (mismatch === 'version') value.draftVersion = 4
  if (mismatch === 'hash') value.contentHash = 'c'.repeat(64)
  if (mismatch === 'report') value.report.revision = 3
  respond(value); await mount(); await run(); expect(document.body.textContent).toContain('验收响应与所选草稿或报告修订不一致')
  expect(document.querySelector('[aria-label="实际报告验收结果"]')).toBeNull()
})

it.each(['dirty', 'version', 'hash', 'format'])('%s变化清除已展示证据', async changed => {
  respond(); await mount(); await run(); expect(document.querySelector('[aria-label="实际报告验收结果"]')).not.toBeNull()
  await mount(changed === 'dirty' ? { disabled: true } : changed === 'version' ? { version: 4 } : changed === 'hash' ? { contentHash: 'c'.repeat(64) } : { format: 'pdf' })
  expect(document.querySelector('[aria-label="实际报告验收结果"]')).toBeNull()
  if (changed === 'dirty') expect(button('关联并验收报告').disabled).toBe(true)
})

it.each(['dirty', 'version', 'format', 'close'])('%s变化取消在途运行，不把异步结果归给新上下文', async changed => {
  respond(); const previous = fetcher.getMockImplementation()!; let finish!: (response: Response) => void
  fetcher.mockImplementation((url, options) => url.endsWith('/run') ? new Promise(resolve => { finish = resolve }) : previous(url, options))
  await mount(); await run()
  if (changed === 'close') await act(async () => document.querySelector<HTMLButtonElement>('.ant-modal-close')!.click())
  else await mount(changed === 'dirty' ? { disabled: true } : changed === 'version' ? { version: 4 } : { format: 'pdf' })
  await act(async () => finish(json(result())))
  expect(document.querySelector('[aria-label="实际报告验收结果"]')).toBeNull()
})

it('dirty草稿不能关联或创建挑战', async () => {
  await mount({ disabled: true }); expect(button('实际报告验收').disabled).toBe(true)
  await act(async () => button('实际报告验收').click()); expect(fetcher).not.toHaveBeenCalled()
})

it('最终绑定复核失败但已有已授权产物时，不误报通过且保留当前格式读取入口', async () => {
  const value = result(); value.bindingValid = false
  Object.assign(value.formats.word, { artifact: { filename: 'report.docx', mediaType: 'application/octet-stream', size: 1, sha256: hash, base64: 'YQ==' } })
  respond(value); await mount(); await run()
  expect(button('读取当前格式验收产物')).not.toBeNull(); expect(document.body.textContent).toContain('绑定复核未通过')
  expect(document.body.textContent).not.toContain('当前格式验收通过')
})

it('产物先核对实际字节大小及SHA256，通过后才创建Blob下载', async () => {
  const bytes = new TextEncoder().encode('verified artifact')
  const sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('')
  const artifact = { filename: 'report.docx', mediaType: 'application/octet-stream', size: bytes.length, sha256, base64: btoa('verified artifact') }
  expect([...await verifiedReportArtifactBytes(artifact)]).toEqual([...bytes])
  const value = result(); Object.assign(value.formats.word, { artifact }); respond(value); await mount(); await run()
  await act(async () => { button('读取当前格式验收产物').click(); await vi.waitFor(() => expect(created).toHaveBeenCalledTimes(1)) })
  expect(created).toHaveBeenCalledTimes(1); expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1)
})

it.each(['size', 'hash'])('产物%s不一致不创建下载，显示读取原因', async mismatch => {
  const value = result(); Object.assign(value.formats.word, { artifact: { filename: 'report.docx', mediaType: 'application/octet-stream',
    size: mismatch === 'size' ? 2 : 1, sha256: hash, base64: 'YQ==' } }); respond(value); await mount(); await run()
  const digesting = vi.spyOn(crypto.subtle, 'digest')
  await act(async () => { button('读取当前格式验收产物').click(); if (mismatch === 'hash') await digesting.mock.results[0].value })
  expect(created).not.toHaveBeenCalled(); expect(document.body.textContent).toContain('产物身份核验失败')
})

it.each(['challenge', 'bootstrap'])('%s阶段草稿变化后不继续关联或执行', async stage => {
  respond(); const previous = fetcher.getMockImplementation()!; let finish!: (response: Response) => void
  fetcher.mockImplementation((url, options) => (stage === 'challenge' ? url.endsWith('/report-verification') : url === api)
    ? new Promise(resolve => { finish = resolve }) : previous(url, options))
  await mount(); await run(); await mount({ version: 4 })
  await act(async () => finish(json(stage === 'challenge' ? { handoffToken: token, expiresAt: 'later' } : { csrfToken: 'editor-csrf' })))
  expect(fetcher.mock.calls).toHaveLength(stage === 'challenge' ? 2 : 3)
  expect(document.querySelector('[aria-label="实际报告验收结果"]')).toBeNull()
})

it('报告确认身份不符停止运行，不接受目标自报成功', async () => {
  respond(); const previous = fetcher.getMockImplementation()!
  fetcher.mockImplementation((url, options) => url === api && options.method === 'POST'
    ? Promise.resolve(json({ reportId: 'foreign-report', revision: 2 })) : previous(url, options))
  await mount(); await run(); expect(fetcher.mock.calls).toHaveLength(4)
  expect(document.body.textContent).toContain('报告关联响应与所选修订不一致')
})

it('管理401仍由既有request处理，不把报告侧错误混入管理会话', async () => {
  fetcher.mockResolvedValue(json({ code: 'management_session_invalid', message: '管理会话失效。' }, 401))
  await mount(); await run(); expect(unauthorized).toHaveBeenCalledTimes(1)
  expect(fetcher.mock.calls).toHaveLength(2)
})

it('实际SignatureEditor工具栏传递已保存草稿身份，编辑后禁用报告验收', async () => {
  const { App } = await import('antd')
  const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query')
  const { createMemoryRouter, RouterProvider } = await import('react-router-dom')
  const { SignatureEditor } = await import('./signature-editor')
  const documentValue = { common: { signer: '正式署名', dateFormat: 'iso', font: 'sans', accentColor: '#174a66' },
    word: { common: {}, signature: { font: null, size: 11, color: null, align: 'right', bold: false, description: '' } } }
  const detail = { draft: { version: 3, document: documentValue, contentHash: hash, updatedAt: '2026-11-13' },
    initial: documentValue, effective: null, changes: [], application: { canApply: false, reason: '尚未应用' } }
  const router = createMemoryRouter([{ path: '/', element: <SignatureEditor detail={detail} format="word" common={false}
    csrf="admin-csrf" onNavigate={() => {}} active readonlyContent={null} section="signature" /> }])
  respond()
  await act(async () => root.render(<App><QueryClientProvider client={new QueryClient()}><RouterProvider router={router} /></QueryClientProvider></App>))
  await run(); expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ expectedVersion: 3, expectedHash: hash })
  await act(async () => document.querySelector<HTMLButtonElement>('.ant-modal-close')!.click())
  const signer = document.querySelector<HTMLInputElement>('input[aria-label="格式署名"]')!
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(signer, '尚未保存'); signer.dispatchEvent(new Event('input', { bubbles: true })) })
  expect(button('实际报告验收').disabled).toBe(true)
})

it('通用偏好默认展示文本报告，同次结果切换格式不重复生成或误归产物', async () => {
  const value = result(); Object.assign(value.formats.md, { artifact: { filename: 'report.md', mediaType: 'text/markdown', size: 1, sha256: hash, base64: 'YQ==' } })
  respond(value); await mount({ format: 'common' }); await run()
  expect(document.body.textContent).toContain('当前格式：文本报告')
  expect(button('读取当前格式验收产物')).not.toBeNull()
  await act(async () => document.querySelector('[aria-label="验收结果格式"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))
  await act(async () => document.querySelector<HTMLDivElement>('.ant-select-item-option[title="PDF"]')!.click())
  expect(document.body.textContent).toContain('当前格式：PDF')
  expect(button('读取当前格式验收产物')).toBeNull()
  expect(fetcher.mock.calls).toHaveLength(5)
})

it('同一草稿累计服务器验收记录，地址与再次运行保留累计且只按需汇总', async () => {
  const firstId = '744e861b-2300-49d4-bf1b-5bef9297b997', secondId = '408309ec-026d-4cb7-821c-18142b36a5b2'
  const receipt = (id: string) => ({ id, contentHash: 'c'.repeat(64), contractHash: 'd'.repeat(64),
    executorManifestHash: 'e'.repeat(64), expiresAt: '2099-01-01T00:00:00Z' })
  respond(Object.assign(result(), { verificationReceipt: receipt(firstId) }))
  await mount(); await run()
  expect(document.body.textContent).toContain('已关联 1 条验收记录')
  expect(fetcher.mock.calls).toHaveLength(5)
  respond(Object.assign(result(), { verificationReceipt: receipt(secondId) }))
  await fill(editor); await act(async () => button('关联并验收报告').click())
  expect(document.body.textContent).toContain('已关联 2 条验收记录')
  expect(fetcher.mock.calls).toHaveLength(9)
  const previous = fetcher.getMockImplementation()!
  fetcher.mockImplementation((url, options) => url.endsWith('/prepare') ? Promise.resolve(json({
    id: '9a47cbe3-bdac-4d19-a470-8cd03dfcf44c', contentHash: 'f'.repeat(64), draft: { version: 3, contentHash: hash },
    contractVersion: 1, contractHash: 'd'.repeat(64), executorManifestHash: 'e'.repeat(64), expiresAt: '2099-01-01T00:00:00Z',
    status: 'incomplete', canApply: false, missingRequirements: [{ requirementId: 'template-binding-and-precedence',
      reason: 'implementation_missing', message: '模板落点尚未完成。', missingDimensions: [] }],
  })) : previous(url, options))
  await act(async () => button('汇总当前草稿验收').click())
  expect(JSON.parse(fetcher.mock.calls[9][1].body).evidenceIds).toEqual([firstId, secondId])
  expect(document.body.textContent).toContain('模板落点尚未完成')
  expect(document.querySelector('[aria-label="实际报告验收结果"]')).not.toBeNull()
  await mount({ version: 4 })
  expect(document.querySelector('[aria-label="全局偏好验收汇总"]')).toBeNull()
})

it('留存回执损坏不吞已生成验收文件，不把损坏回执加入汇总', async () => {
  const value = Object.assign(result(), { verificationReceipt: { id: 'invalid-receipt', contentHash: hash } })
  Object.assign(value.formats.word, { artifact: { filename: 'report.docx', mediaType: 'application/octet-stream',
    size: 1, sha256: hash, base64: 'YQ==' } })
  respond(value); await mount(); await run()
  expect(document.querySelector('[aria-label="读取当前格式验收产物"]')).not.toBeNull()
  expect(document.body.textContent).toContain('记录身份不完整')
  expect(document.querySelector('[aria-label="全局偏好验收汇总"]')).toBeNull()
  expect(document.querySelector<HTMLInputElement>('[aria-label="已打开的报告修订地址"]')?.value).toBe(editor)
})

it('关闭验收对话框清除本次累积记录，不写浏览器持久化', async () => {
  respond(Object.assign(result(), { verificationReceipt: { id: '744e861b-2300-49d4-bf1b-5bef9297b997',
    contentHash: 'c'.repeat(64), contractHash: 'd'.repeat(64), executorManifestHash: 'e'.repeat(64), expiresAt: '2099-01-01T00:00:00Z' } }))
  await mount(); await run()
  expect(document.body.textContent).toContain('已关联 1 条验收记录')
  await act(async () => document.querySelector<HTMLButtonElement>('.ant-modal-close')!.click())
  await open()
  expect(document.querySelector('[aria-label="全局偏好验收汇总"]')).toBeNull()
  expect(localStorage.length).toBe(0)
})

it('关闭后从服务端恢复当前草稿的验收记录并重新选择', async () => {
  const id = '744e861b-2300-49d4-bf1b-5bef9297b997'
  const saved = { id, contentHash: 'c'.repeat(64), contractHash: 'd'.repeat(64), executorManifestHash: 'e'.repeat(64),
    expiresAt: '2099-01-01T00:00:00Z', createdAt: '2026-11-13T03:00:00Z', draft: { version: 3, contentHash: hash },
    report: { reportId: 'report-1', revision: 2 }, assessment: { status: 'incomplete', canApply: false, missingRequirementCount: 12 } }
  respond(undefined, [saved]); await mount(); await open()
  const selector = () => document.querySelector<HTMLInputElement>(`input[aria-label="选择 report-1 修订 2 的验收记录"]`)!
  expect(document.body.textContent).toContain('未完成 · 12 项缺口')
  await act(async () => selector().click())
  expect(document.body.textContent).toContain('已关联 1 条验收记录')
  await act(async () => document.querySelector<HTMLButtonElement>('.ant-modal-close')!.click())
  await open(); expect(selector().checked).toBe(false)
  await act(async () => selector().click())
  expect(document.body.textContent).toContain('已关联 1 条验收记录')
  expect(fetcher.mock.calls.filter(call => String(call[0]).startsWith('/management/api/v1/configuration/preferences/report-verification/results?'))).toHaveLength(2)
})

it('读取已保存记录时修改报告地址，取消加载并忽略迟到的列表', async () => {
  let finish!: (response: Response) => void
  fetcher.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  await mount()
  await act(async () => button('实际报告验收').click())
  const records = () => document.querySelector('[aria-label="已保存验收记录"]')!
  expect(records().textContent).toContain('正在读取已保存记录')
  const signal = fetcher.mock.calls[0][1].signal as AbortSignal
  await fill()
  expect(signal.aborted).toBe(true)
  expect(records().textContent).not.toContain('正在读取已保存记录')
  expect(records().textContent).not.toContain('没有可恢复的验收记录')
  await act(async () => finish(json([{ id: '744e861b-2300-49d4-bf1b-5bef9297b997',
    contentHash: 'c'.repeat(64), contractHash: 'd'.repeat(64), executorManifestHash: 'e'.repeat(64),
    expiresAt: '2099-01-01T00:00:00Z', createdAt: '2026-11-13T03:00:00Z', draft: { version: 3, contentHash: hash },
    report: { reportId: 'report-1', revision: 2 }, assessment: { status: 'incomplete', canApply: false, missingRequirementCount: 12 } }])))
  expect(records().textContent).not.toContain('正在读取已保存记录')
  expect(records().querySelector('input[type="checkbox"]')).toBeNull()
})

it('切换格式清除已选验收记录，不能沿用旧格式的汇总选择', async () => {
  respond(Object.assign(result(), { verificationReceipt: { id: '744e861b-2300-49d4-bf1b-5bef9297b997',
    contentHash: 'c'.repeat(64), contractHash: 'd'.repeat(64), executorManifestHash: 'e'.repeat(64), expiresAt: '2099-01-01T00:00:00Z' } }))
  await mount(); await run()
  expect(document.body.textContent).toContain('已关联 1 条验收记录')
  await mount({ format: 'pdf' })
  expect(document.querySelector('[aria-label="全局偏好验收汇总"]')).toBeNull()
})

it('模板来源默认折叠，区分冻结正文、草稿落款与尚未完成的版式', async () => {
  const value = result()
  Object.assign(value.formats.word, { status: 'incomplete', readback: { status: 'passed' }, provenance: {
    layoutSource: 'uploaded_template', contentSource: 'frozen_report_markdown', signatureSource: 'current_draft',
    generatedDate: '2026-11-13', template: { filename: '财务模板.docx', size: 100, sha256: hash },
    bodyRepresentation: 'frozen_markdown_text', richDocumentProjection: 'unverified',
    internalPath: '/private/workspace/template.docx',
  } })
  respond(value); await mount(); await run()
  const details = document.querySelector<HTMLDetailsElement>('details[aria-label="模板排版来源"]')
  expect(details).not.toBeNull(); expect(details?.open).toBe(false)
  expect(document.body.textContent).toContain('模板局部回读通过，完整验收尚未完成')
  expect(details?.textContent).toContain('财务模板.docx')
  expect(details?.textContent).toContain('正文与标题：当前修订冻结成稿')
  expect(details?.textContent).toContain('落款：本次已保存草稿')
  expect(details?.textContent).toContain('2026-11-13')
  expect(details?.textContent).toContain('富文档转换尚未验证')
  expect(document.body.textContent).not.toContain('/private/workspace')
  expect(fetcher.mock.calls).toHaveLength(5)
})

it.each([
  ['native_docx_blocks', 'structure_verified', '原生标题、列表、表格与图片已按冻结正文独立核对。'],
  ['pdf_text_sample', 'sample_only', 'PDF 可见文字已抽样核对，原生对象结构尚未验证。'],
])('模板正文核验范围准确展示 %s', async (bodyRepresentation, richDocumentProjection, message) => {
  const value = result()
  Object.assign(value.formats.word, { status: 'incomplete', readback: { status: 'passed' }, provenance: {
    layoutSource: 'uploaded_template', contentSource: 'frozen_report_markdown', signatureSource: 'current_draft',
    generatedDate: '2026-11-13', template: { filename: '财务模板.docx', size: 100, sha256: hash },
    bodyRepresentation, richDocumentProjection,
  } })
  respond(value); await mount(); await run()
  expect(document.body.textContent).toContain(message)
  expect(document.body.textContent).toContain('完整布局尚未核验')
  expect(document.body.textContent).not.toContain('当前格式验收通过')
})

it('模板来源损坏仅提示具体回执问题，保留已生成文件入口', async () => {
  const value = result()
  Object.assign(value.formats.word, { provenance: { layoutSource: 'uploaded_template' },
    artifact: { filename: 'report.docx', mediaType: 'application/octet-stream', size: 1, sha256: hash, base64: 'YQ==' } })
  respond(value); await mount(); await run()
  expect(document.body.textContent).toContain('模板来源回执不完整，版式与来源仍需复核')
  expect(document.querySelector('[aria-label="读取当前格式验收产物"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="实际报告验收结果"]')).not.toBeNull()
})

it.each([
  ['declared_template_slot', 'template', 'replaced', 'passed', '模板声明的落款槽', '模板原有排版', '声明样例已替换', '通过（不含完整布局）'],
  ['body_end', 'generated_fallback', 'no_declared_slot', 'unverified', '正文末尾回退', '新增回退排版', '未声明落款槽', '尚未核验'],
])('模板来源展示实际落点与样例处理，生成回执不冒充完整验收：%s', async (
  placement, signatureLayoutSource, templateSampleStatus, signatureReadback, position, layout, sample, readback,
) => {
  const value = result()
  Object.assign(value.formats.word, { readback: { status: 'passed' }, provenance: {
    layoutSource: 'uploaded_template', contentSource: 'frozen_report_markdown', signatureSource: 'current_draft',
    generatedDate: '2026-11-13', template: { filename: '财务模板.docx', size: 100, sha256: hash },
    bodyRepresentation: 'native_docx_blocks', richDocumentProjection: 'structure_verified',
    placement, signatureLayoutSource, templateSampleStatus, signatureReadback,
  } })
  respond(value); await mount(); await run()
  const details = document.querySelector<HTMLDetailsElement>('details[aria-label="模板排版来源"]')!
  expect(details.open).toBe(false)
  expect(details.textContent).toContain('落款生成位置（生成回执）：' + position)
  expect(details.textContent).toContain('落款排版（生成回执）：' + layout)
  expect(details.textContent).toContain('声明样例处理（生成回执）：' + sample)
  expect(details.textContent).toContain('落款内容独立回读：' + readback)
  expect(details.textContent).toContain('未声明的模板样例尚未评估')
  expect(document.body.textContent).not.toContain('当前格式验收通过')
})

it.each(['constructor', { status: 'passed', path: '/private/material.docx' }])(
  '未知或损坏模板落点仅显示待复核，不丢其他来源和可下载产物：%s', async placement => {
    const value = result()
    Object.assign(value.formats.word, { artifact: { filename: 'report.docx', mediaType: 'application/octet-stream',
      size: 1, sha256: hash, base64: 'YQ==' }, provenance: {
      layoutSource: 'uploaded_template', contentSource: 'frozen_report_markdown', signatureSource: 'current_draft',
      generatedDate: '2026-11-13', template: { filename: '财务模板.docx', size: 100, sha256: hash },
      bodyRepresentation: 'native_docx_blocks', richDocumentProjection: 'structure_verified',
      placement, signatureLayoutSource: '__proto__', templateSampleStatus: 'constructor', signatureReadback: 'unexpected',
    } })
    respond(value); await mount(); await run()
    const details = document.querySelector<HTMLDetailsElement>('details[aria-label="模板排版来源"]')!
    expect(details.textContent).toContain('财务模板.docx')
    expect(details.textContent).toContain('落款生成位置（生成回执）：待复核')
    expect(details.textContent).toContain('落款排版（生成回执）：待复核')
    expect(details.textContent).toContain('声明样例处理（生成回执）：待复核')
    expect(details.textContent).toContain('落款内容独立回读：尚未核验')
    expect(details.textContent).not.toContain('/private/')
    expect(details.textContent).not.toContain('function Object')
    expect(button('读取当前格式验收产物')).not.toBeNull()
  },
)

it.each(['replaced', 'cleared'])('管理语义落点和样例处理区分模型判断与作者声明：%s', async status => {
  const value = result()
  Object.assign(value.formats.word, { artifact: { filename: 'report.docx', mediaType: 'application/octet-stream',
    size: 1, sha256: hash, base64: 'YQ==' }, provenance: {
    layoutSource: 'uploaded_template', contentSource: 'frozen_report_markdown', signatureSource: 'current_draft',
    generatedDate: '2026-11-13', template: { filename: '模板.docx', size: 100, sha256: hash },
    bodyRepresentation: 'native_docx_blocks', richDocumentProjection: 'structure_verified',
    placement: 'semantic_template_slot', signatureLayoutSource: 'template', templateSampleStatus: status, signatureReadback: 'passed',
  } })
  respond(value); await mount(); await run()
  const details = document.querySelector<HTMLDetailsElement>('details[aria-label="模板排版来源"]')!
  expect(details.open).toBe(false)
  expect(details.textContent).toContain('语义识别位置（模型判断）')
  expect(details.textContent).toContain(status === 'replaced' ? '语义识别样例已替换' : '语义识别样例已清除')
  expect(details.textContent).not.toContain('声明样例处理')
  expect(details.textContent).toContain('完整布局尚未核验')
  expect(button('读取当前格式验收产物')).not.toBeNull()
})

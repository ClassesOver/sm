import { afterEach, expect, it, vi } from 'vitest'
import { ReportEditorClient } from './api'
import { mountDataRefresh } from './evidence-refresh'
import { mountPolicyAdoption } from './evidence-policy-adoption'

afterEach(() => { document.body.innerHTML = ''; sessionStorage.clear() })

const provenance = {
  ok: true,
  templateLayout: { source: 'uploaded_template', scope: 'outside_declared_binding_targets',
    globalDefaults: 'not_applied', layoutValidation: 'unverified' },
  signature: { source: 'frozen_run_preferences', configurationHash: 'a'.repeat(64), generatedDate: '2026-11-13',
    bindingStatus: 'recorded', placement: 'declared_named_range', layoutSource: 'template',
    templateSampleStatus: 'replaced', undeclaredSamples: 'not_assessed', sheetName: '业务数据', cellRange: 'A20:A22' },
}

async function show(mode: 'refresh' | 'adopt', validation: unknown, files: Record<string, unknown> = {}) {
  const operation = mode === 'refresh' ? 'refresh_data' : 'adopt_policy'
  sessionStorage.setItem('provenance:' + (mode === 'refresh' ? 'data-refresh' : 'policy-adoption'), JSON.stringify({
    requestId: 'original-request', parentRevision: 1, expectedSha256: 'a'.repeat(64), operation,
    ...(mode === 'adopt' ? { confirmation: { requestId: 'original-request', previewHash: 'b'.repeat(64),
      targetPolicyVersion: { policyId: 'budget', revision: 2 },
      questionChoices: [{ questionId: 'q', metricVersion: null, reason: '明确保留缺项' }] } } : {}),
  }))
  const fetcher = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/delivery')
    ? Response.json({ task: {}, delivery: { revision: 2, validation,
      ...Object.fromEntries(['pdf', 'word', 'pptx', 'xlsx', 'md'].map(format => [format, { downloadUrl: '/download/' + format }])),
      ...files } })
    : Response.json({ taskId: 'task', status: 'completed', execution: { status: 'completed' } }))
  const root = document.createElement('div'); document.body.append(root)
  const options = { client: new ReportEditorClient('/editor', fetcher as typeof fetch), storageKey: 'provenance',
    getDraft: () => ({ markdown: '报告' }) }
  if (mode === 'refresh') mountDataRefresh(root, options)
  else mountPolicyAdoption(root, options)
  const status = mode === 'refresh' ? root.querySelector<HTMLButtonElement>('button')!
    : root.querySelector<HTMLButtonElement>('[data-action="status"]')!
  status.click()
  const delivery = mode === 'refresh' ? root.querySelectorAll<HTMLButtonElement>('button')[1]!
    : root.querySelector<HTMLButtonElement>('[data-action="delivery"]')!
  await vi.waitFor(() => expect(delivery.hidden).toBe(false))
  delivery.click()
  await vi.waitFor(() => expect(root.querySelectorAll('a').length).toBeGreaterThan(0))
  return { root, delivery, fetcher }
}

it.each(['refresh', 'adopt'] as const)('%s交付显示紧凑来源详情，中文下载名不混入扩展名，来源不等于验收', async mode => {
  const { root, delivery } = await show(mode, { ok: false, issues: [{ message: '模板视觉核验未完成' }], readback: provenance })
  expect([...root.querySelectorAll('a')].map(link => link.textContent)).toEqual([
    '下载 PDF · 修订 2', '下载 文字文档 · 修订 2', '下载 演示文稿 · 修订 2',
    '下载 电子表格 · 修订 2', '下载 文本报告 · 修订 2',
  ])
  const details = root.querySelector<HTMLDetailsElement>('details.delivery-layout-provenance')!
  expect(details).not.toBeNull(); expect(details.open).toBe(false)
  expect(details.querySelector('summary')?.textContent).toBe('排版来源')
  details.querySelector('summary')!.click(); expect(details.open).toBe(true)
  expect(details.textContent).toContain('上传模板')
  expect(details.textContent).toContain('本次运行冻结偏好')
  expect(details.textContent).toContain('模板声明的命名区域')
  expect(details.textContent).toContain('业务数据'); expect(details.textContent).toContain('A20:A22')
  expect(details.textContent).toContain('布局尚未核验')
  expect(details.textContent).toContain('未声明样例尚未评估')
  expect(details.textContent).toContain('来源记录不代表验收通过')
  expect(root.textContent).toContain('模板视觉核验未完成')
  expect(details.textContent).not.toContain('验收已通过')
  delivery.click()
  await vi.waitFor(() => expect(root.querySelectorAll('details.delivery-layout-provenance')).toHaveLength(1))
})

it.each(['refresh', 'adopt'] as const)('%s缺失/损坏来源、告警或某个下载链接时保留其他可用文件', async mode => {
  const { root } = await show(mode, { ok: false, issues: 'damaged', readback: { ok: true,
    templateLayout: [], signature: { source: 'unexpected', placement: 'declared_textbox', bindingStatus: 'unavailable' } } },
    { pdf: { downloadUrl: 'http://[' } })
  expect(root.querySelectorAll('a')).toHaveLength(4)
  expect(root.querySelector('a[href$="/download/md"]')).not.toBeNull()
  expect(root.textContent).toContain('文件可下载，验收尚未通过')
  const details = root.querySelector('details.delivery-layout-provenance')!
  expect(details.textContent).toContain('未知或未核验')
  expect(details.textContent).not.toContain('模板声明的文本框')
  expect(details.textContent).not.toContain('unexpected')
})

it.each(['refresh', 'adopt'] as const)('%s旧响应仍可下载，未知来源不会伪装为全局偏好', async mode => {
  const { root } = await show(mode, undefined)
  expect(root.querySelectorAll('a')).toHaveLength(5)
  expect(root.querySelector('details.delivery-layout-provenance')?.textContent).toContain('未知或未核验')
  expect(root.textContent).not.toContain('本次运行冻结偏好')
})

it.each(['refresh', 'adopt'] as const)('%s回退位置、保留样例及不可信字符串以普通文字显示', async mode => {
  const readback = { ...provenance, signature: { ...provenance.signature, placement: 'signature_sheet',
    layoutSource: 'generated_fallback', templateSampleStatus: 'preserved_for_review',
    sheetName: '<img src=x onerror="alert(1)">', cellRange: null } }
  const { root } = await show(mode, { ok: false, issues: [], readback })
  const details = root.querySelector('details.delivery-layout-provenance')!
  expect(details.textContent).toContain('独立说明页')
  expect(details.textContent).toContain('生成的回退布局')
  expect(details.textContent).toContain('保留待核对')
  expect(details.textContent).toContain('<img src=x')
  expect(details.querySelector('img')).toBeNull()
  expect(details.querySelector('script')).toBeNull()
})

it.each(['refresh', 'adopt'] as const)('%s未知枚举不能借用对象原型伪装来源', async mode => {
  const { root } = await show(mode, { ok: false, issues: [], readback: { ...provenance,
    signature: { ...provenance.signature, placement: 'constructor', templateSampleStatus: '__proto__' } } })
  const details = root.querySelector('details.delivery-layout-provenance')!
  expect(details.textContent).toContain('落款位置：未知或未核验')
  expect(details.textContent).not.toContain('function Object')
  expect(details.textContent).not.toContain('[object Object]')
})

it.each(['refresh', 'adopt'] as const)('%s单个产物字段损坏为原始值时仍展示后续可用下载', async mode => {
  const { root } = await show(mode, { ok: false, issues: [], readback: provenance },
    { pdf: 'damaged', word: true, pptx: 1 })
  expect(root.querySelectorAll('a')).toHaveLength(2)
  expect(root.querySelector('a[href$="/download/xlsx"]')).not.toBeNull()
  expect(root.querySelector('a[href$="/download/md"]')).not.toBeNull()
  expect(root.querySelector('details.delivery-layout-provenance')).not.toBeNull()
  expect(root.textContent).toContain('文件可下载，验收尚未通过')
})

it.each(['refresh', 'adopt'] as const)('%s语义落点明确模型判断，不冒称作者声明或完整验收', async mode => {
  const readback = { ...provenance, signature: { ...provenance.signature,
    placement: 'semantic_template_slot', sheetName: undefined, cellRange: undefined } }
  const { root } = await show(mode, { ok: false, issues: [], readback })
  const details = root.querySelector<HTMLDetailsElement>('details.delivery-layout-provenance')!
  expect(details.open).toBe(false)
  expect(details.textContent).toContain('语义识别位置（模型判断）')
  expect(details.textContent).not.toContain('模板声明的')
  expect(details.textContent).toContain('来源记录不代表验收通过')
  expect(root.querySelectorAll('a')).toHaveLength(5)
})

it.each(['replaced', 'cleared'])('工作流语义位置的样例处理不冒称作者声明：%s', async status => {
  const readback = { ...provenance, signature: { ...provenance.signature,
    placement: 'semantic_template_slot', templateSampleStatus: status } }
  const { root } = await show('refresh', { ok: false, issues: [], readback })
  const text = root.querySelector('details.delivery-layout-provenance')!.textContent
  expect(text).toContain(status === 'replaced' ? '语义识别样例已替换' : '语义识别样例已清除')
  expect(text).not.toContain('声明样例已')
})

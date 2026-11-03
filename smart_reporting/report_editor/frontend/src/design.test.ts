import { beforeEach, describe, expect, it, vi } from 'vitest'
import fixture from './fixtures/report-design.json'
import { ReportEditorApiError, ReportEditorClient } from './api'
import { clampCoverBox, coverText, applyCoverPreset } from './design-geometry'
import { createDesignPanel } from './design-panel'
import type { DesignDocument, ReportDesign } from './design-types'

const context = { title: '经营报告', periodLabel: '2026 年', organizationName: '本院', generatedByLabel: '报告组', generatedDate: '2026-11-03', watermarkText: '内部资料' }
function state(hash = 'design-a'): DesignDocument { return { design: structuredClone(fixture) as ReportDesign, designSha256: hash, documentContext: context } }
function setup() {
  const client = {
    saveDesign: vi.fn(async (design: ReportDesign) => ({ ...state('design-b'), design: structuredClone(design) })),
    design: vi.fn(async () => state('remote')),
    designTemplates: vi.fn(async () => ({ items: [] })),
    saveDesignTemplate: vi.fn(async (templateId: string, name: string, design: ReportDesign) => ({ templateId, name, design })),
    deleteDesignTemplate: vi.fn(async () => ({ deleted: true })),
    startDesignPreview: vi.fn(async () => ({ previewId: 'preview-1', status: 'running' as const, documentSha256: 'body-a', designSha256: 'design-b' })),
    designPreview: vi.fn(async () => ({ previewId: 'preview-1', status: 'succeeded' as const })),
    designPreviewUrl: () => '/editor/api/design-preview/preview-1/pdf',
  }
  let markdown = 'body'
  const saveMarkdown = vi.fn(async () => 'body-a')
  const panel = createDesignPanel({ root: document.body, editor: document.querySelector<HTMLElement>('#editor')!, basePath: '/editor', initial: state(), client, saveMarkdown, getMarkdown: () => markdown, pollMs: 0 })
  return { panel, client, saveMarkdown, changeMarkdown: () => { markdown = 'edited'; panel.markMarkdownChanged() } }
}
function input(name: string, value: string | boolean) {
  const el = document.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(`[name="${name}"]`)!
  if (typeof value === 'boolean') (el as HTMLInputElement).checked = value
  else el.value = value
  el.dispatchEvent(new Event('change', { bubbles: true }))
}
function click(action: string) { document.querySelector<HTMLButtonElement>(`[data-design-action="${action}"]`)!.click() }
function switchTab(tab: string) { document.querySelector<HTMLButtonElement>(`[data-design-tab="${tab}"]`)!.click() }

describe('report design geometry', () => {
  it('clamps movement and resizing inside finite A4 bounds', () => {
    expect(clampCoverBox({ ...state().design.cover.title, x: 205, y: -12, width: 40, height: 400 })).toMatchObject({ x: 170, y: 0, width: 40, height: 297 })
    expect(clampCoverBox({ ...state().design.cover.title, x: 25.123456 }).x).toBe(25.12)
  })
  it('binds destination facts and keeps custom overrides when applying a preset', () => {
    const design = state().design
    design.cover.title.text = '自定义标题'
    expect(coverText(design, context, 'signature')).toBe('本院\n报告组\n2026-11-03')
    const result = applyCoverPreset(design, 'minimal')
    expect(result.cover.title).toMatchObject({ text: '自定义标题', align: 'left' })
    expect(design.cover.preset).toBe('formal')
  })
})

describe('report design panel', () => {
  beforeEach(() => { document.body.innerHTML = '<div id="editor"></div>'; localStorage.clear() })
  it('edits live cover styles, saves server CAS, and supports undo', async () => {
    const { panel, client } = setup()
    panel.open()
    input('box.x', '500')
    expect(panel.read().design.cover.title.x).toBe(50)
    expect(panel.dirty).toBe(true)
    click('undo')
    expect(panel.read().design.cover.title.x).toBe(25)
    input('box.size', '32')
    await panel.flush()
    expect(client.saveDesign).toHaveBeenCalledWith(expect.objectContaining({ cover: expect.objectContaining({ title: expect.objectContaining({ size: 32 }) }) }), 'design-a')
    expect(panel.read().designSha256).toBe('design-b')
    expect(panel.dirty).toBe(false)
    expect(document.querySelector<HTMLElement>('[data-cover-block="title"]')!.textContent).toBe('经营报告')
    panel.destroy()
  })
  it('retains local edits after a conflict until the user explicitly retries', async () => {
    const { panel, client } = setup()
    client.saveDesign.mockRejectedValueOnce(new ReportEditorApiError(409, 'report_editor_design_conflict'))
    input('box.text', '本地封面')
    await expect(panel.flush()).rejects.toMatchObject({ status: 409 })
    expect(panel.read().design.cover.title.text).toBe('本地封面')
    expect(client.saveDesign).toHaveBeenCalledTimes(1)
    click('retry-local')
    await vi.waitFor(() => expect(client.saveDesign).toHaveBeenCalledTimes(2))
    expect(client.saveDesign.mock.calls[1]).toEqual([expect.objectContaining({ cover: expect.objectContaining({ title: expect.objectContaining({ text: '本地封面' }) }) }), 'remote'])
    panel.destroy()
  })
  it('saves both drafts before an explicit PDF preview and marks it stale only on actual text changes', async () => {
    const { panel, client, saveMarkdown, changeMarkdown } = setup()
    input('box.size', '30')
    expect(client.startDesignPreview).not.toHaveBeenCalled()
    await panel.preview()
    expect(saveMarkdown).toHaveBeenCalledOnce()
    expect(client.startDesignPreview).toHaveBeenCalledWith('body-a', 'design-b')
    expect(document.querySelector<HTMLAnchorElement>('[data-design-pdf]')!.getAttribute('href')).toBe('/editor/api/design-preview/preview-1/pdf')
    panel.markMarkdownChanged()
    expect(panel.previewStale).toBe(false)
    changeMarkdown()
    expect(panel.previewStale).toBe(true)
    panel.destroy()
  })
  it('applies a personal template with destination text and scopes actual editor typography', async () => {
    const { panel, client } = setup()
    const template = state().design
    template.cover.title.text = '别人的报告'
    client.designTemplates.mockResolvedValue({ items: [{ templateId: 'my-template', name: '月报', design: template }] } as never)
    await panel.loadTemplates()
    switchTab('templates')
    await vi.waitFor(() => expect(document.querySelector('[name="templateId"] option[value="my-template"]')).not.toBeNull())
    input('templateId', 'my-template')
    click('template-apply')
    expect(panel.read().design.cover.title.text).toBeNull()
    switchTab('typography')
    input('typography.role', 'body')
    input('type.size', '15')
    expect(document.querySelector<HTMLElement>('#editor')!.style.getPropertyValue('--design-body-size')).toBe('15pt')
    panel.destroy()
  })
  it('updates the canvas immediately while typing, without requiring a field blur', () => {
    const { panel } = setup()
    const text = document.querySelector<HTMLTextAreaElement>('[name="box.text"]')!
    text.value = '正在输入'
    text.dispatchEvent(new Event('input', { bubbles: true }))
    expect(document.querySelector('[data-cover-block="title"]')!.textContent).toBe('正在输入')
    expect(panel.dirty).toBe(true)
    panel.destroy()
  })
  it('flushes new Markdown typed while design is being saved before starting a PDF preview', async () => {
    const { panel, client, saveMarkdown, changeMarkdown } = setup()
    let finish!: (value: DesignDocument) => void
    client.saveDesign.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    input('box.size', '30')
    const pending = panel.preview()
    await vi.waitFor(() => expect(client.saveDesign).toHaveBeenCalledOnce())
    const submitted = structuredClone(client.saveDesign.mock.calls[0][0])
    changeMarkdown()
    finish({ ...state('design-b'), design: submitted })
    await pending
    expect(saveMarkdown).toHaveBeenCalledTimes(2)
    expect(panel.previewStale).toBe(false)
    panel.destroy()
  })
})

describe('design API', () => {
  it('sends the design hash with writes, previews, history restore and exports', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (url) => new Response(JSON.stringify(String(url).endsWith('/api/export') ? { exportId: 'job' } : String(url).endsWith('/api/export/job') ? { status: 'succeeded', result: { revision: 2 } } : state())))
    const client = new ReportEditorClient('/editor', fetcher, 0)
    await client.saveDesign(state().design, 'design-a')
    await client.startDesignPreview('body-a', 'design-a')
    await client.restoreHistory(1, 'body-a', undefined, 'design-a')
    await client.export('body-a', {}, '', 'design-a')
    const bodies = fetcher.mock.calls.filter(([, init]) => init?.body).map(([, init]) => JSON.parse(init!.body as string))
    expect(bodies).toHaveLength(4)
    bodies.forEach(body => expect(body.expectedDesignSha256).toBe('design-a'))
  })
})

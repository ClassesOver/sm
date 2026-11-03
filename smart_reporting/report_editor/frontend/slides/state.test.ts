import { describe, expect, it } from 'vitest'
import { SlidesState, ApiError, requestJson, safeImageSource, type SlidesDocument } from './state'

const fixture = (): SlidesDocument => ({
  reportId: 'report-1', revision: 1, sha256: 'initial', csrfToken: 'csrf-token', width: 1280, height: 720,
  slides: [{ index: 0, title: '第一页', background: '#ffffff', elements: [
    { id: 'title', kind: 'text', text: '原标题', x: 40, y: 50, width: 500, height: 80, rotation: 0, fontSize: 32 },
    { id: 'image', kind: 'image', editable: false, x: 40, y: 180, width: 300, height: 200, rotation: 0 },
  ] }],
})

describe('幻灯片草稿操作', () => {
  it('合并已有元素的修改，保留最终值和独立属性', () => {
    const state = new SlidesState(fixture())
    state.update(0, 'title', { x: 60, text: '新标题' })
    state.update(0, 'title', { x: 90, bold: true })
    expect(state.operations).toEqual([{ op: 'update', slide: 0, id: 'title', x: 90, text: '新标题', bold: true }])
    expect(state.document.slides[0].elements[0].text).toBe('新标题')
    expect(state.dirty).toBe(true)
  })

  it('新增文字后编辑只发送 addText，不发送临时 id', () => {
    const state = new SlidesState(fixture())
    const id = state.addText(0, { text: '新增', x: 10, y: 20, width: 200, height: 80 })
    state.update(0, id, { x: 70, text: '已修改', rotation: -25 })
    expect(state.operations).toEqual([{ op: 'addText', slide: 0, text: '已修改', x: 70, y: 20, width: 200, height: 80, rotation: -25 }])
    expect(JSON.stringify(state.operations)).not.toContain(id)
    state.delete(0, id)
    expect(state.operations).toEqual([])
    expect(state.dirty).toBe(false)
  })

  it('删除已有文字去掉其 update，并合并页面背景', () => {
    const state = new SlidesState(fixture())
    state.update(0, 'title', { text: '即将删除' })
    state.delete(0, 'title')
    state.background(0, '#eeeeee')
    state.background(0, '#ffffff')
    expect(state.operations).toEqual([
      { op: 'delete', slide: 0, id: 'title' },
      { op: 'background', slide: 0, color: '#ffffff' },
    ])
  })

  it('只读复杂元素不能被修改或删除', () => {
    const state = new SlidesState(fixture())
    state.update(0, 'image', { x: 99 })
    state.delete(0, 'image')
    expect(state.operations).toEqual([])
    expect(state.document.slides[0].elements).toHaveLength(2)
  })

  it('保存期间冻结编辑，成功后采用服务端新身份并清空修改', async () => {
    const state = new SlidesState(fixture())
    state.update(0, 'title', { text: '已保存' })
    let complete!: (doc: SlidesDocument) => void
    const pending = state.save(async (body) => {
      expect(body).toEqual({ expectedSha256: 'initial', operations: [{ op: 'update', slide: 0, id: 'title', text: '已保存' }] })
      return new Promise((resolve) => { complete = resolve })
    })
    expect(state.busy).toBe(true)
    state.update(0, 'title', { text: '不应覆盖' })
    const saved = fixture()
    saved.sha256 = 'saved'
    saved.slides[0].elements[0].id = 'server-title'
    saved.slides[0].elements[0].text = '已保存'
    complete(saved)
    await pending
    expect(state.document.sha256).toBe('saved')
    expect(state.document.slides[0].elements[0].id).toBe('server-title')
    expect(state.dirty).toBe(false)
    expect(state.busy).toBe(false)
  })

  it('保存冲突保留本地修改和原始版本，允许再次保存', async () => {
    const state = new SlidesState(fixture())
    state.update(0, 'title', { text: '本地文案' })
    await expect(state.save(async () => { throw new ApiError('版本已改变', 409, 'conflict') })).rejects.toThrow('版本已改变')
    expect(state.document.slides[0].elements[0].text).toBe('本地文案')
    expect(state.document.sha256).toBe('initial')
    expect(state.dirty).toBe(true)
    expect(state.busy).toBe(false)
  })
})

describe('HTTP 与预览边界', () => {
  it('读取服务端结构化冲突消息并发送同源凭证', async () => {
    let received: RequestInit | undefined
    const send: typeof fetch = async (_url, options) => {
      received = options
      return new Response(JSON.stringify({ detail: { code: 'draft_conflict', message: '请保留本地修改' } }), { status: 409 })
    }
    await expect(requestJson('/draft', { method: 'PUT', body: '{}' }, send)).rejects.toMatchObject({ status: 409, code: 'draft_conflict', message: '请保留本地修改' })
    expect(received?.credentials).toBe('same-origin')
    expect(new Headers(received?.headers).get('Content-Type')).toBe('application/json')
  })

  it('预览只接受内嵌光栅图片，拒绝外链和 SVG', () => {
    expect(safeImageSource('data:image/png;base64,aGVsbG8=')).toBe('data:image/png;base64,aGVsbG8=')
    expect(safeImageSource('https://example.com/a.png')).toBeUndefined()
    expect(safeImageSource('data:image/svg+xml,<svg></svg>')).toBeUndefined()
    expect(safeImageSource('javascript:alert(1)')).toBeUndefined()
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createAssetAIActions } from './asset-ai-actions'

describe('graph and table AI entry points', () => {
  let controller: ReturnType<typeof createAssetAIActions> | undefined
  beforeEach(() => {
    document.body.innerHTML = `<main id="editor"><p><span class="report-table-marker">[[table:tbl-1]]</span></p><table><tbody><tr><td>收入</td></tr></tbody></table><img src="chart.png"><p id="plain">正文</p></main>`
  })
  afterEach(() => { controller?.dispose(); controller = undefined })
  const editor = () => document.querySelector<HTMLElement>('#editor')!
  const toolbar = () => document.querySelector<HTMLElement>('.asset-ai-actions')!
  const button = () => toolbar().querySelector('button')!
  const hover = (selector: string) => editor().querySelector(selector)!.dispatchEvent(new MouseEvent('pointerover', { bubbles: true }))

  it('opens the identified table without inserting UI into editable content', () => {
    const onTableEdit = vi.fn()
    controller = createAssetAIActions(editor(), { onTableEdit })
    hover('td')
    expect(toolbar().hidden).toBe(false)
    expect(button().textContent).toBe('AI 改表')
    expect(editor().querySelector('.asset-ai-actions')).toBeNull()
    hover('#plain')
    expect(toolbar().hidden).toBe(false)
    button().click()
    expect(onTableEdit).toHaveBeenCalledWith('tbl-1')
    expect(toolbar().hidden).toBe(true)
  })

  it('opens chart editing directly, including noneditable image node wrappers', () => {
    const onChartEdit = vi.fn()
    controller = createAssetAIActions(editor(), { onChartEdit })
    const image = editor().querySelector('img')!
    image.setAttribute('contenteditable', 'false')
    hover('img')
    expect(button().textContent).toBe('AI 改图')
    const outline = document.querySelector<HTMLElement>('.asset-ai-outline')!
    expect(outline.hidden).toBe(false)
    expect(editor().contains(outline)).toBe(false)
    button().click()
    expect(onChartEdit).toHaveBeenCalledWith(image)
    expect(outline.hidden).toBe(true)
  })

  it('honors feature flags and does not offer edits for unregistered tables', () => {
    controller = createAssetAIActions(editor(), {})
    hover('img'); expect(toolbar().hidden).toBe(true)
    hover('td'); expect(toolbar().hidden).toBe(true)
    controller.dispose()
    controller = createAssetAIActions(editor(), { onTableEdit: vi.fn() })
    editor().querySelector('.report-table-marker')!.remove()
    hover('td'); expect(toolbar().hidden).toBe(true)
  })

  it('places the table entry above the table so it never covers header cells; images keep it inside', () => {
    controller = createAssetAIActions(editor(), { onTableEdit: vi.fn(), onChartEdit: vi.fn() })
    const rect = (top: number) => ({ top, bottom: top + 200, left: 100, right: 700, width: 600, height: 200, x: 100, y: top, toJSON: () => ({}) })
    editor().querySelector('table')!.getBoundingClientRect = () => rect(300) as DOMRect
    editor().querySelector('img')!.getBoundingClientRect = () => rect(300) as DOMRect
    hover('td')
    expect(parseFloat(toolbar().style.top)).toBeLessThan(300)
    editor().querySelector('table')!.getBoundingClientRect = () => rect(20) as DOMRect
    hover('td')
    expect(parseFloat(toolbar().style.top)).toBeGreaterThanOrEqual(20)
    hover('img')
    expect(parseFloat(toolbar().style.top)).toBe(308)
  })

  it('supports keyboard selection and Escape dismissal', () => {
    controller = createAssetAIActions(editor(), { onTableEdit: vi.fn() })
    const range = document.createRange()
    range.selectNodeContents(editor().querySelector('td')!)
    window.getSelection()!.removeAllRanges()
    window.getSelection()!.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
    expect(toolbar().hidden).toBe(false)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(toolbar().hidden).toBe(true)
  })

  it('rejects a removed or rebound table before starting an edit', () => {
    const onTableEdit = vi.fn()
    controller = createAssetAIActions(editor(), { onTableEdit })
    hover('td')
    editor().querySelector('.report-table-marker')!.textContent = '[[table:tbl-2]]'
    button().click()
    expect(onTableEdit).not.toHaveBeenCalled()
    hover('td')
    editor().querySelector('table')!.remove()
    button().click()
    expect(onTableEdit).not.toHaveBeenCalled()
  })
})

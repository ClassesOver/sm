import { afterEach, expect, it, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { DocxLayoutSource } from './docx-layout-source'

afterEach(() => { document.body.replaceChildren() })

it('routes page orientation, paper size, margins, columns, and header/footer distances to section settings', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const onChange = vi.fn()
  const root = createRoot(host)
  flushSync(() => root.render(<DocxLayoutSource editable settings={{
    orientation: 'portrait', pageWidth: 12240, pageHeight: 15840, pageBorder: false,
    marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440,
    columns: 1, headerDist: 720, footerDist: 720,
  }} onChange={onChange} />))

  const orientation = host.querySelector<HTMLSelectElement>('[data-source-action="layout-orientation"]')!
  orientation.value = 'landscape'
  orientation.dispatchEvent(new Event('change', { bubbles: true }))
  expect(onChange).toHaveBeenLastCalledWith({ orientation: 'landscape', pageWidth: 15840, pageHeight: 12240 })

  const paper = host.querySelector<HTMLSelectElement>('[data-source-action="layout-paper-size"]')!
  paper.value = 'a4'
  paper.dispatchEvent(new Event('change', { bubbles: true }))
  expect(onChange).toHaveBeenLastCalledWith({ pageWidth: 16838, pageHeight: 11906 })
  paper.value = 'custom'
  paper.dispatchEvent(new Event('change', { bubbles: true }))
  expect(host.querySelector<HTMLInputElement>('[data-source-action="layout-custom-page-width"]')?.disabled).toBe(false)
  const customWidth = host.querySelector<HTMLInputElement>('[data-source-action="layout-custom-page-width"]')!
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(customWidth, '16000')
  customWidth.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: '16000' }))
  expect(onChange).toHaveBeenLastCalledWith({ pageWidth: 16000 })

  const margin = host.querySelector<HTMLInputElement>('[data-source-action="layout-margin-left"]')!
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(margin, '1200')
  margin.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: '1200' }))
  expect(onChange).toHaveBeenLastCalledWith({ marginLeft: 1200 })

  const columns = host.querySelector<HTMLSelectElement>('[data-source-action="layout-columns"]')!
  columns.value = '2'
  columns.dispatchEvent(new Event('change', { bubbles: true }))
  expect(onChange).toHaveBeenLastCalledWith({ columns: 2 })

  const header = host.querySelector<HTMLInputElement>('[data-source-action="layout-header-distance"]')!
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(header, '800')
  header.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: '800' }))
  expect(onChange).toHaveBeenLastCalledWith({ headerDist: 800 })
  root.unmount()
})

it('keeps Header/Footer part and navigation controls identified but disabled with contract reasons', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  flushSync(() => root.render(<DocxLayoutSource editable settings={null} onChange={vi.fn()} />))
  for (const [id, reason] of [
    ['header-edit', '页眉/页脚 part 编辑写回尚未接入'],
    ['header-remove', '页眉/页脚 part 删除与关系写回尚未接入'],
    ['footer-remove', '页眉/页脚 part 删除与关系写回尚未接入'],
    ['footer-edit', '页眉/页脚 part 编辑写回尚未接入'],
    ['page-number', '页码字段与页眉/页脚关系写回尚未接入'],
    ['page-number-format', '页码格式设置写回尚未接入'],
    ['page-number-remove', '页码字段与页眉/页脚关系写回尚未接入'],
    ['header-picture', '页眉/页脚图片与关系写回尚未接入'],
    ['header-link-previous', '分节页眉/页脚关系写回尚未接入'],
    ['header-title-page', '首页不同设置写回尚未接入'],
    ['header-even-odd', '奇偶页不同设置写回尚未接入'],
  ]) {
    const control = host.querySelector<HTMLButtonElement>(`[data-source-action="${id}"]`)
    expect(control?.disabled).toBe(true)
    expect(control?.title).toContain(reason)
    expect(control?.getAttribute('aria-label')).toContain(reason)
  }
  expect(host.querySelector<HTMLInputElement>('[data-source-action="header-distance"]')?.disabled).toBe(true)
  root.unmount()
})

import { afterEach, expect, it, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { DocxLayoutSource } from './docx-layout-source'

afterEach(() => { document.body.replaceChildren() })

it('offers the pinned Word paper gallery and applies dimensions in the active orientation', () => {
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host), onChange = vi.fn()
  const settings = { orientation: 'landscape' as const, pageWidth: 15840, pageHeight: 12240, pageBorder: false,
    marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1 as const, headerDist: 720, footerDist: 720 }
  flushSync(() => root.render(<DocxLayoutSource editable settings={settings} onChange={onChange} />))
  const paper = host.querySelector<HTMLSelectElement>('[data-source-action="layout-paper-size"]')!
  expect(Array.from(paper.options, option => option.value)).toEqual(['letter', 'legal', 'executive', 'a3', 'a4', 'a5', 'b4', 'b5', 'tabloid', 'statement', 'env10', 'envdl', 'envc5', 'custom'])
  for (const [key, width, height] of [['executive', 10440, 15120], ['a3', 16838, 23811], ['a5', 8391, 11906], ['b4', 14572, 20639], ['b5', 10319, 14572], ['tabloid', 15840, 24480], ['statement', 7920, 12240], ['env10', 5940, 13680], ['envdl', 6237, 12474], ['envc5', 9185, 12983]] as const) {
    paper.value = key; paper.dispatchEvent(new Event('change', { bubbles: true }))
    expect(onChange).toHaveBeenLastCalledWith({ pageWidth: height, pageHeight: width })
  }
  root.unmount()
})

it('recognizes rounded paper dimensions and refreshes custom state when switching sections', () => {
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host), onChange = vi.fn()
  const settings = { orientation: 'portrait' as const, pageWidth: 11907, pageHeight: 16836, pageBorder: false,
    marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1 as const, headerDist: 720, footerDist: 720 }
  flushSync(() => root.render(<DocxLayoutSource editable settings={settings} sectionLabel="第 1 节，共 2 节" onChange={onChange} />))
  const paper = host.querySelector<HTMLSelectElement>('[data-source-action="layout-paper-size"]')!
  expect(paper.value).toBe('a4')
  paper.value = 'custom'; paper.dispatchEvent(new Event('change', { bubbles: true }))
  expect(host.querySelector<HTMLInputElement>('[data-source-action="layout-custom-page-width"]')!.disabled).toBe(false)
  flushSync(() => root.render(<DocxLayoutSource editable settings={{ ...settings, pageWidth: 8391, pageHeight: 11906 }} sectionLabel="第 2 节，共 2 节" onChange={onChange} />))
  expect(paper.value).toBe('a5')
  expect(host.querySelector<HTMLInputElement>('[data-source-action="layout-custom-page-width"]')!.disabled).toBe(true)
  expect(onChange).not.toHaveBeenCalled()
  root.unmount()
})

it('allows editing an existing custom paper without requiring a change to another preset', () => {
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host), onChange = vi.fn()
  const settings = { orientation: 'portrait' as const, pageWidth: 10000, pageHeight: 20000, pageBorder: false,
    marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1 as const, headerDist: 720, footerDist: 720 }
  flushSync(() => root.render(<DocxLayoutSource editable settings={settings} onChange={onChange} />))
  expect(host.querySelector<HTMLSelectElement>('[data-source-action="layout-paper-size"]')!.value).toBe('custom')
  expect(host.querySelector<HTMLInputElement>('[data-source-action="layout-custom-page-width"]')!.disabled).toBe(false)
  expect(host.querySelector<HTMLInputElement>('[data-source-action="layout-custom-page-height"]')!.disabled).toBe(false)
  flushSync(() => root.render(<DocxLayoutSource editable={false} settings={settings} onChange={onChange} />))
  expect(host.querySelector<HTMLInputElement>('[data-source-action="layout-custom-page-width"]')!.disabled).toBe(true)
  root.unmount()
})

it('applies the pinned Wide margins and recognizes only its actual four sides', () => {
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host), onChange = vi.fn()
  const settings = { orientation: 'portrait' as const, pageWidth: 12240, pageHeight: 15840, pageBorder: false,
    marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1 as const, headerDist: 720, footerDist: 720 }
  flushSync(() => root.render(<DocxLayoutSource editable settings={settings} onChange={onChange} />))
  const margins = host.querySelector<HTMLSelectElement>('[data-source-action="layout-margins"]')!
  const wide = Array.from(margins.options).find(option => option.textContent === '宽')!
  margins.value = wide.value; margins.dispatchEvent(new Event('change', { bubbles: true }))
  expect(onChange).toHaveBeenLastCalledWith({ marginTop: 1440, marginRight: 2880, marginBottom: 1440, marginLeft: 2880 })
  flushSync(() => root.render(<DocxLayoutSource editable settings={{ ...settings, marginRight: 2880, marginLeft: 2880 }} onChange={onChange} />))
  expect(margins.selectedOptions[0]!.textContent).toBe('宽')
  flushSync(() => root.render(<DocxLayoutSource editable settings={{ ...settings, marginTop: 2160, marginRight: 2160, marginBottom: 2160, marginLeft: 2160 }} onChange={onChange} />))
  expect(margins.value).toBe('custom')
  root.unmount()
})

it('shows and changes the active section different-first-page flag without editing header text', () => {
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host), onChange = vi.fn()
  flushSync(() => root.render(<DocxLayoutSource editable settings={null} titlePg={false} onChange={onChange} />))
  const input = host.querySelector<HTMLInputElement>('[data-source-action="header-title-page"]')!
  expect(input.tagName).toBe('INPUT')
  expect(input.checked).toBe(false)
  flushSync(() => root.render(<DocxLayoutSource editable settings={{ orientation: 'portrait', pageWidth: 12240, pageHeight: 15840, pageBorder: false, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1 }} titlePg={false} onChange={onChange} />))
  input.click()
  expect(onChange).toHaveBeenLastCalledWith({ titlePg: true })
  flushSync(() => root.render(<DocxLayoutSource editable settings={null} titlePg={null} titlePgReason="无法解释来源标记" onChange={onChange} />))
  expect(input.disabled).toBe(true)
  expect(input.indeterminate).toBe(true)
  expect(input.title).toContain('无法解释来源标记')
  root.unmount()
})

it('exposes document-wide odd-even headers and shows unknown source state honestly', () => {
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host), onChange = vi.fn()
  const settings = { orientation: 'portrait' as const, pageWidth: 12240, pageHeight: 15840, pageBorder: false, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1 as const }
  flushSync(() => root.render(<DocxLayoutSource editable settings={settings} evenAndOddHeaders={false} onChange={onChange} />))
  const checkbox = host.querySelector<HTMLInputElement>('[data-source-action="header-even-odd"]')!
  expect(checkbox.tagName).toBe('INPUT')
  expect(checkbox.title).toContain('整篇文档')
  checkbox.click()
  expect(onChange).toHaveBeenLastCalledWith({ evenAndOddHeaders: true })
  flushSync(() => root.render(<DocxLayoutSource editable settings={settings} evenAndOddHeaders={null} evenAndOddHeadersReason="无法解释奇偶页标记" onChange={onChange} />))
  expect(checkbox.disabled).toBe(true)
  expect(checkbox.indeterminate).toBe(true)
  expect(checkbox.title).toBe('无法解释奇偶页标记')
  root.unmount()
})

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
    ['page-number', '页码字段与页眉/页脚关系写回尚未接入'],
    ['page-number-remove', '页码字段与页眉/页脚关系写回尚未接入'],
    ['header-picture', '页眉/页脚图片与关系写回尚未接入'],
    ['header-link-previous', '分节页眉/页脚关系写回尚未接入'],
  ]) {
    const control = host.querySelector<HTMLButtonElement>(`[data-source-action="${id}"]`)
    expect(control?.disabled).toBe(true)
    expect(control?.title).toContain(reason)
    expect(control?.getAttribute('aria-label')).toContain(reason)
  }
  // 页眉与页脚编辑已合并为单一入口（header-edit）；未传入编辑回调时仍以契约原因禁用。
  expect(host.querySelector('[data-source-action="footer-edit"]')).toBeNull()
  expect(host.querySelector<HTMLInputElement>('[data-source-action="header-distance"]')?.disabled).toBe(true)
  root.unmount()
})


it('edits the current section page-number format atomically and cancels without changing the draft', () => {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host), onChange = vi.fn()
  const settings = { orientation: 'portrait' as const, pageWidth: 12240, pageHeight: 15840, pageBorder: false, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1 as const }
  flushSync(() => root.render(<DocxLayoutSource editable settings={settings} pageNumberFmt="upperRoman" pageNumberStart={3} onChange={onChange} sectionLabel="第 1 节，共 2 节" />))
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-source-action="page-number-format"]')!.click())
  const format = host.querySelector<HTMLSelectElement>('[aria-label="页码编号格式"]')!
  expect(format.options.length).toBe(7)
  expect(format.value).toBe('upperRoman')
  const start = host.querySelector<HTMLInputElement>('[aria-label="起始页码"]')!
  expect(start.value).toBe('3')
  format.value = 'lowerLetter'
  flushSync(() => format.dispatchEvent(new Event('change', { bubbles: true })))
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-source-action="page-number-cancel"]')!.click())
  expect(onChange).not.toHaveBeenCalled()
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-source-action="page-number-format"]')!.click())
  const freshStart = host.querySelector<HTMLInputElement>('[aria-label="起始页码"]')!
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(freshStart, '')
  flushSync(() => freshStart.dispatchEvent(new Event('input', { bubbles: true })))
  flushSync(() => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(onChange).toHaveBeenCalledExactlyOnceWith({ pageNumberFmt: 'upperRoman', pageNumberStart: null })
  root.unmount()
})


it('keeps unknown page-number source read-only and rejects invalid start values without committing', () => {
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host), onChange = vi.fn()
  const settings = { orientation: 'portrait' as const, pageWidth: 12240, pageHeight: 15840, pageBorder: false, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1 as const }
  flushSync(() => root.render(<DocxLayoutSource editable settings={settings} pageNumberFmt={null} pageNumberStart={null} pageNumberReason="unknown marker" onChange={onChange} />))
  expect(host.querySelector<HTMLButtonElement>('[data-source-action="page-number-format"]')!.disabled).toBe(true)
  expect(host.querySelector<HTMLButtonElement>('[data-source-action="page-number-format"]')!.title).toContain('unknown marker')
  flushSync(() => root.render(<DocxLayoutSource editable settings={settings} pageNumberFmt={null} pageNumberStart={null} onChange={onChange} />))
  flushSync(() => host.querySelector<HTMLButtonElement>('[data-source-action="page-number-format"]')!.click())
  const input = host.querySelector<HTMLInputElement>('[aria-label="起始页码"]')!
  for (const value of ['-1', '1.5', '9007199254740992']) {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    flushSync(() => input.dispatchEvent(new Event('input', { bubbles: true })))
    flushSync(() => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    expect(onChange).not.toHaveBeenCalled()
    expect(host.querySelector('[role="dialog"]')).not.toBeNull()
  }
  root.unmount()
})

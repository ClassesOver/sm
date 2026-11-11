import { afterEach, expect, it } from 'vitest'
import { createPdfRibbon } from './pdf-ribbon'

afterEach(() => document.body.replaceChildren())

it('shows field design without exposing form filling on a source without fields',()=>{
 const root=document.createElement('main');document.body.append(root)
 const ribbon=createPdfRibbon(root)
 ribbon.setHasForms(false,true)
 expect(root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=formDesign]')!.hidden).toBe(false)
 expect(root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=fillForm]')!.hidden).toBe(true)
 root.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=home]')!.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}))
 expect(root.querySelector('[data-pdf-ribbon-tab=formDesign]')!.getAttribute('aria-selected')).toBe('true')
})

it('shows GenOffice PDF ribbon tabs and reveals form context only for forms', () => {
  document.body.innerHTML = '<main></main>'
  const ribbon = createPdfRibbon(document.querySelector('main')!, { hasForms: true })

  expect([...document.querySelectorAll('[role=tab]')].map(tab => tab.textContent)).toEqual([
    'Home', 'Annotate', 'Edit', 'Pages', 'View', 'Fill Form', 'Form Design',
  ])
  expect(document.querySelector('[data-pdf-ribbon-panel=home]')?.hasAttribute('hidden')).toBe(false)
  expect(document.querySelector('[data-pdf-ribbon-panel=fillForm]')?.hasAttribute('hidden')).toBe(true)
  document.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=fillForm]')!.click()
  expect(document.querySelector('[data-pdf-ribbon-panel=fillForm]')?.hasAttribute('hidden')).toBe(false)
  expect(document.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=fillForm]')?.getAttribute('aria-selected')).toBe('true')
  ribbon.dispose()
})

it('groups commands under the selected GenOffice ribbon tab and disposes cleanly', () => {
  document.body.innerHTML = '<main></main>'
  const ribbon = createPdfRibbon(document.querySelector('main')!)
  const page = ribbon.group('page', 'Organize')
  const button = document.createElement('button')
  button.textContent = 'Rotate page'
  page.append(button)

  document.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=page]')!.click()
  expect(button.closest('[data-pdf-ribbon-panel=page]')?.hasAttribute('hidden')).toBe(false)
  expect(button.closest('.pdf-ribbon-group')?.querySelector('h3')?.textContent).toBe('Organize')
  ribbon.dispose()
  expect(document.querySelector('.pdf-ribbon')).toBeNull()
})

it('adds contextual form tabs only when the opened PDF contains form fields', () => {
  document.body.innerHTML = '<main></main>'
  const ribbon = createPdfRibbon(document.querySelector('main')!)
  expect(document.querySelector('[data-pdf-ribbon-tab=fillForm]')?.hasAttribute('hidden')).toBe(true)
  ribbon.setHasForms(true)
  expect(document.querySelector('[data-pdf-ribbon-tab=fillForm]')?.hasAttribute('hidden')).toBe(false)
  document.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=formDesign]')!.click()
  ribbon.setHasForms(false)
  expect(document.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=home]')?.getAttribute('aria-selected')).toBe('true')
})

it('supports standard keyboard navigation across visible tabs', () => {
  document.body.innerHTML = '<main></main>'
  createPdfRibbon(document.querySelector('main')!)
  const home = document.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=home]')!
  home.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
  const annotate = document.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=annotate]')!
  expect(annotate.getAttribute('aria-selected')).toBe('true')
  expect(annotate.tabIndex).toBe(0)
  annotate.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }))
  expect(document.querySelector<HTMLButtonElement>('[data-pdf-ribbon-tab=view]')?.getAttribute('aria-selected')).toBe('true')
})

it('localizes the source ribbon tabs and group titles from the active document language', () => {
  document.body.innerHTML = '<main></main>'
  const ribbon = createPdfRibbon(document.querySelector('main')!)
  const group = ribbon.group('page', 'Organize')
  ribbon.setLanguage('zh-CN')
  expect(document.querySelector('[data-pdf-ribbon-tab=home]')?.textContent).toBe('开始')
  expect(group.querySelector('h3')?.textContent).toBe('页面组织')
  ribbon.setLanguage('en-US')
  expect(document.querySelector('[data-pdf-ribbon-tab=home]')?.textContent).toBe('Home')
  expect(group.querySelector('h3')?.textContent).toBe('Organize')
})

it('places AI first and conversion last in Home keyboard order', () => {
  const host = document.body.appendChild(document.createElement('main'))
  const ribbon = createPdfRibbon(host)
  for (const group of ['AI','Markup','Edit','Convert & Export','Page & Zoom','Search, Print & Properties']) ribbon.group('home',group)
  expect([...host.querySelectorAll('[data-pdf-ribbon-panel=home] > section')].map(group => (group as HTMLElement).dataset.ribbonGroup))
    .toEqual(['AI','Markup','Edit','Page & Zoom','Search, Print & Properties','Convert & Export'])
  ribbon.dispose()
})

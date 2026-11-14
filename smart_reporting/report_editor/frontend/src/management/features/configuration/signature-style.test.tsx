import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SignatureStyleFields } from './signature-style'

let root: Root
const update = vi.fn()
const documentValue = { common: { font: 'sans' }, word: { common: { font: null }, signature: { font: null, size: 11, color: null, align: 'right', bold: false } } }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })
it.each(['word', 'pdf'])('文档落款间距折叠维护，%s 错误能定位并保留原始值', async format => {
  const signature = { ...documentValue.word.signature, lineHeight: 1.8, spaceBefore: 24, spaceAfter: 7, dateGap: 9 }
  await act(async () => root.render(<SignatureStyleFields document={{ [format]: { signature } }} format={format} onChange={update}
    errors={[{ path: format + '.signature.dateGap', message: '署名与日期间距越界' }]} />))
  expect(document.activeElement?.getAttribute('aria-label')).toBe('日期及说明段前（磅）')
  for (const [label, value] of [['落款行距（倍）', 1.8], ['与前文间距（磅）', 24], ['落款段后（磅）', 7], ['日期及说明段前（磅）', 9]] as const) {
    expect(Number(document.querySelector<HTMLInputElement>('[aria-label="' + label + '"]')?.value)).toBe(value)
  }
  const field = document.querySelector<HTMLInputElement>('[aria-label="日期及说明段前（磅）"]')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, '10')
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(update).toHaveBeenLastCalledWith([format, 'signature', 'dateGap'], 10)
})
it.each(['xlsx'])('%s 不展示尚未整体验证的文档间距入口', async format => {
  await act(async () => root.render(<SignatureStyleFields document={{ [format]: documentValue.word }} format={format} onChange={update} />))
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="落款样式"]')!.click())
  expect(document.querySelector('[aria-label="与前文间距（磅）"]')).toBeNull()
})
it('演示文稿标题间距默认折叠，按磅维护并自动定位错误', async () => {
  const document = { pptx: { signature: { ...documentValue.word.signature, spaceBefore: 144 } } }
  await act(async () => root.render(<SignatureStyleFields document={document} format="pptx" onChange={update} />))
  expect(globalThis.document.querySelector('[aria-label="与落款页标题间距（磅）"]')).toBeNull()
  await act(async () => root.render(<SignatureStyleFields document={document} format="pptx" onChange={update}
    errors={[{ path: 'pptx.signature.spaceBefore', message: '间距越界' }]} />))
  const field = globalThis.document.querySelector<HTMLInputElement>('[aria-label="与落款页标题间距（磅）"]')!
  expect(Number(field.value)).toBe(144)
  expect(field.getAttribute('aria-valuemin')).toBe('0'); expect(field.getAttribute('aria-valuemax')).toBe('144')
  expect(globalThis.document.activeElement).toBe(field)
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, '24')
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(update).toHaveBeenLastCalledWith(['pptx', 'signature', 'spaceBefore'], 24)
})
it('落款样式默认折叠，不挤占内容维护区', async () => {
  await act(async () => root.render(<SignatureStyleFields document={documentValue} format="word" onChange={update} />))
  expect(document.querySelector('[aria-label="落款字号"]')).toBeNull()
  const toggle = document.querySelector<HTMLButtonElement>('[aria-label="落款样式"]')!
  await act(async () => toggle.click())
  expect(document.querySelector('[aria-label="落款字体"]')).not.toBeNull()
  expect(Number(document.querySelector<HTMLInputElement>('[aria-label="落款字号"]')?.value)).toBe(11)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="落款加粗"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['word', 'signature', 'bold'], true)
})
it('样式错误自动展开并定位，Markdown不显示物理样式', async () => {
  await act(async () => root.render(<SignatureStyleFields document={documentValue} format="word" onChange={update}
    errors={[{ path: 'word.signature.color', message: '请输入六位颜色' }]} />))
  expect(document.activeElement?.getAttribute('aria-label')).toBe('落款颜色')
  expect(document.body.textContent).toContain('请输入六位颜色')
  await act(async () => root.render(<SignatureStyleFields document={documentValue} format="md" onChange={update} />))
  expect(document.querySelector('[aria-label="落款样式"]')).toBeNull()
})

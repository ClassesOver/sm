import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TypographyFields } from './typography'
import { SignatureStyleFields } from './signature-style'
import { HeaderFooterStyleFields } from './header-footer-style'
import { setPreferenceValue, validateSignatureDraft } from './preference-draft'

let root: Root
const update = vi.fn()
const style = { font: null, color: null, size: 11, bold: false, lineHeight: 1.5, spaceBefore: 0, spaceAfter: 0, indent: 18 }
const initial = { common: { signer: '首行缩进验证' }, pptx: {
  typography: { body: style, h1: style, table: style, caption: style },
  signature: { ...style, align: 'right', description: '' }, footerStyle: style } }

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })

it.each(['body', 'h1', 'table', 'caption'])('演示文稿%s缩进默认折叠，错误展开并定位当前对象，修改只写精确路径', async role => {
  await act(async () => root.render(<TypographyFields document={initial} format="pptx" onChange={update} />))
  expect(document.querySelector('[aria-label="首行缩进（磅）"]')).toBeNull()
  const path = 'pptx.typography.' + role + '.indent'
  await act(async () => root.render(<TypographyFields document={initial} format="pptx" onChange={update}
    errors={[{ path, message: '首行缩进需为0–48磅' }]} />))
  const input = document.querySelector<HTMLInputElement>('[aria-label="首行缩进（磅）"]')!
  expect(input).not.toBeNull()
  expect(document.activeElement).toBe(input)
  expect(input.id).toBe('preference-' + path)
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '19')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(update).toHaveBeenLastCalledWith(path.split('.'), 19)
})

it.each(['signature', 'footerStyle'])('演示文稿%s缩进沿用样式折叠和错误定位，单位与界限明确', async role => {
  const Component = role === 'signature' ? SignatureStyleFields : HeaderFooterStyleFields
  const label = role === 'signature' ? '落款首行缩进（磅）' : '页脚首行缩进'
  await act(async () => root.render(<Component document={initial} format="pptx" onChange={update} />))
  expect(document.querySelector(`[aria-label="${label}"]`)).toBeNull()
  const path = 'pptx.' + role + '.indent'
  await act(async () => root.render(<Component document={initial} format="pptx" onChange={update}
    errors={[{ path, message: '首行缩进需为0–48磅' }]} />))
  const input = document.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!
  expect(input).not.toBeNull()
  expect(document.activeElement).toBe(input)
  expect(input.getAttribute('aria-valuemin')).toBe('0')
  expect(input.getAttribute('aria-valuemax')).toBe('48')
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '19')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(update).toHaveBeenLastCalledWith(path.split('.'), 19)
})

it('六个演示文稿首行缩进字段拒绝越界及非有限数，不影响空缺历史字段', () => {
  const paths = ['signature.indent', 'footerStyle.indent', ...['body', 'h1', 'table', 'caption'].map(role => 'typography.' + role + '.indent')]
  expect(validateSignatureDraft(initial)).toEqual([])
  for (const path of paths) for (const value of [-0.1, 48.1, Number.NaN, Number.POSITIVE_INFINITY, '18']) {
    const full = 'pptx.' + path
    expect(validateSignatureDraft(setPreferenceValue(initial, full.split('.'), value)))
      .toContainEqual(expect.objectContaining({ path: full }))
  }
  expect(validateSignatureDraft({ common: initial.common, pptx: { signature: {}, footerStyle: {} } })).toEqual([])
})

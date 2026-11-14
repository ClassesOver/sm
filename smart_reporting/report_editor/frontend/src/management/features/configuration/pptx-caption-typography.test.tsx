import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TypographyFields } from './typography'
import { setPreferenceValue, validateSignatureDraft } from './preference-draft'

let root: Root
const update = vi.fn()
const style = { font: null, color: null, size: 11, bold: false, lineHeight: 1.5, spaceBefore: 0, spaceAfter: 0, indent: 0 }
const initial = { common: { signer: '排版样例' }, pptx: { typography: { body: style, h1: style, caption: { ...style, size: 13 } }, charts: { captionNumbering: true } } }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'
  root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })

it('PPTX图注校验错误切换真实角色、展开行距并聚焦，编号只写PPTX图表偏好', async () => {
  await act(async () => root.render(<TypographyFields document={initial} format="pptx" onChange={update}
    errors={[{ path: 'pptx.typography.caption.lineHeight', message: '图注行距越界' }]} />))
  expect(document.querySelector('.preference-story-selector')?.textContent).toContain('图注')
  expect(document.activeElement?.getAttribute('aria-label')).toBe('排版行距')
  expect(Number(document.querySelector<HTMLInputElement>('[aria-label="排版字号"]')?.value)).toBe(13)
  expect(document.body.textContent).toContain('图注行距越界')
  for (const field of ['段前（磅）', '段后（磅）']) expect(document.querySelector(`[aria-label="${field}"]`)).not.toBeNull()
  expect(document.querySelector('[aria-label="首行缩进（磅）"]')).not.toBeNull()
  const numbering = document.querySelector<HTMLButtonElement>('[aria-label="图注编号"]')
  expect(numbering).not.toBeNull()
  await act(async () => numbering!.click())
  expect(update).toHaveBeenLastCalledWith(['pptx', 'charts', 'captionNumbering'], false)
})

it('PPTX正文不显示图注编号，段落细节默认折叠', async () => {
  await act(async () => root.render(<TypographyFields document={initial} format="pptx" onChange={update} />))
  expect(document.querySelector('[aria-label="图注编号"]')).toBeNull()
  expect(document.querySelector('[aria-label="排版行距"]')).toBeNull()
  expect(document.querySelector('[aria-label="段前（磅）"]')).toBeNull()
  expect(document.querySelector('[aria-label="段后（磅）"]')).toBeNull()
})

it('PPTX图注字号颜色行距校验定位到真实字段', () => {
  for (const [key, value] of [['size', 73], ['color', 'red'], ['lineHeight', 3.1], ['spaceBefore', -1], ['spaceAfter', 73]]) {
    expect(validateSignatureDraft(setPreferenceValue(initial, ['pptx', 'typography', 'caption', String(key)], value)))
      .toContainEqual(expect.objectContaining({ path: 'pptx.typography.caption.' + key }))
  }
  expect(validateSignatureDraft(initial)).toEqual([])
})

it.each(['word', 'pdf'])('%s图注编号只维护当前格式，低频段落细节仍默认折叠', async format => {
  const documentValue = { common: initial.common, [format]: { typography: { body: style, caption: style }, charts: { captionNumbering: true } } }
  await act(async () => root.render(<TypographyFields document={documentValue} format={format} onChange={update} />))
  expect(document.querySelector('[aria-label="图注编号"]')).toBeNull()
  await act(async () => document.querySelector('[aria-label="排版对象"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))
  const caption = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option')].find(item => item.getAttribute('title') === '图注')!
  await act(async () => caption.click())
  expect(document.querySelector('[aria-label="排版行距"]')).toBeNull()
  expect(document.querySelector('[aria-label="段前（磅）"]')).toBeNull()
  const numbering = document.querySelector<HTMLButtonElement>('[aria-label="图注编号"]')
  expect(numbering).not.toBeNull()
  await act(async () => numbering!.click())
  expect(update).toHaveBeenLastCalledWith([format, 'charts', 'captionNumbering'], false)
})

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TypographyFields } from './typography'

let root: Root
const update = vi.fn()
const style = { font: null, color: null, size: 11, bold: false, lineHeight: 1.6, spaceBefore: 0, spaceAfter: 6, indent: 0 }
const documentValue = { word: { typography: { body: style, h1: { ...style, size: 16, bold: true }, caption: { ...style, size: 9 } } } }

it('PPTX标题展开后显示已执行的行距及段前段后，不显示缩进', async () => {
  const doc = { pptx: { typography: { body: style, h1: { ...style, size: 28 } } } }
  await act(async () => root.render(<TypographyFields document={doc} format="pptx" onChange={update}
    errors={[{ path: 'pptx.typography.h1.lineHeight', message: '行距越界' }]} />))
  expect(document.querySelector('[aria-label="排版字号"]')).not.toBeNull()
  expect(Number(document.querySelector<HTMLInputElement>('[aria-label="排版字号"]')?.value)).toBe(28)
  expect(document.activeElement?.getAttribute('aria-label')).toBe('排版行距')
  expect(document.querySelector('[aria-label="段前（磅）"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="段后（磅）"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="首行缩进（磅）"]')).toBeNull()
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="排版加粗"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['pptx', 'typography', 'h1', 'bold'], true)
})
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })
it('默认只显示正文样式，段落间距折叠，恢复字体只影响当前角色', async () => {
  await act(async () => root.render(<TypographyFields document={documentValue} format="word" onChange={update} />))
  expect(document.querySelector('[aria-label="排版字号"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="排版行距"]')).toBeNull()
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="排版加粗"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['word', 'typography', 'body', 'bold'], true)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="段落细节"]')!.click())
  expect(document.querySelector('[aria-label="排版行距"]')).not.toBeNull()
  expect(document.querySelector('[aria-label="首行缩进（磅）"]')).not.toBeNull()
})
it('标题校验错误切换角色、展开细节并聚焦，不隐藏错误', async () => {
  await act(async () => root.render(<TypographyFields document={documentValue} format="word" onChange={update}
    errors={[{ path: 'word.typography.h1.spaceAfter', message: '间距越界' }]} />))
  expect(document.activeElement?.getAttribute('aria-label')).toBe('段后（磅）')
  expect(document.body.textContent).toContain('间距越界')
  expect(Number(document.querySelector<HTMLInputElement>('[aria-label="排版字号"]')?.value)).toBe(16)
})
it('保存时禁止修改，MD不显示物理排版', async () => {
  await act(async () => root.render(<TypographyFields document={documentValue} format="word" onChange={update} disabled />))
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="排版加粗"]')!.click())
  expect(update).not.toHaveBeenCalled()
  await act(async () => root.render(<TypographyFields document={documentValue} format="md" onChange={update} />))
  expect(document.querySelector('[aria-label="排版字号"]')).toBeNull()
})

it('XLSX使用正文与表头角色，不展示段落间距，错误能定位表头字号', async () => {
  const doc = { xlsx: { body: style, header: { ...style, size: 14 } } }
  await act(async () => root.render(<TypographyFields document={doc} format="xlsx" onChange={update}
    errors={[{ path: 'xlsx.header.size', message: '字号越界' }]} />))
  expect(Number(document.querySelector<HTMLInputElement>('[aria-label="排版字号"]')?.value)).toBe(14)
  expect(document.activeElement?.getAttribute('aria-label')).toBe('排版字号')
  expect(document.querySelector('[aria-label="段落细节"]')).toBeNull()
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="排版加粗"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['xlsx', 'header', 'bold'], true)
})

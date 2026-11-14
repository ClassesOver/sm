import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PagePreferenceFields, HeaderFooterFields } from './document-fields'

let root: Root
const update = vi.fn()
const documentValue = { word: { page: { paper: 'A4', orientation: 'portrait' }, headerFooter: { enabled: true, firstPageDifferent: true, oddEvenDifferent: false, header: { left: '{signer}', center: '', right: '{title}' }, footer: { left: '', center: '', right: '{page}/{pages}' }, firstHeader: { left: '', center: '', right: '' }, firstFooter: { left: '', center: '', right: '' } } },
  xlsx: { print: { page: { paper: 'A3', orientation: 'landscape' }, headerFooter: { enabled: false } } }, pptx: { aspectRatio: '16:9', layout: 'image_left', density: 'compact', theme: 'modern', footer: { left: '', center: '', right: '{slide}' }, hideTitleSlideFooter: true } }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })
it('XLSX 纸张读取打印设置，不展示 Word 段落参数', async () => {
  await act(async () => root.render(<PagePreferenceFields document={documentValue} format="xlsx" onChange={update} />))
  expect(document.body.textContent).toContain('A3')
  expect(document.body.textContent).toContain('横向')
  expect(document.body.textContent).not.toMatch(/行距|页眉|段前/)
})
it('PPTX 只显示比例，不错误显示纸张与分页', async () => {
  await act(async () => root.render(<PagePreferenceFields document={documentValue} format="pptx" onChange={update} />))
  expect(document.body.textContent).toContain('页面比例')
  expect(document.body.textContent).toContain('图片居左')
  expect(document.body.textContent).toContain('紧凑')
  expect(document.body.textContent).not.toMatch(/纸张|方向/)
})
it('页眉与页脚切换，不把六个位置一起纵向铺开', async () => {
  await act(async () => root.render(<HeaderFooterFields document={documentValue} format="word" onChange={update} />))
  expect(document.querySelectorAll('input.ant-input[aria-label^="页"]')).toHaveLength(3)
  expect(document.querySelector<HTMLInputElement>('[aria-label="页眉左侧"]')?.value).toBe('{signer}')
  const footer = [...document.querySelectorAll('label')].find(label => label.textContent === '页脚')!
  await act(async () => footer.click())
  expect(document.querySelector<HTMLInputElement>('[aria-label="页脚右侧"]')?.value).toBe('{page}/{pages}')
})
it('关闭页眉页脚后不渲染无效的文本配置', async () => {
  await act(async () => root.render(<HeaderFooterFields document={documentValue} format="xlsx" onChange={update} />))
  expect(document.querySelectorAll('input.ant-input[aria-label^="页"]')).toHaveLength(0)
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="启用页眉页脚"]')!.click())
  expect(update).toHaveBeenLastCalledWith(['xlsx', 'print', 'headerFooter', 'enabled'], true)
})

it('校验错误自动打开首页页脚并聚焦真实字段', async () => {
  await act(async () => root.render(<HeaderFooterFields document={documentValue} format="word" onChange={update}
    errors={[{ path: 'word.headerFooter.firstFooter.center', message: '请检查字段' }]} />))
  const input = document.querySelector<HTMLInputElement>('[aria-label="页脚中间"]')!
  expect(input).toBeTruthy()
  expect(document.activeElement).toBe(input)
  expect(document.body.textContent).toContain('请检查字段')
})

it('页面边距默认显示预设，自定义时才展开四个毫米输入', async () => {
  const value = { word: { page: { paper: 'A4', orientation: 'portrait', margins: { top: 25, right: 22, bottom: 24, left: 22 } } } }
  await act(async () => root.render(<PagePreferenceFields document={value} format="word" onChange={update} />))
  expect(document.querySelector('[aria-label="页边距"]')).not.toBeNull()
  expect(document.querySelectorAll('[role="spinbutton"]')).toHaveLength(0)
})

it('实际报告默认边距匹配预设，不自动展开毫米参数', async () => {
  const value = { word: { page: { paper: 'A4', orientation: 'portrait', margins: { top: 20, right: 18, bottom: 22, left: 18 } } } }
  await act(async () => root.render(<PagePreferenceFields document={value} format="word" onChange={update} />))
  expect(document.body.textContent).toContain('报告默认')
  expect(document.querySelectorAll('[role="spinbutton"]')).toHaveLength(0)
  expect(update).not.toHaveBeenCalled()
})

it('历史自定义边距保留原值，主动调整时才展开', async () => {
  const value = { word: { page: { paper: 'A4', orientation: 'portrait', margins: { top: 21, right: 19, bottom: 23, left: 19 } } } }
  await act(async () => root.render(<PagePreferenceFields document={value} format="word" onChange={update} />))
  expect(document.querySelectorAll('[role="spinbutton"]')).toHaveLength(0)
  const edit = document.querySelector<HTMLButtonElement>('[aria-label="调整自定义边距"]')!
  expect(edit).not.toBeNull()
  await act(async () => edit.click())
  expect(document.querySelector<HTMLInputElement>('[aria-label="左边距（毫米）"]')?.value).toBe('19.0')
  expect(update).not.toHaveBeenCalled()
})

it('自定义边距错误展开并聚焦对应输入，单位和校验清楚', async () => {
  const value = { xlsx: { print: { page: { paper: 'A4', orientation: 'portrait', margins: { top: 15, right: 98, bottom: 15, left: 98 } } } } }
  await act(async () => root.render(<PagePreferenceFields document={value} format="xlsx" onChange={update}
    errors={[{ path: 'xlsx.print.page.margins.left', message: '请保留可打印宽度' }]} />))
  const input = document.querySelector<HTMLInputElement>('[aria-label="左边距（毫米）"]')!
  expect(input).toBeTruthy()
  expect(document.activeElement).toBe(input)
  expect(document.querySelectorAll('[role="spinbutton"]')).toHaveLength(4)
  expect(document.body.textContent).toContain('请保留可打印宽度')
})

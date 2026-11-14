import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { HeaderFooterFields } from './document-fields'
import { validateSignatureDraft } from './preference-draft'

let root: Root
const update = vi.fn()
const style = { font: null, size: 14, color: '#345678', bold: false }
const value = { enabled: true, header: { left: '报告', center: '', right: '' },
  footer: { left: '', center: '', right: '{page}/{pages}' }, style }
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  document.body.innerHTML = '<div id="root"></div>'; root = createRoot(document.getElementById('root')!)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); update.mockReset() })

it.each(['word', 'pdf', 'xlsx', 'pptx'])('%s页眉页脚样式默认折叠，只维护已消费的四项并保留正确路径', async format => {
  const documentValue = { [format]: format === 'xlsx' ? { print: { headerFooter: value } }
    : format === 'pptx' ? { footer: value.footer, footerStyle: style, hideTitleSlideFooter: true }
      : { headerFooter: value } }
  const label = format === 'pptx' ? '页脚' : '页眉页脚'
  await act(async () => root.render(<HeaderFooterFields document={documentValue} format={format} onChange={update} />))
  const toggle = document.querySelector<HTMLButtonElement>(`[aria-label="${label}样式"]`)
  expect(toggle).not.toBeNull(); expect(toggle?.getAttribute('aria-expanded')).toBe('false')
  expect(document.querySelector(`[aria-label="${label}字号"]`)).toBeNull()
  await act(async () => toggle!.click())
  expect(document.querySelector(`[aria-label="${label}字体"]`)).not.toBeNull()
  expect(document.querySelector(`[aria-label="${label}颜色"]`)).not.toBeNull()
  expect(Number(document.querySelector<HTMLInputElement>(`[aria-label="${label}字号"]`)?.value)).toBe(14)
  await act(async () => document.querySelector<HTMLButtonElement>(`[aria-label="${label}加粗"]`)!.click())
  expect(update).toHaveBeenLastCalledWith(format === 'xlsx' ? ['xlsx', 'print', 'headerFooter', 'style', 'bold']
    : format === 'pptx' ? ['pptx', 'footerStyle', 'bold'] : [format, 'headerFooter', 'style', 'bold'], true)
  expect(document.querySelectorAll('form')).toHaveLength(1)
  expect(document.querySelector(`[aria-label="${label}首行缩进"]`) === null).toBe(format !== 'pptx')
})

it('错误自动展开样式并聚焦字号，修正后不折叠，隐藏页眉页脚时不提供样式', async () => {
  const documentValue = { xlsx: { print: { headerFooter: value } } }
  await act(async () => root.render(<HeaderFooterFields document={documentValue} format="xlsx" onChange={update}
    errors={[{ path: 'xlsx.print.headerFooter.style.size', message: '字号越界' }]} />))
  expect(document.activeElement?.getAttribute('aria-label')).toBe('页眉页脚字号')
  expect(document.body.textContent).toContain('字号越界')
  await act(async () => root.render(<HeaderFooterFields document={documentValue} format="xlsx" onChange={update} />))
  expect(document.querySelector('[aria-label="页眉页脚字号"]')).not.toBeNull()
  await act(async () => root.render(<HeaderFooterFields document={{ xlsx: { print: { headerFooter: { ...value, enabled: false } } } }}
    format="xlsx" onChange={update} />))
  expect(document.querySelector('[aria-label="页眉页脚样式"]')).toBeNull()
})

it('页眉页脚字号及颜色校验使用真实格式路径', () => {
  const errors = validateSignatureDraft({ common: { signer: '编制' },
    xlsx: { print: { headerFooter: { ...value, style: { ...style, size: 99, color: 'red' } } } },
    pptx: { footer: value.footer, footerStyle: { ...style, size: 0 } } })
  expect(errors.map(error => error.path)).toEqual(expect.arrayContaining([
    'xlsx.print.headerFooter.style.size', 'xlsx.print.headerFooter.style.color', 'pptx.footerStyle.size',
  ]))
})

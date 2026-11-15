import { afterEach, expect, it, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { DocxLayoutSource } from './docx-layout-source'
import { marginsFitPage, paperSizeInRange } from './docx-page-setup'
import { setMeasurementUnit } from './vendor/genoffice-docs/apps/docs/src/renderer/units'
const settings = { orientation: 'portrait' as const, pageWidth: 12240, pageHeight: 15840, pageBorder: false, marginTop: 1440, marginRight: 1440, marginBottom: 1440, marginLeft: 1440, columns: 1 as const }
const roots: ReturnType<typeof createRoot>[] = []
afterEach(() => { roots.splice(0).forEach(root => flushSync(() => root.unmount())); document.body.replaceChildren(); localStorage.clear() })
function setup(extra: Record<string, unknown> = {}) {
 const host = document.body.appendChild(document.createElement('div')), root = createRoot(host), onChange = vi.fn()
 roots.push(root)
 const render = (next: Record<string, unknown> = {}) => flushSync(() => root.render(<DocxLayoutSource editable settings={settings} onChange={onChange} {...extra} {...next} />))
 render(); return { host, onChange, render }
}
function select(host: HTMLElement, selector: string, value: string) { const el = host.querySelector<HTMLSelectElement>(selector)!; el.value = value; flushSync(() => el.dispatchEvent(new Event('change', { bubbles: true }))) }
function input(host: HTMLElement, label: string, value: string) { const el = host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value); flushSync(() => el.dispatchEvent(new Event('input', { bubbles: true }))) }
it('offers source moderate and Office 2003 presets with exact geometry', () => {
 const { host, onChange } = setup()
 const options = Array.from(host.querySelector<HTMLSelectElement>('[data-source-action="layout-margins"]')!.options, option => option.value)
 expect(options).toContain('moderate'); expect(options).toContain('office2003')
 select(host, '[data-source-action="layout-margins"]', 'moderate')
 expect(onChange).toHaveBeenLastCalledWith({ marginTop:1440,marginRight:1080,marginBottom:1440,marginLeft:1080 })
 select(host, '[data-source-action="layout-margins"]', 'office2003')
 expect(onChange).toHaveBeenLastCalledWith({ marginTop:1440,marginRight:1800,marginBottom:1440,marginLeft:1800 })
})
it('buffers unit-aware custom margins and remembers the successful custom value', () => {
 setMeasurementUnit('in')
 const { host, onChange } = setup()
 expect(host.querySelector('[data-source-action="layout-custom-margins"]')).not.toBeNull()
 flushSync(() => host.querySelector<HTMLButtonElement>('[data-source-action="layout-custom-margins"]')!.click())
 input(host, '上', '36pt'); expect(onChange).not.toHaveBeenCalled()
 flushSync(() => host.querySelector<HTMLButtonElement>('[data-page-setup-apply]')!.click())
 expect(onChange).toHaveBeenLastCalledWith({ marginTop:720,marginRight:1440,marginBottom:1440,marginLeft:1440 })
 expect(JSON.parse(localStorage.getItem('aidocs.marginLastCustom')!)).toEqual({top:720,right:1440,bottom:1440,left:1440})
 expect(host.querySelector<HTMLSelectElement>('[data-source-action="layout-margins"]')!.querySelector('[value="lastCustom"]')).not.toBeNull()
})
it('opens paper dialog with section and document targets and sends normalized dimensions to document callback', () => {
 const onPaperSizeAll = vi.fn(), { host, onChange } = setup({ onPaperSizeAll, sectionLabel:'第 1 节，共 2 节' })
 expect(host.querySelector('[data-source-action="layout-more-paper-sizes"]')).not.toBeNull()
 flushSync(() => host.querySelector<HTMLButtonElement>('[data-source-action="layout-more-paper-sizes"]')!.click())
 input(host, '宽度', '12in'); input(host, '高度', '8in')
 select(host,'[aria-label="应用于"]','document')
 flushSync(() => host.querySelector<HTMLButtonElement>('[data-page-setup-apply]')!.click())
 expect(onPaperSizeAll).toHaveBeenCalledWith(11520,17280,'landscape'); expect(onChange).not.toHaveBeenCalled()
})
it('never invokes mirror writer when source mirror state is unknown', () => {
 const onMirrorMargins = vi.fn(), { host } = setup({ onMirrorMargins })
 select(host,'[data-source-action="layout-margins"]','mirrored')
 expect(onMirrorMargins).not.toHaveBeenCalled()
})
it('retains a failed custom-margin draft without recording it and blocks commits after read-only transition', () => {
 const { host, render, onChange } = setup()
 const reject=vi.fn(()=>({error:'来源已变化'}))
 render({onChange:reject})
 flushSync(()=>host.querySelector<HTMLButtonElement>('[data-source-action="layout-custom-margins"]')!.click())
 input(host,'上','36pt')
 flushSync(()=>host.querySelector<HTMLButtonElement>('[data-page-setup-apply]')!.click())
 expect(host.querySelector('[role=dialog]')).not.toBeNull();expect(host.querySelector('[role=alert]')?.textContent).toContain('来源已变化')
 expect(localStorage.getItem('aidocs.marginLastCustom')).toBeNull()
 render({editable:false,onChange})
 expect(host.querySelector<HTMLButtonElement>('[data-page-setup-apply]')!.disabled).toBe(true)
 expect(host.querySelector<HTMLInputElement>('[aria-label="上"]')!.disabled).toBe(true)
 expect(onChange).not.toHaveBeenCalled()
})
it('closes source-bound setup drafts when switching sections', () => {
 const {host,render,onChange}=setup({sectionLabel:'第一节'})
 flushSync(()=>host.querySelector<HTMLButtonElement>('[data-source-action="layout-more-paper-sizes"]')!.click())
 input(host,'宽度','12in')
 render({sectionLabel:'第二节',settings:{...settings,pageWidth:20000}})
 expect(host.querySelector('[role=dialog]')).toBeNull();expect(onChange).not.toHaveBeenCalled()
})
it('rejects paper outside source bounds and margin-overflow without emitting operations', () => {
 const {host,onChange}=setup()
 flushSync(()=>host.querySelector<HTMLButtonElement>('[data-source-action="layout-more-paper-sizes"]')!.click())
 for(const width of ['7.15pt','1584.05pt','1in']) {
  input(host,'宽度',width)
  expect(host.querySelector<HTMLButtonElement>('[data-page-setup-apply]')!.disabled).toBe(true)
 }
 expect(onChange).not.toHaveBeenCalled()
})
it('restores last custom only when stored JSON is numeric and fits the active page', () => {
 localStorage.setItem('aidocs.marginLastCustom',JSON.stringify({top:14400,bottom:14400,left:14400,right:14400}))
 const {host,render}=setup()
 expect(host.querySelector('option[value="lastCustom"]')).toBeNull()
 localStorage.setItem('aidocs.marginLastCustom','{"top":"1440","bottom":1440,"left":1440,"right":1440}')
 render();expect(host.querySelector('option[value="lastCustom"]')).toBeNull()
})
it('reports invalid direct numeric input and preserves the current geometry', () => {
 const {host,onChange}=setup({settings:{...settings,pageWidth:10000,pageHeight:20000}})
 input(host,'自定义纸张宽度','')
 expect(onChange).not.toHaveBeenCalled()
 expect(host.querySelector('[role=alert]')?.textContent).toContain('144')
})
it('blocks a bounded paper width that leaves less body space than the fixed source permits', () => {
 const {host,onChange}=setup({settings:{...settings,pageWidth:10000,pageHeight:20000}})
 input(host,'自定义纸张宽度','4000')
 expect(onChange).not.toHaveBeenCalled()
 expect(host.querySelector('[role=alert]')?.textContent).toContain('正文空间')
})

it('accepts source-sized margins above ten inches when one inch of body remains', () => {
 expect(marginsFitPage({top:16000,right:1440,bottom:1440,left:16000},31680,31680)).toBe(true)
 expect(marginsFitPage({top:31681,right:0,bottom:0,left:0},31680,31680)).toBe(false)
})
it('distinguishes the source 144-twip numeric paper lower bound from usable-body validation', () => {
 expect(paperSizeInRange(144,144)).toBe(true)
 expect(paperSizeInRange(143,144)).toBe(false)
 expect(paperSizeInRange(144.5,144)).toBe(false)
 expect(paperSizeInRange(Number.NaN,144)).toBe(false)
 expect(marginsFitPage({top:0,right:0,bottom:0,left:0},144,144)).toBe(false)
})

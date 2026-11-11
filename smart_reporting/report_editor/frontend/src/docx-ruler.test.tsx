import { afterEach, expect, it } from 'vitest'
import { Editor, Extension } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { undoDepth } from '@tiptap/pm/history'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { DEFAULT_SECTION } from '@genoffice/docx-engine'
import { createDocxRuler } from './docx-ruler'
import { NativeDocxRulerIndent, applyDocxRulerIndent, docxRulerParagraphReason } from './docx-ruler-indent'
import { NativeDocxTabStops, applyDocxTabStops } from './docx-tab-stops'
import { docxOperations, replayDocxOperations } from './docx-operations'

const cleanups: Array<() => void> = []
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); document.body.replaceChildren() })
function setup(extendedIndents = false, native = false, editableTabs = false) {
  const host = document.body.appendChild(document.createElement('div')); host.className = 'docx-native'
  const container = host.appendChild(document.createElement('div')); container.className = 'doc-zoom'
  let zoom = 1, locked = false, updates = 0, transactions = 0, section = { ...DEFAULT_SECTION }, targetReason: string | null = null
  const errors: string[] = [], marginChanges: Array<{ left: number; right: number }> = []
  const Guard = Extension.create({ name: 'rulerGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction: tr => !tr.docChanged || !locked })] })
  const editor = new Editor({ element: container.appendChild(document.createElement('div')), extensions: [...editorExtensions, ...(native ? [NativeDocxRulerIndent, ...(editableTabs ? [NativeDocxTabStops] : [])] : []), Guard], editorProps: { attributes: { class: 'doc-page' }, handleScrollToSelection: () => true }, content: { type: 'doc', content: [
    { type: 'docParagraph', attrs: { docxIndex: 0, tabStops: JSON.stringify([{ pos: 2160, val: 'left' }]), indentLeft: 720, indentRight: 360, indentFirstLine: 180 }, content: [{ type: 'text', text: '第一段' }] },
    { type: 'docParagraph', attrs: { docxIndex: 1, tabStops: JSON.stringify([{ pos: 4320, val: 'right' }]), indentLeft: 1440 }, content: [{ type: 'text', text: '第二段' }] },
    { type: 'docParagraph', content: [{ type: 'text', text: '新增段落' }] },
  ] } })
  if (native) editor.commands.setContent({ type: 'doc', content: [editor.getJSON().content![0]!] })
  const baseline = editor.getJSON()
  editor.on('update', () => { updates++ }); editor.on('transaction', () => { transactions++ })
  const apply = (attrs: Record<string, unknown>) => editor.commands.updateAttributes('docParagraph', attrs)
  const anchors = [{ docxIndex: 0, blockId: 'p0', expectedObjectSha256: 'sha0', editable: true, rulerIndentEditable: true, tabStopsEditable: true }]
  const ruler = createDocxRuler({ editor, container, extendedIndents, editableTabs, getSection: () => section, getZoom: () => zoom, onTabStopsChange: stops => { if (native && editableTabs) applyDocxTabStops(editor, anchors, stops ?? []); else apply({ tabStops: stops ? JSON.stringify(stops) : null }) }, onIndentsChange: attrs => { if (native && attrs.indentRight === undefined) applyDocxRulerIndent(editor, anchors, attrs); else apply({ ...attrs }) }, onMarginsChange: margins => { marginChanges.push(margins); section = { ...section, marginLeft: margins.left, marginRight: margins.right } }, readOnlyReason: () => targetReason, onError: error => errors.push(String((error as Error).message)) })
  cleanups.push(() => { ruler.dispose(); editor.destroy() })
  const rect = (element: Element, width: number) => Object.defineProperty(element, 'getBoundingClientRect', { configurable: true, value: () => ({ left: 0, top: 0, width, height: 20, right: width, bottom: 20, x: 0, y: 0, toJSON() {} }) })
  return { host, container, editor, ruler, baseline, anchors, errors, marginChanges, rect, updates: () => updates, transactions: () => transactions, setZoom: (value: number) => { zoom = value }, setSection: (value: typeof section) => { section = value }, setReason: (value: string | null) => { targetReason = value }, lock() { locked = true; editor.setEditable(false, false) } }
}
const key = (element: Element, value: string) => element.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true }))

it('mounts the unchanged source ruler only when visible without document, storage or history writes', () => {
  const f = setup(), storage = { ...localStorage }, history = undoDepth(f.editor.state)
  expect(f.ruler.visible).toBe(false); expect(f.host.querySelector('.ruler')).toBeNull()
  f.ruler.toggle(); expect(f.ruler.visible).toBe(true); expect(f.host.querySelector('.ruler-tab-type')?.textContent).toBe('L')
  expect(f.host.querySelectorAll('.ruler-tick,.ruler-num').length).toBeGreaterThan(20)
  expect(f.host.querySelector('.ruler-tab')?.getAttribute('aria-valuenow')).toBe('2160')
  f.ruler.refresh(); f.ruler.toggle()
  expect(f.host.querySelector('.ruler')).toBeNull(); expect(f.editor.getJSON()).toEqual(f.baseline); expect(f.updates()).toBe(0); expect(f.transactions()).toBe(0); expect(undoDepth(f.editor.state)).toBe(history); expect({ ...localStorage }).toEqual(storage)
})

it('uses source right-indent and margin keyboard math and existing editor UndoRedo', () => {
  const f = setup(); f.ruler.toggle()
  key(f.host.querySelector('.ruler-tab')!, 'ArrowRight')
  expect(f.editor.getJSON()).toEqual(f.baseline)
  key(f.host.querySelector('.ruler-ind-right')!, 'ArrowLeft'); expect(f.editor.getAttributes('docParagraph').indentRight).toBe(450)
  f.editor.commands.undo(); expect(f.editor.getJSON()).toEqual(f.baseline); f.editor.commands.redo()
  key(f.host.querySelector('.ruler-margin-handle[data-side=left]')!, 'ArrowRight'); expect(f.marginChanges).toEqual([{ left: 1530, right: 1440 }])
  expect(f.errors).toEqual([])
})

it('follows selection, paragraph attributes and active section sizes without replacing source math', () => {
  const f = setup(); f.ruler.toggle(); const second = f.editor.state.doc.child(0).nodeSize + 1
  f.editor.commands.setTextSelection(second)
  expect(f.host.querySelector('.ruler-tab')?.getAttribute('aria-valuenow')).toBe('4320')
  expect(f.host.querySelector('.ruler-ind-left')?.getAttribute('aria-valuenow')).toBe('2880')
  f.setSection({ ...DEFAULT_SECTION, pageWidth: 14400, marginLeft: 1800 }); f.ruler.refresh()
  expect(f.host.querySelector<HTMLElement>('.ruler')?.style.width).toBe('960px')
  expect(f.host.querySelector('.ruler-ind-left')?.getAttribute('aria-valuenow')).toBe('3240')
})

it('shows read-only markers but prevents all writes under save locks, unsupported targets and callback reasons', () => {
  const f = setup(); f.ruler.toggle(); f.lock(); f.ruler.refresh()
  key(f.host.querySelector('.ruler-tab')!, 'Delete'); key(f.host.querySelector('.ruler-ind-right')!, 'ArrowLeft'); key(f.host.querySelector('.ruler-margin-handle')!, 'ArrowRight')
  expect(f.editor.getJSON()).toEqual(f.baseline); expect(f.marginChanges).toEqual([])
  expect(f.ruler.reason('tabs')).not.toBeNull(); expect(f.host.querySelector('.ruler')?.getAttribute('aria-disabled')).toBe('true')
  const other = setup(); other.ruler.toggle(); other.setReason('来源段落不支持保存'); other.ruler.refresh(); key(other.host.querySelector('.ruler-tab')!, 'Delete'); expect(other.editor.getJSON()).toEqual(other.baseline)
  other.setReason(null); other.editor.commands.setTextSelection(other.editor.state.doc.content.size - 1)
  expect(other.ruler.reason('indentRight')).toContain('新增'); expect(other.ruler.reason('indents')).not.toBeNull()
})

it('cancels source drag cleanup when hidden or disposed and never commits a late mouseup', () => {
  const f = setup(); f.ruler.toggle(); const node = f.host.querySelector('.ruler')!; f.rect(node, 816)
  f.host.querySelector('.ruler-ind-right')!.dispatchEvent(new MouseEvent('mousedown', { clientX: 696, bubbles: true, cancelable: true }))
  document.dispatchEvent(new MouseEvent('mousemove', { clientX: 680, bubbles: true }))
  expect(document.querySelector('.ruler-drag-guide')).not.toBeNull()
  f.ruler.toggle(); expect(document.querySelector('.ruler-drag-guide')).toBeNull()
  document.dispatchEvent(new MouseEvent('mouseup', { clientX: 680, bubbles: true })); expect(f.editor.getJSON()).toEqual(f.baseline)
  f.ruler.toggle(); f.ruler.dispose(); f.ruler.dispose(); expect(f.host.querySelector('.docx-ruler-host')).toBeNull(); expect(f.ruler.reason()).not.toBeNull()
})

it('blocks unsupported marker keyboard, mouse and ruler-click writes with explicit reasons', () => {
  const f = setup(); f.ruler.toggle()
  for (const selector of ['.ruler-tab', '.ruler-ind-left', '.ruler-ind-firstLine', '.ruler-ind-hanging']) {
    const marker = f.host.querySelector(selector)!
    expect(marker.getAttribute('aria-disabled')).toBe('true'); expect(marker.getAttribute('title')).toBeTruthy()
    key(marker, 'ArrowRight'); key(marker, 'Delete')
    marker.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    document.dispatchEvent(new MouseEvent('mouseup', { clientX: 500, bubbles: true }))
  }
  f.host.querySelector('.ruler')!.dispatchEvent(new MouseEvent('click', { clientX: 400, bubbles: true, cancelable: true }))
  expect(f.editor.getJSON()).toEqual(f.baseline)
  expect(f.host.querySelector<HTMLButtonElement>('.ruler-tab-type')!.disabled).toBe(true)
})

it('centres the scaled ruler above the page and follows page zoom without document writes', async () => {
  const f = setup(); f.editor.view.dom.setAttribute('style', 'zoom: 0.75'); f.setZoom(0.75); f.ruler.toggle()
  const host = f.host.querySelector<HTMLElement>('.docx-ruler-host')!, ruler = host.querySelector<HTMLElement>('.ruler')!
  expect(host.nextElementSibling).toBe(f.container); expect(host.style.width).toBe('612px'); expect(ruler.style.zoom).toBe('0.75')
  f.editor.view.dom.setAttribute('style', 'zoom: 1.25'); f.setZoom(1.25)
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(host.style.width).toBe('1020px'); expect(ruler.style.zoom).toBe('1.25'); expect(f.editor.getJSON()).toEqual(f.baseline)
})

for (const change of ['selection', 'document', 'section', 'zoom', 'lock', 'reason'] as const) it('cancels source drag after ' + change + ' changes', () => {
  const f = setup(); f.ruler.toggle(); f.rect(f.host.querySelector('.ruler')!, 816)
  f.host.querySelector('.ruler-ind-right')!.dispatchEvent(new MouseEvent('mousedown', { clientX: 696, bubbles: true, cancelable: true }))
  document.dispatchEvent(new MouseEvent('mousemove', { clientX: 680, bubbles: true }))
  expect(document.querySelector('.ruler-drag-guide')).not.toBeNull()
  if (change === 'selection') f.editor.commands.setTextSelection(f.editor.state.doc.child(0).nodeSize + 1)
  if (change === 'document') f.editor.commands.insertContent('changed')
  if (change === 'section') f.setSection({ ...DEFAULT_SECTION, marginLeft: 1800 })
  if (change === 'zoom') f.setZoom(0.75)
  if (change === 'lock') f.lock()
  if (change === 'reason') f.setReason('保存中')
  const before = f.editor.getJSON(); f.ruler.refresh()
  document.dispatchEvent(new MouseEvent('mouseup', { clientX: 680, bubbles: true }))
  expect(f.editor.getJSON()).toEqual(before); expect(f.marginChanges).toEqual([])
  expect(document.querySelector('.ruler-drag-guide')).toBeNull()
})

it('commits zoom-scaled source drag once and cancels a margin drag on disposal', () => {
  const f = setup(); f.setZoom(0.5); f.ruler.toggle(); f.rect(f.host.querySelector('.ruler')!, 408)
  f.host.querySelector('.ruler-ind-right')!.dispatchEvent(new MouseEvent('mousedown', { clientX: 348, bubbles: true, cancelable: true }))
  document.dispatchEvent(new MouseEvent('mousemove', { clientX: 342, bubbles: true }))
  document.dispatchEvent(new MouseEvent('mouseup', { clientX: 342, bubbles: true }))
  expect(f.editor.getAttributes('docParagraph').indentRight).toBe(540); expect(f.updates()).toBe(1)
  f.host.querySelector('.ruler-margin-handle[data-side=left]')!.dispatchEvent(new MouseEvent('mousedown', { clientX: 48, bubbles: true, cancelable: true }))
  document.dispatchEvent(new MouseEvent('mousemove', { clientX: 54, bubbles: true }))
  f.ruler.dispose(); document.dispatchEvent(new MouseEvent('mouseup', { clientX: 54, bubbles: true }))
  expect(f.marginChanges).toEqual([]); expect(document.querySelector('.ruler-drag-guide')).toBeNull()
})

it('rechecks callback locks on mouseup without an explicit refresh and restores marker state', async () => {
  const f = setup(); f.ruler.toggle(); f.rect(f.host.querySelector('.ruler')!, 816)
  const originalLeft = f.host.querySelector<HTMLElement>('.ruler-ind-right')!.style.left
  f.host.querySelector('.ruler-ind-right')!.dispatchEvent(new MouseEvent('mousedown', { clientX: 696, bubbles: true, cancelable: true }))
  document.dispatchEvent(new MouseEvent('mousemove', { clientX: 680, bubbles: true }))
  f.setReason('保存中')
  document.dispatchEvent(new MouseEvent('mouseup', { clientX: 680, bubbles: true }))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(f.editor.getJSON()).toEqual(f.baseline)
  expect(f.host.querySelector<HTMLElement>('.ruler-ind-right')!.style.left).toBe(originalLeft)
  expect(f.host.querySelector('.ruler-ind-right')?.getAttribute('aria-disabled')).toBe('true')
  expect(document.querySelector('.ruler-drag-guide')).toBeNull()
})


it('opens source left, first-line and hanging math only for extended writeback', () => {
  const f = setup(true); f.ruler.toggle()
  for (const name of ['left', 'firstLine', 'hanging']) expect(f.host.querySelector('.ruler-ind-' + name)?.getAttribute('aria-disabled')).toBe('false')
  key(f.host.querySelector('.ruler-ind-left')!, 'ArrowRight')
  expect(f.editor.state.doc.child(0).attrs.indentLeft).toBe(810)
  expect(f.editor.state.doc.child(0).attrs.indentFirstLine).toBe(180)
  key(f.host.querySelector('.ruler-ind-firstLine')!, 'ArrowRight')
  expect(f.editor.state.doc.child(0).attrs.indentFirstLine).toBe(270)
  key(f.host.querySelector('.ruler-ind-hanging')!, 'ArrowRight')
  expect(f.editor.state.doc.child(0).attrs.indentLeft).toBe(900)
  expect(f.editor.state.doc.child(0).attrs.indentFirstLine).toBe(180)
  f.editor.commands.undo()
  expect(f.editor.state.doc.child(0).attrs.indentLeft).toBe(720)
})

it('keeps extended source markers read-only when the host capability rejects them', () => {
  const f = setup(true); f.setReason('字符缩进来源暂不支持标尺写回'); f.ruler.toggle()
  key(f.host.querySelector('.ruler-ind-firstLine')!, 'ArrowRight')
  expect(f.editor.getJSON()).toEqual(f.baseline)
  expect(f.host.querySelector('.ruler-ind-firstLine')?.getAttribute('aria-disabled')).toBe('true')
})

it('commits native first-line and hanging gestures as separate undo steps with atomic collector and replay', () => {
  const f = setup(true, true); f.ruler.toggle()
  key(f.host.querySelector('.ruler-ind-firstLine')!, 'ArrowRight')
  const first = f.editor.getJSON()
  key(f.host.querySelector('.ruler-ind-hanging')!, 'ArrowRight')
  const both = f.editor.getJSON(), ops = docxOperations(f.baseline, both, f.anchors)
  expect(ops).toEqual([{ kind: 'setParagraphRulerIndent', blockId: 'p0', expectedObjectSha256: 'sha0', leftTwips: 810, firstLineTwips: 180 }])
  expect(replayDocxOperations(f.baseline, ops, f.anchors)).toEqual(both)
  f.editor.commands.undo(); expect(f.editor.getJSON()).toEqual(first)
  f.editor.commands.undo(); expect(f.editor.getJSON()).toEqual(f.baseline)
  f.editor.commands.redo(); f.editor.commands.redo(); expect(f.editor.getJSON()).toEqual(both)
  expect(f.errors).toEqual([])
})

it('commits a real half-zoom first-line mouse drag through native projection only on release', () => {
  const f = setup(true, true); f.setZoom(0.5); f.ruler.toggle(); f.rect(f.host.querySelector('.ruler')!, 408)
  f.host.querySelector('.ruler-ind-firstLine')!.dispatchEvent(new MouseEvent('mousedown', { clientX: 78, bubbles: true, cancelable: true }))
  document.dispatchEvent(new MouseEvent('mousemove', { clientX: 84, bubbles: true }))
  expect(f.editor.getJSON()).toEqual(f.baseline)
  document.dispatchEvent(new MouseEvent('mouseup', { clientX: 84, bubbles: true }))
  expect(f.editor.state.doc.child(0).attrs.indentFirstLine).toBe(360)
  expect(f.updates()).toBe(1)
  f.editor.commands.undo(); expect(f.editor.getJSON()).toEqual(f.baseline)
  expect(f.errors).toEqual([])
})

it('checks native paragraph capability and unique source identity for host marker reasons', () => {
  const f = setup(true, true)
  expect(docxRulerParagraphReason(f.editor, f.anchors, 'indentFirstLine')).toBeNull()
  expect(docxRulerParagraphReason(f.editor, [...f.anchors, ...f.anchors], 'indentLeft')).not.toBeNull()
  const locked = [{ ...f.anchors[0]!, rulerIndentEditable: false, rulerIndentReadOnlyReason: '字符缩进来源' }]
  expect(docxRulerParagraphReason(f.editor, locked, 'indentHanging')).toBe('字符缩进来源')
  expect(docxRulerParagraphReason(f.editor, locked, 'indentRight')).toBeNull()
  expect(docxRulerParagraphReason(f.editor, [{ ...f.anchors[0]!, paragraphLayoutEditable: false }], 'indentLeft')).not.toBeNull()
})

it('opens tab callbacks only with explicit capability at source pointer scale', () => {
  const f = setup(true, false, true); f.ruler.toggle()
  expect(f.host.querySelector('.ruler-tab-type')?.getAttribute('aria-disabled')).toBe('false')
  key(f.host.querySelector('.ruler-tab')!, 'ArrowRight')
  expect(JSON.parse(f.editor.getAttributes('docParagraph').tabStops)).toEqual([{ pos: 2220, val: 'left' }])
  f.setZoom(0.5); f.ruler.refresh()
  const before = f.editor.getJSON()
  key(f.host.querySelector('.ruler-tab')!, 'Delete')
  expect(f.editor.getJSON()).toEqual(before)
  expect(f.ruler.reason('tabs')).not.toBeNull()
})

it('collects native tab keyboard edits with separate undo steps and explicit last-stop deletion', () => {
  const f=setup(true,true,true); f.ruler.toggle()
  key(f.host.querySelector('.ruler-tab')!,'ArrowRight')
  const nudged=f.editor.getJSON()
  expect(docxOperations(f.baseline,nudged,f.anchors)).toEqual([{kind:'setParagraphTabStops',blockId:'p0',expectedObjectSha256:'sha0',stops:[{pos:2220,val:'left'}]}])
  key(f.host.querySelector('.ruler-tab')!,'Delete')
  const empty=f.editor.getJSON(), ops=docxOperations(f.baseline,empty,f.anchors)
  expect(ops[0]).toMatchObject({kind:'setParagraphTabStops',stops:[]})
  expect(replayDocxOperations(f.baseline,ops,f.anchors)).toEqual(empty)
  f.editor.commands.undo(); expect(f.editor.getJSON()).toEqual(nudged)
  f.editor.commands.undo(); expect(f.editor.getJSON()).toEqual(f.baseline)
  f.editor.commands.redo(); f.editor.commands.redo(); expect(f.editor.getJSON()).toEqual(empty)
  expect(f.errors).toEqual([])
})

it('uses source tab click type and real drag without writing before release', async () => {
  const f=setup(true,true,true); f.ruler.toggle(); f.rect(f.host.querySelector('.ruler')!,816)
  const before=f.editor.getJSON()
  f.host.querySelector('.ruler-tab-type')!.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}))
  document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))
  f.host.querySelector<HTMLButtonElement>('.ruler-tab-type')!.click()
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(f.host.querySelector('.ruler-tab-type')?.textContent).toBe('⊥')
  expect(f.editor.getJSON()).toEqual(before)
  f.host.querySelector('.ruler')!.dispatchEvent(new MouseEvent('click',{clientX:240,bubbles:true,cancelable:true}))
  expect(docxOperations(f.baseline,f.editor.getJSON(),f.anchors)[0]).toMatchObject({stops:[{pos:2160,val:'left'},{pos:3600,val:'center'}]})
  const added=f.editor.getJSON()
  f.host.querySelector('.ruler-tab-center')!.dispatchEvent(new MouseEvent('mousedown',{clientX:240,bubbles:true,cancelable:true}))
  document.dispatchEvent(new MouseEvent('mousemove',{clientX:288,bubbles:true}))
  expect(f.editor.getJSON()).toEqual(added)
  document.dispatchEvent(new MouseEvent('mouseup',{clientX:288,bubbles:true}))
  expect(docxOperations(f.baseline,f.editor.getJSON(),f.anchors)[0]).toMatchObject({stops:[{pos:2160,val:'left'},{pos:4320,val:'center'}]})
  expect(f.errors).toEqual([])
})

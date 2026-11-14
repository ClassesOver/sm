import { NativeDocxFontDialog } from './docx-font-properties'
import { afterEach, expect, it, vi } from 'vitest'
import { Editor } from '@tiptap/core'
import { flushSync } from 'react-dom'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations, replayDocxOperations } from './docx-operations'
import { normalizePlainDocxRuns, replayPlainDocxRuns } from './docx-plain-paragraph-runs'
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup(caret = false) {
 const editor = new Editor({ extensions: [...editorExtensions,NativeDocxFontDialog], editorProps:{handleScrollToSelection:()=>true},content:{ type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[
  {type:'text',text:'Latin',marks:[{type:'bold'},{type:'docTextStyle',attrs:{fontAscii:'Cambria',font:'宋体',eastAsiaFont:'宋体',sizeHalfPoints:24,color:'112233',charScalePct:80,charSpacingTwips:15,positionHalfPoints:2,kernHalfPoints:20,dstrike:true,caps:'small',vanishOwn:false}}]},
  {type:'text',text:' 中文',marks:[{type:'italic'},{type:'docTextStyle',attrs:{fontAscii:'Arial',font:'楷体',eastAsiaFont:'楷体',sizeHalfPoints:28,color:'445566',charScalePct:100,charSpacingTwips:-10,positionHalfPoints:-2,kernHalfPoints:0}}]},
 ]}]}});editors.push(editor)
 const anchors=[{docxIndex:0,blockId:'p0',expectedObjectSha256:'hash0',editable:true}]
 editor.commands.setTextSelection(caret?3:{from:1,to:editor.state.doc.content.size-1})
 const root=document.body.appendChild(document.createElement('div'));root.append(createDocxRibbon(editor,true,undefined,undefined,undefined,anchors))
 const open=()=>flushSync(()=>{const entry=root.querySelector<HTMLButtonElement>('[data-action="font-options"]');expect(entry).not.toBeNull();entry!.click()})
 const field=(label:string)=>root.querySelector<HTMLInputElement|HTMLSelectElement>(`[aria-label="字体设置"] [aria-label="${label}"]`)!
 const submit=()=>flushSync(()=>root.querySelector<HTMLFormElement>('[aria-label="字体设置"] form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})))
 const change=(label:string,value:string)=>{const input=field(label);input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}))}
 return{editor,anchors,root,open,field,submit,change}
}
it('opens the complete Font and Advanced dialog and preserves current mixed values on noop/cancel',()=>{
 const f=setup(),before=f.editor.getJSON(),doc=f.editor.state.doc;f.open()
 expect(f.root.querySelectorAll('[aria-label="字体设置"] [role=tab]')).toHaveLength(2)
 for(const label of ['西文字体','中文字体','字体样式','字号（pt）','字体颜色','字符缩放（%）'])expect(f.field(label).value).toBe('')
 f.submit();expect(f.editor.state.doc).toBe(doc)
 f.open();f.change('中文字体','仿宋');f.root.querySelector<HTMLButtonElement>('[data-font-cancel]')!.click();expect(f.editor.getJSON()).toEqual(before)
})
it('applies touched Latin and Asian slots with all advanced fields as one undoable change preserving per-run fields',()=>{
 const f=setup(),before=f.editor.getJSON();f.open();f.change('西文字体','Calibri');f.change('中文字体','仿宋');f.change('字符缩放（%）','125');f.change('字符间距','expanded');f.change('字符间距值（pt）','1.25');f.change('字符位置','raised');f.change('字符位置值（pt）','2.5');f.change('字距调整阈值（pt）','10')
 const kern=f.field('启用字距调整') as HTMLInputElement;kern.checked=true;kern.dispatchEvent(new Event('change',{bubbles:true}));f.submit()
 expect(f.root.querySelector('[role=alert]')).toBeNull()
 const ops=docxOperations(before,f.editor.getJSON(),f.anchors,undefined,f.editor.schema)
 expect(ops.length).toBeGreaterThan(0);expect(JSON.stringify(ops)).toContain('charScalePct')
 expect(f.editor.state.doc.firstChild!.firstChild!.marks.some(mark=>mark.type.name==='bold')).toBe(true)
 expect(f.editor.state.doc.firstChild!.lastChild!.marks.some(mark=>mark.type.name==='italic')).toBe(true)
 const restored=replayDocxOperations(before,ops,f.anchors,undefined,f.editor.schema);expect(f.editor.schema.nodeFromJSON(restored).toJSON()).toEqual(f.editor.getJSON())
 f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(before);f.editor.commands.redo();expect(f.editor.state.doc.firstChild!.firstChild!.marks.find(mark=>mark.type.name==='docTextStyle')!.attrs.charScalePct).toBe(125)
})
it.each(['selection','document','readonly','selection-return'])('rejects stale %s before applying a touched field',kind=>{
 const f=setup();f.open();f.change('西文字体','Calibri')
 if(kind==='document')f.editor.commands.insertContent('新');else if(kind==='readonly')f.editor.setEditable(false);else{const original=f.editor.state.selection;f.editor.commands.setTextSelection(2);if(kind==='selection-return')f.editor.commands.setTextSelection(original)}
 const before=f.editor.getJSON();f.submit();expect(f.editor.getJSON()).toEqual(before);expect(f.root.querySelector('[role=alert]')!.textContent).toContain('重新打开')
})
it('keeps caret font changes pending and persists only later typed text through the native source-run plan',()=>{
 const f=setup(true),before=f.editor.getJSON();f.open();f.change('字符缩放（%）','150');f.change('字符间距','expanded');f.change('字符间距值（pt）','1.5');f.submit();expect(f.editor.getJSON()).toEqual(before)
 f.editor.commands.insertContent('Z')
 const normalized=normalizePlainDocxRuns(before,f.editor.getJSON(),f.anchors)
 expect(normalized.operations).toHaveLength(1);expect(JSON.stringify(normalized.operations)).toContain('charScalePct')
 const restored=replayPlainDocxRuns(before,normalized.operations,f.anchors);expect(f.editor.schema.nodeFromJSON(restored).textContent).toBe(f.editor.state.doc.textContent)
})
it('applies all Font effects, size and color, then explicit clearing without flattening untouched marks',()=>{
 const f=setup();f.open();f.change('字体样式','boldItalic');f.change('字号（pt）','230.5');f.change('字体颜色','#ABCDEF')
 for(const label of ['下划线','删除线','上标','双删除线','全部大写字母','隐藏文字']){const el=f.field(label) as HTMLInputElement;el.checked=true;el.dispatchEvent(new Event('change',{bubbles:true}))}
 f.submit();expect(f.root.querySelector('[role=alert]')).toBeNull()
 let mark=f.editor.state.doc.firstChild!.firstChild!.marks.find(m=>m.type.name==='docTextStyle')!
 expect(mark.attrs).toMatchObject({sizeHalfPoints:461,color:'ABCDEF',vertAlign:'superscript',dstrike:true,caps:'all',vanishOwn:true})
 f.open();for(const label of ['下划线','删除线','上标','双删除线','全部大写字母','隐藏文字']){const el=f.field(label) as HTMLInputElement;el.checked=false;el.dispatchEvent(new Event('change',{bubbles:true}))};f.change('字符缩放（%）','100');f.change('字符间距','normal');f.change('字符位置','normal');const kern=f.field('启用字距调整') as HTMLInputElement;kern.checked=false;kern.dispatchEvent(new Event('change',{bubbles:true}));f.submit()
 mark=f.editor.state.doc.firstChild!.firstChild!.marks.find(m=>m.type.name==='docTextStyle')!;expect(mark.attrs).toMatchObject({vertAlign:'baseline',dstrike:false,caps:'none',vanishOwn:false,charScalePct:null,charSpacingTwips:null,positionHalfPoints:null,kernHalfPoints:0})
})
it('rejects invalid fields atomically and preserves both current values at a single-run caret',()=>{
 const f=setup(true),before=f.editor.getJSON();f.open();expect(f.field('西文字体').value).toBe('Cambria');expect(f.field('中文字体').value).toBe('宋体');expect(f.field('字符缩放（%）').value).toBe('80')
 f.change('西文字体','Calibri');f.change('字符缩放（%）','601');f.submit();expect(f.editor.getJSON()).toEqual(before);expect(f.root.querySelector('[role=alert]')!.textContent).toContain('无效');expect(f.editor.state.storedMarks).toBeNull()
})
it('keeps Font/Advanced keyboard focus and rejects late system-font callbacks after selection changes',async()=>{
 let resolve!: (value:{family:string}[])=>void;Object.defineProperty(window,'queryLocalFonts',{configurable:true,value:()=>new Promise(r=>{resolve=r})})
 const f=setup();f.open();f.field('西文字体').click();const tabs=[...f.root.querySelectorAll<HTMLButtonElement>('[role=tab]')];tabs[0]!.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));expect(tabs[1]!.getAttribute('aria-selected')).toBe('true');expect(document.activeElement).toBe(tabs[1]);tabs[1]!.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true,cancelable:true}));expect(tabs[0]!.getAttribute('aria-selected')).toBe('true');tabs[0]!.dispatchEvent(new KeyboardEvent('keydown',{key:'End',isComposing:true,bubbles:true,cancelable:true}));expect(tabs[0]!.getAttribute('aria-selected')).toBe('true')
 f.editor.commands.setTextSelection(2);resolve([{family:'late-system-family'}]);await Promise.resolve();expect(f.root.querySelector('option[value="late-system-family"]')).toBeNull();delete (window as any).queryLocalFonts
})
it('rejects unsupported edits even under explicit Font mode and keeps basic format protocol bounded',()=>{
 const f=setup(),before=f.editor.getJSON(),after=structuredClone(before);const mark=after.content![0]!.content![0]!.marks!.find(m=>m.type==='docTextStyle')!;mark.attrs={...mark.attrs,nativeFontDialog:true,rawRPr:'<evil/>'};expect(()=>docxOperations(before,after,f.anchors,undefined,f.editor.schema)).toThrow()
 for(const style of [{fontAscii:'Calibri'},{fontDialog:'true',charScalePct:120},{fontDialog:true,unknown:'x'}])expect(()=>replayDocxOperations(before,[{kind:'formatRange',blockId:'p0',expectedObjectSha256:'hash0',from:0,to:1,style}],f.anchors,undefined,f.editor.schema)).toThrow()
})

it('previews Advanced spacing, raised position and kerning without changing the document',()=>{
 const f=setup(),before=f.editor.getJSON();f.open();f.change('字符位置','raised');f.change('字符位置值（pt）','2.5');f.change('字符间距','expanded');f.change('字符间距值（pt）','1.25');f.change('字符缩放（%）','125');const kern=f.field('启用字距调整') as HTMLInputElement;kern.checked=true;kern.dispatchEvent(new Event('change',{bubbles:true}))
 const preview=f.root.querySelector<HTMLElement>('.docx-font-preview span')!;expect(preview.style.top).toBe('-2.5pt');expect(Number.parseFloat(preview.style.letterSpacing)).toBeGreaterThan(1.25);expect(preview.style.fontKerning).toBe('normal');expect(f.editor.getJSON()).toEqual(before)
})


it('reveals a keyboard-readable font error without stealing input focus, then applies corrected values',()=>{
 const f=setup(true),before=f.editor.getJSON();f.open()
 const advanced=f.root.querySelector<HTMLButtonElement>('[data-tab=advanced]')!;advanced.click()
 f.change('字符缩放（%）','601');f.field('字符缩放（%）').focus()
 const alert=f.root.querySelector<HTMLElement>('[role=alert]')!,reveal=vi.fn(),dispatch=vi.spyOn(f.editor.view,'dispatch')
 alert.scrollIntoView=reveal
 f.submit()
 expect(dispatch).not.toHaveBeenCalled();expect(f.editor.getJSON()).toEqual(before);expect(f.editor.state.storedMarks).toBeNull()
 expect(alert.hidden).toBe(false);expect(alert.textContent).toContain('字符缩放（%）数值或精度无效')
 expect(alert.getAttribute('aria-label')).toBe('字体设置错误');expect(alert.tabIndex).toBe(0)
 expect(reveal).toHaveBeenCalledWith({block:'nearest'});expect(document.activeElement).toBe(f.field('字符缩放（%）'))
 expect(f.field('字符缩放（%）').value).toBe('601')
 f.change('字符缩放（%）','125');f.submit()
 expect(dispatch).toHaveBeenCalled();expect(f.root.querySelector('[aria-label="字体设置"]')).toBeNull()
 expect(f.editor.state.storedMarks?.find(mark=>mark.type.name==='docTextStyle')?.attrs.charScalePct).toBe(125)
})

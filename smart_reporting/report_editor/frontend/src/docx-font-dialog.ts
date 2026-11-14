import type { Editor } from '@tiptap/core'
import { closeHistory } from '@tiptap/pm/history'
import { docxOperations, type DocxAnchor } from './docx-operations'
import { docxFontProperties } from '../../../reporting/doc_engine/bridge/docx-font-properties'
import { charSpacingAttrs, charSpacingFromAttrs, fontTabAttrs, selectionRanges, setTextStyleWithScale } from './docx-font-source'
import { fontFamiliesFor } from './vendor/genoffice-docs/apps/docs/src/renderer/font-list'
import { charScaleEm, cssFontFamily } from './vendor/genoffice-docs/apps/docs/src/renderer/line-metrics'
import { createModal } from './modal'
import { buttonClasses } from './button'
import './docx-font-dialog.css'

function trusted(editor: Editor, anchors: DocxAnchor[]) {
 const { $from, $to } = editor.state.selection
 if ($from.depth !== 1 || $to.depth !== 1) return false
 let count = 0, valid = true
 editor.state.doc.forEach((node, _pos, index) => {
  if (index < $from.index(0) || index > $to.index(0)) return
  const found = anchors.filter(a => a.docxIndex === node.attrs.docxIndex); count++
  if (!['docParagraph','docHeading','docListItem'].includes(node.type.name) || found.length !== 1 || !found[0]!.editable || found[0]!.fontDialogEditable === false || !found[0]!.blockId || !found[0]!.expectedObjectSha256) valid = false
  node.forEach(child => { if (!child.isText) valid = false })
 }); return valid && count > 0
}
export function docxFontDialogUnavailable(editor: Editor, anchors: DocxAnchor[]) {
 return !editor.isEditable || !trusted(editor, anchors) ? '请选择可信原有正文、标题或列表文字；表格和受保护对象暂不支持' : null
}
let dialogId = 0
/** Fixed-source fields, per-run merge, and pending caret marks feed the existing strict writer. */
export function openDocxFontDialog(root: HTMLElement, editor: Editor, anchors: DocxAnchor[]) {
 const unavailable = docxFontDialogUnavailable(editor, anchors); if (unavailable) throw new Error(unavailable)
 const doc = editor.state.doc, selection = editor.state.selection, id = `docx-font-${++dialogId}`
 let closed = false, selectionChanged = false
 const onSelection = () => { selectionChanged = true }; editor.on('selectionUpdate', onSelection)
 const close = () => { if (closed) return; closed = true; editor.off('selectionUpdate',onSelection); modal.remove() }
 const valid = () => !closed && !editor.isDestroyed && editor.isEditable && !selectionChanged && editor.state.doc === doc && editor.state.selection.eq(selection)
 const input = (label: string,type = 'text',extra = '') => `<label>${label}<input aria-label="${label}" type="${type}" ${extra}></label>`
 const select = (label: string,values: [string,string][]) => `<label>${label}<select aria-label="${label}"><option value="">混合（保持原样）</option>${values.map(([value,text]) => `<option value="${value}">${text}</option>`).join('')}</select></label>`
 const check = (label: string) => `<label class="docx-font-check"><input type="checkbox" aria-label="${label}">${label}</label>`
 const modal = createModal({ root,label:'字体设置',cardClass:'docx-settings-dialog docx-font-dialog',closeLabel:'关闭字体设置',onRequestClose:close,content:`
 <h2>字体</h2><div role="tablist" aria-label="字体设置页签">${[['font','字体'],['advanced','高级']].map(([key,label],i) => `<button type="button" role="tab" data-tab="${key}" id="${id}-${key}-tab" aria-controls="${id}-${key}-panel" aria-selected="${i === 0}" tabindex="${i ? -1 : 0}">${label}</button>`).join('')}</div>
 <form novalidate><div role="tabpanel" data-panel="font" id="${id}-font-panel" aria-labelledby="${id}-font-tab">
 ${input('西文字体','text',`list="${id}-fonts"`)}${input('中文字体','text',`list="${id}-fonts"`)}${select('字体样式',[['regular','常规'],['italic','斜体'],['bold','粗体'],['boldItalic','粗斜体']])}${input('字号（pt）','number','min="1" max="1638" step="0.5"')}${input('字体颜色','text','placeholder="#RRGGBB"')}${['下划线','删除线','上标','下标','双删除线','小型大写字母','全部大写字母','隐藏文字'].map(check).join('')}
 </div><div role="tabpanel" data-panel="advanced" id="${id}-advanced-panel" aria-labelledby="${id}-advanced-tab" hidden>
 ${input('字符缩放（%）','number','min="1" max="600" step="1"')}${select('字符间距',[['normal','标准'],['expanded','加宽'],['condensed','紧缩']])}${input('字符间距值（pt）','number','min="0" max="1584" step="0.05"')}${select('字符位置',[['normal','标准'],['raised','提升'],['lowered','降低']])}${input('字符位置值（pt）','number','min="0" max="1584" step="0.5"')}${check('启用字距调整')}${input('字距调整阈值（pt）','number','min="0.5" max="1638" step="0.5"')}
 </div><datalist id="${id}-fonts"></datalist><div class="docx-font-preview" aria-label="字体预览"><span>AaBbCc 中文字体预览</span></div><p>未修改的字段保持各文字原样；清空字体恢复继承。字体须在本机安装。</p><p role="alert" aria-label="字体设置错误" tabindex="0" hidden></p><button type="button" data-font-cancel class="${buttonClasses('secondary')}">取消</button><button type="submit" class="${buttonClasses('primary')}">确定</button></form>` })
 const field = (label: string) => modal.card.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!
 const runs: { attrs: Record<string,unknown>; marks: readonly { type:{name:string} }[] }[] = []
 if (selection.empty) { const marks = editor.state.storedMarks ?? selection.$from.marks(); runs.push({attrs:marks.find(mark => mark.type.name === 'docTextStyle')?.attrs ?? {},marks}) }
 else doc.nodesBetween(selection.from,selection.to,node => { if (node.isText) runs.push({attrs:node.marks.find(mark => mark.type.name === 'docTextStyle')?.attrs ?? {},marks:node.marks}) })
 const common = (read:(run:typeof runs[number]) => unknown) => { const values = runs.map(read); return values.every(value => value === values[0]) ? values[0] : undefined }
 const set = (label:string,value:unknown) => { const f = field(label); if (f.type === 'checkbox') { const c = f as HTMLInputElement; c.checked = value === true; c.indeterminate = value === undefined } else f.value = value == null ? '' : String(value) }
 set('西文字体',common(r => r.attrs.fontAscii ?? '')); set('中文字体',common(r => r.attrs.eastAsiaFont ?? (r.attrs.eaSlotEmpty ? '' : r.attrs.font ?? '')))
 set('字体样式',common(r => { const has = (key:string) => r.marks.some(mark => mark.type.name === key); return has('bold') ? has('italic') ? 'boldItalic' : 'bold' : has('italic') ? 'italic' : 'regular' }))
 set('字号（pt）',common(r => Number(r.attrs.sizeHalfPoints ?? 22) / 2)); set('字体颜色',common(r => r.attrs.color ?? '000000'))
 for (const [label,key] of [['下划线','underline'],['删除线','strike']]) set(label!,common(r => r.marks.some(mark => mark.type.name === key)))
 for (const [label,key,value] of [['上标','vertAlign','superscript'],['下标','vertAlign','subscript'],['小型大写字母','caps','small'],['全部大写字母','caps','all']]) set(label!,common(r => r.attrs[key!] === value))
 set('双删除线',common(r => r.attrs.dstrike === true)); set('隐藏文字',common(r => r.attrs.vanishOwn ?? r.attrs.vanish ?? false))
 const advanced = (r:typeof runs[number]) => charSpacingFromAttrs(r.attrs,Number(r.attrs.sizeHalfPoints ?? 22) / 2)
 for (const [label,key] of [['字符缩放（%）','scalePct'],['字符间距','spacing'],['字符间距值（pt）','spacingPt'],['字符位置','position'],['字符位置值（pt）','positionPt'],['启用字距调整','kern'],['字距调整阈值（pt）','kernPt']] as const) set(label,common(r => advanced(r)[key]))
 const touched = new Set<string>(), checked = (label:string) => (field(label) as HTMLInputElement).checked
 const preview = () => {
  const el = modal.card.querySelector<HTMLElement>('.docx-font-preview span')!, size = Number(field('字号（pt）').value) || 12
  el.style.fontFamily = cssFontFamily(field('中文字体').value || field('西文字体').value || 'Calibri'); el.style.fontSize = `${Math.min(size,36)}pt`
  el.style.fontWeight = field('字体样式').value.includes('bold') ? 'bold' : 'normal'; el.style.fontStyle = ['italic','boldItalic'].includes(field('字体样式').value) ? 'italic' : 'normal'
  const color = field('字体颜色').value.replace(/^#/,''); el.style.color = /^[\da-f]{6}$/i.test(color) ? `#${color}` : ''
  el.style.fontVariantCaps = checked('小型大写字母') ? 'small-caps' : 'normal'; el.style.textTransform = checked('全部大写字母') ? 'uppercase' : 'none'
  el.style.textDecorationLine = [checked('下划线') ? 'underline' : '',checked('删除线') || checked('双删除线') ? 'line-through' : ''].join(' '); el.style.textDecorationStyle = checked('双删除线') ? 'double' : 'solid'; el.style.opacity = checked('隐藏文字') ? '.45' : '1'
  const spacing = Number(field('字符间距值（pt）').value) || 0, scale = Number(field('字符缩放（%）').value) || 100
  el.style.letterSpacing = `${(field('字符间距').value === 'condensed' ? -spacing : field('字符间距').value === 'expanded' ? spacing : 0) + (scale === 100 ? 0 : charScaleEm(el.textContent ?? '',scale) * size)}pt`
  const position = Number(field('字符位置值（pt）').value) || 0
  el.style.position = 'relative'; el.style.top = `${field('字符位置').value === 'raised' ? -position : field('字符位置').value === 'lowered' ? position : 0}pt`
  el.style.verticalAlign = checked('上标') ? 'super' : checked('下标') ? 'sub' : 'baseline'
  el.style.fontKerning = checked('启用字距调整') ? 'normal' : 'none'
 }
 for (const control of modal.card.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input,select')) { const label = control.getAttribute('aria-label')!; const changed = () => { touched.add(label); if (control.type === 'checkbox') (control as HTMLInputElement).indeterminate = false; preview() }; control.addEventListener('input',changed); control.addEventListener('change',changed) }
 for (const pair of [['上标','下标'],['小型大写字母','全部大写字母']]) for (const label of pair) field(label).addEventListener('change',() => { if (checked(label)) { const other = pair.find(v => v !== label)!; (field(other) as HTMLInputElement).checked = false; touched.add(other) }; preview() })
 const syncAdvanced = () => {
  field('字符间距值（pt）').disabled = !['expanded','condensed'].includes(field('字符间距').value)
  field('字符位置值（pt）').disabled = !['raised','lowered'].includes(field('字符位置').value)
  field('字距调整阈值（pt）').disabled = !checked('启用字距调整')
 }
 for (const [label,amount,fallback] of [['字符间距','字符间距值（pt）','1'],['字符位置','字符位置值（pt）','3'],['启用字距调整','字距调整阈值（pt）',field('字号（pt）').value || '11']]) field(label!).addEventListener('change',() => { if (!field(amount!).value) field(amount!).value = fallback!; syncAdvanced(); preview() })
 syncAdvanced()
 const tabs = [...modal.card.querySelectorAll<HTMLButtonElement>('[data-tab]')]
 const selectTab = (tab:HTMLButtonElement) => { for (const item of tabs) { item.setAttribute('aria-selected',String(item === tab)); item.tabIndex = item === tab ? 0 : -1 }; for (const panel of modal.card.querySelectorAll<HTMLElement>('[data-panel]')) panel.hidden = panel.dataset.panel !== tab.dataset.tab }
 for (const tab of tabs) { tab.addEventListener('click',() => selectTab(tab)); tab.addEventListener('keydown',event => { if (event.isComposing || event.keyCode === 229 || event.defaultPrevented || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; event.preventDefault(); const at = tabs.indexOf(tab),next = event.key === 'Home' ? tabs[0]! : event.key === 'End' ? tabs.at(-1)! : tabs[(at + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]!; selectTab(next); next.focus() }) }
 const list = modal.card.querySelector<HTMLDataListElement>('datalist')!
 const addFamilies = (names:Iterable<string>) => { for (const family of names) if (family && ![...list.options].some(option => option.value === family)) { const option = document.createElement('option'); option.value = family; list.append(option) } }
 addFamilies(fontFamiliesFor('zh')); addFamilies(runs.flatMap(r => [String(r.attrs.fontAscii ?? ''),String(r.attrs.eastAsiaFont ?? r.attrs.font ?? '')]))
 let fontQueryStarted = false
 for (const label of ['西文字体','中文字体']) field(label).addEventListener('click',() => { if (fontQueryStarted) return; fontQueryStarted = true; const query = (window as typeof window & {queryLocalFonts?:() => Promise<{family:string}[]>}).queryLocalFonts; if (query) void query.call(window).then(fonts => { if (valid()) addFamilies(fonts.map(font => font.family)) }).catch(() => {}) })
 modal.card.querySelector('[data-font-cancel]')!.addEventListener('click',close)
 modal.card.querySelector('form')!.addEventListener('submit',event => {
  event.preventDefault()
  try {
   if (!valid() || !trusted(editor,anchors)) throw new Error('文档或选区已变化，请重新打开字体设置')
   if (!touched.size) { close(); editor.view.focus(); return }
   const number = (label:string,min:number,max:number,unit:number) => { const value = Number(field(label).value),scaled = value * unit; if (!field(label).value.trim() || !Number.isFinite(value) || value < min || value > max || Math.abs(scaled - Math.round(scaled)) > 1e-7) throw new Error(`${label}数值或精度无效`); return value }
   const keys = new Set<string>()
   for (const [label,key] of [['西文字体','fontLatin'],['中文字体','fontEastAsia'],['字号（pt）','size'],['字体颜色','color']]) if (touched.has(label!)) keys.add(key!)
   if (touched.has('上标') || touched.has('下标')) keys.add('vertAlign'); if (touched.has('字符缩放（%）')) keys.add('scale')
   if (touched.has('字符间距') || touched.has('字符间距值（pt）')) keys.add('spacing'); if (touched.has('字符位置') || touched.has('字符位置值（pt）')) keys.add('position'); if (touched.has('启用字距调整') || touched.has('字距调整阈值（pt）')) keys.add('kern')
   const size = keys.has('size') ? number('字号（pt）',1,1638,2) : Number(field('字号（pt）').value) || 11,color = field('字体颜色').value.replace(/^#/,'')
   if (keys.has('color') && !/^[\da-f]{6}$/i.test(color)) throw new Error('字体颜色须为六位十六进制颜色')
   const attrs = fontTabAttrs({fontLatin:field('西文字体').value.trim(),fontEastAsia:field('中文字体').value.trim(),sizePt:size,colorHex:color,vertAlign:checked('上标') ? 'superscript' : checked('下标') ? 'subscript' : 'baseline'},keys)
   const adv = {scalePct:keys.has('scale') ? number('字符缩放（%）',1,600,1) : 100,spacing:(field('字符间距').value || 'normal') as 'normal'|'expanded'|'condensed',spacingPt:keys.has('spacing') && field('字符间距').value !== 'normal' ? number('字符间距值（pt）',0,1584,20) : 0,position:(field('字符位置').value || 'normal') as 'normal'|'raised'|'lowered',positionPt:keys.has('position') && field('字符位置').value !== 'normal' ? number('字符位置值（pt）',0,1584,2) : 0,kern:checked('启用字距调整'),kernPt:keys.has('kern') && checked('启用字距调整') ? number('字距调整阈值（pt）',.5,1638,2) : size}
   if (touched.has('双删除线')) attrs.dstrike = checked('双删除线'); if (touched.has('小型大写字母') || touched.has('全部大写字母')) attrs.caps = checked('小型大写字母') ? 'small' : checked('全部大写字母') ? 'all' : 'none'; if (touched.has('隐藏文字')) attrs.vanishOwn = attrs.vanish = checked('隐藏文字')
   docxFontProperties(attrs)
   const tr = closeHistory(editor.state.tr),ranges = selectionRanges(selection)
   const apply = (from:number,to:number,prior:Record<string,unknown>) => {
    const values = {...attrs,...charSpacingAttrs(adv,keys,prior,keys.has('size') ? size * 2 : Number(prior.sizeHalfPoints) || 22),nativeFontDialog:true}
    docxFontProperties(values); setTextStyleWithScale(tr,[{from,to}],values)
    for (const [name,label,want] of [['bold','字体样式',['bold','boldItalic'].includes(field('字体样式').value)],['italic','字体样式',['italic','boldItalic'].includes(field('字体样式').value)],['underline','下划线',checked('下划线')],['strike','删除线',checked('删除线')]] as const) if (touched.has(label)) { const type = editor.schema.marks[name]!; if (from === to) { if (want) tr.addStoredMark(type.create()); else tr.removeStoredMark(type) } else if (want) tr.addMark(from,to,type.create()); else tr.removeMark(from,to,type) }
   }
   if (selection.empty) apply(selection.from,selection.to,runs[0]!.attrs)
   else for (const range of ranges) doc.nodesBetween(range.from,range.to,(node,pos) => { if (node.isText) apply(Math.max(pos,range.from),Math.min(pos + node.nodeSize,range.to),node.marks.find(mark => mark.type.name === 'docTextStyle')?.attrs ?? {}) })
   if (!selection.empty) docxOperations(doc.toJSON(),tr.doc.toJSON(),anchors,undefined,editor.schema)
   editor.view.dispatch(tr); editor.view.dispatch(closeHistory(editor.state.tr)); close(); editor.view.focus()
  } catch (error) { const alert = modal.card.querySelector<HTMLElement>('[role=alert]')!; alert.hidden = false; alert.textContent = error instanceof Error ? error.message : String(error); alert.scrollIntoView?.({ block: 'nearest' }) }
 })
 preview(); modal.open(field('西文字体')); return close
}

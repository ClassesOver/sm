import {createModal} from './modal'
import {DocxStoryRevisionDialog} from './docx-story-revision-dialog'
import {validatedStoryRevisionDrafts,type DocxStoryRevisionTarget} from './docx-story-revisions'
import type {Editor} from '@tiptap/core'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {docxNativeOperationsOf,commitDocxNativeOperations} from './docx-native-history'
import type {NativeOperation} from './native-draft'
import {docxThemeModel,docxThemeOperations,withDocxTheme,effectiveDocxTheme,type DocxThemeChoice} from './docx-theme'
import {DocxThemeControls} from './docx-theme-controls'
import {docxProtectionModel,docxProtectionOperations} from './docx-protection'
import {DocxProtectionDialog} from './docx-protection-dialog'
import {createDocxInkController,type DocxInkModel} from './docx-ink-controller'
import {InkOverlay} from './docx-ink-overlay'
import type {InkTool} from './docx-ink'
import {docThemeCss,docBodyFont} from './vendor/genoffice-docs/apps/docs/src/renderer/doc-style-css'
import {scopeDocxStyleRules} from './docx-style-scope'
import './docx-ink.css'

export function docxDocumentToolModels(model:unknown){const value=model as Record<string,unknown>;return {theme:docxThemeModel(value.documentTheme),protection:docxProtectionModel(value.documentProtection),ink:value.documentInk as DocxInkModel|undefined,story:value.storyRevisions as {targets:DocxStoryRevisionTarget[];readOnly:{partPath:string;noteId?:string;reason:string}[]}|undefined}}
export function docxDocumentToolOperations(operations:NativeOperation[],models:ReturnType<typeof docxDocumentToolModels>){
 if(models.protection?.contentLocked&&operations.some(op=>op.kind!=='setDocumentProtection'))throw new Error('文档受保护，正文与其他设置保持只读；请先解除保护并保存重开')
 const result=[...docxThemeOperations(operations,models.theme),...docxProtectionOperations(operations,models.protection)]
 const inks=operations.filter(op=>op.kind==='setInk')
 if(inks.length>1||inks.length&&(!models.ink?.editable||inks[0].expectedInkSha256!==models.ink.expectedInkSha256||Object.keys(inks[0]).sort().join()!=='expectedInkSha256,inks,kind'||!Array.isArray(inks[0].inks)))throw new Error('墨迹草稿与来源不一致；原草稿已保留')
 const stories=operations.filter(op=>op.kind==='resolveStoryRevision')
 if(stories.length&&stories.length!==operations.length)throw new Error('非正文修订需要单独保存，请先保存或撤销其他修改')
 return [...result,...inks,...validatedStoryRevisionDrafts(stories,models.story?.targets??[])]
}
export function createDocxDocumentTools(options:{editor:Editor;host:HTMLElement;models:ReturnType<typeof docxDocumentToolModels>;parsed:Parameters<typeof docBodyFont>[0];reason():string|null;flush():void;onError(error:unknown):void}){
 const {editor,host,models}=options
 const themeElement=document.createElement('div'),themeRoot=createRoot(themeElement),themeStyle=document.createElement('style');host.append(themeStyle)
 const drawElement=document.createElement('div');drawElement.className='ribbon-group-items'
 const overlayHost=document.createElement('div');overlayHost.style.cssText='position:absolute;inset:0;pointer-events:none';host.querySelector('.docx-canvas')!.append(overlayHost)
 const overlayRoot=createRoot(overlayHost),dialogHost=document.createElement('div');host.append(dialogHost);const dialogRoot=createRoot(dialogHost)
 let storyModal:ReturnType<typeof createModal>|undefined,storyRoot:ReturnType<typeof createRoot>|undefined
 let disposed=false,tool:InkTool='select',color='000000',width=2,dialogOpen=false
 const canEdit=()=>!options.reason()&&!models.protection?.contentLocked&&!docxNativeOperationsOf(editor.getJSON()).some(op=>op.kind==='setDocumentProtection')
 const commit=(operations:NativeOperation[])=>{const reason=options.reason();if(reason)throw new Error(reason);docxDocumentToolOperations(operations,models);if(!commitDocxNativeOperations(editor,operations,()=>!options.reason()))throw new Error('文档设置未能进入草稿，请重试')}
 const ink=createDocxInkController({editor:()=>editor,model:()=>models.ink,operations:()=>docxNativeOperationsOf(editor.getJSON()),canEdit,commit:operation=>{try{commit([...docxNativeOperationsOf(editor.getJSON()).filter(op=>op.kind!=='setInk'),operation as unknown as NativeOperation]);return true}catch(error){options.onError(error);return false}}})
 const buttons=(['select','pen','highlighter','pencil','eraser'] as const).map((value,index)=>{const button=document.createElement('button');button.type='button';button.textContent=['选择','笔','荧光笔','铅笔','橡皮擦'][index];button.dataset.action='ink-'+value;button.onmousedown=event=>event.preventDefault();button.onclick=()=>{tool=value;refresh()};return button})
 const inkColor=document.createElement('input');inkColor.type='color';inkColor.value='#000000';inkColor.setAttribute('aria-label','墨迹颜色');inkColor.oninput=()=>{color=inkColor.value.slice(1).toUpperCase();refresh()}
 const inkWidth=document.createElement('input');inkWidth.type='number';inkWidth.min='0.5';inkWidth.max='100';inkWidth.step='0.5';inkWidth.value='2';inkWidth.setAttribute('aria-label','墨迹宽度');inkWidth.onchange=()=>{const next=Number(inkWidth.value);if(Number.isFinite(next)&&next>=0.5&&next<=100){width=next;refresh()}}
 const clear=document.createElement('button');clear.type='button';clear.textContent='全部清除';clear.dataset.action='ink-clear';clear.onclick=()=>{try{ink.clear()}catch(error){options.onError(error)}};drawElement.append(...buttons,inkColor,inkWidth,clear)
 function closeProtection(){dialogOpen=false;flushSync(()=>dialogRoot.render(null))}
 function openProtection(){try{const reason=options.reason();if(reason)throw new Error(reason);options.flush();if(!models.protection)throw new Error('来源未提供保护能力');dialogOpen=true;renderProtection()}catch(error){options.onError(error)}}
 function renderProtection(){if(!dialogOpen||!models.protection)return;flushSync(()=>dialogRoot.render(<DocxProtectionDialog model={models.protection!} operations={docxNativeOperationsOf(editor.getJSON())} onApply={operations=>commit(operations)} onClose={closeProtection}/>))}
 function closeStory(){storyRoot?.unmount();storyRoot=undefined;storyModal?.remove();storyModal=undefined}
 function openStory(){try{const reason=options.reason();if(reason)throw new Error(reason);options.flush();closeStory();const operations=docxNativeOperationsOf(editor.getJSON());if(operations.some(op=>op.kind!=='resolveStoryRevision'))throw new Error('非正文修订需要单独保存，请先保存其他修改');const target=models.story??{targets:[],readOnly:[]};const drafts=validatedStoryRevisionDrafts(operations,target.targets);storyModal=createModal({root:host,label:'非正文修订审阅',variant:'wide',closeLabel:'关闭非正文修订',onRequestClose:closeStory,content:'<div data-story-content></div>'});storyRoot=createRoot(storyModal.card.querySelector('[data-story-content]')!);flushSync(()=>storyRoot!.render(<DocxStoryRevisionDialog embedded targets={target.targets} drafts={drafts} readOnly={target.readOnly} onApply={values=>{try{commit(values);closeStory()}catch(error){options.onError(error)}}} onClose={closeStory}/>));storyModal.open()}catch(error){options.onError(error)}}
 function refresh(){
  if(disposed||editor.isDestroyed)return
  const operations=docxNativeOperationsOf(editor.getJSON()),choice=operations.find(op=>op.kind==='setDocumentTheme') as DocxThemeChoice|undefined
  const editable=canEdit(),liveTheme=models.theme?{...models.theme,editable:editable&&models.theme.editable}:null
  flushSync(()=>themeRoot.render(<DocxThemeControls model={liveTheme} value={choice} onChange={value=>{try{commit(withDocxTheme(docxNativeOperationsOf(editor.getJSON()),models.theme,value))}catch(error){options.onError(error)}}}/>))
  if(models.theme){const value=effectiveDocxTheme(operations,models.theme);themeStyle.textContent=docThemeCss(value.fonts,value.colors,!!docBodyFont(options.parsed));if(themeStyle.sheet)scopeDocxStyleRules(themeStyle.sheet)}
  const inkEditable=editable&&!!models.ink?.editable
  if(!inkEditable)tool='select'
  for(const [index,button] of buttons.entries()){button.disabled=!inkEditable;button.setAttribute('aria-pressed',String(['select','pen','highlighter','pencil','eraser'][index]===tool))}
  inkColor.disabled=inkWidth.disabled=clear.disabled=!inkEditable;clear.disabled||=ink.annotations().length===0
  // The source overlay uses paragraph data-idx anchors inside its positioned parent.
  const zoom=Number(host.dataset.docxZoom??100)
  overlayHost.style.zoom=String(zoom/100)
  flushSync(()=>overlayRoot.render(<InkOverlay anchorRoot={host.querySelector<HTMLElement>('.docx-canvas')!} tool={tool} color={tool==='highlighter'&&color==='000000'?'FFFF00':color} width={tool==='highlighter'?Math.max(width,6):width} zoom={zoom} annotations={ink.annotations()} onAdd={value=>{try{ink.add(value)}catch(error){options.onError(error)}}} onRemove={ids=>{try{ink.remove(ids)}catch(error){options.onError(error)}}}/>))
 }
 const observer=new MutationObserver(refresh);observer.observe(host,{attributes:true,attributeFilter:['data-docx-zoom']})
 editor.on('transaction',refresh);refresh()
 return {themeElement,drawElement,openProtection,openStory,refresh,dispose(){closeStory();disposed=true;observer.disconnect();editor.off('transaction',refresh);themeRoot.unmount();overlayRoot.unmount();dialogRoot.unmount();themeElement.remove();drawElement.remove();themeStyle.remove();overlayHost.remove();dialogHost.remove()}}
}

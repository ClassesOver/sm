import {afterEach,expect,it} from 'vitest'
import {Editor,Extension} from '@tiptap/core'
import {UndoRedo} from '@tiptap/extensions'
import {DocDocument,DocParagraph,DocText} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {DelMark,InsMark,RprChangeMark,RevisionOriginalExtension,revisionDisplayState} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/marks'
import {ParaMarkDelExtension} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/decoration-extensions'
import {hfValueInView} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-dom'
import {createDocxReviewView,NativeDocxReviewChangedLines,revisionAuthorsOf,revisionFilterCss,reviewRunsInView,type DocxReviewViewState} from './docx-review-view'

afterEach(()=>{document.body.replaceChildren();revisionDisplayState.mode='all';revisionDisplayState.balloonsActive=false})

it('renders all four views without changing document or history and restores source mode on dispose',()=>{
 const host=document.body.appendChild(document.createElement('div')),mount=host.appendChild(document.createElement('div')),previewRoot=host.appendChild(document.createElement('div'))
 previewRoot.className='docx-preview-root';previewRoot.innerHTML='<div class="doc-page"><p class="docx-review-changed-line"><span class="doc-ins" data-ins-author="Alice">inserted</span><span class="doc-del" data-del-author="Bob">deleted</span></p></div>'
 const Intent=Extension.create({name:'draftIntent',addGlobalAttributes:()=>[{types:['doc'],attributes:{nativeIntent:{default:null,rendered:false}}}]})
 const editor=new Editor({element:mount,extensions:[DocDocument,DocParagraph,DocText,InsMark,DelMark,RprChangeMark,ParaMarkDelExtension,RevisionOriginalExtension,NativeDocxReviewChangedLines,Intent,UndoRedo],content:{type:'doc',attrs:{nativeIntent:[{kind:'preserved'}]},content:[{type:'docParagraph',content:[
  {type:'text',text:'inserted',marks:[{type:'ins',attrs:{author:'Alice'}}]},
  {type:'text',text:'deleted',marks:[{type:'del',attrs:{author:'Bob'}}]},
  {type:'text',text:'formatted',marks:[{type:'rprChange',attrs:{author:'Alice',old:{bold:true}}}]},
 ]}]}})
 const original=editor.getJSON(),state:DocxReviewViewState={mode:'all',insDel:true,format:true,hiddenAuthors:[]}
 const view=createDocxReviewView({host,editor,previewRoot,initial:state})
 editor.commands.insertContentAt(editor.state.doc.content.size-1,'tail')
 const afterEdit=editor.getJSON()
 view.setMode('original')
 const originalDecoration=editor.view.dom.querySelector<HTMLElement>('[style*="font-weight: 600"], [style*="font-weight:600"]')
 expect(originalDecoration).not.toBeNull()
 expect(editor.view.dom.classList.contains('rev-display-original')).toBe(true)
 expect(previewRoot.classList.contains('rev-display-original')).toBe(true)
 expect(hfValueInView({text:'',paras:[{runs:[{text:'insert',ins:{author:'Alice'}},{text:'delete',del:{author:'Bob'}},{text:'keep'}]}]})?.paras?.[0]?.runs.map(run=>run.text)).toEqual(['delete','keep'])
 view.setMode('none');expect(editor.view.dom.classList.contains('rev-display-none')).toBe(true)
 expect(previewRoot.classList.contains('rev-display-none')).toBe(true)
 view.setMode('simple');expect(editor.view.dom.classList.contains('rev-display-simple')).toBe(true)
 expect(editor.view.dom.querySelector('.docx-review-changed-line')).not.toBeNull()
 expect(previewRoot.querySelector('.docx-review-changed-line')).not.toBeNull()
 view.setMode('all');expect(editor.view.dom.classList.contains('rev-display-all')).toBe(true)
 view.setMode('all')
 expect(editor.getJSON()).toEqual(afterEdit);expect(editor.getJSON().attrs?.nativeIntent).toEqual(original.attrs?.nativeIntent)
 expect(editor.commands.undo()).toBe(true);expect(editor.getText()).not.toContain('tail')
 view.dispose();expect(host.classList.contains('rev-display-all')).toBe(false);expect(revisionDisplayState.mode).toBe('all')
 editor.destroy()
})

it('keeps display controls usable in read-only mode and restores the pre-existing global source mode',()=>{
 const make=()=>{const host=document.body.appendChild(document.createElement('div')),mount=host.appendChild(document.createElement('div')),editor=new Editor({element:mount,extensions:[DocDocument,DocParagraph,DocText],content:{type:'doc',content:[{type:'docParagraph'}]}});return{host,editor,view:createDocxReviewView({host,editor,initial:{mode:'all',insDel:true,format:true,hiddenAuthors:[]}})}}
 const view=make();view.editor.setEditable(false);view.view.setMode('original')
 expect(view.editor.view.dom.classList.contains('rev-display-original')).toBe(true)
 expect(revisionDisplayState.mode).toBe('original')
 view.view.dispose();expect(revisionDisplayState.mode).toBe('all')
 view.editor.destroy()
})

it('collects every rendered revision author and emits escaped CSS for hidden authors',()=>{
 const editor=new Editor({extensions:[DocDocument,DocParagraph,DocText,InsMark,DelMark,RprChangeMark],content:{type:'doc',content:[{type:'docParagraph',attrs:{pPrChange:JSON.stringify({author:'Carol'})},content:[
  {type:'text',text:'i',marks:[{type:'ins',attrs:{author:'Alice'}}]},
  {type:'text',text:'d',marks:[{type:'del',attrs:{author:'Bob'}}]},
  {type:'text',text:'f',marks:[{type:'rprChange',attrs:{author:'Dana'}}]},
 ]}]}})
 expect(revisionAuthorsOf(editor.state.doc)).toEqual(['Carol','Alice','Bob','Dana'])
 expect(revisionFilterCss(['a"]\nbody{display:none}'],['a"]\nbody{display:none}'])).toBe('')
 const css=revisionFilterCss(['author'],['author'])
 expect(css).toContain('.has-ppr-change[data-ppr-change-author=')
 expect(css).not.toContain('.has-ppr-change[data-ppr-change-author="author"]{display:none}')
 expect(css).toContain('.has-move-from[data-rev-author=')
 editor.destroy()
})

it('projects HF runs through the same display mode and Show Markup filters',()=>{
 const runs=[{text:'insert',ins:{author:'Alice'}},{text:'delete',del:{author:'Bob'}},{text:'plain'}]
 const state:DocxReviewViewState={mode:'original',insDel:true,format:true,hiddenAuthors:[]}
 expect(reviewRunsInView(runs,state).map(run=>run.text)).toEqual(['delete','plain'])
 expect(reviewRunsInView(runs,{...state,mode:'all',hiddenAuthors:['Bob']}).map(run=>run.text)).toEqual(['insert','plain'])
 expect(reviewRunsInView(runs,{...state,mode:'all',insDel:false}).map(run=>run.text)).toEqual(['insert','plain'])
 const hiddenAuthorRuns=reviewRunsInView(runs,{...state,mode:'all',hiddenAuthors:['Alice']})
 expect(hiddenAuthorRuns.map(run=>run.text)).toEqual(['insert','delete','plain'])
 expect(hiddenAuthorRuns[0]).not.toHaveProperty('ins')
})

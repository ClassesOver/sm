import {Extension} from '@tiptap/core'
import type {Node as PmNode} from '@tiptap/pm/model'
import {PluginKey} from '@tiptap/pm/state'
import {Decoration} from '@tiptap/pm/view'
import {blockDecorationPlugin} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/local-edit'
import {collectRevisions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/revisions'
import {revisionAuthors,revisionAuthorCss,filterRevisions,type RevisionFilter} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/revision-filters'
import type {StoryRevision} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/story-revisions'
import type {Run} from '@genoffice/docx-engine'
import {runHiddenIn} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/revision-view'
import {revisionDisplayState} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/marks'
import type {RevisionDisplayMode} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/revision-view'

export type DocxReviewViewState={mode:RevisionDisplayMode;insDel:boolean;format:boolean;hiddenAuthors:string[]}
type Instance={host:HTMLElement;editor:import('@tiptap/core').Editor;state:DocxReviewViewState;targets:HTMLElement[];style:HTMLStyleElement;disposed:boolean;previousMode:RevisionDisplayMode;previousBalloonsActive:boolean;appMarker:HTMLElement;additionalAuthors:string[]}
const stateByEditor=new WeakMap<object,()=>DocxReviewViewState>()
const key=new PluginKey('nativeDocxReviewChangedLines')
const modes:RevisionDisplayMode[]=['all','simple','none','original']
const copy=(state:DocxReviewViewState):DocxReviewViewState=>({...state,hiddenAuthors:[...state.hiddenAuthors]})
const revisionFilter=(state:DocxReviewViewState):RevisionFilter=>({insDel:state.insDel,format:state.format,hiddenAuthors:state.hiddenAuthors})

export function revisionAuthorsOf(doc:PmNode,other:readonly StoryRevision[]=[]){return revisionAuthors([...collectRevisions(doc),...other])}
export function reviewRunsInView(runs:readonly Run[],state:DocxReviewViewState):Run[]{
 const hidden=new Set(state.hiddenAuthors)
 return runs.flatMap(run=>{
  const authorHidden=!!(run.ins&&hidden.has(run.ins.author)||run.del&&hidden.has(run.del.author))
  if(runHiddenIn(state.mode,run)||(run.del&&(!state.insDel||authorHidden)))return []
  if(run.ins&&(!state.insDel||authorHidden)){const {ins:_ins,...plain}=run;return [plain]}
  return [run]
 })
}

const cssString=(value:string)=>`"${value.replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/[\n\r\f]/g,char=>`\\${char.charCodeAt(0).toString(16)} `)}"`
export function revisionFilterCss(authors:string[],hiddenAuthors:string[]){
 const safe=(value:string)=>!/[\u0000-\u001f\u007f]/.test(value)
 return revisionAuthorCss(authors.filter(safe),hiddenAuthors.filter(safe))
}

const allRevisionAuthors=(editor:import('@tiptap/core').Editor)=>revisionAuthorsOf(editor.state.doc)
function changedLineDecorations(doc:PmNode,state:DocxReviewViewState){
 const shown=filterRevisions(collectRevisions(doc),revisionFilter(state)),decos=[] as ReturnType<typeof Decoration.node>[]
 doc.descendants((node,pos)=>{
  if(!node.isTextblock)return
  const end=pos+node.nodeSize
  if(shown.some(revision=>revision.from<end&&revision.to>pos))decos.push(Decoration.node(pos,end,{class:'docx-review-changed-line'}))
 })
 return decos
}

export const NativeDocxReviewChangedLines=Extension.create({
 name:'nativeDocxReviewChangedLines',
 addProseMirrorPlugins(){
  const editor=this.editor
  return[blockDecorationPlugin({key,build:doc=>changedLineDecorations(doc,stateByEditor.get(editor)?.()??{mode:'all',insDel:true,format:true,hiddenAuthors:[]}),needsRecompute:node=>node.isTextblock||!!node.attrs?.pPrChange,signature:()=>JSON.stringify(stateByEditor.get(editor)?.()??null)})]
 },
})

function apply(instance:Instance){
 const {state,host,editor,targets,style}=instance
 for(const target of targets){
  for(const mode of modes)target.classList.toggle(`rev-display-${mode}`,mode===state.mode)
  target.classList.toggle('rev-hide-insdel',!state.insDel)
  target.classList.toggle('rev-hide-format',!state.format)
 }
 for(const mode of modes)instance.appMarker.classList.toggle(`rev-display-${mode}`,mode===state.mode)
 instance.appMarker.dataset.revHiddenAuthors=JSON.stringify(state.hiddenAuthors)
 instance.appMarker.dataset.revInsDel=String(state.insDel)
 const bodyAuthors=allRevisionAuthors(editor)
 const authors=[...bodyAuthors,...instance.additionalAuthors.filter(author=>!bodyAuthors.includes(author))]
 style.textContent=`@scope (.docx-native){${revisionFilterCss(authors,state.hiddenAuthors)}}`
 if(!editor.isDestroyed)editor.view.dispatch(editor.state.tr.setMeta('addToHistory',false))
}

export function createDocxReviewView(options:{host:HTMLElement;editor:import('@tiptap/core').Editor;previewRoot?:HTMLElement|null;initial:DocxReviewViewState;onChange?:()=>void}){
 const {host,editor}=options,canvas=editor.view.dom,targets=[canvas,...(options.previewRoot?[options.previewRoot]:[])],style=document.createElement('style')
 style.dataset.docxReviewView='';host.append(style)
 const appMarker=document.createElement('div'),previousMode=revisionDisplayState.mode,previousBalloonsActive=revisionDisplayState.balloonsActive
 appMarker.className='app';appMarker.dataset.nativeDocxReviewState='';appMarker.setAttribute('aria-hidden','true');appMarker.style.display='none';document.body.prepend(appMarker)
 const instance:Instance={host,editor,state:copy(options.initial),targets,style,disposed:false,previousMode,previousBalloonsActive,appMarker,additionalAuthors:[]}
 stateByEditor.set(editor,()=>instance.state)
 revisionDisplayState.mode=instance.state.mode
 revisionDisplayState.balloonsActive=false
 apply(instance)
 const update=(next:Partial<DocxReviewViewState>)=>{
  if(instance.disposed)return
  if(next.mode&&modes.includes(next.mode)){
   revisionDisplayState.mode=next.mode
  }
  instance.state={...instance.state,...next,hiddenAuthors:next.hiddenAuthors?[...next.hiddenAuthors]:instance.state.hiddenAuthors}
  apply(instance)
  options.onChange?.()
 }
 return{
  get state(){return copy(instance.state)},
  setMode(mode:RevisionDisplayMode){update({mode})},
  setFilter(filter:RevisionFilter){update({insDel:filter.insDel,format:filter.format,hiddenAuthors:[...filter.hiddenAuthors]})},
  setAuthors(authors:string[]){instance.additionalAuthors=[...authors];apply(instance)},
  refresh(){apply(instance)},
  dispose(){
   if(instance.disposed)return
   instance.disposed=true;stateByEditor.delete(editor);style.remove()
   appMarker.remove()
   for(const target of targets)for(const mode of modes)target.classList.remove(`rev-display-${mode}`)
   for(const target of targets){target.classList.remove('rev-hide-insdel','rev-hide-format')}
   revisionDisplayState.mode=previousMode;revisionDisplayState.balloonsActive=previousBalloonsActive
   if(!editor.isDestroyed)editor.view.dispatch(editor.state.tr.setMeta('addToHistory',false))
  },
 }
}

import './pdf-outline-edit.css'
import type {NativeDraft,NativeOperation} from './native-draft'

export interface PdfBookmarkNode {title:string;pageId:string;top:number|null;children:PdfBookmarkNode[]}
export interface PdfOutlineModel {sourceSha256:string;pages:{pageId:string;index:number}[];outline?:PdfBookmarkNode[];outlineEditable?:boolean;outlineReason?:string|null}

export function validatePdfOutlineOperations(pages:{pageId:string}[],operations:NativeOperation[]):void {
 const edits=operations.filter(op=>op.kind==='setOutline')
 if(edits.length>1)throw Error('书签树替换不能重复')
 const ids=new Set([...pages.map(page=>page.pageId),...operations.filter(op=>op.kind==='insertBlankPage').map(op=>String(op.pageId))])
 let count=0
 const validate=(tree:unknown,depth:number):void=>{
  if(!Array.isArray(tree)||depth>32)throw Error('书签层级无效')
  for(const node of tree){
   if(++count>2000||!node||typeof node!=='object'||Array.isArray(node)||Object.keys(node).some(key=>!['title','pageId','top','children'].includes(key))||typeof node.title!=='string'||!node.title.trim()||node.title.length>4000||!ids.has(node.pageId)||node.top!==null&&(typeof node.top!=='number'||!Number.isFinite(node.top)))throw Error('书签标题、页面身份或树无效')
   validate(node.children,depth+1)
  }
 }
 for(const op of edits){
  if(Object.keys(op).some(key=>!['kind','sourceSha256','tree'].includes(key))||typeof op.sourceSha256!=='string'||!/^[a-f0-9]{64}$/.test(op.sourceSha256))throw Error('书签来源身份无效')
  validate(op.tree,0)
 }
}
export function pdfOutlineTree(model:PdfOutlineModel,operations:NativeOperation[]):PdfBookmarkNode[] {
 validatePdfOutlineOperations(model.pages,operations)
 const edit=operations.find(op=>op.kind==='setOutline')
 if(edit&&edit.sourceSha256!==model.sourceSha256)throw Error('书签来源已变化，原草稿已保留')
 return structuredClone(edit?edit.tree as PdfBookmarkNode[]:model.outline??[])
}
export function stagePdfOutline(model:PdfOutlineModel,operations:NativeOperation[],tree:PdfBookmarkNode[]):NativeOperation[] {
 if(model.outlineEditable!==true)throw Error(model.outlineReason||'当前来源书签只读')
 const next=[...operations.filter(op=>op.kind!=='setOutline'),{kind:'setOutline',sourceSha256:model.sourceSha256,tree:structuredClone(tree)}]
 if(next.length>500)throw Error('超过 500 条修改，请先保存')
 validatePdfOutlineOperations(model.pages,next)
 return next
}
export function mutatePdfOutline(tree:PdfBookmarkNode[],path:string,title:string|null):PdfBookmarkNode[] {
 if(!/^\d+(\.\d+)*$/.test(path)||title!==null&&!title.trim())throw Error('书签路径或标题无效')
 const copy=structuredClone(tree),parts=path.split('.').map(Number)
 let siblings=copy
 for(const index of parts.slice(0,-1)){if(!siblings[index])throw Error('书签已变化，请重新选择');siblings=siblings[index]!.children}
 const index=parts.at(-1)!
 if(!siblings[index])throw Error('书签已变化，请重新选择')
 if(title===null)siblings.splice(index,1)
 else siblings[index]!.title=title.trim()
 return copy
}

/** 固定源目录编辑：当前页新增、行内重命名和删子树均进入原生草稿历史。 */
export function mountPdfOutlineEditor(options:{panel:HTMLElement;header:HTMLElement;model:PdfOutlineModel;draft:NativeDraft;pages:()=>{pageId:string}[];currentPage:()=>string;unavailable:()=>string|null;changed:()=>void;navigate:(pageId:string)=>void;error:(error:unknown)=>void}) {
 const {panel,header,model,draft}=options,doc=panel.ownerDocument
 const toggle=doc.createElement('button');toggle.type='button';toggle.className='pdf-tool';toggle.dataset.pdfOutlineEditable='true';toggle.dataset.sourceCommandId='genoffice.pdf.view.outline.edit'
 header.insertBefore(toggle,header.lastElementChild)
 let editing=false,disposed=false
 const reason=()=>options.unavailable()??(model.outlineEditable===true?null:model.outlineReason||'当前来源书签只读')
 const action=(label:string,run:()=>void)=>{
  const button=doc.createElement('button');button.type='button';button.className='pdf-tool';button.textContent=label;button.dataset.pdfOutlineEditable='true'
  button.addEventListener('click',()=>{if(disposed||reason())return;try{run()}catch(error){options.error(error)}})
  return button
 }
 const commit=(tree:PdfBookmarkNode[])=>{if(disposed||reason())return;draft.setOperations(stagePdfOutline(model,draft.operations,tree));options.changed()}
 toggle.addEventListener('click',()=>{if(disposed||reason())return;editing=!editing;render();if(!editing&&!draft.operations.some(op=>op.kind==='setOutline'))options.changed()})
 function update(){
  toggle.textContent=editing?'✓':'✎';toggle.setAttribute('aria-pressed',String(editing));toggle.setAttribute('aria-label',editing?'完成书签编辑':'编辑书签')
  const unavailable=reason()
  for(const control of panel.querySelectorAll<HTMLButtonElement|HTMLInputElement>('[data-pdf-outline-editable]')){control.disabled=unavailable!==null;control.title=unavailable??control.getAttribute('aria-label')??control.textContent??''}
 }
 function render():boolean {
  for(const node of panel.querySelectorAll('[data-outline-editor-content]'))node.remove()
  const pending=draft.operations.some(op=>op.kind==='setOutline')
  update()
  if(!editing&&!pending)return false
  for(const node of panel.querySelectorAll('.pdf-outline-link,:scope > p'))node.remove()
  const body=doc.createElement('div');body.dataset.outlineEditorContent='true';body.setAttribute('role','tree');body.setAttribute('aria-label','书签编辑树');panel.append(body)
  if(editing){const add=action('添加当前页书签',()=>commit([...pdfOutlineTree(model,draft.operations),{title:'新书签',pageId:options.currentPage(),top:null,children:[]}]));add.dataset.outlineAdd='true';body.append(add)}
  const visible=new Set(options.pages().map(page=>page.pageId)),tree=pdfOutlineTree(model,draft.operations)
  const walk=(nodes:PdfBookmarkNode[],prefix:string,depth:number)=>nodes.forEach((node,index)=>{
   if(!visible.has(node.pageId))return
   const path=prefix?`${prefix}.${index}`:String(index),row=doc.createElement('div');row.className='pdf-bookmark-row';row.style.paddingInlineStart=`${depth*12}px`;row.setAttribute('role','treeitem');row.setAttribute('aria-level',String(depth+1))
   const jump=doc.createElement('button');jump.type='button';jump.textContent=node.title;jump.className='pdf-outline-link';jump.dataset.pageId=node.pageId;jump.dataset.outlinePage='true';jump.addEventListener('click',()=>options.navigate(node.pageId));row.append(jump)
   if(editing){
    const rename=action('重命名',()=>{
     const snapshot=JSON.stringify(draft.operations),input=doc.createElement('input');input.value=node.title;input.maxLength=4000;input.setAttribute('aria-label','书签名称');input.dataset.pdfOutlineEditable='true';jump.replaceWith(input);rename.hidden=true
     let done=false
     const finish=(cancel=false)=>{
      if(done||!cancel&&reason())return;done=true
      if(cancel||!input.value.trim()||input.value.trim()===node.title){render();return}
      try{if(snapshot!==JSON.stringify(draft.operations))throw Error('草稿已变化，请重新选择书签');commit(mutatePdfOutline(pdfOutlineTree(model,draft.operations),path,input.value))}catch(error){options.error(error);render()}
     }
     input.addEventListener('keydown',event=>{if(event.isComposing||event.keyCode===229)return;if(event.key==='Enter'){event.preventDefault();finish()}else if(event.key==='Escape'){event.preventDefault();finish(true)}})
     input.addEventListener('blur',()=>finish());input.focus();input.select()
    });rename.textContent='✎';rename.dataset.outlineRename=path;rename.setAttribute('aria-label',`重命名书签 ${node.title}`)
    const remove=action('删除',()=>commit(mutatePdfOutline(pdfOutlineTree(model,draft.operations),path,null)));remove.textContent='✕';remove.dataset.outlineDelete=path;remove.setAttribute('aria-label',`删除书签 ${node.title}`);row.append(rename,remove)
   }
   body.append(row);walk(node.children,path,depth+1)
  })
  walk(tree,'',0)
  if(!body.querySelector('[data-outline-page]')){const empty=doc.createElement('p');empty.textContent='当前没有可跳转的目录条目';empty.setAttribute('role','status');body.append(empty)}
  update();return true
 }
 return {render,update,dispose(){disposed=true;toggle.remove();for(const node of panel.querySelectorAll('[data-outline-editor-content]'))node.remove()}}
}

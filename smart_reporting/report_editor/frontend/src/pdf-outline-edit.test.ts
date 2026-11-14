// @vitest-environment jsdom
import {expect,it} from 'vitest'
import {NativeDraft} from './native-draft'
import {pdfPageState} from './pdf-operations'
import {pdfOutlineTree,stagePdfOutline,mutatePdfOutline,mountPdfOutlineEditor,type PdfBookmarkNode} from './pdf-outline-edit'
const sha='a'.repeat(64),pages=[0,1].map(index=>({pageId:`sha256:${sha}:page:${index}`,index,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},rotation:0}))
const first:PdfBookmarkNode={title:'First',pageId:pages[0].pageId,top:320,children:[{title:'Child',pageId:pages[1].pageId,top:null,children:[]}]}
const model={sourceSha256:sha,pages,outline:[first],outlineEditable:true}
function draft(){const values=new Map<string,string>();return new NativeDraft({documentId:'pdf-outline',revision:1,sourceSha256:sha,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'}},{getItem:key=>values.get(key)??null,setItem:(key,value)=>{values.set(key,value)},removeItem:key=>{values.delete(key)}})}
it('stages a complete nested tree while preserving other operations, UndoRedo and source-bound restoration',()=>{
 const value=draft(),rotation={kind:'rotatePage',pageId:pages[1].pageId,delta:90}
 value.setOperations([rotation]);value.setOperations(stagePdfOutline(model,value.operations,mutatePdfOutline(model.outline,'0','Renamed')))
 expect(value.operations[0]).toEqual(rotation);expect(pdfOutlineTree(model,value.operations)[0].title).toBe('Renamed');expect(pdfPageState(pages,value.operations)[1].rotation).toBe(90)
 value.undo();expect(pdfOutlineTree(model,value.operations)[0].title).toBe('First');value.redo();expect(pdfOutlineTree(model,value.operations)[0].title).toBe('Renamed')
 expect(value.beginSave().operations).toEqual(value.operations);value.saveFailed()
})
it('keeps paths and nested targets while rename/delete/add compose with reordered and inserted pages',()=>{
 const operations=[{kind:'insertBlankPage',pageId:'blank:outline-test',width:300,height:400},{kind:'reorderPages',pageIds:['blank:outline-test',pages[1].pageId,pages[0].pageId]}]
 const tree=mutatePdfOutline([first],'0.0',null)
 const next=stagePdfOutline(model,operations,[...tree,{title:'Blank',pageId:'blank:outline-test',top:null,children:[]}])
 expect(pdfPageState(pages,next).map(page=>page.pageId)).toEqual(['blank:outline-test',pages[1].pageId,pages[0].pageId]);expect(pdfOutlineTree(model,next)[0].children).toEqual([])
 expect(first.children[0].title).toBe('Child')
})
it('rejects foreign targets, unsafe source, malformed paths and duplicate replacements without mutating old draft',()=>{
 for(const tree of [[{...first,pageId:'foreign'}],[{...first,title:''}],[{...first,top:Infinity}]])expect(()=>stagePdfOutline(model,[],tree)).toThrow()
 expect(()=>stagePdfOutline({...model,outlineEditable:false,outlineReason:'含外链书签'},[],[])).toThrow(/外链/)
 expect(()=>mutatePdfOutline([first],'9','New')).toThrow();expect(()=>mutatePdfOutline([first],'0.9','New')).toThrow()
 const op=stagePdfOutline(model,[],[])[0];expect(()=>pdfOutlineTree(model,[op,op])).toThrow()
})
it('shows source edit/add/rename/delete controls, stages only explicit changes and respects locks',()=>{
 const root=document.createElement('nav'),header=document.createElement('header');root.append(header);document.body.append(root)
 const value=draft();let locked=false,changes=0;const navigate:string[]=[]
 const editor=mountPdfOutlineEditor({panel:root,header,model,draft:value,pages:()=>pdfPageState(pages,value.operations),currentPage:()=>pages[1].pageId,unavailable:()=>locked?'正在保存':null,changed:()=>{changes++;editor.render()},navigate:id=>navigate.push(id),error:error=>{throw error}})
 editor.render();(header.querySelector('button') as HTMLButtonElement).click();expect(value.dirty).toBe(false)
 const rename=root.querySelector<HTMLButtonElement>('[data-outline-rename="0"]')!;rename.click();const input=root.querySelector('input')!;input.value='Renamed';input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))
 expect(pdfOutlineTree(model,value.operations)[0].title).toBe('Renamed');expect(changes).toBe(1)
 root.querySelector<HTMLButtonElement>('[data-outline-delete="0.0"]')!.click();expect(pdfOutlineTree(model,value.operations)[0].children).toEqual([])
 root.querySelector<HTMLButtonElement>('[data-outline-add]')!.click();expect(pdfOutlineTree(model,value.operations)[1].pageId).toBe(pages[1].pageId)
 root.querySelector<HTMLButtonElement>('[data-outline-page]')!.click();expect(navigate).toEqual([pages[0].pageId])
 locked=true;editor.update();expect([...root.querySelectorAll<HTMLInputElement|HTMLButtonElement>('[data-pdf-outline-editable]')].every(control=>control.disabled)).toBe(true)
 editor.dispose();root.remove()
})
it('keeps an uncommitted rename available after a temporary save lock',()=>{
 const root=document.createElement('nav'),header=document.createElement('header');root.append(header);document.body.append(root)
 const value=draft();let locked=false
 const editor=mountPdfOutlineEditor({panel:root,header,model,draft:value,pages:()=>pages,currentPage:()=>pages[0].pageId,unavailable:()=>locked?'正在保存':null,changed:()=>editor.render(),navigate:()=>{},error:error=>{throw error}})
 editor.render();header.querySelector('button')!.click();root.querySelector<HTMLButtonElement>('[data-outline-rename="0"]')!.click()
 const input=root.querySelector('input')!;input.value='After lock';locked=true;editor.update();input.dispatchEvent(new Event('blur'));expect(value.dirty).toBe(false)
 locked=false;editor.update();input.dispatchEvent(new Event('blur'));expect(pdfOutlineTree(model,value.operations)[0].title).toBe('After lock')
 editor.dispose();root.remove()
})

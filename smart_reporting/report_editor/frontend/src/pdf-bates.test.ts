// @vitest-environment jsdom
import {expect,it} from 'vitest'
import {NativeDraft} from './native-draft'
import {pdfPageState,reversePdfPages,deletePdfPage,insertBlankPdfPage} from './pdf-operations'
import {buildPdfBatesOperation,validatePdfBates,bindPdfBates} from './pdf-bates'
const sha='a'.repeat(64),pages=[0,1,2].map(index=>({pageId:`sha256:${sha}:page:${index}`,index,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:10,y:20,width:280,height:360},rotation:0}))
const cfg={prefix:'ACME-',start:41,digits:6,fontSize:10,color:[.1,.1,.12] as [number,number,number],position:'bottom-right' as const,firstPage:2,lastPage:3}
const measure=(text:string)=>text.length*5
function setup(){const store=new Map<string,string>(),storage={getItem:(k:string)=>store.get(k)??null,setItem:(k:string,v:string)=>{store.set(k,v)},removeItem:(k:string)=>{store.delete(k)}};const identity={documentId:'bates',revision:4,sourceSha256:sha,scope:{database:'x',companyId:'x',userId:'x',threadId:'x'}};return {value:new NativeDraft(identity,storage),storage,identity}}
it('builds source range and geometry with immutable application targets rather than ordinary page numbers',()=>{
 const op=buildPdfBatesOperation(sha,[pages[2],pages[0],pages[1]],cfg,measure)
 expect(op.entries.map(e=>e.pageId)).toEqual([pages[0].pageId,pages[1].pageId]);expect(op.entries.map(e=>e.ordinal)).toEqual([0,1])
 expect(op.entries[0]).toEqual({pageId:pages[0].pageId,ordinal:0,origin:[262,48],rotate:0,lineXOffsets:[-55]})
 expect(buildPdfBatesOperation(sha,[{...pages[0],rotation:90}],{...cfg,firstPage:1,lastPage:null},measure).entries[0].origin).toEqual([262,352])
})
it('keeps assigned numbers, source identity and history through later page changes, restoration and canceled blanks',()=>{
 const {value,storage,identity}=setup();let ops=insertBlankPdfPage(pages,[],pages[0].pageId,()=> 'bates')
 const op=buildPdfBatesOperation(sha,pdfPageState(pages,ops),{...cfg,firstPage:1,lastPage:null},measure)
 value.setOperations([...ops,op]);value.setOperations(reversePdfPages(pages,value.operations));expect(value.operations.find(o=>o.kind==='addBates')).toEqual(op)
 value.setOperations(deletePdfPage(pages,value.operations,'blank:bates'));const kept=value.operations.find(o=>o.kind==='addBates') as typeof op
 expect(kept.entries.map(e=>e.ordinal)).toEqual([0,2,3]);expect(pdfPageState(pages,value.operations)).toHaveLength(3)
 value.undo();expect(pdfPageState(pages,value.operations)).toHaveLength(4);value.redo()
 const restored=new NativeDraft(identity,storage);expect(restored.operations).toEqual(value.operations)
 expect(()=>validatePdfBates(pages,[{...op,sourceSha256:'b'.repeat(64)}])).toThrow()
})
it('rejects invalid ranges, source-only unsupported style fields, foreign targets and duplicate target entries',()=>{
 for(const config of [{...cfg,start:-1},{...cfg,digits:16},{...cfg,fontSize:37},{...cfg,firstPage:0},{...cfg,lastPage:1}])expect(()=>buildPdfBatesOperation(sha,pages,config,measure)).toThrow()
 const op=buildPdfBatesOperation(sha,pages,cfg,measure)
 for(const bad of [{...op,config:{...cfg,suffix:'X'}},{...op,entries:[{...op.entries[0],pageId:'foreign'}]},{...op,entries:[op.entries[0],op.entries[0]]}])expect(()=>validatePdfBates(pages,[bad])).toThrow()
})
it('opens source fields without dirtying, stages one action, cancels cleanly and refuses stale or locked apply',()=>{
 HTMLDialogElement.prototype.showModal=function(){this.open=true};HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new Event('close'))}
 const {value}=setup(),root=document.createElement('div');document.body.append(root);let locked=false,changed=0
 const dialog=bindPdfBates({root,draft:value,pages:()=>pages,unavailable:()=>locked?'正在保存':null,measure,changed:()=>{changed++},status:()=>{}})
 dialog.open();expect(value.dirty).toBe(false);expect(root.querySelector('[aria-label="Bates 前缀"]')).not.toBeNull()
 ;(root.querySelector('[aria-label="Bates 前缀"]') as HTMLInputElement).value='CASE-'
 locked=true;root.querySelector<HTMLButtonElement>('[data-bates-apply]')!.click();expect(value.dirty).toBe(false)
 locked=false;root.querySelector<HTMLButtonElement>('[data-bates-apply]')!.click();expect(value.operations[0].kind).toBe('addBates');expect(changed).toBe(1)
 dialog.open();value.setOperations([...value.operations,{kind:'rotatePage',pageId:pages[0].pageId,delta:90}]);root.querySelector<HTMLButtonElement>('[data-bates-apply]')!.click();expect(changed).toBe(1)
 dialog.dispose();root.remove()
})
it('matches all six source positions and UserUnit display margins',()=>{
 const expected={ 'top-left':[38,342], 'top-center':[150,342], 'top-right':[262,342], 'bottom-left':[38,48], 'bottom-center':[150,48], 'bottom-right':[262,48] }
 for(const [position,origin]of Object.entries(expected))expect(buildPdfBatesOperation(sha,[pages[0]],{...cfg,position:position as typeof cfg.position,firstPage:1,lastPage:null},measure).entries[0].origin).toEqual(origin)
 expect(buildPdfBatesOperation(sha,[{...pages[0],userUnit:2}],{...cfg,firstPage:1,lastPage:null},measure).entries[0].origin).toEqual([276,34])
})
it('closes an empty source range without adding a draft operation',()=>{
 HTMLDialogElement.prototype.showModal=function(){this.open=true};HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new Event('close'))}
 const {value}=setup(),root=document.createElement('div');document.body.append(root)
 const controller=bindPdfBates({root,draft:value,pages:()=>pages,unavailable:()=>null,measure,changed:()=>{throw Error('空范围不得变脏')},status:()=>{}})
 controller.open();(root.querySelector('[aria-label="Bates 起始页"]') as HTMLInputElement).value='20';root.querySelector<HTMLButtonElement>('[data-bates-apply]')!.click()
 expect(root.querySelector('dialog')!.open).toBe(false);expect(value.dirty).toBe(false);controller.dispose();root.remove()
})

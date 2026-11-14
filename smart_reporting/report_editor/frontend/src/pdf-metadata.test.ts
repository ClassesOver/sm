// @vitest-environment jsdom
import {expect,it} from 'vitest'
import {NativeDraft} from './native-draft'
import {pdfPageState} from './pdf-operations'
import {bindPdfMetadata,metadataSnapshot,stagePdfMetadata} from './pdf-metadata'
const sha='a'.repeat(64),pages=[{pageId:`sha256:${sha}:page:0`,index:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},rotation:0}]
const values={title:'New 中文',author:'Alice',subject:'',keywords:'one，two;three'}
function setup(){const store=new Map<string,string>(),storage={getItem:(k:string)=>store.get(k)??null,setItem:(k:string,v:string)=>{store.set(k,v)},removeItem:(k:string)=>{store.delete(k)}};const identity={documentId:'metadata',revision:4,sourceSha256:sha,scope:{database:'x',companyId:'x',userId:'x',threadId:'x'}};return {value:new NativeDraft(identity,storage),storage,identity}}
it('stages one source metadata snapshot, replaces it as one history action and restores with page edits',()=>{
 const {value,storage,identity}=setup(),rotate={kind:'rotatePage',pageId:pages[0].pageId,delta:90};value.setOperations([rotate]);value.setOperations(stagePdfMetadata(value.operations,sha,values,123000));const first=value.operations
 expect(pdfPageState(pages,value.operations)[0].rotation).toBe(90);expect(metadataSnapshot({Title:'Source'},value.operations,sha)).toEqual(values)
 value.setOperations(stagePdfMetadata(value.operations,sha,{...values,title:''},124000));expect(value.operations.filter(o=>o.kind==='setMetadata')).toHaveLength(1);value.undo();expect(value.operations).toEqual(first);value.redo();expect(metadataSnapshot({},value.operations,sha).title).toBe('')
 expect(new NativeDraft(identity,storage).operations).toEqual(value.operations)
 expect(()=>metadataSnapshot({},[{...first[1],sourceSha256:'b'.repeat(64)}],sha)).toThrow()
})
it('opens baseline or pending fields without dirtying, cancels without changes and applies editable fields only',()=>{
 HTMLDialogElement.prototype.showModal=function(){this.open=true};HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new Event('close'))}
 const {value}=setup(),root=document.createElement('div');document.body.append(root);let changed=0
 const ctl=bindPdfMetadata({root,draft:value,info:{Title:'Original',Author:'Source author',Subject:'Source subject',Keywords:'old',Producer:'Read only producer'},fileName:'source.pdf',fileSize:1024,pageCount:()=>1,unavailable:()=>null,changed:()=>{changed++},now:()=>123000})
 ctl.open();expect(value.dirty).toBe(false);expect(root.querySelector<HTMLInputElement>('[aria-label="文档属性 标题"]')!.value).toBe('Original');expect(root.textContent).toContain('Read only producer')
 root.querySelector<HTMLButtonElement>('[data-metadata-cancel]')!.click();expect(value.dirty).toBe(false)
 ctl.open();for(const [field,label]of Object.entries({title:'标题',author:'作者',subject:'主题',keywords:'关键词'}))root.querySelector<HTMLInputElement>(`[aria-label="文档属性 ${label}"]`)!.value=values[field as keyof typeof values]
 root.querySelector<HTMLButtonElement>('[data-metadata-apply]')!.click();expect(changed).toBe(1);expect(value.operations[0]).toEqual({kind:'setMetadata',sourceSha256:sha,modifiedMs:123000,metadata:values});ctl.open();expect(root.querySelector<HTMLInputElement>('[aria-label="文档属性 主题"]')!.value).toBe('');ctl.dispose();root.remove()
})
it('keeps read-only metadata visible and refuses a stale or newly locked apply',()=>{
 HTMLDialogElement.prototype.showModal=function(){this.open=true};HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new Event('close'))}
 const {value}=setup(),root=document.createElement('div');document.body.append(root);let reason:string|null='来源只读'
 const ctl=bindPdfMetadata({root,draft:value,info:{Title:'Read only'},fileName:'x.pdf',fileSize:2,pageCount:()=>1,unavailable:()=>reason,changed:()=>{throw Error('must not change')},now:()=>1})
 ctl.open();expect(root.querySelector<HTMLInputElement>('input')!.disabled).toBe(true);expect(root.querySelector<HTMLButtonElement>('[data-metadata-apply]')!.hidden).toBe(true);root.querySelector<HTMLButtonElement>('[data-metadata-cancel]')!.click()
 reason=null;ctl.open();value.setOperations([{kind:'rotatePage',pageId:pages[0].pageId,delta:90}]);root.querySelector<HTMLButtonElement>('[data-metadata-apply]')!.click();expect(value.operations).toHaveLength(1);expect(root.querySelector('[role="alert"]')!.textContent).toContain('草稿已变化');ctl.dispose();root.remove()
})

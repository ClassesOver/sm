import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {bindPdfExistingImagePanel} from './pdf-existing-image'
const show=vi.hoisted(()=>vi.fn((_options:any)=>({dispose:vi.fn()})))
vi.mock('./pdf-image-dialogs',()=>({showPdfImageDialog:show}))
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0',png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
const descriptors=Object.fromEntries(['showModal','close'].map(name=>[name,Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype,name)]))
let panel:ReturnType<typeof bindPdfExistingImagePanel>|undefined
beforeEach(()=>{localStorage.clear();show.mockClear();Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(this:HTMLDialogElement){this.open=true}});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})})
afterEach(()=>{panel?.dispose();document.body.replaceChildren();vi.restoreAllMocks();for(const name of ['showModal','close']){const d=descriptors[name];if(d)Object.defineProperty(HTMLDialogElement.prototype,name,d);else Reflect.deleteProperty(HTMLDialogElement.prototype,name)}})
function fixture(){
 const root=document.body.appendChild(document.createElement('div')),draft=new NativeDraft({documentId:'visual',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 const image={pageId,pageIndex:0,rect:[60,90,160,170] as [number,number,number,number],imageId:'b'.repeat(64),expectedImageSha256:'c'.repeat(64),aboveText:true,editable:true,replaceable:true,bakeable:true}
 let resolve!:(value:unknown)=>void;const readPixels=vi.fn(()=>new Promise<any>(yes=>{resolve=yes}))
 panel=bindPdfExistingImagePanel({root,draft,pages:()=>[{pageId,index:0,rotation:0,cropBox:{x:0,y:0,width:400,height:500},mediaBox:{x:0,y:0,width:400,height:500}}],images:()=>[image],unavailable:()=>null,refresh:async()=>{},status(){},readPixels});panel.open()
 const reply=()=>resolve({sourceSha256:sha,pageId,imageId:image.imageId,expectedImageSha256:image.expectedImageSha256,image:png,width:1,height:1,sha256:'d'.repeat(64)})
 return {root,draft,image,readPixels,reply,button:root.querySelector<HTMLButtonElement>('[data-pdf-image-visual=crop]')!}
}
it('reads identified object pixels and stages cropped replacement only after source dialog apply',async()=>{
 const f=fixture();f.button.click();expect(f.draft.operations).toEqual([]);expect(f.readPixels).toHaveBeenCalledWith({sourceSha256:sha,pageId,imageId:f.image.imageId,expectedImageSha256:f.image.expectedImageSha256})
 f.reply();await vi.waitFor(()=>expect(show).toHaveBeenCalledTimes(1));const args=show.mock.calls[0]![0] as any
 args.onApply(png,{l:.25,t:.25,r:.75,b:.75});await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1));expect(f.draft.operations[0]).toMatchObject({image:png,rect:[85,110,135,150]})
})
it.each(['cancel','draft','dispose'])('discards delayed pixel reads after %s',async action=>{const f=fixture();f.button.click();if(action==='cancel')panel!.cancel();if(action==='draft')f.draft.setOperations([{kind:'setMetadata',title:'changed'}]);if(action==='dispose')panel!.dispose();f.reply();await new Promise(resolve=>setTimeout(resolve,10));expect(show).not.toHaveBeenCalled();expect(f.draft.operations).toHaveLength(action==='draft'?1:0)})
it('cancel leaves draft unchanged and ignores a late apply callback',async()=>{const f=fixture();f.button.click();f.reply();await vi.waitFor(()=>expect(show).toHaveBeenCalledTimes(1));const args=show.mock.calls[0]![0] as any;args.onCancel();args.onApply(png,{l:.25,t:.25,r:.75,b:.75});expect(f.draft.operations).toEqual([])})

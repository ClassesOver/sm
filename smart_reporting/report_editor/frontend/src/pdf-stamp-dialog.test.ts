import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {bindPdfStampDialog} from './pdf-stamp-dialog'
import {DEFAULT_HEADER_FOOTER,DEFAULT_WATERMARK} from './vendor/genoffice-pdf/renderer/stamps'
const render=vi.hoisted(()=>vi.fn((_options:any)=>({dispose:vi.fn()})))
vi.mock('./pdf-stamp-dialog-source',()=>({showPdfStampDialog:render}))
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0'
let control:ReturnType<typeof bindPdfStampDialog>|undefined
beforeEach(()=>{localStorage.clear();render.mockClear()})
afterEach(()=>{control?.dispose();document.body.replaceChildren()})
async function fixture(){
 const root=document.body.appendChild(document.createElement('div')),draft=new NativeDraft({documentId:'stamp-source',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},localStorage)
 const status=vi.fn(),refresh=vi.fn(async()=>{}),build=vi.fn(()=>({kind:'setStamps',watermark:{...DEFAULT_WATERMARK,text:'机密'},headerFooter:null,images:['pixels'],stamps:[{pageId,image:0,rect:[0,0,100,100]}]}))
 let unavailable:string|null=null
 control=bindPdfStampDialog({root,draft,pages:()=>[{pageId,index:0,rotation:0,cropBox:{x:0,y:0,width:400,height:500},mediaBox:{x:0,y:0,width:400,height:500}}],unavailable:()=>unavailable,refresh,status,build})
 await control.open();expect(render).toHaveBeenCalledTimes(1)
 return {draft,build,status,refresh,args:render.mock.calls[0]![0] as any,block:()=>{unavailable='当前只读'}}
}
it('opens full source family without staging until apply',async()=>{const f=await fixture();expect(f.draft.operations).toEqual([]);f.args.onApply({...DEFAULT_WATERMARK,text:'机密'},null);expect(f.build).toHaveBeenCalledOnce();expect(f.draft.operations[0]?.kind).toBe('setStamps');await vi.waitFor(()=>expect(f.refresh).toHaveBeenCalledOnce())})
it('cancel ignores a late apply callback',async()=>{const f=await fixture();f.args.onCancel();f.args.onApply(DEFAULT_WATERMARK,DEFAULT_HEADER_FOOTER);expect(f.draft.operations).toEqual([])})
it.each(['draft','readonly','dispose'])('rejects stale confirmation after %s',async action=>{const f=await fixture();if(action==='draft')f.draft.setOperations([{kind:'rotatePage',pageId,delta:90}]);if(action==='readonly')f.block();if(action==='dispose')control!.dispose();f.args.onApply(DEFAULT_WATERMARK,DEFAULT_HEADER_FOOTER);expect(f.build).not.toHaveBeenCalled();expect(f.draft.operations).toHaveLength(action==='draft'?1:0)})
it('clear removes only staged stamps and preserves other edits',async()=>{const f=await fixture();f.args.onCancel();f.draft.setOperations([{kind:'rotatePage',pageId,delta:90},{kind:'setStamps',watermark:{...DEFAULT_WATERMARK,text:'旧'},headerFooter:null}]);await control!.open();const args=render.mock.calls[1]![0] as any;expect(args.initialWatermark.text).toBe('旧');expect(args.canClear).toBe(true);args.onClear();expect(f.draft.operations).toEqual([{kind:'rotatePage',pageId,delta:90}])})

import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {createHash} from 'node:crypto'
import {createEditorShell} from './shell'
import {createSlidesEditorView} from './slides-main'
import {NativeDraft} from './native-draft'
vi.mock('./slides-canvas',()=>({mountSlidesCanvas:()=>({update(){},destroy(){}})}))
const cutout=vi.hoisted(()=>vi.fn((_host:unknown,_options:{dataUrl:string;isCurrent:()=>boolean;onApply:(data:string)=>void})=>({dispose:vi.fn()})));vi.mock('./slides-cutout-dialog',()=>({openSlidesCutout:cutout}))
const base64='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',dataUrl='data:image/png;base64,'+base64
let view:ReturnType<typeof createSlidesEditorView>
beforeEach(()=>{vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});cutout.mockClear()})
afterEach(()=>{view?.dispose();document.body.replaceChildren();vi.unstubAllGlobals()})
it('来源原图核验后打开完整去背景，Apply单笔NativeDraft，可撤销重做，过期选择拒绝',async()=>{
 const bytes=Buffer.from(base64,'base64'),sha=createHash('sha256').update(bytes).digest('hex'),element={id:'pic',type:'picture',name:'源图片',text:'',editable:true,pictureReplaceable:true,pictureSha256:sha,pictureSize:bytes.length},source={sha256:'a'.repeat(64),revision:1,size:{cx:9144000,cy:5143500},slides:[{slideIndex:0,elements:[element]},{slideIndex:1,elements:[]}]},tree={slides:source.slides.map(s=>({...s,widthPx:960,heightPx:540,nodes:s.slideIndex?[]:[{sourceId:'pic',type:'picture',dataUrl,box:{x:0,y:0,w:100,h:100}}],scale:1,background:{kind:'solid',color:'#fff'}}))}
 const draft=new NativeDraft({documentId:'cutout-test',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}}),shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx'),request=vi.fn(async(path:string)=>path==='deck'?source:path==='preview'?{sourceSha256:source.sha256,model:source}:tree)
 view=createSlidesEditorView(shell.editor,{native:true,draft,request:request as never,save:shell.save,download:shell.exportPptx});await view.ready;await new Promise(r=>setTimeout(r,30))
 shell.editor.querySelector<HTMLButtonElement>('[data-command="removeBackground"]')!.click();await vi.waitFor(()=>expect(cutout).toHaveBeenCalledOnce());const options=cutout.mock.calls[0]![1];expect(options.dataUrl).toBe(dataUrl);expect(options.isCurrent()).toBe(true);options.onApply(dataUrl)
 expect(draft.operations[0]?.pictureReplacements).toEqual([{slideIndex:0,elementId:'pic',expectedSha256:sha,expectedSize:bytes.length,bytesBase64:base64,extension:'png',keepSrcRect:true}]);shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(draft.operations[0]?.pictureReplacements).toBeUndefined();shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(draft.operations[0]?.pictureReplacements).toHaveLength(1)
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();shell.editor.querySelector<HTMLButtonElement>('[data-command="removeBackground"]')!.click();await vi.waitFor(()=>expect(cutout).toHaveBeenCalledTimes(2));const late=cutout.mock.calls[1]![1];shell.editor.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="1"]')!.click();expect(late.isCurrent()).toBe(false);expect(()=>late.onApply(dataUrl)).toThrow('变化');expect(draft.operations[0]?.pictureReplacements).toBeUndefined()
 shell.editor.querySelector<HTMLButtonElement>('.slide-open[data-slide-index="0"]')!.click();shell.editor.querySelector<HTMLButtonElement>('[data-command="removeBackground"]')!.click();await vi.waitFor(()=>expect(cutout).toHaveBeenCalledTimes(3));const locked=cutout.mock.calls[2]![1];const saving=vi.spyOn(draft,'saving','get').mockReturnValue(true);expect(locked.isCurrent()).toBe(false);expect(()=>locked.onApply(dataUrl)).toThrow('变化');saving.mockRestore();view.dispose();expect(locked.isCurrent()).toBe(false)
})

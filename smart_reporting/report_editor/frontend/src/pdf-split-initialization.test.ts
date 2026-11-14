import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {createPdfEditorView} from './pdf-main'
import type {EditorShell} from './shell'
import type {createNativeApi,NativeContextResponse} from './native-api'

vi.mock('pdfjs-dist/legacy/build/pdf.mjs',()=>({AnnotationMode:{ENABLE:1},GlobalWorkerOptions:{},TextLayer:class{}}))
vi.mock('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url',()=>({default:'fixture-worker'}))
beforeEach(()=>{localStorage.clear();vi.stubGlobal('IntersectionObserver',undefined)})
afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})

it('来源尚未读取时刷新拆分入口不会提前访问未初始化的PDF模型',async()=>{
  const root=document.body.appendChild(document.createElement('div')),sha='a'.repeat(64)
  const identity={documentId:'split-initialization',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
  const draft=new NativeDraft(identity,localStorage),reachedSource=new Error('已抵达来源文件读取')
  const file=vi.fn(async()=>{throw reachedSource})
  const api={file} as unknown as ReturnType<typeof createNativeApi>
  const context={context:{documentId:identity.documentId,revision:1,format:'pdf',scope:identity.scope,sourceFile:{path:'source.pdf',size:2,sha256:sha}},editingEnabled:true,pdfTextEnabled:false} as NativeContextResponse
  await expect(createPdfEditorView({editor:root,save:document.createElement('button')} as unknown as EditorShell,{api,context,draft})).rejects.toBe(reachedSource)
  expect(file).toHaveBeenCalledOnce()
  expect(root.querySelector<HTMLButtonElement>('[data-source-command-id="genoffice.pdf.page.splitPdf"]')?.disabled).toBe(true)
})

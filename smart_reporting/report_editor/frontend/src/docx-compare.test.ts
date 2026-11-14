import {afterEach,expect,it,vi} from 'vitest'
import {Editor,Node} from '@tiptap/core'
const parse=vi.hoisted(()=>vi.fn())
vi.mock('./vendor/genoffice-docs/apps/docs/src/renderer/parse-off-thread',()=>({parseDocxOffThread:parse}))
import {createDocxCompareControls} from './docx-compare'
const Doc=Node.create({name:'doc',topNode:true,content:'block+'}),Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',renderHTML:()=>['p',0]}),Text=Node.create({name:'text',group:'inline'})
const disposals:(()=>void)[]=[]
afterEach(()=>{disposals.splice(0).forEach(fn=>fn());document.body.replaceChildren();vi.clearAllMocks()})
function setup(){const root=document.body.appendChild(document.createElement('div')),editor=new Editor({element:root.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text],content:'<p>原文 &lt;script&gt;</p>'});const errors:unknown[]=[];const controls=createDocxCompareControls({editor,blocks:[],container:root,onError:error=>errors.push(error),flush:vi.fn()});disposals.push(()=>{controls.dispose();editor.destroy()});return {root,editor,controls,errors}}
function file(root:HTMLElement){const input=root.querySelector<HTMLInputElement>('input[type=file]')!;Object.defineProperty(input,'files',{configurable:true,value:[{name:'比较.docx',size:12,arrayBuffer:async()=>new ArrayBuffer(12)}]});input.dispatchEvent(new Event('change',{bubbles:true}))}
it('compares current unsaved text using the source paragraph diff and renders uploaded text safely',async()=>{
 const f=setup();parse.mockResolvedValue({blocks:[{runs:[{text:'比较 <img src=x onerror=alert(1)>'}]}]});f.controls.open();file(f.root)
 await vi.waitFor(()=>expect(f.root.querySelector('[data-compare-results]')?.textContent).toContain('比较 <img'))
 expect(f.root.querySelector('[data-compare-results]')!.textContent).toContain('原文 <script>');expect(f.root.querySelector('[data-compare-results] img')).toBeNull();expect(f.editor.getText()).toBe('原文 <script>');expect(f.errors).toEqual([])
})
it('closing or changing the current document while parsing discards stale results',async()=>{
 const f=setup();let finish!:(value:object)=>void;parse.mockImplementation(()=>new Promise(resolve=>{finish=resolve}));f.controls.open();file(f.root);await vi.waitFor(()=>expect(parse).toHaveBeenCalled());f.editor.commands.insertContent('新稿');finish({blocks:[{runs:[{text:'旧比较结果'}]}]})
 await vi.waitFor(()=>expect(f.root.textContent).toContain('已变化'));expect(f.root.querySelector('[data-compare-results]')?.textContent).not.toContain('旧比较结果')
 parse.mockClear();f.controls.open();file(f.root);await vi.waitFor(()=>expect(parse).toHaveBeenCalled());f.root.querySelector<HTMLButtonElement>('[aria-label="关闭文档比较"]')!.click();finish({blocks:[{runs:[{text:'关闭后迟到'}]}]});await Promise.resolve();expect(f.root.querySelector('[data-compare-results]')).toBeNull()
})
it('rejects oversized file before parsing',async()=>{
 const f=setup();f.controls.open();const input=f.root.querySelector<HTMLInputElement>('input[type=file]')!;Object.defineProperty(input,'files',{value:[{name:'large.docx',size:8*1024*1024+1}]});input.dispatchEvent(new Event('change'));await vi.waitFor(()=>expect(f.errors).toHaveLength(1));expect(parse).not.toHaveBeenCalled()
})

it('bounds LCS work for a large parsed document without modifying the editor',async()=>{
 const f=setup();f.editor.commands.setContent({type:'doc',content:Array.from({length:1500},()=>({type:'docParagraph',content:[{type:'text',text:'current'}]}))});parse.mockResolvedValue({blocks:Array.from({length:1500},()=>({previewText:'other'}))});f.controls.open();file(f.root)
 await vi.waitFor(()=>expect(f.errors).toHaveLength(1));expect(String(f.errors[0])).toContain('段落数量过多');expect(f.root.querySelector('[data-compare-results]')!.textContent).toBe('');expect(f.editor.state.doc.childCount).toBe(1500)
})

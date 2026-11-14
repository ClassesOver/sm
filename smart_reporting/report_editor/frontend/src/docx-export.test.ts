import {afterEach,expect,it,vi} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import JSZip from 'jszip'
import {buildDocxExportArtifact,createDocxExportControls} from './docx-export'
const Doc=Node.create({name:'doc',topNode:true,content:'docParagraph+',renderHTML:()=>['div',0]})
const P=Node.create({name:'docParagraph',content:'inline*',renderHTML:()=>['p',0]})
const Text=Node.create({name:'text',group:'inline'})
const Image=Node.create({name:'docInlineImage',group:'inline',inline:true,atom:true,addAttributes:()=>({dataUrl:{default:null}}),renderHTML:({node})=>['img',{src:node.attrs.dataUrl}]})
const png='data:image/png;base64,iVBORw0KGgo='
let editor:Editor
function make(image=false){const host=document.body.appendChild(document.createElement('div'));return editor=new Editor({element:host,extensions:[Doc,P,Text,Image],content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'正文'},...(image?[{type:'docInlineImage',attrs:{dataUrl:png}}]:[])]}]}})}
afterEach(()=>{editor?.destroy();document.body.replaceChildren();vi.restoreAllMocks()})
it('exports upstream Markdown and includes exact picture bytes with relative media paths',async()=>{
 const artifact=await buildDocxExportArtifact({editor:make(true),format:'markdown',title:'报告.docx'})
 expect(artifact.fileName).toBe('报告.zip')
 const zip=await JSZip.loadAsync(artifact.bytes)
 expect(await zip.file('报告.md')!.async('string')).toBe('正文![](media/image1.png)\n')
 expect(Array.from(await zip.file('media/image1.png')!.async('uint8array'))).toEqual([137,80,78,71,13,10,26,10])
})
it('exports a plain md when there are no pictures',async()=>{
 const artifact=await buildDocxExportArtifact({editor:make(),format:'markdown',title:'../报告.docx'})
 expect(artifact.fileName).toBe('_报告.md');expect(new TextDecoder().decode(artifact.bytes)).toBe('正文\n')
})
it('exports standalone HTML with title, content and inline pictures',async()=>{
 const nativeStyle=window.getComputedStyle.bind(window);vi.spyOn(window,'getComputedStyle').mockImplementation((el)=>nativeStyle(el))
 const artifact=await buildDocxExportArtifact({editor:make(true),format:'html',title:'A & B.docx'})
 const html=new TextDecoder().decode(artifact.bytes)
 expect(html).toContain('<!DOCTYPE html>');expect(html).toContain('<title>A &amp; B</title>');expect(html).toContain(png);expect(html).toContain('正文')
})
it('flushes before downloading and cleans up its anchor',async()=>{
 make();const calls:string[]=[]
 vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:()=>{calls.push('url');return 'blob:test'},revokeObjectURL:()=>{}}))
 vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this:HTMLAnchorElement){calls.push(this.download)})
 const control=createDocxExportControls({editor,container:document.body,title:()=> '报告.docx',flush:async()=>{calls.push('flush')},onError:()=>{throw Error('unexpected')}})
 expect(await control.run('markdown')).toBe(true);expect(calls).toEqual(['flush','url','报告.md']);expect(document.querySelector('a[download]')).toBeNull();control.dispose()
})
it('reports an unsupported image instead of silently dropping it',async()=>{
 make(true);editor.commands.setContent({type:'doc',content:[{type:'docParagraph',content:[{type:'docInlineImage',attrs:{dataUrl:'data:image/avif;base64,AAAA'}}]}]})
 await expect(buildDocxExportArtifact({editor,format:'markdown',title:'图'})).rejects.toThrow(/图片格式/)
})

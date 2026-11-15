import type {Editor, JSONContent} from '@tiptap/core'
import JSZip from 'jszip'
import {documentToMarkdown} from './vendor/genoffice-docs/apps/docs/src/renderer/export-markdown'
import {buildStandaloneHtml} from './vendor/genoffice-docs/apps/docs/src/renderer/html-export'
import {MARKDOWN_MEDIA_DIR_TOKEN} from './vendor/genoffice-docs/apps/docs/src/shared/ipc'

export type DocxExportFormat='html'|'markdown'
export interface DocxExportArtifact {fileName:string;mimeType:string;bytes:Uint8Array}
interface ArtifactOptions {editor:Editor;format:DocxExportFormat;title:string}
const encoder=new TextEncoder()
function baseName(title:string):string{return (title.replace(/\.docx$/i,'').replace(/[\\/:*?"<>|\u0000-\u001f]+/g,'_').replace(/^\.+/,'').trim()||'文档')}
async function dataUrl(src:string):Promise<string>{
 if(/^data:image\/[\w.+-]+;base64,/.test(src))return src
 const response=await fetch(src)
 if(!response.ok)throw new Error(`无法读取导出图片 (${response.status})`)
 const blob=await response.blob()
 if(!blob.type.startsWith('image/'))throw new Error('导出图片格式无效')
 return await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(new Error('无法读取导出图片'));reader.readAsDataURL(blob)})
}
async function embedJsonImages(node:JSONContent):Promise<void>{
 for(const key of ['dataUrl','imageDataUrl'])if(typeof node.attrs?.[key]==='string'&&node.attrs[key]){
  const src=await dataUrl(node.attrs[key])
  if(!/^data:image\/(?:png|jpeg|gif|bmp|webp|svg\+xml|tiff);base64,/.test(src))throw new Error('Markdown 导出不支持此图片格式，请使用 HTML 导出')
  node.attrs[key]=src
 }
 for(const child of node.content??[])await embedJsonImages(child)
}
function imageBytes(src:string):Uint8Array{
 const match=/^data:image\/[\w.+-]+;base64,([\s\S]*)$/.exec(src)
 if(!match)throw new Error('无法打包导出图片')
 return Uint8Array.from(atob(match[1]),c=>c.charCodeAt(0))
}
/** Read-only conversion; no document transactions or persistence changes. */
export async function buildDocxExportArtifact({editor,format,title}:ArtifactOptions):Promise<DocxExportArtifact>{
 const base=baseName(title)
 if(format==='html'){
  const root=editor.view.dom as HTMLElement
  const width=Number.parseFloat(getComputedStyle(root).getPropertyValue('--section-content-w'))
  const source=buildStandaloneHtml(root,{title:title.replace(/\.docx$/i,''),lang:root.lang||document.documentElement.lang||'zh-CN',textWidthPx:Number.isFinite(width)?width:root.clientWidth})
  const parsed=new DOMParser().parseFromString(source,'text/html')
  for(const image of Array.from(parsed.querySelectorAll('img[src]')))image.setAttribute('src',await dataUrl(image.getAttribute('src')!))
  // Background pictures can also reference transient blob or application URLs.
  for(const element of Array.from(parsed.querySelectorAll<HTMLElement>('[style]'))){
   const style=element.getAttribute('style')??''
   let embedded=style
   for(const match of style.matchAll(/url\(["']?([^"')]+)["']?\)/g))embedded=embedded.replace(match[0],`url("${await dataUrl(match[1])}")`)
   element.setAttribute('style',embedded)
  }
  return {fileName:`${base}.html`,mimeType:'text/html;charset=utf-8',bytes:encoder.encode('<!DOCTYPE html>\n'+parsed.documentElement.outerHTML)}
 }
 const json=editor.getJSON();await embedJsonImages(json)
 const doc=editor.schema.nodeFromJSON(json)
 const snapshot={state:{doc},getJSON:()=>json} as unknown as Editor
 const {markdown,images}=documentToMarkdown(snapshot)
 const body=markdown.split(MARKDOWN_MEDIA_DIR_TOKEN).join('media')
 if(!images.length)return {fileName:`${base}.md`,mimeType:'text/markdown;charset=utf-8',bytes:encoder.encode(body)}
 const zip=new JSZip();zip.file(`${base}.md`,body)
 for(const image of images)zip.file(`media/${image.name}`,imageBytes(image.src))
 return {fileName:`${base}.zip`,mimeType:'application/zip',bytes:await zip.generateAsync({type:'uint8array'})}
}
export interface DocxExportControlsOptions {
 editor:Editor;container:HTMLElement;reason?:()=>string|null|undefined;flush?:()=>void|Promise<void>;onError:(error:unknown)=>void;title:string|(()=>string)
}
export function createDocxExportControls(options:DocxExportControlsOptions){
 let disposed=false,busy=false
 const urls=new Set<string>()
 return {
  async run(format:DocxExportFormat):Promise<boolean>{
   if(disposed||busy)return false
   busy=true
   try{
    const reason=options.reason?.();if(reason)throw new Error(reason)
    await options.flush?.();if(disposed)return false
    const artifact=await buildDocxExportArtifact({editor:options.editor,format,title:typeof options.title==='function'?options.title():options.title})
    if(disposed)return false
    const url=URL.createObjectURL(new Blob([artifact.bytes as BlobPart],{type:artifact.mimeType}));urls.add(url)
    const anchor=document.createElement('a');anchor.href=url;anchor.download=artifact.fileName;anchor.hidden=true;options.container.append(anchor)
    try{anchor.click()}finally{anchor.remove()}
    setTimeout(()=>{URL.revokeObjectURL(url);urls.delete(url)},60_000)
    return true
   }catch(error){options.onError(error);return false}finally{busy=false}
  },
  dispose(){disposed=true;for(const url of urls)URL.revokeObjectURL(url);urls.clear()},
 }
}

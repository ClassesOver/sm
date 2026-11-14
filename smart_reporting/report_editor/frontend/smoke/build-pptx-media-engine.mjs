// 隔离验收引擎：全部 workspace 包显式指向本次源码，禁止改共享 dist。
import {build} from '../../../reporting/slides_engine/node_modules/esbuild/lib/main.js'
import {readdir,readFile,mkdir,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {resolve,dirname} from 'node:path'
import {fileURLToPath} from 'node:url'
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../../../reporting/slides_engine')
assertTarget()
function assertTarget(){if(!process.env.PPTX_MEDIA_ENGINE_TARGET)throw Error('请显式指定 PPTX_MEDIA_ENGINE_TARGET（不得指向共享引擎目录）')}
const target=resolve(process.env.PPTX_MEDIA_ENGINE_TARGET)
if(target===root||target.startsWith(root+'/'))throw Error('不得写共享引擎目录')
const alias={}
for(const directory of await readdir(root+'/packages')){
 try{const p=JSON.parse(await readFile(root+'/packages/'+directory+'/package.json','utf8'));for(const [key,value] of Object.entries(p.exports??{})){if(typeof value==='string')alias[p.name+(key==='.'?'':'/'+key.slice(2))]=root+'/packages/'+directory+'/'+value}}catch{}
}
await mkdir(target+'/dist',{recursive:true})
const result=await build({absWorkingDir:root,entryPoints:['bridge/edit-pptx.ts','bridge/render-pptx.ts'],bundle:true,platform:'node',format:'esm',loader:{'.md':'text'},outdir:target+'/dist',outExtension:{'.js':'.mjs'},alias,metafile:true,banner:{js:"import {createRequire} from 'node:module'; const require=createRequire(import.meta.url);"}})
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),inputs=[]
for(const input of Object.keys(result.metafile.inputs)){const path=resolve(root,input.replace(/\?.*$/,''));inputs.push({input,path,sha256:sha(await readFile(path))})}
await writeFile(target+'/bundle-identities.json',JSON.stringify({aliases:alias,inputs,outputs:await Promise.all(['edit-pptx.mjs','render-pptx.mjs'].map(async name=>({name,sha256:sha(await readFile(target+'/dist/'+name))})))},null,2))

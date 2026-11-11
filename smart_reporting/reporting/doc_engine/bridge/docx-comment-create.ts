/** 新线程只从授权原 bytes 建立范围身份；不使用 saveDocx 重建整族批注。 */
import {createHash} from 'node:crypto'
import {XMLBuilder} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {attrsOf,childrenOf,nameOf,textOf,xmlParser,type XNode} from '../packages/docx-engine/src/xml-utils.ts'
import {readTrustedDocxComments,parseCommentSourceXml} from './docx-comment-source.ts'
const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main',W14='http://schemas.microsoft.com/office/word/2010/wordml',W15='http://schemas.microsoft.com/office/word/2012/wordml'
const R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const MAIN='word/document.xml',COMMENTS='word/comments.xml',RELS='word/_rels/document.xml.rels'
const hash=(s:string|Uint8Array)=>createHash('sha256').update(s).digest('hex')
const fail=(s:string):never=>{throw new Error('docx_comment_create_'+s)}
const builder=new XMLBuilder({preserveOrder:true,ignoreAttributes:false,attributeNamePrefix:'',format:false,suppressEmptyNode:true})
const node=(name:string,attrs:Record<string,string>={},children:XNode[]=[]):XNode=>({[name]:children,...(Object.keys(attrs).length?{':@':attrs}:{})})
const xml=(nodes:XNode[])=>builder.build(nodes) as string
interface Slice {name:string;xml:string;start:number}
function open(s:Slice){return s.xml.match( /^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail('xml_slice')}
function children(s:Slice):Slice[]{
 const o=open(s);if(o.endsWith('/>'))return[]
 const inner=s.xml.slice(o.length,s.xml.lastIndexOf('</')),parts=splitXmlChildren(inner)
 if(parts.map(p=>p.xml).join('').replace(/\s/g,'')!==inner.replace(/\s/g,''))fail('xml_slice')
 let at=o.length
 return parts.map(p=>{const i=s.xml.indexOf(p.xml,at);at=i+p.xml.length;return{...p,start:s.start+i}})
}
function rootSlice(raw:string,name:string):Slice{const start=raw.indexOf('<'+name);if(start<0)fail('root');return{name,start,xml:raw.slice(start)}}
function append(raw:string,name:string,addition:string):string{
 const s=rootSlice(raw,name),o=open(s)
 return o.endsWith('/>')?raw.slice(0,s.start)+o.slice(0,-2)+'>'+addition+'</'+name+'>':raw.slice(0,raw.lastIndexOf('</'+name+'>'))+addition+raw.slice(raw.lastIndexOf('</'+name+'>'))
}
function rootNamespace(raw:string,name:string,prefix:string,uri:string):string{
 const s=rootSlice(raw,name),root=parseCommentSourceXml(raw),a=attrsOf(root)
 if(a['xmlns:'+prefix]&&a['xmlns:'+prefix]!==uri)fail('namespace')
 if(a['xmlns:'+prefix]===uri)return raw
 const replacement=xml([node(name,{...a,['xmlns:'+prefix]:uri})]),opening=replacement.slice(0,replacement.indexOf('>')+1)
 return raw.slice(0,s.start)+opening.replace(/\/>$/,'>')+s.xml.slice(open(s).length).replace(/^$/,'</'+name+'>')
}
export interface CommentCreationTarget {targetId:string;blockIndex:number;paragraphOrdinal:number;expectedParagraphSha256:string;text:string;readOnlyReason:string|null}
export interface CommentCreationModel {sourceSha256:string;sourceId:string|null;targets:CommentCreationTarget[];readOnlyReason:string|null}
export interface CommentCreationRange {targetId:string;expectedParagraphSha256:string;from:number;to:number;text:string}
export interface CommentCreationOperation {kind:'createComment';sourceId:string;clientId:string;author:string;date:string;text:string;ranges:CommentCreationRange[]}
interface Paragraph extends CommentCreationTarget {slice:Slice;runs:{slice:Slice;node:XNode;text:string;from:number;to:number}[]}
async function source(bytes:Uint8Array){
 const trusted=await readTrustedDocxComments(bytes,true),documentXml=await trusted.zip.file(MAIN)!.async('string'),root=rootSlice(documentXml,'w:document')
 const body=children(root).find(p=>p.name==='w:body')??fail('body'),paragraphs:Paragraph[]=[]
 const blocks=children(body)
 for(const [blockIndex,block] of blocks.entries()){
  let ordinal=0
  function walk(s:Slice,path:string[]){
   if(s.name==='w:p'){
    const target:Paragraph={slice:s,runs:[],blockIndex,paragraphOrdinal:ordinal++,expectedParagraphSha256:hash(s.xml),targetId:hash(JSON.stringify([trusted.sourceId,blockIndex,ordinal-1,hash(s.xml)])),text:'',readOnlyReason:null}
    if(path.some(n=>!['w:tbl','w:tr','w:tc'].includes(n)))target.readOnlyReason='复杂正文包装暂不支持精确批注锚点'
    for(const c of children(s)){
     if(['w:pPr','w:commentRangeStart','w:commentRangeEnd','w:bookmarkStart','w:bookmarkEnd','w:proofErr'].includes(c.name))continue
     if(c.name!=='w:r'){target.readOnlyReason='域、超链接、修订或绘图内的复杂锚点暂不支持';continue}
     const n=(xmlParser.parse(c.xml) as XNode[])[0],cs=childrenOf(n),texts=cs.filter(n=>nameOf(n)==='w:t')
     if(cs.every(n=>['w:rPr','w:commentReference'].includes(nameOf(n)??'')))continue
     if(texts.length!==1||cs.some(n=>!['w:rPr','w:t'].includes(nameOf(n)??''))){target.readOnlyReason='内联对象、域或控制字符暂不支持精确批注锚点';continue}
     const t=textOf(texts[0]),from=target.text.length;target.text+=t;target.runs.push({slice:c,node:n,text:t,from,to:target.text.length})
    }
    paragraphs.push(target);return
   }
   for(const c of children(s))if(['w:p','w:tbl','w:tr','w:tc','w:sdt','w:sdtContent'].includes(c.name))walk(c,[...path,s.name])
  }
  walk(block,[])
 }
 return{...trusted,documentXml,paragraphs}
}
export async function inspectDocxCommentCreation(bytes:Uint8Array):Promise<CommentCreationModel>{
 try{const s=await source(bytes);return{sourceSha256:s.sourceSha256,sourceId:s.sourceId,targets:s.paragraphs.map(({slice,runs,...t})=>t),readOnlyReason:null}}
 catch(e){return{sourceSha256:hash(bytes),sourceId:null,targets:[],readOnlyReason:e instanceof Error?e.message:'docx_comment_create_invalid'}}
}
function validText(t:unknown,max:number):t is string{
 if(typeof t!=='string'||t.length>max||t.includes('\r'))return false
 return [...t].every(c=>{const n=c.codePointAt(0)!;return n===9||n===10||n>=32&&n<=0xd7ff||n>=0xe000&&n<=0xfffd||n>=0x10000&&n<=0x10ffff})
}
function boundary(t:string,n:number){return Number.isSafeInteger(n)&&n>=0&&n<=t.length&&!(n>0&&n<t.length&&/[\uD800-\uDBFF]/.test(t[n-1])&&/[\uDC00-\uDFFF]/.test(t[n]))}
function keys(value:unknown,expected:string[]):value is Record<string,unknown>{return !!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join('|')===expected.sort().join('|')}
function splitRun(run:Paragraph['runs'][number],from:number,to:number):string{
 const n=structuredClone(run.node),t=childrenOf(n).find(c=>nameOf(c)==='w:t')!
 t['w:t']=[{'#text':run.text.slice(from-run.from,to-run.from)}];t[':@']={...attrsOf(t),'xml:space':'preserve'}
 return xml([n])
}
export async function patchDocxCommentCreation(bytes:Uint8Array,operations:readonly CommentCreationOperation[]):Promise<Uint8Array>{
 const s=await source(bytes)
 if(!Array.isArray(operations)||!operations.length||operations.length>100)fail('operations')
 const clients=new Set<string>(),plans:{operation:CommentCreationOperation;paragraphs:Paragraph[]}[]=[]
 for(const op of operations){
  if(!keys(op,['kind','sourceId','clientId','author','date','text','ranges'])||op.kind!=='createComment'||op.sourceId!==s.sourceId||typeof op.clientId!=='string'||!/^[-\w]{1,128}$/.test(op.clientId)||clients.has(op.clientId)||!validText(op.author,255)||!op.author.trim()||!validText(op.text,65536)||!op.text.trim()||typeof op.date!=='string'||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(op.date)||!Number.isFinite(Date.parse(op.date))||new Date(op.date).toISOString().replace(/\.\d{3}Z$/,'Z')!==op.date||!Array.isArray(op.ranges)||!op.ranges.length||op.ranges.length>500)fail('operation')
  clients.add(op.clientId);const ps:Paragraph[]=[]
  for(const [i,r] of op.ranges.entries()){
   if(!keys(r,['targetId','expectedParagraphSha256','from','to','text']))fail('range')
   const p=s.paragraphs.find(p=>p.targetId===r.targetId)
   if(!p||p.readOnlyReason||r.expectedParagraphSha256!==p.expectedParagraphSha256||!boundary(p.text,r.from)||!boundary(p.text,r.to)||(r.from>r.to||r.from===r.to&&!(p.text.length===0&&i>0&&i<op.ranges.length-1))||r.text!==p.text.slice(r.from,r.to))fail('range_identity')
   if(i&&(s.paragraphs.indexOf(p)!==s.paragraphs.indexOf(ps[i-1])+1||r.from!==0||op.ranges[i-1].to!==ps[i-1].text.length))fail('range_continuity')
   ps.push(p)
  }
  plans.push({operation:op,paragraphs:ps})
 }
 const {usedIds,usedHex}=await commentPackageIdentities(s.zip),relationshipIds=new Set<string>()
 const relXml=await s.zip.file(RELS)!.async('string');childrenOf(parseCommentSourceXml(relXml)).forEach(n=>relationshipIds.add(attrsOf(n).Id))
 let id=0,hexId=1
 const minted=plans.map(plan=>{while(usedIds.has(String(id)))id++;const next=String(id++);usedIds.add(next);while(usedHex.has(hexId.toString(16).padStart(8,'0').toUpperCase()))hexId++;const paraId=hexId++.toString(16).padStart(8,'0').toUpperCase();usedHex.add(paraId);return{...plan,id:next,paraId}})
 const events=new Map<Paragraph,{at:number;fragment:string}[]>()
 for(const plan of minted){
  const first=plan.paragraphs[0],last=plan.paragraphs.at(-1)!,start=events.get(first)??[],end=first===last?start:events.get(last)??[]
  start.push({at:plan.operation.ranges[0].from,fragment:xml([node('w:commentRangeStart',{'w:id':plan.id})])});events.set(first,start)
  end.push({at:plan.operation.ranges.at(-1)!.to,fragment:xml([node('w:commentRangeEnd',{'w:id':plan.id}),node('w:r',{},[node('w:commentReference',{'w:id':plan.id})])])});events.set(last,end)
 }
 const replacements:{start:number;length:number;value:string}[]=[]
 for(const [p,list] of events){
  const emitted=new Set<number>(),pieces:string[]=[];const emit=(at:number)=>{if(emitted.has(at))return;emitted.add(at);pieces.push(...list.filter(e=>e.at===at).map(e=>e.fragment))}
  for(const c of children(p.slice)){
   const run=p.runs.find(r=>r.slice.start===c.start)
   if(!run){pieces.push(c.xml);continue}
   const cuts=[...new Set([run.from,run.to,...list.filter(e=>e.at>=run.from&&e.at<=run.to).map(e=>e.at)])].sort((a,b)=>a-b)
   emit(run.from)
   for(let i=0;i<cuts.length-1;i++){pieces.push(cuts.length===2?c.xml:splitRun(run,cuts[i],cuts[i+1]));emit(cuts[i+1])}
  }
  if(list.some(e=>!emitted.has(e.at)))fail('range_anchor')
  replacements.push({start:p.slice.start,length:p.slice.xml.length,value:open(p.slice)+pieces.join('')+'</w:p>'})
 }
 let document=s.documentXml
 for(const r of replacements.sort((a,b)=>b.start-a.start))document=document.slice(0,r.start)+r.value+document.slice(r.start+r.length)
 let comments=s.zip.file(COMMENTS)?await s.zip.file(COMMENTS)!.async('string'):xml([node('w:comments',{'xmlns:w':W})])
 comments=rootNamespace(comments,'w:comments','w14',W14)
 for(const plan of minted){const lines=plan.operation.text.split('\n');comments=append(comments,'w:comments',xml([node('w:comment',{'w:id':plan.id,'w:author':plan.operation.author,'w:date':plan.operation.date},lines.map((line,i)=>node('w:p',i===lines.length-1?{'w14:paraId':plan.paraId}:{},[node('w:r',{},[node('w:t',{'xml:space':'preserve'},[{'#text':line}])])])))]))}
 const changed=new Map([[MAIN,document],[COMMENTS,comments]])
 if(!s.zip.file(COMMENTS)){
  let n=1;while(relationshipIds.has('rId'+n))n++
  changed.set(RELS,append(relXml,'Relationships',xml([node('Relationship',{Id:'rId'+n,Type:R+'/comments',Target:'comments.xml'})])))
  const types=await s.zip.file('[Content_Types].xml')!.async('string');changed.set('[Content_Types].xml',append(types,'Types',xml([node('Override',{PartName:'/word/comments.xml',ContentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'})])))
 }
 // 固定源新线程无 parent；仅扩展已知 commentsEx，未知现代元数据原字节保留。
 const ex=s.zip.file('word/commentsExtended.xml')
 if(ex){const raw=await ex.async('string'),root=parseCommentSourceXml(raw);if(nameOf(root)==='w15:commentsEx'&&attrsOf(root)['xmlns:w15']===W15){let next=raw;for(const p of minted)next=append(next,'w15:commentsEx',xml([node('w15:commentEx',{'w15:paraId':p.paraId,'w15:done':'0'})]));changed.set(ex.name,next)}}
 for(const [path,value] of changed){parseCommentSourceXml(value);s.zip.file(path,value,{createFolders:false})}
 const output=await s.zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
 const reopened=await inspectDocxCommentCreation(output);if(reopened.readOnlyReason)fail('output_'+reopened.readOnlyReason)
 return output
}

/** 回复与新根线程共用实际 XML/content-type 身份避碰，不重建既有元数据。 */
export async function commentPackageIdentities(zip:Awaited<ReturnType<typeof source>>['zip']){
 const usedIds=new Set<string>(),usedHex=new Set<string>()
 const contentTypes=childrenOf(parseCommentSourceXml(await zip.file('[Content_Types].xml')!.async('string')))
 const xmlPart=(path:string)=>{const type=contentTypes.find(n=>nameOf(n)==='Override'&&attrsOf(n).PartName==='/'+path)??contentTypes.find(n=>nameOf(n)==='Default'&&attrsOf(n).Extension===path.split('.').at(-1));const value=type?attrsOf(type).ContentType:'';return /\.(xml|rels)$/i.test(path)||value==='application/xml'||value?.endsWith('+xml')}
 for(const f of Object.values(zip.files))if(!f.dir&&xmlPart(f.name)){
  const root=parseCommentSourceXml(await f.async('string'))
  const scan=(n:XNode)=>{for(const [k,v] of Object.entries(attrsOf(n))){if(k.split(':').at(-1)==='id'&&/^\d+$/.test(v))usedIds.add(String(BigInt(v)));if(/(?:paraId|durableId|paraIdParent)$/.test(k))usedHex.add(v.toUpperCase())}childrenOf(n).forEach(scan)};scan(root)
 }
 return{usedIds,usedHex}
}
export {source as readDocxCommentCreationSource}
export const commentCreationXml={children,append,rootNamespace,rootSlice,open,node,xml}

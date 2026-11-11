/** 书签只改授权 document.xml 的范围标记；不经 saveDocx 重建段落或其它 ZIP 部件。 */
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {assertZipInflatesWithinLimits,loadDocxZip} from '../packages/docx-engine/src/zip-load.ts'
import {resolveRelationshipTargetPath} from '../packages/docx-engine/src/parse-package.ts'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {attrsOf,childrenOf,nameOf,textOf,xmlParser,type XNode} from '../packages/docx-engine/src/xml-utils.ts'
import {assertZipIdentity,parseCommentSourceXml} from './docx-comment-source.ts'
export interface DocxBookmarkRange {targetId:string;expectedParagraphSha256:string;from:number;to:number;text:string}
export interface DocxBookmarkTarget {targetId:string;blockIndex:number;paragraphOrdinal:0;expectedParagraphSha256:string;text:string;readOnlyReason:string|null}
export interface DocxBookmarkEntry {bookmarkId:string;name:string;ranges:DocxBookmarkRange[];readOnlyReason:string|null}
export interface DocxBookmarksModel {sourceSha256:string;sourceId:string|null;targets:DocxBookmarkTarget[];bookmarks:DocxBookmarkEntry[];readOnlyReason:string|null}
export type DocxBookmarkOperation = {kind:'createBookmark';sourceId:string;name:string;ranges:DocxBookmarkRange[]}|{kind:'deleteBookmark';sourceId:string;bookmarkId:string}
const W='http://schemas.openxmlformats.org/wordprocessingml/2006/main',R='http://schemas.openxmlformats.org/officeDocument/2006/relationships',P='http://schemas.openxmlformats.org/package/2006/relationships',MAIN='word/document.xml'
const hash=(v:string|Uint8Array)=>createHash('sha256').update(v).digest('hex'),fail=(s:string):never=>{throw new Error('docx_bookmark_'+s)}
const exact=(o:unknown,keys:string[]):o is Record<string,unknown>=>!!o&&typeof o==='object'&&!Array.isArray(o)&&Object.keys(o).sort().join('|')===keys.sort().join('|')
const validName=(n:unknown):n is string=>typeof n==='string'&&n.length<=40&&/^[A-Za-z_一-鿿][\w一-鿿]*$/.test(n)
const boundary=(t:string,n:unknown):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0&&n<=t.length&&!(n>0&&n<t.length&&/[\uD800-\uDBFF]/.test(t[n-1])&&/[\uDC00-\uDFFF]/.test(t[n]))
interface Slice {name:string;xml:string;start:number}
interface Run {slice:Slice;from:number;to:number;text:string;textSlice:Slice}
interface Paragraph {slice:Slice;target:DocxBookmarkTarget;runs:Run[]}
interface Mark {slice:Slice;kind:'start'|'end';id:string;name:string;paragraph?:Paragraph;offset:number;safe:boolean}
const opening=(s:Slice)=>s.xml.match(/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail('xml_slice')
function children(s:Slice):Slice[]{
 const o=opening(s);if(o.endsWith('/>'))return[]
 const inner=s.xml.slice(o.length,s.xml.lastIndexOf('</')),parts=splitXmlChildren(inner)
 if(parts.map(p=>p.xml).join('').replace(/\s/g,'')!==inner.replace(/\s/g,''))fail('xml_slice')
 let at=o.length;return parts.map(p=>{const i=s.xml.indexOf(p.xml,at);at=i+p.xml.length;return{...p,start:s.start+i}})
}
// 全文已验证命名空间；这里读取继承根命名空间的原始片段。
const parsed=(s:Slice)=>(xmlParser.parse(s.xml) as XNode[])[0]
function root(raw:string,name:string):Slice{const start=raw.indexOf('<'+name);if(start<0)fail('xml_root');return{name,start,xml:raw.slice(start)}}
function rels(raw:string){
 const n=parseCommentSourceXml(raw);if(nameOf(n)!=='Relationships'||attrsOf(n).xmlns!==P)fail('relationships')
 const entries=childrenOf(n).filter(c=>nameOf(c)),ids=new Set<string>()
 return entries.map(c=>{const a=attrsOf(c);if(nameOf(c)!=='Relationship'||!a.Id||ids.has(a.Id)||!a.Type||!a.Target||a.TargetMode&&a.TargetMode!=='External')fail('relationships');ids.add(a.Id);return a})
}
async function source(bytes:Uint8Array){
 if(!(bytes instanceof Uint8Array)||!bytes.length||bytes.length>24*1024*1024)fail('bytes')
 await assertZipInflatesWithinLimits(bytes,{maxParts:2000,maxPartBytes:8*1024*1024,maxTotalBytes:64*1024*1024});assertZipIdentity(bytes)
 const zip=await JSZip.loadAsync(bytes,{checkCRC32:true}),normalized=await loadDocxZip(bytes)
 for(const f of Object.values(zip.files))if(!f.dir){const actual=await f.async('uint8array'),loaded=await normalized.file(f.name)?.async('uint8array');if(!loaded||!Buffer.from(actual).equals(Buffer.from(loaded)))fail('normalization_required')}
 const read=async(path:string)=>{const f=zip.file(path);if(!f)fail('part_missing');try{return new TextDecoder('utf-8',{fatal:true}).decode(await f!.async('uint8array'))}catch{fail('xml_encoding')}}
 const office=rels(await read('_rels/.rels')).filter(a=>a.Type===R+'/officeDocument')
 if(office.length!==1||office[0].TargetMode||resolveRelationshipTargetPath('',office[0].Target)!==MAIN)fail('main_part')
 const documentXml=await read(MAIN),document=parseCommentSourceXml(documentXml)
 if(nameOf(document)!=='w:document'||attrsOf(document)['xmlns:w']!==W)fail('namespace')
 const sourceSha256=hash(bytes),sourceId=hash(JSON.stringify([sourceSha256,MAIN,hash(documentXml)]))
 let reason:string|null=null
 const settings=rels(await read('word/_rels/document.xml.rels')).filter(a=>a.Type===R+'/settings')
 if(settings.length>1)fail('settings_ambiguous')
 if(settings.length){if(settings[0].TargetMode)fail('settings_external');const path=resolveRelationshipTargetPath(MAIN,settings[0].Target);if(!path)fail('settings_path');const n=parseCommentSourceXml(await read(path!))
  const scan=(node:XNode,inherited:Record<string,string>)=>{const a=attrsOf(node),ns={...inherited};for(const [k,v] of Object.entries(a))if(k==='xmlns'||k.startsWith('xmlns:'))ns[k==='xmlns'?'':k.slice(6)]=v
   const parts=(nameOf(node)??'').split(':');if(parts.at(-1)==='documentProtection'&&ns[parts.length===2?parts[0]:'']===W){const enforcement=Object.entries(a).find(([k])=>k.split(':')[1]==='enforcement'&&ns[k.split(':')[0]]===W)?.[1];if(!['0','false','off'].includes(enforcement??''))reason='文档受保护，书签仅供查看'}childrenOf(node).forEach(c=>scan(c,ns))};scan(n,{})
 }else if(zip.file('word/settings.xml'))fail('settings_ambiguous')
 const bodies=children(root(documentXml,'w:document')).filter(s=>s.name==='w:body');if(bodies.length!==1)fail('body')
 const blocks=children(bodies[0]),paragraphs:Paragraph[]=[],marks:Mark[]=[]
 function mark(s:Slice,p?:Paragraph,offset=0,direct=false){const n=parsed(s),a=attrsOf(n),isStart=s.name==='w:bookmarkStart',id=a['w:id']??''
  const valid=/^\d+$/.test(id),attrs=isStart?['w:id','w:name']:['w:id']
  marks.push({slice:s,kind:isStart?'start':'end',id:valid?String(BigInt(id)):id,name:isStart?a['w:name']??'':'',paragraph:p,offset,safe:direct&&valid&&Object.keys(a).every(k=>attrs.includes(k))&&!childrenOf(n).length})
  if(!valid)reason='书签身份不合法，当前文件仅供查看'
 }
 function scanComplex(s:Slice){if(s.name==='w:bookmarkStart'||s.name==='w:bookmarkEnd'){mark(s);return}if(!childrenOf(parsed(s)).some(n=>nameOf(n)))return;for(const c of children(s))scanComplex(c)}
 for(const [blockIndex,b] of blocks.entries()){
  if(b.name!=='w:p'){scanComplex(b);continue}
  const p:Paragraph={slice:b,runs:[],target:{targetId:hash(JSON.stringify([sourceId,blockIndex,hash(b.xml)])),blockIndex,paragraphOrdinal:0,expectedParagraphSha256:hash(b.xml),text:'',readOnlyReason:null}}
  for(const c of children(b)){
   if(['w:bookmarkStart','w:bookmarkEnd'].includes(c.name)){mark(c,p,p.target.text.length,true);continue}
   if(['w:pPr','w:proofErr','w:commentRangeStart','w:commentRangeEnd'].includes(c.name))continue
   if(c.name!=='w:r'){p.target.readOnlyReason='域、链接、修订或复杂包装内的锚点只读';scanComplex(c);continue}
   const cs=children(c),texts=cs.filter(c=>c.name==='w:t')
   if(cs.every(c=>['w:rPr','w:commentReference'].includes(c.name)))continue
   if(texts.length!==1||cs.some(c=>!['w:rPr','w:t'].includes(c.name))){p.target.readOnlyReason='包含域、内联对象或控制符的段落只读';scanComplex(c);continue}
   const t=textOf(parsed(texts[0])),from=p.target.text.length;p.target.text+=t;p.runs.push({slice:c,textSlice:texts[0],from,to:p.target.text.length,text:t})
  }
  paragraphs.push(p)
 }
 // 未知/别名 Word 端点与局部改绑不能被当作普通文本锚点遗漏。
 let actualMarks=0
 const inspectNames=(n:XNode,ns:Record<string,string>)=>{const a=attrsOf(n),next={...ns};for(const [k,v]of Object.entries(a))if(k.startsWith('xmlns:'))next[k.slice(6)]=v;const q=(nameOf(n)??'').split(':');if(['bookmarkStart','bookmarkEnd'].includes(q.at(-1)!)&&next[q.length===2?q[0]:'']===W){actualMarks++;if(q[0]!=='w')reason='书签命名空间别名暂不支持编辑'};childrenOf(n).forEach(c=>inspectNames(c,next))};inspectNames(document,{})
 if(actualMarks!==marks.length)reason='未核验的复杂书签端点，当前文件仅供查看'
 const starts=marks.filter(m=>m.kind==='start'),ids=new Set<string>(),names=new Set<string>(),bookmarks:DocxBookmarkEntry[]=[]
 for(const start of starts){const ends=marks.filter(m=>m.kind==='end'&&m.id===start.id),same=starts.filter(m=>m.id===start.id)
  if(ids.has(start.id)||names.has(start.name)||same.length!==1||ends.length!==1||!start.name)reason='书签名称、范围身份重复或端点缺失，当前文件仅供查看'
  ids.add(start.id);names.add(start.name)
  const end=ends[0],first=start.paragraph,last=end?.paragraph,a=first?paragraphs.indexOf(first):-1,b=last?paragraphs.indexOf(last):-1
  let readOnlyReason:string|null=!start.safe||!end?.safe||!first||!last||a>b||start.slice.start>end.slice.start?'复杂或不完整书签范围仅供查看':null
  const selected=a>=0&&b>=a?paragraphs.slice(a,b+1):[]
  if(selected.some((p,i)=>p.target.readOnlyReason||i>0&&p.target.blockIndex!==selected[i-1].target.blockIndex+1))readOnlyReason='书签跨越复杂或非普通正文对象，仅供查看'
  const ranges=selected.map((p,i)=>({targetId:p.target.targetId,expectedParagraphSha256:p.target.expectedParagraphSha256,from:i?0:start.offset,to:i===selected.length-1?end.offset:p.target.text.length,text:p.target.text.slice(i?0:start.offset,i===selected.length-1?end.offset:p.target.text.length)}))
  bookmarks.push({bookmarkId:hash(JSON.stringify([sourceId,start.id,start.slice.start,end?.slice.start??null])),name:start.name,ranges,readOnlyReason})
 }
 if(marks.some(m=>m.kind==='end'&&!starts.some(s=>s.id===m.id)))reason='书签结束端点没有唯一来源，当前文件仅供查看'
 const model:DocxBookmarksModel={sourceSha256,sourceId,targets:paragraphs.map(p=>p.target),bookmarks,readOnlyReason:reason}
 return{zip,documentXml,model,paragraphs,marks,starts}
}
export async function inspectDocxBookmarks(bytes:Uint8Array):Promise<DocxBookmarksModel>{try{return(await source(bytes)).model}catch(e){return{sourceSha256:hash(bytes),sourceId:null,targets:[],bookmarks:[],readOnlyReason:e instanceof Error?e.message:'docx_bookmark_source_invalid'}}}
function rangesOf(value:unknown,s:Awaited<ReturnType<typeof source>>):{range:DocxBookmarkRange;p:Paragraph}[]{
 if(!Array.isArray(value)||!value.length||value.length>500)fail('ranges')
 return value.map((r,i)=>{if(!exact(r,['targetId','expectedParagraphSha256','from','to','text']))fail('range')
  const p=s.paragraphs.find(p=>p.target.targetId===r.targetId),t=p?.target
  if(!p||!t||t.readOnlyReason||r.expectedParagraphSha256!==t.expectedParagraphSha256||!boundary(t.text,r.from)||!boundary(t.text,r.to)||r.from>r.to||r.from===r.to&&!(t.text.length===0&&i>0&&i<value.length-1)||r.text!==t.text.slice(r.from,r.to))fail('range_identity')
  if(i){const prev=value[i-1],pt=s.paragraphs.find(p=>p.target.targetId===prev.targetId)!.target;if(t.blockIndex!==pt.blockIndex+1||r.from!==0||prev.to!==pt.text.length)fail('range_continuity')}
  return{range:r as unknown as DocxBookmarkRange,p:p!}
 })
}
const escape=(s:string)=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')
function splitRun(r:Run,a:number,b:number){const relative=r.textSlice.start-r.slice.start,o=opening(r.textSlice).replace(/\s+xml:space\s*=\s*(?:"[^"]*"|'[^']*')/g,'').replace(/>$/,' xml:space="preserve">');return r.slice.xml.slice(0,relative)+o+escape(r.text.slice(a-r.from,b-r.from))+'</w:t>'+r.slice.xml.slice(relative+r.textSlice.xml.length)}
export async function patchDocxBookmarks(bytes:Uint8Array,operations:readonly DocxBookmarkOperation[]):Promise<Uint8Array>{
 const s=await source(bytes);if(s.model.readOnlyReason||!s.model.sourceId)fail('source_readonly')
 if(!Array.isArray(operations)||!operations.length||operations.length>100)fail('operations')
 const names=new Set(s.starts.map(m=>m.name)),deletions=new Set<string>(),events=new Map<Paragraph,{at:number;xml:string}[]>(),remove=new Set<Mark>()
 let id=s.marks.reduce((n,m)=>/^\d+$/.test(m.id)&&BigInt(m.id)>=n?BigInt(m.id)+1n:n,0n)
 for(const op of operations){
  if(op?.sourceId!==s.model.sourceId)fail('source_identity')
  if(op.kind==='createBookmark'){
   if(!exact(op,['kind','sourceId','name','ranges'])||!validName(op.name)||names.has(op.name))fail('name');names.add(op.name)
   const ranges=rangesOf(op.ranges,s),first=ranges[0],last=ranges.at(-1)!,next=String(id++)
   for(const [p,at,xml]of [[first.p,first.range.from,`<w:bookmarkStart w:id="${next}" w:name="${escape(op.name)}"/>`],[last.p,last.range.to,`<w:bookmarkEnd w:id="${next}"/>`]] as const){const list=events.get(p)??[];list.push({at,xml});events.set(p,list)}
  }else if(op.kind==='deleteBookmark'){
   if(!exact(op,['kind','sourceId','bookmarkId'])||deletions.has(op.bookmarkId))fail('delete_identity');deletions.add(op.bookmarkId)
   const index=s.model.bookmarks.findIndex(b=>b.bookmarkId===op.bookmarkId),b=s.model.bookmarks[index];if(!b||b.readOnlyReason)fail('delete_readonly')
   const start=s.starts[index];s.marks.filter(m=>m.id===start.id).forEach(m=>remove.add(m))
  }else fail('operation_kind')
 }
 const changes:{at:number;length:number;value:string}[]=[]
 for(const p of s.paragraphs){const list=events.get(p)??[],removed=s.marks.filter(m=>m.paragraph===p&&remove.has(m));if(!list.length&&!removed.length)continue
  const emitted=new Set<number>(),emit=(at:number)=>{if(emitted.has(at))return'';emitted.add(at);return list.filter(e=>e.at===at).map(e=>e.xml).join('')},pieces:string[]=[]
  for(const c of children(p.slice)){if(removed.some(m=>m.slice.start===c.start))continue;const r=p.runs.find(r=>r.slice.start===c.start)
   if(!r){pieces.push(c.xml);continue}
   const cuts=[...new Set([r.from,r.to,...list.filter(e=>e.at>=r.from&&e.at<=r.to).map(e=>e.at)])].sort((a,b)=>a-b);pieces.push(emit(r.from))
   for(let i=0;i<cuts.length-1;i++){pieces.push(cuts.length===2?c.xml:splitRun(r,cuts[i],cuts[i+1]));pieces.push(emit(cuts[i+1]))}
  }
  if(list.some(e=>!emitted.has(e.at)))fail('range_anchor')
  changes.push({at:p.slice.start,length:p.slice.xml.length,value:opening(p.slice)+pieces.join('')+'</w:p>'})
 }
 let output=s.documentXml;for(const c of changes.sort((a,b)=>b.at-a.at))output=output.slice(0,c.at)+c.value+output.slice(c.at+c.length)
 parseCommentSourceXml(output);s.zip.file(MAIN,output,{createFolders:false});const bytesOut=await s.zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
 const reopened=await inspectDocxBookmarks(bytesOut);if(reopened.readOnlyReason)fail('output_readonly');return bytesOut
}

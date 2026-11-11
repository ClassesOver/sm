/** 仅插入可信单段书签 REF；不重建段落或其它 ZIP 部件。 */
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {XMLParser} from 'fast-xml-parser'
import {decodeNumericCharRefs} from '../packages/docx-engine/src/parse-xml-text.ts'
import {splitXmlChildren} from '../packages/docx-engine/src/generate.ts'
import {attrsOf,childrenOf,nameOf,textOf,xmlParser,type XNode} from '../packages/docx-engine/src/xml-utils.ts'
import {parseCommentSourceXml} from './docx-comment-source.ts'
import {inspectDocxBookmarks,type DocxBookmarksModel} from './docx-bookmarks.ts'
export type DocxCrossReferencesModel=DocxBookmarksModel
export interface DocxCrossReferenceOperation {kind:'insertCrossReference';sourceId:string;bookmarkId:string;targetId:string;expectedParagraphSha256:string;offset:number}
const MAIN='word/document.xml',W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const hash=(v:string|Uint8Array)=>createHash('sha256').update(v).digest('hex')
const fail=(s:string):never=>{throw new Error('docx_cross_reference_'+s)}
const boundary=(t:string,n:unknown):n is number=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0&&n<=t.length&&!(n>0&&n<t.length&&t.charCodeAt(n-1)>=0xd800&&t.charCodeAt(n-1)<=0xdbff&&t.charCodeAt(n)>=0xdc00&&t.charCodeAt(n)<=0xdfff)
const escape=(s:string)=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll(String.fromCharCode(34),'&quot;')
const validName=(n:string)=>n.length<=40&&/^[A-Za-z_一-鿿][A-Za-z_0-9一-鿿]*$/.test(n)
export async function inspectDocxCrossReferences(bytes:Uint8Array):Promise<DocxCrossReferencesModel>{
 const m=await inspectDocxBookmarks(bytes)
 for(const b of m.bookmarks)if(!b.readOnlyReason&&(b.ranges.length!==1||!b.ranges[0].text||!validName(b.name)))b.readOnlyReason='交叉引用仅支持名称合法且包含文字的单段普通书签'
 if(!m.readOnlyReason&&m.sourceId)try{
  const zip=await JSZip.loadAsync(bytes),names=new Set(m.bookmarks.map(b=>b.name));normalizeSourceText(m,await zip.file(MAIN)!.async('string'))
  for(const file of Object.values(zip.files)){if(file.dir||file.name===MAIN||!file.name.startsWith('word/')||!file.name.endsWith('.xml'))continue
   const root=parseCommentSourceXml(await file.async('string'))
   const scan=(n:XNode,ns:Record<string,string>)=>{const a=attrsOf(n),next={...ns};for(const[k,v]of Object.entries(a))if(k==='xmlns'||k.startsWith('xmlns:'))next[k==='xmlns'?'':k.slice(6)]=v
    const q=(nameOf(n)??'').split(':');if(q.at(-1)==='bookmarkStart'&&next[q.length===2?q[0]:'']===W){const value=Object.entries(a).find(([k])=>k.split(':').at(-1)==='name'&&next[k.split(':')[0]]===W)?.[1];if(value&&names.has(value))m.readOnlyReason='跨故事重复书签名称，交叉引用仅供查看'}childrenOf(n).forEach(c=>scan(c,next))};scan(root,{})
  }
 }catch{m.readOnlyReason='无法核验跨故事书签身份，交叉引用仅供查看'}
 return m
}
interface Slice {name:string;xml:string;start:number}
function opening(s:Slice){let quote='';for(let i=0;i<s.xml.length;i++){const c=s.xml[i];if(quote){if(c===quote)quote=''}else if(c===String.fromCharCode(34)||c===String.fromCharCode(39))quote=c;else if(c==='>')return s.xml.slice(0,i+1)}return fail('xml_slice')}
function children(s:Slice):Slice[]{const o=opening(s);if(o.endsWith('/>'))return[];const inner=s.xml.slice(o.length,s.xml.lastIndexOf('</')),parts=splitXmlChildren(inner);let at=o.length;return parts.map(p=>{const i=s.xml.indexOf(p.xml,at);if(i<0)fail('xml_slice');at=i+p.xml.length;return{...p,start:s.start+i}})}
function root(xml:string,name:string):Slice{const start=xml.indexOf('<'+name);if(start<0)fail('xml_root');return{name,start,xml:xml.slice(start)}}
function textOpening(s:Slice){
 const open=opening(s);let quote=''
 for(let i=0;i<open.length;i++){const c=open[i];if(quote){if(c===quote)quote='';continue}
  if(c===String.fromCharCode(34)||c===String.fromCharCode(39)){quote=c;continue}
  if(open.startsWith('xml:space',i)&&(open[i+9]==='='||open.charCodeAt(i+9)<=32)&&i>0&&open.charCodeAt(i-1)<=32){const equal=open.indexOf('=',i+9);let start=equal+1;while(open.charCodeAt(start)<=32)start++;if(equal<0||![String.fromCharCode(34),String.fromCharCode(39)].includes(open[start]))fail('text_space');const end=open.indexOf(open[start],start+1);if(end<0)fail('text_space');return open.slice(0,start+1)+'preserve'+open.slice(end)}
 }return open.slice(0,-1)+' xml:space="preserve">'
}
// 来源已由书签 inspect 严格验证，仅启用库的单次 XML 数字实体解码。
const textParser=new XMLParser({preserveOrder:true,ignoreAttributes:false,attributeNamePrefix:'',trimValues:false,parseTagValue:false,parseAttributeValue:false,htmlEntities:true})
const text=(s:Slice)=>textOf((textParser.parse(s.xml) as XNode[])[0])
function normalizeSourceText(m:DocxCrossReferencesModel,xml:string){
 const body=children(root(xml,'w:document')).find(s=>s.name==='w:body');if(!body)fail('body')
 const blocks=children(body!),maps=new Map<string,Map<number,number>>()
 for(const target of m.targets){if(target.readOnlyReason)continue;const p=blocks[target.blockIndex];if(!p||hash(p.xml)!==target.expectedParagraphSha256)fail('paragraph_identity')
  let legacy='',decoded='';const offsets=new Map<number,number>([[0,0]])
  for(const run of children(p)){if(run.name!=='w:r')continue;for(const t of children(run)){if(t.name!=='w:t')continue;legacy+=textOf((xmlParser.parse(t.xml) as XNode[])[0]);decoded+=text(t);offsets.set(legacy.length,decoded.length)}}
  if(legacy!==target.text)fail('paragraph_text_identity');if(decodeNumericCharRefs(legacy)!==decoded)m.readOnlyReason='当前编辑器对字面实体的投影与 Word 原文不一致，交叉引用仅供查看';target.text=decoded;maps.set(target.targetId,offsets)
 }
 for(const book of m.bookmarks)for(const range of book.ranges){const offsets=maps.get(range.targetId);if(!offsets)continue;const from=offsets.get(range.from),to=offsets.get(range.to),target=m.targets.find(t=>t.targetId===range.targetId)!;if(from==null||to==null){book.readOnlyReason='无法核验书签的字符边界';continue}range.from=from;range.to=to;range.text=target.text.slice(from,to)}
}

export async function patchDocxCrossReference(bytes:Uint8Array,operation:DocxCrossReferenceOperation):Promise<Uint8Array>{
 const m=await inspectDocxCrossReferences(bytes),op=operation
 if(m.readOnlyReason||!m.sourceId)fail('source_readonly')
 if(!op||typeof op!=='object'||Array.isArray(op)||Object.keys(op).sort().join('|')!==['kind','sourceId','bookmarkId','targetId','expectedParagraphSha256','offset'].sort().join('|')||op.kind!=='insertCrossReference'||op.sourceId!==m.sourceId)fail('operation_identity')
 const target=m.targets.find(t=>t.targetId===op.targetId),book=m.bookmarks.find(b=>b.bookmarkId===op.bookmarkId)
 if(!target||target.readOnlyReason||target.expectedParagraphSha256!==op.expectedParagraphSha256||!boundary(target.text,op.offset))fail('target_identity')
 if(!book||book.readOnlyReason||book.ranges.length!==1||!book.ranges[0].text||!validName(book.name))fail('bookmark_identity')
 if(m.bookmarks.some(b=>b.ranges.some(r=>r.targetId===target.targetId)))fail('target_bookmark_overlap')
 const zip=await JSZip.loadAsync(bytes,{checkCRC32:true}),xml=await zip.file(MAIN)!.async('string'),body=children(root(xml,'w:document')).find(s=>s.name==='w:body');if(!body)fail('body')
 const p=children(body!).at(target.blockIndex);if(!p||p.name!=='w:p'||hash(p.xml)!==target.expectedParagraphSha256)fail('paragraph_identity')
 const field='<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve">'+escape(' REF '+book.name+' '+String.fromCharCode(92)+'h ')+'</w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t xml:space="preserve">'+escape(book.ranges[0].text)+'</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
 let changed:string|undefined,offset=0
 for(const run of children(p!)){if(run.name!=='w:r')continue;const t=children(run).find(c=>c.name==='w:t');if(!t)continue;const value=text(t),end=offset+value.length
  if(op.offset>=offset&&op.offset<=end){const cut=op.offset-offset;let replacement:string
   if(cut===0)replacement=field+run.xml
   else if(cut===value.length)replacement=run.xml+field
   else {const rel=t.start-run.start,part=(v:string)=>run.xml.slice(0,rel)+textOpening(t)+escape(v)+'</w:t>'+run.xml.slice(rel+t.xml.length);replacement=part(value.slice(0,cut))+field+part(value.slice(cut))}
   const at=run.start-p!.start;changed=p!.xml.slice(0,at)+replacement+p!.xml.slice(at+run.xml.length);break
  }offset=end
 }
 if(changed===undefined&&target.text.length===0&&op.offset===0){const open=opening(p!);changed=open.endsWith('/>')?open.slice(0,-2)+'>'+field+'</w:p>':p!.xml.slice(0,p!.xml.lastIndexOf('</'))+field+'</w:p>'}
 if(changed===undefined)fail('caret')
 const output=xml.slice(0,p!.start)+changed+xml.slice(p!.start+p!.xml.length);parseCommentSourceXml(output)
 zip.file(MAIN,output,{createFolders:false});return zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
}

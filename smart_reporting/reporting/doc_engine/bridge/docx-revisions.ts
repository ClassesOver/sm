/** 顶层正文简单插入/删除的原 XML 决策；不提升普通段落编辑权限，不写文件。
 * 宿主必须从授权的原始 DOCX 取得 block / blockId，核验文档命名空间及保护状态，
 * 并在整份请求校验完后使用 saveDocx(kind:'xml') 原子保存。这里不接受客户端 XML/filter。
 */
import {createHash} from 'node:crypto'
import type {Block,Run} from '@genoffice/docx-engine'
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import {splitXmlChildren} from '../packages/docx-engine/src/generate'
import {applyTrackedChangesXml} from '../packages/docx-engine/src/revision-xml'

export interface TextRevisionOperation {
 blockId:string
 expectedObjectSha256:string
 revisionId:string
 action:'accept'|'reject'
}
export interface TextRevisionTarget {
 blockId:string
 expectedObjectSha256:string
 /** 服务端快照绑定身份；与可重复的 OOXML w:id 不同。 */
 revisionId:string
 originalRevisionId:string
 type:'insertion'|'deletion'
 author:string
 date:string|null
}
export interface NewTextRevisionOperation {
 blockId:string
 expectedObjectSha256:string
 from:number
 to:number
 text:string
}
interface Element {name:string;xml:string;start:number}
interface Target {element:Element;public:TextRevisionTarget}
const hash=(s:string)=>createHash('sha256').update(s).digest('hex')
function fail(reason:string):never{throw new Error(reason)}
const parser=new XMLParser({ignoreAttributes:false,attributeNamePrefix:'',parseAttributeValue:false,parseTagValue:false,trimValues:false,htmlEntities:true})
function openOf(n:Element){return n.xml.match(/^<[\w:.-]+\b(?:[^>"']|"[^"]*"|'[^']*')*>/)?.[0]??fail('docx_revision_xml_unsupported')}
function children(n:Element):Element[]{
 const open=openOf(n);if(open.endsWith('/>'))return[]
 const inner=n.xml.slice(open.length,n.xml.lastIndexOf('</')),parts=splitXmlChildren(inner)
 if(inner.replace(/\s/g,'')!==parts.map(p=>p.xml).join('').replace(/\s/g,''))fail('docx_revision_xml_unsupported')
 let cursor=open.length
 return parts.map(p=>{const at=n.xml.indexOf(p.xml,cursor);cursor=at+p.xml.length;return{...p,start:n.start+at}})
}
const revisionPattern=/<w:(?:ins|del)\b/g
function sourceOf(block:Block,blockId:string,protectedDocument:boolean):{xml:string;targets:Target[]}{
 if(protectedDocument)fail('docx_revision_protected')
 const xml=block.originalXml
 if(!['paragraph','heading','listItem'].includes(block.type)||!xml||!/^<w:p(?:\s|>)/.test(xml)||!blockId)fail('docx_revision_block_unsupported')
 if(xml.length>1024*1024||XMLValidator.validate(xml)!==true||/<!|<\?/.test(xml))fail('docx_revision_xml_unsupported')
 if(/\sxmlns(?::[\w.-]+)?\s*=/.test(xml))fail('docx_revision_namespace_unsupported')
 // 跨范围、段落/表格属性以及未知修订家族没有这里的单包装语义。
 if(/<w:(?:move\w*|\w+Change|cellIns|cellDel|cellMerge|conflict\w*|customXml\w*(?:Start|End))\b/.test(xml))fail('docx_revision_complex_unsupported')
 const root:Element={name:'w:p',xml,start:0},parts=children(root),wrappers=parts.filter(p=>p.name==='w:ins'||p.name==='w:del')
 if([...xml.matchAll(revisionPattern)].length!==wrappers.length)fail('docx_revision_nested_unsupported')
 const expectedObjectSha256=hash(xml)
 const targets=wrappers.map((element,ordinal):Target=>{
  const open=openOf(element)
  // 源工具会无条件清理这种字面空属性；首版不能授权这一有损来源。
  if(/<w:(rPr|trPr)><\/w:\1>/.test(element.xml))fail('docx_revision_empty_properties_unsupported')
  // vendor revision scanner 的标签边界不理解属性内的 >；在调用前收窄来源。
  if([...element.xml.matchAll(/(?:"([^"]*)"|'([^']*)')/g)].some(m=>(m[1]??m[2]).includes('>')))fail('docx_revision_payload_unsupported')
  const a=parser.parse(open.replace(/\/?>$/,'/>'))[element.name]
  if(typeof a?.['w:id']!=='string'||!a['w:id'])fail('docx_revision_id_missing')
  const runs=children(element)
  if(!runs.length||runs.some(r=>r.name!=='w:r'))fail('docx_revision_payload_unsupported')
  for(const run of runs){
   const payload=children(run),props=payload.filter(p=>p.name==='w:rPr')
   if(props.length>1||props.length&&payload[0]!==props[0])fail('docx_revision_payload_unsupported')
   for(const p of payload){
    if(p.name==='w:rPr')continue // 原样保留未知 run properties。
    if(!['w:tab','w:br','w:cr',element.name==='w:ins'?'w:t':'w:delText'].includes(p.name))fail('docx_revision_payload_unsupported')
    if(p.name==='w:t'||p.name==='w:delText'){
     const inner=p.xml.slice(openOf(p).length,p.xml.lastIndexOf('</'))
     if(!openOf(p).endsWith('/>')&&inner.includes('<'))fail('docx_revision_payload_unsupported')
    }else if(children(p).length)fail('docx_revision_payload_unsupported')
   }
  }
  return{element,public:{blockId,expectedObjectSha256,revisionId:hash(JSON.stringify([blockId,expectedObjectSha256,ordinal,element.xml])),originalRevisionId:a['w:id'],type:element.name==='w:ins'?'insertion':'deletion',author:typeof a['w:author']==='string'?a['w:author']:'',date:typeof a['w:date']==='string'?a['w:date']:null}}
 })
 return{xml,targets}
}
export function inspectTextRevisions(block:Block,blockId:string,protectedDocument=false):{reviewTargets:TextRevisionTarget[];revisionReadOnlyReason:string|null}{
 try{return{reviewTargets:sourceOf(block,blockId,protectedDocument).targets.map(t=>t.public),revisionReadOnlyReason:null}}
 catch(error){return{reviewTargets:[],revisionReadOnlyReason:error instanceof Error?error.message:'docx_revision_unsupported'}}
}
export function resolveTextRevisions(block:Block,blockId:string,operations:readonly TextRevisionOperation[],protectedDocument=false){
 const source=sourceOf(block,blockId,protectedDocument),seen=new Set<string>()
 if(!Array.isArray(operations)||!operations.length)fail('docx_revision_operations_invalid')
 // 全部按原快照验证，再生成任何替换；迟到无效操作不会返回部分成功 XML。
 const planned=operations.map(op=>{
  if(!op||Object.keys(op).sort().join(',')!=='action,blockId,expectedObjectSha256,revisionId'||op.blockId!==blockId||op.expectedObjectSha256!==hash(source.xml)||(op.action!=='accept'&&op.action!=='reject'))fail('docx_revision_anchor_invalid')
  const target=source.targets.find(t=>t.public.revisionId===op.revisionId)
  if(!target||seen.has(op.revisionId))fail('docx_revision_target_invalid')
  seen.add(op.revisionId);return{target,action:op.action}
 })
 let xml=source.xml
 for(const {target,action} of planned.sort((a,b)=>b.target.element.start-a.target.element.start)){
  // 仅在已核验 wrapper 上调用同源工具，不触发非目标 move/空属性清理。
  const result=applyTrackedChangesXml(target.element.xml,action)
  if(result.applied!==1||result.remaining!==0)fail('docx_revision_result_invalid')
  const at=target.element.start;xml=xml.slice(0,at)+result.xml+xml.slice(at+target.element.xml.length)
 }
 if(XMLValidator.validate(xml)!==true)fail('docx_revision_result_invalid')
 return{xml,resolvedRevisionIds:operations.map(op=>op.revisionId)}
}

/** Creates run-level revisions only for source-bound, plain-text paragraph edits. */
export function recordTextRevisions(block:Block,blockId:string,operations:readonly NewTextRevisionOperation[],author:string,date:string,protectedDocument=false):{runs:Run[];revisionCount:number}{
 const xml=block.originalXml
 if(protectedDocument)fail('docx_revision_protected')
 if(!['paragraph','heading','listItem'].includes(block.type)||!xml||!/^<w:p(?:\s|>)/.test(xml)||!blockId||xml.length>1024*1024||XMLValidator.validate(xml)!==true||/<!|<\?/.test(xml)||/\sxmlns(?::[\w.-]+)?\s*=/.test(xml))fail('docx_revision_block_unsupported')
 if(/<w:(?:ins|del|move\w*|\w+Change|cellIns|cellDel|cellMerge|hyperlink|fldChar|instrText|drawing|object|pict|ruby|sdt|customXml|bookmark\w*|comment\w*|proofErr)\b/.test(xml))fail('docx_revision_complex_unsupported')
 if(!Array.isArray(operations)||!operations.length||operations.length>500||typeof author!=='string'||!author||author.length>255||typeof date!=='string'||!/\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ/.test(date)||!Number.isFinite(Date.parse(date))||new Date(date).toISOString().replace(/\.\d{3}Z$/,'Z')!==date)fail('docx_revision_operations_invalid')
 const root:Element={name:'w:p',xml,start:0},parts=children(root)
 if(parts.some(part=>part.name!=='w:pPr'&&part.name!=='w:r')||parts.filter(part=>part.name==='w:pPr').length>1)fail('docx_revision_complex_unsupported')
 for(const run of parts.filter(part=>part.name==='w:r')){
  const payload=children(run),properties=payload.filter(part=>part.name==='w:rPr')
  if(properties.length>1||properties.length&&payload[0]!==properties[0]||payload.some(part=>part.name!=='w:rPr'&&part.name!=='w:t'))fail('docx_revision_complex_unsupported')
 }
 const source=block.runs
 if(!Array.isArray(source)||!source.length||source.some(run=>!run.text||run.ins||run.del||run.image||run.math||run.ruby||run.noteRef||run.link||run.instrField!==undefined||run.refField!==undefined||run.sym))fail('docx_revision_complex_unsupported')
 const sourceText=source.map(run=>run.text).join(''),expectedObjectSha256=hash(xml)
 const validBoundary=(at:number)=>at>=0&&at<=sourceText.length&&!(at>0&&at<sourceText.length&&/[\uD800-\uDBFF]/.test(sourceText[at-1]!)&&/[\uDC00-\uDFFF]/.test(sourceText[at]!))
 let previousTo=-1
 const planned=operations.map(op=>{
  if(!op||Object.keys(op).sort().join(',')!=='blockId,expectedObjectSha256,from,text,to'||op.blockId!==blockId||op.expectedObjectSha256!==expectedObjectSha256||!Number.isSafeInteger(op.from)||!Number.isSafeInteger(op.to)||op.from<0||op.to<op.from||!validBoundary(op.from)||!validBoundary(op.to)||op.from<=previousTo||typeof op.text!=='string'||!op.text&&op.from===op.to||!op.text.isWellFormed()||op.text.length>20000||/[\u0000-\u0008\u000B-\u001F\uFFFE\uFFFF]/.test(op.text))fail('docx_revision_anchor_invalid')
  previousTo=op.to
  if(op.from===op.to&&!op.text)fail('docx_revision_anchor_invalid')
  return op
 })
 const slice=(from:number,to:number,revision:'ins'|'del'|null,text?:string,inheritAt=from):Run[]=>{
  let offset=0;const out:Run[]=[]
  for(const run of source){
   const end=offset+run.text.length
   if(revision==='ins'){
    if(offset<=inheritAt&&inheritAt<=end){const plain={...structuredClone(run),text:text!};delete plain.ins;delete plain.del;out.push({...plain,ins:{author,date}});return out}
   }else if(from<end&&to>offset){const piece={...structuredClone(run),text:run.text.slice(Math.max(from,offset)-offset,Math.min(to,end)-offset)};if(revision==='del')out.push({...piece,del:{author,date}});else out.push(piece)}
   offset=end
  }
  if(revision==='ins'&&inheritAt===sourceText.length){const run=source.at(-1)!;const plain={...structuredClone(run),text:text!};delete plain.ins;delete plain.del;out.push({...plain,ins:{author,date}});return out}
  if(revision==='ins')fail('docx_revision_anchor_invalid')
  return out
 }
 const runs:Run[]=[];let cursor=0
 for(const op of planned){
  runs.push(...slice(cursor,op.from,null))
  if(op.to>op.from)runs.push(...slice(op.from,op.to,'del'))
  if(op.text)runs.push(...slice(op.from,op.from,'ins',op.text,op.from))
  cursor=op.to
 }
 runs.push(...slice(cursor,sourceText.length,null))
 if(!runs.length)fail('docx_revision_result_invalid')
 return{runs,revisionCount:planned.length}
}

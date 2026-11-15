/** Fixed-source story revision decisions. Clients send identities, never XML or filters.
 * All authorization completes before model construction; only saveDocx saves the result.
 */
import {createHash} from 'node:crypto'
import {posix} from 'node:path'
import JSZip from 'jszip'
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import {parseDocx,readSections,type ParsedDoc,type SaveOptions,type RevisionResolution} from '../packages/docx-engine/src/index'
import {applyTrackedChangesXml} from '../packages/docx-engine/src/revision-xml'
export interface StoryRevisionTarget {
 targetId:string;partPath:string;expectedPartSha256:string;expectedWrapperSha256:string
 originalRevisionId:string;kind:'footnote'|'endnote'|'header'|'footer';noteId?:string
 type:'insertion'|'deletion';author:string;date:string|null;text:string
}
export interface StoryRevisionOperation {targetId:string;expectedPartSha256:string;expectedWrapperSha256:string;action:'accept'|'reject'}
interface Scope {kind:StoryRevisionTarget['kind'];partPath:string;xml:string;noteId?:string;route?:{lastBlockIndex:number;kind:'header'|'footer';variant:'default'|'first'|'even';last:boolean}}
interface Target {public:StoryRevisionTarget;scope:Scope;wrapper:string}
const hash=(s:string)=>createHash('sha256').update(s).digest('hex')
const fail=(s:string):never=>{throw new Error(s)}
const parser=new XMLParser({ignoreAttributes:false,attributeNamePrefix:'',parseTagValue:false,parseAttributeValue:false,trimValues:false})
function attrs(tag:string):Record<string,string>{return Object.values(parser.parse(tag.replace(/\/?>$/,'/>')))[0] as Record<string,string>}
const list=(value:any)=>value===undefined?[]:Array.isArray(value)?value:[value]
async function scopes(parsed:ParsedDoc):Promise<Scope[]>{
 const zip=await JSZip.loadAsync(parsed.internal.originalBytes),out:Scope[]=[]
 for(const kind of ['footnote','endnote'] as const){
  const partPath=`word/${kind}s.xml`,xml=await zip.file(partPath)?.async('string');if(!xml)continue
  for(const m of xml.matchAll(new RegExp(`<w:${kind}\\b[^>]*>[\\s\\S]*?</w:${kind}>`,'g'))){const a=attrs(m[0].slice(0,m[0].indexOf('>')+1));if(a['w:type']||!a['w:id'])continue;out.push({kind,partPath,xml:m[0],noteId:a['w:id']})}
 }
 const relXml=await zip.file('word/_rels/document.xml.rels')?.async('string'),rels=new Map<string,string>()
 if(relXml)for(const r of list(parser.parse(relXml)?.Relationships?.Relationship))if(!r.TargetMode&&typeof r.Target==='string'&&typeof r.Id==='string')rels.set(r.Id,posix.normalize(r.Target.startsWith('/')?r.Target.slice(1):`word/${r.Target}`))
 const seen=new Set<string>()
 for(const [si,section] of readSections(parsed).entries())for(const kind of ['header','footer'] as const)for(const variant of ['default','first','even'] as const){
  const rid=(kind==='header'?section.headerRefs:section.footerRefs)[variant],partPath=rid?rels.get(rid):undefined
  if(!partPath||seen.has(partPath)||!partPath.startsWith('word/')||!parsed.hfParts?.[rid!])continue
  const xml=await zip.file(partPath)?.async('string');if(!xml)continue;seen.add(partPath)
  out.push({kind,partPath,xml,route:{lastBlockIndex:section.lastBlockIndex,kind,variant,last:si===readSections(parsed).length-1}})
 }
 return out
}
async function snapshot(parsed:ParsedDoc){
 const zip=await JSZip.loadAsync(parsed.internal.originalBytes),partXml=new Map<string,string>(),targets:Target[]=[],readOnly:{partPath:string;noteId?:string;reason:string}[]=[]
 for(const scope of await scopes(parsed)){
  try{
   if(parsed.protection)fail('docx_story_revision_protected')
   let whole=partXml.get(scope.partPath);if(!whole){whole=await zip.file(scope.partPath)!.async('string');partXml.set(scope.partPath,whole)}
   if(scope.noteId){
    if(new RegExp(`<w:${scope.kind}\\b[^>]*\\/>`).test(whole))fail('docx_story_revision_note_serialization_unsupported')
    const noteIds=[...whole.matchAll(new RegExp(`<w:${scope.kind}\\b[^>]*>`,'g'))].map(m=>attrs(m[0])['w:id']).filter(Boolean)
    if(new Set(noteIds).size!==noteIds.length)fail('docx_story_revision_note_id_ambiguous')
   }
   if(XMLValidator.validate(whole)!==true||/<!/.test(whole)||!/xmlns:w="http:\/\/schemas.openxmlformats.org\/wordprocessingml\/2006\/main"/.test(whole)||[...whole.matchAll(/xmlns:w\s*=/g)].length!==1)fail('docx_story_revision_namespace_unsupported')
   if(/<w:(?:move\w*|\w+Change|cellIns|cellDel|cellMerge|conflict\w*|customXml\w*(?:Start|End))\b/.test(scope.xml))fail('docx_story_revision_complex_unsupported')
   if(/<w:(rPr|trPr)><\/w:\1>/.test(scope.xml))fail('docx_story_revision_empty_properties_unsupported')
   const wrappers=[...scope.xml.matchAll(/<w:(ins|del)\b[^>]*>[\s\S]*?<\/w:\1>/g)]
   if([...scope.xml.matchAll(/<w:(?:ins|del)\b/g)].length!==wrappers.length)fail('docx_story_revision_nested_unsupported')
   const ids=new Set<string>(),pending:Target[]=[]
   for(const m of wrappers){
    const wrapper=m[0],open=wrapper.slice(0,wrapper.indexOf('>')+1)
    if(/\sw:(?:id|author|date)\s*=\s*'/.test(open)||[...wrapper.matchAll(/"([^"]*)"|'([^']*)'/g)].some(a=>(a[1]??a[2]).includes('>')))fail('docx_story_revision_payload_unsupported')
    const a=attrs(open),id=a['w:id'];if(!id)fail('docx_story_revision_id_missing');if(ids.has(id))fail('docx_story_revision_id_ambiguous');ids.add(id)
    // Property-level insertion/deletion marks and nested revisions have distinct semantics.
    if(!/^<w:(?:ins|del)\b[^>]*>\s*<w:r(?:\s|>)/.test(wrapper)||/<w:(?:ins|del)\b/.test(wrapper.slice(open.length)))fail('docx_story_revision_payload_unsupported')
    const expectedPartSha256=hash(whole),expectedWrapperSha256=hash(wrapper)
    const publicTarget:StoryRevisionTarget={targetId:hash(JSON.stringify([scope.partPath,scope.noteId??'',expectedPartSha256,expectedWrapperSha256,id])),partPath:scope.partPath,expectedPartSha256,expectedWrapperSha256,originalRevisionId:id,kind:scope.kind,...(scope.noteId?{noteId:scope.noteId}:{}),type:m[1]==='ins'?'insertion':'deletion',author:a['w:author']??'',date:a['w:date']??null,text:wrapper.replace(/<[^>]*>/g,'')}
    pending.push({public:publicTarget,scope,wrapper})
   }
   targets.push(...pending)
  }catch(error){readOnly.push({partPath:scope.partPath,...(scope.noteId?{noteId:scope.noteId}:{}),reason:error instanceof Error?error.message:'docx_story_revision_unsupported'})}
 }
 return{targets,readOnly,partXml}
}
export async function inspectStoryRevisions(parsed:ParsedDoc){const s=await snapshot(parsed);return{targets:s.targets.map(t=>t.public),readOnly:s.readOnly}}
export async function resolveStoryRevisions(parsed:ParsedDoc,operations:readonly StoryRevisionOperation[]):Promise<SaveOptions>{
 if(!Array.isArray(operations)||!operations.length)fail('docx_story_revision_operations_invalid')
 const source=await snapshot(parsed),seen=new Set<string>()
 const plans=operations.map(op=>{
  if(!op||Object.keys(op).sort().join(',')!=='action,expectedPartSha256,expectedWrapperSha256,targetId'||!['accept','reject'].includes(op.action))fail('docx_story_revision_operation_invalid')
  const target=source.targets.find(t=>t.public.targetId===op.targetId)
  if(!target||seen.has(op.targetId)||op.expectedPartSha256!==target.public.expectedPartSha256||op.expectedWrapperSha256!==target.public.expectedWrapperSha256)fail('docx_story_revision_anchor_invalid')
  seen.add(op.targetId);return{target,action:op.action}
 })
 const zip=await JSZip.loadAsync(parsed.internal.originalBytes),changed=new Map<string,string>()
 for(const {target,action} of plans){
  const path=target.public.partPath,xml=changed.get(path)??source.partXml.get(path)!,scopeXml=target.scope.noteId?xml.match(new RegExp(`<w:${target.scope.kind}\\b[^>]*\\bw:id="${target.scope.noteId.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}"[^>]*>[\\s\\S]*?</w:${target.scope.kind}>`))?.[0]:xml
  if(!scopeXml)fail('docx_story_revision_scope_invalid')
  const result=applyTrackedChangesXml(scopeXml,action,{ids:[target.public.originalRevisionId]}),single=applyTrackedChangesXml(target.wrapper,action,{ids:[target.public.originalRevisionId]})
  if(result.applied!==1||single.applied!==1||result.xml!==scopeXml.replace(target.wrapper,single.xml))fail('docx_story_revision_source_boundary_invalid')
  changed.set(path,xml.replace(scopeXml,result.xml))
 }
 for(const [path,xml] of changed)zip.file(path,xml)
 // Reparse the source engine's actual outcome to obtain faithful display models.
 const resolved=await parseDocx(await zip.generateAsync({type:'uint8array'})),options:SaveOptions={}
 for(const kind of ['footnote','endnote'] as const){const mine=plans.filter(p=>p.target.public.kind===kind);if(!mine.length)continue;const key=kind==='footnote'?'footnotes':'endnotes';options[key]=parsed[key].map(note=>{const n=mine.filter(p=>p.target.public.noteId===note.id);if(!n.length)return note;const next=resolved[key].find(x=>x.id===note.id)??fail('docx_story_revision_model_missing');return{...next,revisionsResolved:n.map(p=>({mode:p.action,filter:{ids:[p.target.public.originalRevisionId]}}))}})}
 for(const scope of await scopes(parsed)){
  if(!scope.route)continue;const mine=plans.filter(p=>p.target.scope.partPath===scope.partPath);if(!mine.length)continue
  const route=scope.route,section=readSections(resolved)[readSections(parsed).findIndex(s=>s.lastBlockIndex===route.lastBlockIndex)],rid=(route.kind==='header'?section.headerRefs:section.footerRefs)[route.variant],model=rid?resolved.hfParts?.[rid]:undefined
  if(!model)fail('docx_story_revision_model_missing')
  const hf={text:model.text,paras:model.paras,pageNumber:model.hasPageNumber,keepContent:true as const,revisionsResolved:mine.map(p=>({mode:p.action,filter:{ids:[p.target.public.originalRevisionId]}} satisfies RevisionResolution))}
  if(route.last){const key=`${route.kind}${route.variant==='default'?'':route.variant==='first'?'First':'Even'}` as 'header';options[key]=hf}else(options.sectionHf??=[]).push({lastBlockIndex:route.lastBlockIndex,kind:route.kind,variant:route.variant,hf})
 }
 return options
}
/** Reopen the actual output ZIP. Verify source decisions plus every unrelated part byte.
 * Notes' source writer normalizes declaration/structural separators; each real note entry
 * is checked byte for byte, and all existing structural entries must survive unchanged.
 */
export async function verifyStoryRevisionOutput(parsed:ParsedDoc,operations:readonly StoryRevisionOperation[],output:Uint8Array){
 await resolveStoryRevisions(parsed,operations) // whole-batch identity validation, no write
 const source=await snapshot(parsed),before=await JSZip.loadAsync(parsed.internal.originalBytes),after=await JSZip.loadAsync(output),expected=new Map<string,string>()
 for(const op of operations){const t=source.targets.find(t=>t.public.targetId===op.targetId)!,path=t.public.partPath,xml=expected.get(path)??source.partXml.get(path)!,replacement=applyTrackedChangesXml(t.wrapper,op.action,{ids:[t.public.originalRevisionId]}).xml
  if(t.scope.noteId){
   const scope=xml.match(new RegExp(`<w:${t.scope.kind}\\b[^>]*\\bw:id="${t.scope.noteId.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}"[^>]*>[\\s\\S]*?</w:${t.scope.kind}>`))?.[0]??fail('docx_story_revision_scope_invalid');expected.set(path,xml.replace(scope,scope.replace(t.wrapper,replacement)))
  }else expected.set(path,xml.replace(t.wrapper,replacement))
 }
 const names=(zip:JSZip)=>Object.keys(zip.files).filter(n=>!zip.files[n].dir).sort()
 if(JSON.stringify(names(before))!==JSON.stringify(names(after)))fail('docx_story_revision_package_changed')
 for(const path of names(before)){
  const a=await before.file(path)!.async('uint8array'),b=await after.file(path)!.async('uint8array')
  if(!expected.has(path)){
   if(Buffer.from(a).equals(Buffer.from(b)))continue
   if(path==='docProps/core.xml'){
    const original=Buffer.from(a).toString('utf8'),actual=Buffer.from(b).toString('utf8'),timestamp=actual.match(/<dcterms:modified[^>]*>([^<]*)<\/dcterms:modified>/)?.[1]
    if(timestamp&&!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(timestamp))fail('docx_story_revision_metadata_invalid')
    let wanted=original.replace(/(<dcterms:modified[^>]*>)[^<]*(<\/dcterms:modified>)/,`$1${timestamp??''}$2`)
    wanted=wanted.replace(/(<cp:revision>)(\d+)(<\/cp:revision>)/,(_m,open,n,close)=>`${open}${Number.isFinite(parseInt(n,10)+1)?parseInt(n,10)+1:n}${close}`)
    if(actual===wanted)continue
   }
   fail(`docx_story_revision_non_target_changed:${path}`)
  }
  const xml=await after.file(path)!.async('string'),wanted=expected.get(path)!
  if(XMLValidator.validate(xml)!==true)fail('docx_story_revision_output_xml_invalid')
  if(!/word\/(?:footnotes|endnotes)\.xml$/.test(path)){if(xml!==wanted)fail('docx_story_revision_output_mismatch');continue}
  const entry=path.includes('footnotes')?'footnote':'endnote',entries=(v:string)=>[...v.matchAll(new RegExp(`<w:${entry}\\b[^>]*>[\\s\\S]*?</w:${entry}>`,'g'))].map(m=>m[0])
  const expectedEntries=entries(wanted),actualEntries=entries(xml),real=(v:string)=>!/^<[^>]*\sw:type=/.test(v)
  if(JSON.stringify(expectedEntries.filter(real))!==JSON.stringify(actualEntries.filter(real)))fail('docx_story_revision_output_mismatch')
  for(const structural of expectedEntries.filter(v=>!real(v)))if(!actualEntries.includes(structural))fail('docx_story_revision_structural_changed')
  const root=(v:string)=>v.match(new RegExp(`<w:${entry}s\\b[^>]*>`))?.[0]??fail('docx_story_revision_output_xml_invalid')
  if(JSON.stringify(attrs(root(xml)))!==JSON.stringify(attrs(root(wanted))))fail('docx_story_revision_root_changed')
 }
 await parseDocx(output)
 return{verified:true as const,targetCount:operations.length,changedParts:[...expected.keys()]}
}

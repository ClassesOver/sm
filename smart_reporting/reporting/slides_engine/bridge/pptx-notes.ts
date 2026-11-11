/** 备注只收纯文本；来源校验只读，所有OOXML写入委托固定源get/setSlideNotes。 */
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import {getSlideNotes,setSlideNotes,type OpenedPptx} from '@genoffice/pptx-engine'
import {relsPathFor,resolveTarget} from '../packages/pptx-engine/src/zip.ts'
export type NotesEdit={slideIndex:number;text:string}
export type PreparedNotesEdit={sourcePath:string;text:string}
type Conflicts={deletedSlides?:readonly number[];newSlides?:readonly {duplicateOf?:number;layoutFrom?:number;withLayout?:string}[]}
const relBase='http://schemas.openxmlformats.org/officeDocument/2006/relationships',relNs='http://schemas.openxmlformats.org/package/2006/relationships',ctNs='http://schemas.openxmlformats.org/package/2006/content-types'
const namespaces={p:'http://schemas.openxmlformats.org/presentationml/2006/main',a:'http://schemas.openxmlformats.org/drawingml/2006/main',r:relBase}
const notesCt='application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml',masterCt='application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml'
// numeric实体必须由解析器单次解释，不能沿用原生getter的numeric后named二次解码。
const parser=new XMLParser({ignoreAttributes:false,parseTagValue:false,parseAttributeValue:false,trimValues:false,htmlEntities:true})
const record=(v:unknown):v is Record<string,any>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const list=(v:any):any[]=>v===undefined?[]:Array.isArray(v)?v:[v]
const keys=(v:Record<string,any>)=>Object.keys(v).filter(k=>k!=='#text'||String(v[k]).trim()!=='')
const empty=(v:any)=>v===''||record(v)&&keys(v).length===0
function fail(reason:string):never{throw Error('notes_edit_'+reason)}
function xmlCharacters(text:string):boolean{
 for(const ch of text){const cp=ch.codePointAt(0)!;if(cp<32&&![9,10,13].includes(cp)||cp>=0xd800&&cp<=0xdfff||cp===0xfffe||cp===0xffff)return false}
 return true
}
function normalized(value:unknown):string{
 if(typeof value!=='string'||value.length>20000||!xmlCharacters(value))fail('text_invalid')
 return value.replace(/\r\n?/g,'\n').replace(/\n+$/,'')
}
function root(xml:string|null,name:string,namespace?:string):Record<string,any>{
 if(!xml||!xmlCharacters(xml)||/<!DOCTYPE|<!ENTITY|<!--|<!\[CDATA\[/.test(xml)||XMLValidator.validate(xml)!==true)fail('xml_invalid')
 for(const match of xml.matchAll(/&#(?:x([\da-f]+)|(\d+));/gi)){const cp=match[1]?Number.parseInt(match[1],16):Number(match[2]);if(!Number.isSafeInteger(cp)||cp>0x10ffff||!xmlCharacters(String.fromCodePoint(cp)))fail('xml_characters_invalid')}
 for(const match of xml.matchAll(/xmlns:(p|a|r)\s*=\s*['"]([^'"]*)['"]/g))if(namespaces[match[1] as keyof typeof namespaces]!==match[2])fail('namespace_invalid')
 const doc=parser.parse(xml),node=doc[name]
 if(!record(node)||Object.keys(doc).some(k=>k!==name&&k!=='?xml')||namespace&&node['@_xmlns']!==namespace)fail('structure_invalid')
 if(name.startsWith('p:')&&Object.entries(namespaces).some(([prefix,uri])=>node['@_xmlns:'+prefix]!==uri))fail('namespace_invalid')
 return node
}
function relationships(opened:OpenedPptx,path:string,appendable=true){
 const xml=opened.archive.readText(relsPathFor(path)),node=root(xml,'Relationships',relNs),engine=opened.archive.readRels(path),seen=new Set<string>()
 if(appendable&&!xml!.includes('</Relationships>')||keys(node).some(k=>!['@_xmlns','Relationship'].includes(k))||[...xml!.matchAll(/xmlns\s*=\s*['"]([^'"]*)['"]/g)].some(m=>m[1]!==relNs))fail('relationships_invalid')
 for(const row of list(node.Relationship)){
  if(!record(row)||keys(row).some(k=>!['@_Id','@_Type','@_Target','@_TargetMode'].includes(k))||typeof row['@_Id']!=='string'||!/^rId\d+$/.test(row['@_Id'])||seen.has(row['@_Id'])||typeof row['@_Type']!=='string'||!row['@_Type']||typeof row['@_Target']!=='string'||!row['@_Target'])fail('relationships_invalid')
  const number=Number(row['@_Id'].slice(3));if(!Number.isSafeInteger(number)||number>Number.MAX_SAFE_INTEGER-200)fail('relationship_id_capacity')
  const rel=engine.get(row['@_Id']);if(!rel||rel.type!==row['@_Type']||rel.target!==row['@_Target']||rel.targetMode!==row['@_TargetMode'])fail('relationships_invalid')
  seen.add(row['@_Id'])
 }
 if(engine.size!==seen.size)fail('relationships_invalid')
 return [...engine.values()]
}
function contentTypes(opened:OpenedPptx){
 const xml=opened.archive.readText('[Content_Types].xml'),node=root(xml,'Types',ctNs),types=new Map<string,string>(),defaults=new Set<string>()
 if(!xml!.includes('</Types>')||keys(node).some(k=>!['@_xmlns','Override','Default'].includes(k)))fail('content_types_invalid')
 for(const row of list(node.Override)){
  if(!record(row)||keys(row).sort().join()!=='@_ContentType,@_PartName'||typeof row['@_PartName']!=='string'||!row['@_PartName'].startsWith('/')||types.has(row['@_PartName'])||typeof row['@_ContentType']!=='string'||!row['@_ContentType'])fail('content_types_invalid')
  types.set(row['@_PartName'],row['@_ContentType'])
 }
 for(const row of list(node.Default)){
  if(!record(row)||keys(row).sort().join()!=='@_ContentType,@_Extension'||typeof row['@_Extension']!=='string'||defaults.has(row['@_Extension'])||typeof row['@_ContentType']!=='string'||!row['@_ContentType'])fail('content_types_invalid')
  defaults.add(row['@_Extension'])
 }
 return types
}
function registeredMaster(opened:OpenedPptx,types:Map<string,string>,creating:boolean):string|null{
 const paths=[...opened.archive.entries.keys()].filter(p=>p.startsWith('ppt/notesMasters/')&&!p.includes('/_rels/')),presXml=opened.archive.readText('ppt/presentation.xml'),pres=root(presXml,'p:presentation'),rels=relationships(opened,'ppt/presentation.xml'),links=rels.filter(r=>r.type===relBase+'/notesMaster'),ids=list(pres['p:notesMasterIdLst']?.['p:notesMasterId'])
 if(paths.length>1||paths.some(p=>!/^ppt\/notesMasters\/notesMaster\d+\.xml$/.test(p)))fail('master_identity_invalid')
 if(!paths.length){
  if(!creating||links.length||ids.length||pres['p:notesMasterIdLst']!==undefined&&!empty(pres['p:notesMasterIdLst'])||[...opened.archive.entries.keys()].some(p=>p.startsWith('ppt/notesMasters/')))fail('master_registration_invalid')
  if(pres['p:notesMasterIdLst']===undefined&&!presXml!.includes('</p:sldMasterIdLst>')&&!presXml!.includes('<p:sldIdLst>'))fail('master_insert_anchor_invalid')
  if(pres['p:notesMasterIdLst']!==undefined&&!/<p:notesMasterIdLst\b[^>]*\/>/.test(presXml!))fail('master_insert_anchor_invalid')
  if(types.has('/ppt/notesMasters/notesMaster1.xml')&&types.get('/ppt/notesMasters/notesMaster1.xml')!==masterCt)fail('master_content_type_invalid')
  const theme=[...opened.archive.entries.keys()].find(p=>/^ppt\/theme\/theme\d+\.xml$/.test(p));if(!theme||!opened.archive.readBytes(theme)?.length)fail('master_theme_missing')
  return null
 }
 const path=paths[0]!,node=root(opened.archive.readText(path),'p:notesMaster')
 if(!record(node['p:cSld'])||!record(node['p:cSld']['p:spTree'])||types.get('/'+path)!==masterCt||links.length!==1||links[0]!.targetMode!==undefined||resolveTarget('ppt/presentation.xml',links[0]!.target)!==path||ids.length!==1||!record(ids[0])||keys(ids[0]).join()!=='@_r:id'||ids[0]['@_r:id']!==links[0]!.id||!record(pres['p:notesMasterIdLst'])||keys(pres['p:notesMasterIdLst']).join()!=='p:notesMasterId')fail('master_registration_invalid')
 const masterRels=relationships(opened,path)
 if(masterRels.length!==1||masterRels[0]!.type!==relBase+'/theme'||masterRels[0]!.targetMode!==undefined||!opened.archive.readBytes(resolveTarget(path,masterRels[0]!.target)))fail('master_relationships_invalid')
 return path
}
function sourceIndex(opened:OpenedPptx,path:string):number{
 const indices=opened.deck.slides.flatMap((s,i)=>s.path===path?[i]:[])
 if(!/^ppt\/slides\/[^/]+\.xml$/.test(path)||indices.length!==1||!opened.archive.readBytes(path))fail('source_identity_invalid')
 return indices[0]!
}
function readSource(opened:OpenedPptx,index:number){
 const slide=Number.isInteger(index)&&index>=0?opened.deck.slides[index]:undefined;if(!slide)fail('source_invalid')
 sourceIndex(opened,slide.path);root(opened.archive.readText(slide.path),'p:sld')
 const refs=relationships(opened,slide.path,false).filter(r=>r.type===relBase+'/notesSlide')
 if(refs.length>1||refs[0]?.targetMode!==undefined)fail('notes_relationships_ambiguous')
 const path=refs[0]?resolveTarget(slide.path,refs[0].target):null
 if(path&&(!/^ppt\/notesSlides\/notesSlide\d+\.xml$/.test(path)||!opened.archive.readBytes(path)))fail('notes_identity_invalid')
 const xml=path?opened.archive.readText(path):null,node=path?root(xml,'p:notes'):null,text=path?getSlideNotes(opened.archive,slide.path):''
 return {slide,path,xml,node,text}
}
/** 同批多个新建项按原生计数依次分配；后项孤立关系必须在首项写入前拒绝。 */
function creationPaths(opened:OpenedPptx,count:number):void{
 if(!count)return
 const types=contentTypes(opened);let max=0
 for(const path of opened.archive.entries.keys()){const match=/^ppt\/notesSlides\/notesSlide(\d+)\.xml$/.exec(path);if(match){if(!Number.isSafeInteger(Number(match[1])+count))fail('notes_part_limit');max=Math.max(max,Number(match[1]))}}
 for(let i=1;i<=count;i++){
  const next='ppt/notesSlides/notesSlide'+(max+i)+'.xml'
  if(opened.archive.readBytes(relsPathFor(next))||types.has('/'+next)&&types.get('/'+next)!==notesCt)fail('notes_orphan_registration_invalid')
 }
}
function plainBody(xml:string,node:Record<string,any>):string{
 const tree=node['p:cSld']?.['p:spTree']
 if(!record(tree)||keys(node).some(k=>!['@_xmlns:p','@_xmlns:a','@_xmlns:r','p:cSld','p:clrMapOvr'].includes(k))||keys(tree).some(k=>!['p:nvGrpSpPr','p:grpSpPr','p:sp'].includes(k))||/<a:hlink(?:Click|Hover)\b/.test(xml))fail('notes_content_readonly')
 const shapes=list(tree['p:sp']),blocks=[...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)],bodies=shapes.filter(s=>s?.['p:nvSpPr']?.['p:nvPr']?.['p:ph']?.['@_type']==='body')
 if(shapes.length!==blocks.length||bodies.length!==1||shapes.some(s=>!record(s)||!['body','sldImg','dt','ftr','hdr','sldNum'].includes(s['p:nvSpPr']?.['p:nvPr']?.['p:ph']?.['@_type'])))fail('notes_body_ambiguous')
 const body=bodies[0]!,block=blocks.find(b=>/<p:ph\b[^>]*\btype=["']body["']/.test(b[0]))?.[0],tx=body['p:txBody']
 if(!block||!record(tx)||keys(body).some(k=>!['p:nvSpPr','p:spPr','p:txBody'].includes(k))||!/<p:txBody>[\s\S]*?<\/p:txBody>/.test(block)||keys(tx).some(k=>!['a:bodyPr','a:lstStyle','a:p'].includes(k))||!empty(tx['a:bodyPr'])||!empty(tx['a:lstStyle']))fail('notes_body_readonly')
 const paragraphs=list(tx['a:p'])
 if(!paragraphs.length||paragraphs.length!==[...block.matchAll(/<a:p>[\s\S]*?<\/a:p>/g)].length)fail('notes_paragraph_readonly')
 function neutral(v:any){return v===undefined||empty(v)||record(v)&&keys(v).every(k=>['@_lang','@_dirty'].includes(k))}
 for(const paragraph of paragraphs){
  if(empty(paragraph))continue
  if(!record(paragraph)||keys(paragraph).some(k=>!['a:r','a:endParaRPr'].includes(k))||!neutral(paragraph['a:endParaRPr']))fail('notes_format_readonly')
  for(const run of list(paragraph['a:r'])){
   if(!record(run)||keys(run).some(k=>!['a:rPr','a:t'].includes(k))||!neutral(run['a:rPr'])||!Object.hasOwn(run,'a:t'))fail('notes_format_readonly')
   const text=run['a:t'];if(typeof text!=='string'&&!(record(text)&&keys(text).every(k=>['#text','@_xml:space'].includes(k))&&[undefined,'preserve','default'].includes(text['@_xml:space'])&&[undefined,'string'].includes(typeof text['#text'])))fail('notes_text_readonly')
  }
 }
 const text=paragraphs.map(p=>empty(p)?'':list(p['a:r']).map(run=>typeof run['a:t']==='string'?run['a:t']:run['a:t']['#text']??'').join(''))
 while(text.length&&text[text.length-1]==='')text.pop()
 return text.join('\n')
}
function validateSource(opened:OpenedPptx,index:number){
 const current=readSource(opened,index);relationships(opened,current.slide.path)
 const types=contentTypes(opened),master=registeredMaster(opened,types,current.path===null)
 if(!current.path){
  creationPaths(opened,1)
  return current
 }
 let owners=0
 for(const path of opened.archive.entries.keys())if(/^ppt\/slides\/[^/]+\.xml$/.test(path))for(const rel of opened.archive.readRels(path).values())if(rel.type===relBase+'/notesSlide'&&resolveTarget(path,rel.target)===current.path)owners++
 const rels=relationships(opened,current.path),back=rels.filter(r=>r.type===relBase+'/slide'),masters=rels.filter(r=>r.type===relBase+'/notesMaster')
 if(owners!==1||types.get('/'+current.path)!==notesCt||rels.length!==2||back.length!==1||back[0]!.targetMode!==undefined||resolveTarget(current.path,back[0]!.target)!==current.slide.path||masters.length!==1||masters[0]!.targetMode!==undefined||resolveTarget(current.path,masters[0]!.target)!==master)fail('notes_relationships_ambiguous')
 if(plainBody(current.xml!,current.node!)!==current.text)fail('native_text_mismatch')
 return current
}
export function inspectSlideNotes(opened:OpenedPptx,index:number):{notesText:string;notesEditable:boolean;notesReason:string|null}{
 let notesText='';try{notesText=readSource(opened,index).text;validateSource(opened,index);return {notesText,notesEditable:true,notesReason:null}}
 catch(cause){return {notesText,notesEditable:false,notesReason:cause instanceof Error?cause.message:'notes_edit_source_invalid'}}
}
export function prepareNotesEdits(opened:OpenedPptx,input:unknown,conflicts:Conflicts={}):PreparedNotesEdit[]{
 if(input===undefined)return []
 if(!Array.isArray(input)||input.length>200)fail('batch_invalid')
 const seen=new Set<number>(),prepared:PreparedNotesEdit[]=[];let total=0,creates=0
 for(const item of input){
  if(!record(item)||Object.keys(item).sort().join()!=='slideIndex,text'||typeof item.slideIndex!=='number'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=opened.deck.slides.length||seen.has(item.slideIndex)||conflicts.deletedSlides?.includes(item.slideIndex)||conflicts.newSlides?.some(s=>s.duplicateOf===item.slideIndex))fail('source_or_conflict_invalid')
  const text=normalized(item.text);total+=item.text.length;if(total>200000)fail('text_budget_exceeded')
  seen.add(item.slideIndex);const current=validateSource(opened,item.slideIndex);prepared.push({sourcePath:current.slide.path,text})
  if(current.path===null&&current.text!==text)creates++
 }
 creationPaths(opened,creates)
 return prepared
}
export function applyNotesEdits(opened:OpenedPptx,prepared:readonly PreparedNotesEdit[]):void{
 const targets=prepared.map(item=>{const index=sourceIndex(opened,item.sourcePath),current=validateSource(opened,index);return {index,current,item}})
 creationPaths(opened,targets.filter(({current,item})=>current.path===null&&current.text!==item.text).length)
 for(const {index,current,item} of targets){
  if(current.text===item.text)continue
  if(!setSlideNotes(opened,index,item.text))fail('native_set_failed')
  const written=validateSource(opened,index);if(written.text!==item.text)fail('native_readback_mismatch')
 }
}

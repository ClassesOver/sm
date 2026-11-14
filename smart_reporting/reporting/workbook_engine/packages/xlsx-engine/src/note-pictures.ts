import JSZip from 'jszip'
import {SaxesParser} from 'saxes'
import {z} from 'zod'
import {assemblePackage,assertOnlyTouchedEntriesChanged,createBufferEntrySource,type EntrySource} from './zip'
import {readSheetNotes,noteKey,type NoteSource} from './note-read'
import {patchSheetNotes} from './notes'
import {parseSheetElements,resolveWorksheetPath} from './workbook-read'
import {relationships,removePartOverrides} from './sheet-removal-parts'
import {resolvePivotTarget} from './pivot-add'
import {sha256Hex} from './sha256'
import {readXmlAttribute,escapeXmlText,decodeXmlText} from './xml'
const V='urn:schemas-microsoft-com:vml',X='urn:schemas-microsoft-com:office:excel',O='urn:schemas-microsoft-com:office:office',R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const relsPath=(part:string)=>part.replace(/([^/]+)$/,'_rels/$1.rels')
const imageRel=R+'/image'
const tag=(name:string)=>'(?:[\\w.-]+:)?'+name
const mediaTags=(shape:string)=>[...shape.matchAll(new RegExp('<'+tag('(?:fill|imagedata)')+'\\b[^>]*\\/?>','g'))].map(m=>m[0])
const rid=(raw:string)=>decodeXmlText(readXmlAttribute(raw,'o:relid')??readXmlAttribute(raw,'r:id')??readXmlAttribute(raw,'relid')??'')
export interface NotePicture {sheetName:string;sheetIndex:number;row:number;column:number;author:string;text:string;sourceIdentity:string;mediaPath:string;relationshipId:string;mediaType:string;sha256:string;size:number;bytes:Uint8Array|null;unavailable?:string}
export interface NotePictureSheet {sheetName:string;sheetIndex:number;sourceIdentity:string;notes:NoteSource['notes'];readOnlyReason?:string}
interface SheetContext extends NotePictureSheet {path:string;model:NoteSource;vmlRels:string}
function assertXml(xml:string,root:string,uri:string){
 const parser=new SaxesParser({xmlns:true});let depth=0
 parser.on('doctype',()=>{throw new Error('图片批注不支持DOCTYPE')})
 parser.on('opentag',t=>{depth++;if(depth===1&&(t.local!==root||t.uri!==uri)||['shape','fill','imagedata'].includes(t.local)&&t.uri!==V||['ClientData','Row','Column'].includes(t.local)&&t.uri!==X)throw new Error('图片批注命名空间身份无效')})
 parser.on('closetag',()=>{depth--});parser.write(xml).close()
}
// VML 根常为无命名空间 xml；只接受其规范 VML/Excel 元素与关系属性。
function assertVml(xml:string){
 const parser=new SaxesParser({xmlns:true})
 parser.on('doctype',()=>{throw new Error('图片批注不支持DOCTYPE')})
 parser.on('opentag',t=>{if(['shape','fill','imagedata'].includes(t.local)&&t.uri!==V||['ClientData','Row','Column'].includes(t.local)&&t.uri!==X)throw new Error('图片批注VML命名空间身份无效');for(const a of Object.values(t.attributes))if(['relid','id'].includes(a.local)&&a.prefix&&['fill','imagedata'].includes(t.local)&&a.uri!==O&&a.uri!==R)throw new Error('图片批注关系命名空间身份无效')})
 parser.write(xml).close()
}
/** 实际签名及像素尺寸：不以扩展名/MIME代替bytes身份。 */
export function noteImageInfo(bytes:Uint8Array):{mediaType:'image/png'|'image/jpeg'|'image/gif';width:number;height:number}{
 if(!bytes.length||bytes.length>6*1024*1024)throw new Error('批注图片须为6 MiB以内PNG/JPEG/GIF')
 const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);let width=0,height=0,mediaType:'image/png'|'image/jpeg'|'image/gif'
 if(bytes.length>=24&&[137,80,78,71,13,10,26,10].every((b,i)=>bytes[i]===b)&&String.fromCharCode(...bytes.slice(12,16))==='IHDR'){mediaType='image/png';width=view.getUint32(16);height=view.getUint32(20);let end=false,i=8;while(i+12<=bytes.length){const length=view.getUint32(i);if(i+length+12>bytes.length)throw new Error('PNG图片结构不完整');const type=String.fromCharCode(...bytes.slice(i+4,i+8));i+=length+12;if(type==='IEND'){end=length===0&&i===bytes.length;break}}if(!end)throw new Error('PNG图片结构不完整')}
 else if(bytes.length>=13&&/^GIF8[79]a$/.test(String.fromCharCode(...bytes.slice(0,6)))){mediaType='image/gif';width=view.getUint16(6,true);height=view.getUint16(8,true);if(bytes.at(-1)!==59)throw new Error('GIF图片结构不完整')}
 else if(bytes.length>=4&&bytes[0]===255&&bytes[1]===216&&bytes.at(-2)===255&&bytes.at(-1)===217){
  mediaType='image/jpeg';let i=2
  while(i+3<bytes.length){if(bytes[i++]!==255)throw new Error('JPEG图片结构无效');while(bytes[i]===255)i++;const marker=bytes[i++]!;if(marker===217||marker===218)break;if(marker===1||marker>=208&&marker<=215)continue;const length=view.getUint16(i);if(length<2||i+length>bytes.length)throw new Error('JPEG图片段无效');if([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(marker)){height=view.getUint16(i+3);width=view.getUint16(i+5);break}i+=length}
 }else throw new Error('批注图片实际格式不是PNG/JPEG/GIF')
 if(!width||!height||width>30000||height>30000||width*height>40_000_000)throw new Error('批注图片像素尺寸超出预算')
 return {mediaType,width,height}
}
async function contexts(bytes:Uint8Array){
 const source=await createBufferEntrySource(bytes),zip=await JSZip.loadAsync(bytes,{checkCRC32:true}),book=await source.readText('xl/workbook.xml'),result:SheetContext[]=[],issues:{sheetName:string;message:string}[]=[]
 assertXml(book,'workbook',S)
 for(const [sheetIndex,sheet] of parseSheetElements(book).entries()){
  if(!sheet.relationshipId)continue
  try{
   const path=await resolveWorksheetPath(source,sheet.relationshipId),worksheet=await source.readText(path)
   assertXml(worksheet,'worksheet',S)
   const model=await readSheetNotes(source,path,{allowPictures:true,allowThreads:true});if(model.readOnlyReason)throw new Error(model.readOnlyReason)
   let vmlRels='';if(model.commentsXml)assertXml(model.commentsXml,'comments',S)
   if(model.vmlXml){assertVml(model.vmlXml!);if(await source.has(relsPath(model.vmlPath!))){vmlRels=await source.readText(relsPath(model.vmlPath!));relationships(vmlRels,relsPath(model.vmlPath!))}}
   const media=[]
   if(vmlRels)for(const rel of relationships(vmlRels,relsPath(model.vmlPath!)))if(!rel.external&&rel.type===imageRel){const part=resolvePivotTarget(model.vmlPath!,rel.target),entry=zip.file(part);media.push([part,entry?sha256Hex(await entry.async('uint8array')):'missing'])}
   const sourceIdentity=sha256Hex(JSON.stringify([path,model.sourceIdentity,vmlRels,media]))
   result.push({sheetName:sheet.name,sheetIndex,path,model,vmlRels,sourceIdentity,notes:model.notes})
  }catch(error){issues.push({sheetName:sheet.name,message:(error as Error).message})}
 }
 return {source,zip,sheets:result,issues}
}
export async function readNotePictures(bytes:Uint8Array):Promise<{pictures:NotePicture[];sheets:NotePictureSheet[];issues:{sheetName:string;message:string}[]}>{
 const ctx=await contexts(bytes),pictures:NotePicture[]=[]
 for(const sheet of ctx.sheets){
  const rels=sheet.vmlRels?relationships(sheet.vmlRels,relsPath(sheet.model.vmlPath!)):[]
  for(const note of sheet.notes){const shape=sheet.model.shapeXml.get(noteKey(note.row,note.column))??'',paint=mediaTags(shape).filter(t=>rid(t));if(!paint.length)continue
   const id=rid(paint[0]!),relationship=rels.find(r=>r.id===id),record:NotePicture={...note,sheetName:sheet.sheetName,sheetIndex:sheet.sheetIndex,sourceIdentity:sheet.sourceIdentity,mediaPath:'',relationshipId:id,mediaType:'',size:0,sha256:'',bytes:null}
   try{if(paint.length!==1||!relationship||relationship.external||relationship.type!==imageRel)throw new Error('批注图片关系身份无效或外部来源不允许读取');const path=resolvePivotTarget(sheet.model.vmlPath!,relationship.target);if(!path.startsWith('xl/media/'))throw new Error('批注图片媒体路径越界');record.mediaPath=path;const entry=ctx.zip.file(path);if(!entry)throw new Error('批注图片文件缺失');const data=await entry.async('uint8array'),info=noteImageInfo(data);Object.assign(record,{mediaType:info.mediaType,bytes:data,size:data.length,sha256:sha256Hex(data)})}catch(error){record.unavailable=(error as Error).message}
   pictures.push(record)
  }
 }
 return {pictures: pictures.sort((a,b)=>a.sheetIndex-b.sheetIndex||a.row-b.row||a.column-b.column),sheets:ctx.sheets.map(({sheetName,sheetIndex,sourceIdentity,notes})=>({sheetName,sheetIndex,sourceIdentity,notes})),issues:ctx.issues}
}
const pictureSchema=z.object({mediaType:z.enum(['image/png','image/jpeg','image/gif']),bytesBase64:z.string().min(1).max(9*1024*1024),size:z.number().int().positive().max(6*1024*1024),sha256:z.string().regex(/^[a-f0-9]{64}$/),widthPx:z.number().int().positive().max(30000),heightPx:z.number().int().positive().max(30000),name:z.string().max(255)}).strict()
export const notePictureOperationSchema=z.object({kind:z.literal('setNotePicture'),sheetName:z.string().min(1).max(31),row:z.number().int().min(0).max(1048575),column:z.number().int().min(0).max(16383),sourceIdentity:z.string().regex(/^[a-f0-9]{64}$/),picture:pictureSchema.nullable()}).strict()
const stripPaint=(shape:string)=>shape.replace(new RegExp('<'+tag('(?:fill|imagedata)')+'\\b[^>]*\\/?>','g'),raw=>rid(raw)?'':raw)
async function mediaReferenced(source:EntrySource,part:string,replacements:Map<string,string>,removed:Set<string>){
 for(const path of await source.paths())if(path.endsWith('.rels')&&!removed.has(path)){
  const owner=path.replace(/(^|\/)_rels\/([^/]+)\.rels$/,'$1$2')
  // 无法证明关系可解析时宁可保留媒体。
  try{for(const r of relationships(replacements.get(path)??await source.readText(path),path))if(!r.external&&resolvePivotTarget(owner,r.target)===part)return true}catch{return true}
 }
 return false
}
export async function applyNotePictureOperation(bytes:Uint8Array,raw:unknown):Promise<Uint8Array>{
 const op=notePictureOperationSchema.parse(raw);let ctx=await contexts(bytes),sheet=ctx.sheets.find(s=>s.sheetName===op.sheetName)
 if(!sheet)throw new Error(ctx.issues.find(i=>i.sheetName===op.sheetName)?.message??'图片批注工作表不存在')
 if(sheet.sourceIdentity!==op.sourceIdentity)throw new Error('图片批注来源身份已变化')
 let image:Uint8Array|undefined
 if(op.picture){if(!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(op.picture.bytesBase64))throw new Error('批注图片base64身份无效');image=Uint8Array.from(atob(op.picture.bytesBase64),c=>c.charCodeAt(0));const info=noteImageInfo(image);if(image.length!==op.picture.size||sha256Hex(image)!==op.picture.sha256||info.mediaType!==op.picture.mediaType||info.width!==op.picture.widthPx||info.height!==op.picture.heightPx)throw new Error('批注图片MIME、尺寸或摘要身份不匹配')}
 const key=noteKey(op.row,op.column)
 if(sheet.model.notes.some(n=>n.row===op.row&&n.column===op.column&&n.author.startsWith('tc=')))throw new Error('线程批注不支持设置旧式批注图片')
 if(!sheet.model.shapeXml.has(key)){
  if(!image)return bytes
  bytes=await patchSheetNotes(bytes,op.sheetName,sheet.model.sourceIdentity,[{row:op.row,column:op.column,text:''}],{allowPictures:true,allowThreads:true});ctx=await contexts(bytes);sheet=ctx.sheets.find(s=>s.sheetName===op.sheetName)!
 }
 const vml=sheet.model.vmlPath!,oldShape=sheet.model.shapeXml.get(key)!,oldPaint=mediaTags(oldShape).filter(t=>rid(t)),replaced=new Map<string,string>(),added=new Map<string,string>(),addedBinary=new Map<string,Uint8Array>(),removed=new Set<string>()
 if(oldPaint.length>1)throw new Error('单个批注含多张图片，无法安全修改')
 let shape=stripPaint(oldShape),rels=sheet.vmlRels,relsPart=relsPath(vml)
 if(oldPaint.length){
  const id=rid(oldPaint[0]!),allRels=relationships(rels,relsPart),relationship=allRels.find(r=>r.id===id)
  if(!relationship||relationship.external||relationship.type!==imageRel)throw new Error('图片批注来源关系身份无效')
  const rest=sheet.model.vmlXml!.replace(oldShape,shape)
  if(!mediaTags(rest).some(t=>rid(t)===id)){
   rels=rels.replace(/<(?:[\w.-]+:)?Relationship\b[^>]*\/?\s*>/g,r=>readXmlAttribute(r,'Id')===id?'':r)
   replaced.set(relsPart,rels)
   const media=resolvePivotTarget(vml,relationship.target)
   if(!await mediaReferenced(ctx.source,media,replaced,removed)){removed.add(media);const types=await ctx.source.readText('[Content_Types].xml');replaced.set('[Content_Types].xml',removePartOverrides(types,new Set([media])))}
  }
 }
 if(image&&op.picture){
  const ext=({'image/png':'png','image/jpeg':'jpeg','image/gif':'gif'}as const)[op.picture.mediaType];let n=1,path='';do{path='xl/media/notePicture'+n+++'.'+ext}while(await ctx.source.has(path));addedBinary.set(path,image)
  if(!rels)rels='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
  const ids=new Set(relationships(rels,relsPart).map(r=>r.id));let id='';n=1;do{id='notePicture'+n++}while(ids.has(id))
  rels=rels.replace(/<\/(?:[\w.-]+:)?Relationships>/,'<Relationship Id="'+id+'" Type="'+imageRel+'" Target="../media/'+path.split('/').at(-1)+'"/></Relationships>')
  shape=shape.replace(/^(<(?:[\w.-]+:)?shape\b[^>]*>)/,'$1<v:fill xmlns:v="'+V+'" xmlns:o="'+O+'" o:relid="'+id+'" o:title="'+escapeXmlText(op.picture.name)+'" type="frame" recolor="t" rotate="t"/>')
  const scale=Math.min(1,255/(Math.max(op.picture.widthPx,op.picture.heightPx)*.75)),size='width:'+Math.max(1,op.picture.widthPx*.75*scale)+'pt;height:'+Math.max(1,op.picture.heightPx*.75*scale)+'pt;'
  shape=shape.replace(/\bstyle="([^"]*)"/,(raw,style:string)=>'style="'+style.replace(/(?:^|;)\s*(?:width|height):[^;]*/g,'')+';'+size+'"')
  let types=replaced.get('[Content_Types].xml')??await ctx.source.readText('[Content_Types].xml')
  if(!new RegExp('<Default\\b[^>]*Extension="'+ext+'"').test(types))types=types.replace('</Types>','<Default Extension="'+ext+'" ContentType="'+op.picture.mediaType+'"/></Types>');replaced.set('[Content_Types].xml',types)
 }
 replaced.set(vml,sheet.model.vmlXml!.replace(oldShape,shape))
 if(rels!==sheet.vmlRels){if(await ctx.source.has(relsPart))replaced.set(relsPart,rels);else added.set(relsPart,rels)}
 const mutation=await assemblePackage(bytes,{replaced,added,addedBinary,removedEntries:[...removed],addedEntries:[...added.keys(),...addedBinary.keys()],touchedEntries:[...replaced.keys(),...added.keys(),...addedBinary.keys(),...removed]});assertOnlyTouchedEntriesChanged(mutation);return mutation.buffer
}

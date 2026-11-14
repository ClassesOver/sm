/** 普通 drawing 图片：受控字节插入及独立回读，不借用批注或报告图表 lineage。 */
import JSZip from 'jszip'
import {SaxesParser} from 'saxes'
import {z} from 'zod'
import {applyStaticImage} from './chart-add'
import {columnWidthToPixels,rowHeightToPixels} from './geometry'
import {noteImageInfo} from './note-pictures'
import {sha256Hex} from './sha256'
import {assemblePackage,assertOnlyTouchedEntriesChanged,createBufferEntrySource} from './zip'
import {parseSheetElements,resolveWorksheetPath} from './workbook-read'
import {relationships,resolveTarget} from './sheet-removal-parts'
import {resolvePivotTarget} from './pivot-add'
const XDR='http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',A='http://schemas.openxmlformats.org/drawingml/2006/main',R='http://schemas.openxmlformats.org/officeDocument/2006/relationships',S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const relsPath=(part:string)=>part.replace(/([^/]+)$/,'_rels/$1.rels')
interface Node {uri:string;local:string;attrs:Record<string,string>;children:Node[];text:string;start:number;end:number;openEnd:number;closeStart:number;prefix:string;selfClosing:boolean}
function tree(xml:string):Node{
 const stack:Node[]=[],roots:Node[]=[];const parser=new SaxesParser({xmlns:true})
 parser.on('doctype',()=>{throw new Error('图片XML不支持DOCTYPE')})
 parser.on('opentag',t=>{const node:Node={uri:t.uri,local:t.local,attrs:Object.fromEntries(Object.values(t.attributes).map(a=>[(a.uri?`{${a.uri}}`:'')+a.local,a.value])),children:[],text:'',start:xml.lastIndexOf('<',parser.position-1),end:0,openEnd:parser.position,closeStart:0,prefix:t.prefix?`${t.prefix}:`:'',selfClosing:t.isSelfClosing};if(stack.length)stack.at(-1)!.children.push(node);else roots.push(node);stack.push(node)})
 parser.on('text',s=>{if(stack.length)stack.at(-1)!.text+=s});parser.on('closetag',()=>{const n=stack.pop()!;n.end=parser.position;n.closeStart=n.selfClosing?n.openEnd:xml.lastIndexOf('<',parser.position-1)});parser.write(xml).close();if(roots.length!==1)throw new Error('图片XML根身份无效');return roots[0]!
}
const child=(n:Node,uri:string,local:string)=>n.children.find(c=>c.uri===uri&&c.local===local)
const number=(n:Node|undefined)=>{const value=Number(n?.text);if(!n||!Number.isFinite(value)||value<0)throw new Error('图片锚点无效');return value}
function index(n:Node|undefined,max:number){const value=number(n);if(!Number.isInteger(value)||value>max)throw new Error('图片锚点范围无效');return value}
function dimensions(sheet:Node){
 const format=child(sheet,S,'sheetFormatPr'),defaultColumn=columnWidthToPixels(Number(format?.attrs.defaultColWidth??8.43)),defaultRow=rowHeightToPixels(Number(format?.attrs.defaultRowHeight??15))
 const columns=child(sheet,S,'cols')?.children.filter(c=>c.uri===S&&c.local==='col')??[],rows=child(sheet,S,'sheetData')?.children.filter(c=>c.uri===S&&c.local==='row')??[]
 return {column:(index:number)=>{const c=columns.find(c=>index+1>=Number(c.attrs.min)&&index+1<=Number(c.attrs.max));return c?.attrs.hidden==='1'?0:c?.attrs.width?columnWidthToPixels(Number(c.attrs.width)):defaultColumn},row:(index:number)=>{const r=rows.find(r=>Number(r.attrs.r)===index+1);return r?.attrs.hidden==='1'?0:r?.attrs.ht?rowHeightToPixels(Number(r.attrs.ht)):defaultRow}}
}
export async function pictureSourceIdentity(bytes:Uint8Array):Promise<string>{
 await createBufferEntrySource(bytes);const zip=await JSZip.loadAsync(bytes,{checkCRC32:true}),entries=[]
 for(const path of Object.keys(zip.files).filter(p=>!zip.files[p]!.dir).sort())entries.push([path,sha256Hex(await zip.file(path)!.async('uint8array'))])
 return sha256Hex(JSON.stringify(entries))
}
const picture=z.object({mediaType:z.enum(['image/png','image/jpeg']),bytesBase64:z.string().min(1).max(9*1024*1024),size:z.number().int().positive().max(6*1024*1024),sha256:z.string().regex(/^[a-f0-9]{64}$/),widthPx:z.number().int().positive().max(30000),heightPx:z.number().int().positive().max(30000),name:z.string().min(1).max(255)}).strict()
export const insertPictureSchema=z.object({kind:z.literal('insertPicture'),sheetName:z.string().min(1).max(31),sourceIdentity:z.string().regex(/^[a-f0-9]{64}$/),imageId:z.string().regex(/^[A-Za-z0-9_-]{1,100}$/),row:z.number().int().min(0).max(1048575),column:z.number().int().min(0).max(16383),widthPx:z.number().finite().positive().max(4000),heightPx:z.number().finite().positive().max(4000),picture}).strict()
export async function insertWorkbookPicture(bytes:Uint8Array,raw:unknown):Promise<Uint8Array>{
 const op=insertPictureSchema.parse(raw)
 if(await pictureSourceIdentity(bytes)!==op.sourceIdentity)throw new Error('普通图片工作簿来源身份已变化')
 if(!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(op.picture.bytesBase64))throw new Error('普通图片base64身份无效')
 const image=Uint8Array.from(atob(op.picture.bytesBase64),c=>c.charCodeAt(0)),info=noteImageInfo(image)
 if(info.mediaType!==op.picture.mediaType||image.length!==op.picture.size||sha256Hex(image)!==op.picture.sha256||info.width!==op.picture.widthPx||info.height!==op.picture.heightPx)throw new Error('普通图片MIME、尺寸或摘要身份不匹配')
 const source=await createBufferEntrySource(bytes),sheets=parseSheetElements(await source.readText('xl/workbook.xml')),sheet=sheets.find(s=>s.name===op.sheetName)
 if(!sheet?.relationshipId)throw new Error('图片工作表不存在')
 const xml=tree(await source.readText(await resolveWorksheetPath(source,sheet.relationshipId)))
 if(xml.uri!==S||xml.local!=='worksheet'||child(xml,S,'sheetProtection'))throw new Error('工作表图片身份无效或受保护')
 const existing=await readWorkbookPictures(bytes);if(existing.pictures.some(p=>p.imageId===op.imageId&&p.sheetName===op.sheetName))throw new Error('图片身份已存在')
 const sizes=dimensions(xml)
 function end(start:number,pixels:number,size:(i:number)=>number,max:number){let index=start;while(index<max&&pixels>=size(index)){pixels-=size(index);index++}if(index===max&&pixels>size(index))throw new Error('图片超出工作表边界');return {index,offset:Math.round(pixels*9525)}}
 const x=end(op.column,op.widthPx,sizes.column,16383),y=end(op.row,op.heightPx,sizes.row,1048575)
 return (await applyStaticImage(bytes,{worksheetSheetName:op.sheetName,imageId:op.imageId,bytes:image,contentType:op.picture.mediaType,anchor:{fromRow:op.row,fromColumn:op.column,fromRowOffset:0,fromColumnOffset:0,toRow:y.index,toColumn:x.index,toRowOffset:y.offset,toColumnOffset:x.offset}})).bytes
}
export interface WorkbookPicture {sheetName:string;imageId:string;drawingPart:string;pictureId:string;anchorKind:string;relationshipId:string;mediaPart:string;geometryReadOnlyReason?:string;row:number;column:number;rowOffsetPx:number;columnOffsetPx:number;widthPx:number;heightPx:number;mediaType:string;sha256:string;bytes:Uint8Array}
/** 导入器尚未投影裁剪、旋转、翻转，几何编辑不得把未显示的语义当成普通矩形。 */
function pictureGeometryReadOnlyReason(pic:Node):string|undefined{
 const fill=child(pic,XDR,'blipFill'),shape=child(pic,XDR,'spPr'),reasons:string[]=[]
 for(const crop of fill?.children.filter(n=>n.uri===A&&n.local==='srcRect')??[])if(['l','t','r','b'].some(k=>Number(crop.attrs[k]??0)!==0))reasons.push('图片包含尚未显示的裁剪，暂不能移动或缩放；可以删除')
 for(const transform of shape?.children.filter(n=>n.uri===A&&n.local==='xfrm')??[]){
  if(Number(transform.attrs.rot??0)!==0)reasons.push('图片包含尚未显示的旋转，暂不能移动或缩放；可以删除')
  if(['flipH','flipV'].some(k=>transform.attrs[k]!==undefined&&!['0','false'].includes(transform.attrs[k]!)))reasons.push('图片包含尚未显示的翻转，暂不能移动或缩放；可以删除')
 }
 return reasons.length?[...new Set(reasons)].join('；'):undefined
}
export async function readWorkbookPictures(bytes:Uint8Array):Promise<{pictures:WorkbookPicture[];issues:string[]}>{
 const source=await createBufferEntrySource(bytes),zip=await JSZip.loadAsync(bytes,{checkCRC32:true}),pictures:WorkbookPicture[]=[],issues:string[]=[]
 for(const sheet of parseSheetElements(await source.readText('xl/workbook.xml'))){
  if(!sheet.relationshipId)continue
  try{
   const part=await resolveWorksheetPath(source,sheet.relationshipId),xml=tree(await source.readText(part)),drawing=child(xml,S,'drawing');if(!drawing)continue
   const rels=relationships(await source.readText(relsPath(part)),relsPath(part)),rel=rels.find(r=>r.id===drawing.attrs[`{${R}}id`])
   if(!rel||rel.external||rel.type!==R+'/drawing')throw new Error('图片drawing关系身份无效')
   const drawingPart=resolvePivotTarget(part,rel.target),root=tree(await source.readText(drawingPart));if(root.uri!==XDR||root.local!=='wsDr')throw new Error('图片drawing命名空间身份无效')
   const drawingRels=relationships(await source.readText(relsPath(drawingPart)),relsPath(drawingPart)),sizes=dimensions(xml)
   for(const anchor of root.children){
    if(anchor.uri!==XDR)continue
    const pic=child(anchor,XDR,'pic');if(!pic)continue
    try{
     if(!['twoCellAnchor','oneCellAnchor'].includes(anchor.local))throw new Error('暂不支持图片绝对锚点')
     const from=child(anchor,XDR,'from')!,row=index(from&&child(from,XDR,'row'),1048575),column=index(from&&child(from,XDR,'col'),16383),rowOffsetPx=number(child(from,XDR,'rowOff'))/9525,columnOffsetPx=number(child(from,XDR,'colOff'))/9525
     let widthPx:number,heightPx:number
     if(anchor.local==='oneCellAnchor'){const ext=child(anchor,XDR,'ext')!;widthPx=Number(ext?.attrs.cx)/9525;heightPx=Number(ext?.attrs.cy)/9525}
     else{const to=child(anchor,XDR,'to')!,toRow=index(to&&child(to,XDR,'row'),1048575),toColumn=index(to&&child(to,XDR,'col'),16383);if(toRow<row||toColumn<column||toRow>1048575||toColumn>16383)throw new Error('图片锚点范围无效');widthPx=number(child(to,XDR,'colOff'))/9525-columnOffsetPx;heightPx=number(child(to,XDR,'rowOff'))/9525-rowOffsetPx;for(let c=column;c<toColumn;c++)widthPx+=sizes.column(c);for(let r=row;r<toRow;r++)heightPx+=sizes.row(r)}
     if(!Number.isFinite(widthPx)||!Number.isFinite(heightPx)||widthPx<=0||heightPx<=0)throw new Error('图片显示尺寸无效')
     const blipFill=child(pic,XDR,'blipFill'),blip=blipFill&&child(blipFill,A,'blip'),imageRel=drawingRels.find(r=>r.id===blip?.attrs[`{${R}}embed`])
     if(!imageRel||imageRel.external||imageRel.type!==R+'/image')throw new Error('图片媒体关系无效或外部来源不允许读取')
     const media=resolvePivotTarget(drawingPart,imageRel.target);if(!media.startsWith('xl/media/'))throw new Error('图片媒体路径越界')
     const entry=zip.file(media);if(!entry)throw new Error('图片媒体缺失');const data=await entry.async('uint8array'),info=noteImageInfo(data)
     const props=child(pic,XDR,'nvPicPr'),id=props&&child(props,XDR,'cNvPr'),geometryReadOnlyReason=pictureGeometryReadOnlyReason(pic)
     pictures.push({sheetName:sheet.name,imageId:id?.attrs.name??media,drawingPart,pictureId:id?.attrs.id??'',anchorKind:anchor.local,...(geometryReadOnlyReason?{geometryReadOnlyReason}:{}),relationshipId:imageRel.id,mediaPart:media,row,column,rowOffsetPx,columnOffsetPx,widthPx,heightPx,bytes:data,sha256:sha256Hex(data),mediaType:info.mediaType})
    }catch(error){issues.push(`${sheet.name}: ${(error as Error).message}`)}
   }
  }catch(error){issues.push(`${sheet.name}: ${(error as Error).message}`)}
 }
 return {pictures,issues}
}

const pictureGeometry=z.object({row:z.number().int().min(0).max(1048575),column:z.number().int().min(0).max(16383),rowOffsetPx:z.number().finite().nonnegative(),columnOffsetPx:z.number().finite().nonnegative(),widthPx:z.number().finite().positive(),heightPx:z.number().finite().positive()}).strict()
export const editPictureSchema=z.object({kind:z.literal('editPicture'),sheetName:z.string().min(1).max(31),sourceIdentity:z.string().regex(/^[a-f0-9]{64}$/),drawingPart:z.string().regex(/^xl\/drawings\/[^/]+\.xml$/),pictureId:z.string().regex(/^(0|[1-9]\d*)$/).refine(v=>Number(v)<=4294967295),mediaSha256:z.string().regex(/^[a-f0-9]{64}$/),before:pictureGeometry,geometry:pictureGeometry.nullable()}).strict()
export type PictureGeometry=z.infer<typeof pictureGeometry>
export type EditPicture=z.infer<typeof editPictureSchema>
const geometryKeys=['row','column','rowOffsetPx','columnOffsetPx','widthPx','heightPx'] as const
function single(n:Node,uri:string,local:string):Node{const matches=n.children.filter(c=>c.uri===uri&&c.local===local);if(matches.length!==1)throw new Error('图片目标结构不完整或不唯一');return matches[0]!}
function descendants(n:Node):Node[]{return [n,...n.children.flatMap(descendants)]}

/** 只改稳定身份对应的普通图片锚点；删除保留关系和媒体，避免破坏共享引用。 */
export async function editWorkbookPicture(bytes:Uint8Array,raw:unknown):Promise<Uint8Array>{
 const op=editPictureSchema.parse(raw)
 if(await pictureSourceIdentity(bytes)!==op.sourceIdentity)throw new Error('普通图片工作簿来源身份已变化')
 const source=await createBufferEntrySource(bytes),zip=await JSZip.loadAsync(bytes,{checkCRC32:true}),sheets=parseSheetElements(await source.readText('xl/workbook.xml')),sheet=sheets.find(s=>s.name===op.sheetName)
 if(!sheet?.relationshipId)throw new Error('图片工作表不存在')
 const worksheetPart=await resolveWorksheetPath(source,sheet.relationshipId),sheetXml=tree(await source.readText(worksheetPart,{preservePrefixes:true}))
 if(sheetXml.uri!==S||sheetXml.local!=='worksheet'||child(sheetXml,S,'sheetProtection'))throw new Error('工作表图片身份无效或受保护')
 const drawing=single(sheetXml,S,'drawing'),sheetRels=relationships(await source.readText(relsPath(worksheetPart)),relsPath(worksheetPart)),drawingRel=sheetRels.find(r=>r.id===drawing.attrs[`{${R}}id`])
 if(!drawingRel||drawingRel.external||drawingRel.type!==R+'/drawing'||resolveTarget(worksheetPart,drawingRel.target)!==op.drawingPart)throw new Error('图片drawing目标身份已变化')
 let incoming=0
 for(const path of Object.keys(zip.files).filter(p=>p.endsWith('.rels')&&!zip.files[p]!.dir)){
  const owner=path==='_rels/.rels'?'':path.replace(/(^|\/)\_rels\/([^/]+)\.rels$/,'$1$2')
  for(const rel of relationships(await source.readText(path),path))if(!rel.external&&resolveTarget(owner,rel.target)===op.drawingPart)incoming++
 }
 if(incoming!==1)throw new Error('图片drawing被多个关系共享，拒绝修改')
 const xml=await source.readText(op.drawingPart,{preservePrefixes:true}),root=tree(xml)
 if(root.uri!==XDR||root.local!=='wsDr')throw new Error('图片drawing命名空间身份无效')
 const ids=descendants(root).filter(n=>n.uri===XDR&&n.local==='cNvPr'&&n.attrs.id===op.pictureId)
 if(ids.length!==1)throw new Error('图片目标身份不唯一或不存在')
 const matches=root.children.filter(n=>n.children.some(p=>p.uri===XDR&&p.local==='pic'&&descendants(p).includes(ids[0]!)))
 if(matches.length!==1)throw new Error('图片目标锚点不唯一或不完整')
 const anchor=matches[0]!
 if(anchor.uri!==XDR||!['oneCellAnchor','twoCellAnchor'].includes(anchor.local))throw new Error('暂不支持图片绝对锚点')
 const allowed=anchor.local==='oneCellAnchor'?['from','ext','pic','clientData']:['from','to','pic','clientData']
 if(anchor.children.some(n=>n.uri!==XDR||!allowed.includes(n.local)))throw new Error('图片目标锚点包含其他对象')
 for(const local of allowed)single(anchor,XDR,local)
 const pic=single(anchor,XDR,'pic'),props=single(single(pic,XDR,'nvPicPr'),XDR,'cNvPr')
 if(props!==ids[0])throw new Error('图片目标属性身份不匹配')
 single(single(pic,XDR,'blipFill'),A,'blip');single(pic,XDR,'spPr')
 for(const side of anchor.local==='twoCellAnchor'?['from','to']:['from']){const marker=single(anchor,XDR,side);if(marker.children.length!==4||marker.children.some(c=>c.uri!==XDR||!['col','colOff','row','rowOff'].includes(c.local)))throw new Error('图片锚点标记结构无效');for(const key of ['col','colOff','row','rowOff'])single(marker,XDR,key)}
 const read=await readWorkbookPictures(bytes),pictures=read.pictures.filter(p=>p.sheetName===op.sheetName&&p.drawingPart===op.drawingPart&&p.pictureId===op.pictureId)
 if(pictures.length!==1||pictures[0]!.sha256!==op.mediaSha256||geometryKeys.some(k=>pictures[0]![k]!==op.before[k]))throw new Error('图片媒体或原始几何身份已变化')
 if(op.geometry!==null&&pictures[0]!.geometryReadOnlyReason)throw new Error(pictures[0]!.geometryReadOnlyReason)
 const patches:{start:number;end:number;text:string}[]=[]
 const replace=(n:Node,text:string)=>patches.push({start:n.start,end:n.end,text})
 function setValue(n:Node,value:number){if(n.selfClosing||n.children.length)throw new Error('图片锚点数值结构无效');patches.push({start:n.openEnd,end:n.closeStart,text:String(value)})}
 function setAttrs(n:Node,values:Record<string,number>){let opening=xml.slice(n.start,n.openEnd);for(const [key,value] of Object.entries(values)){if(!Number.isSafeInteger(value)||value<0)throw new Error('图片几何超出精度范围');const re=new RegExp(`(\\s${key}\\s*=\\s*)(["'])[^"']*\\2`);if(!re.test(opening))throw new Error('图片变换坐标不完整');opening=opening.replace(re,(_m,p,q)=>`${p}${q}${value}${q}`)}patches.push({start:n.start,end:n.openEnd,text:opening})}
 if(op.geometry===null)replace(anchor,'')
 else{
  const g:PictureGeometry=op.geometry,sizes=dimensions(sheetXml),emu=(v:number)=>{const result=Math.round(v*9525);if(!Number.isSafeInteger(result)||result<0)throw new Error('图片几何超出精度范围');return result}
  if(g.columnOffsetPx>=sizes.column(g.column)||g.rowOffsetPx>=sizes.row(g.row))throw new Error('图片起点偏移超出单元格边界')
  function end(start:number,pixels:number,size:(i:number)=>number,max:number){let i=start;for(;i<max&&pixels>=size(i);i++){const dimension=size(i);if(!Number.isFinite(dimension)||dimension<0)throw new Error('图片单元格尺寸无效');pixels-=dimension}if(!Number.isFinite(size(i))||pixels>size(i))throw new Error('图片超出工作表边界');return {index:i,offset:emu(pixels)}}
  const x=end(g.column,g.columnOffsetPx+g.widthPx,sizes.column,16383),y=end(g.row,g.rowOffsetPx+g.heightPx,sizes.row,1048575)
  function marker(n:Node,row:number,col:number,rowOff:number,colOff:number){if(n.children.length!==4||n.children.some(c=>c.uri!==XDR||!['col','colOff','row','rowOff'].includes(c.local)))throw new Error('图片锚点标记结构无效');for(const [key,value] of Object.entries({row,col,rowOff,colOff}))setValue(single(n,XDR,key),value)}
  marker(single(anchor,XDR,'from'),g.row,g.column,emu(g.rowOffsetPx),emu(g.columnOffsetPx))
  if(anchor.local==='twoCellAnchor')marker(single(anchor,XDR,'to'),y.index,x.index,y.offset,x.offset)
  else setAttrs(single(anchor,XDR,'ext'),{cx:emu(g.widthPx),cy:emu(g.heightPx)})
  const spPr=single(pic,XDR,'spPr'),transforms=spPr.children.filter(n=>n.uri===A&&n.local==='xfrm')
  if(transforms.length>1)throw new Error('图片变换身份不唯一')
  if(transforms.length){const transform=transforms[0]!;let left=g.columnOffsetPx,top=g.rowOffsetPx;for(let c=0;c<g.column;c++)left+=sizes.column(c);for(let r=0;r<g.row;r++)top+=sizes.row(r);setAttrs(single(transform,A,'off'),{x:emu(left),y:emu(top)});setAttrs(single(transform,A,'ext'),{cx:emu(g.widthPx),cy:emu(g.heightPx)})}
 }
 let output=xml;for(const patch of patches.sort((a,b)=>b.start-a.start))output=output.slice(0,patch.start)+patch.text+output.slice(patch.end)
 const mutation=await assemblePackage(bytes,{replaced:new Map([[op.drawingPart,output]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[op.drawingPart]})
 assertOnlyTouchedEntriesChanged(mutation);return mutation.buffer
}

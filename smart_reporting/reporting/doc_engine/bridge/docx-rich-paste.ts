/** 结构化外来内容→GenOffice 原生 writer；不接收客户端 XML。 */
import {createHash} from 'node:crypto'
import {parseDocx} from '../packages/docx-engine/src/parse.ts'
import {saveDocx,type SaveBlock,type SaveOptions} from '../packages/docx-engine/src/patch.ts'
import {generateTableModelXml,inlinePictureDrawingXml,NEW_PICTURE_TOKEN_PREFIX,mergePPrFormat,generateParagraphXml,splitXmlChildren,PPR_CHILD_ORDER} from '../packages/docx-engine/src/generate.ts'
import type {Block,GeneratedBlock,Run,TableModel,TableCell,ParaFormat} from '../packages/docx-engine/src/types.ts'
import {richPasteOperation,pasteParagraph,pasteTargetSupported,type PasteNode} from './docx-rich-paste-core.ts'
import {assertZipIdentity} from './docx-comment-source.ts'
import {loadDocxZip} from '../packages/docx-engine/src/zip-load.ts'
import {imageSizeFromBytes} from '../../slides_engine/packages/pptx-render/src/image-dpi.ts'
const fail=(reason:string):never=>{throw new Error('docx_rich_paste_'+reason)}
const sha=(v:Uint8Array)=>createHash('sha256').update(v).digest('hex')
function sliceRuns(b:Block,from:number,to:number):Run[]{const text=(b.runs??[]).map(r=>r.text).join('');for(const n of [from,to])if(!Number.isSafeInteger(n)||n<0||n>text.length||n>0&&/[\uD800-\uDBFF]/.test(text[n-1])&&/[\uDC00-\uDFFF]/.test(text[n]??''))fail('offset');let at=0;return (b.runs??[]).flatMap(r=>{const start=Math.max(0,from-at),end=Math.min(r.text.length,to-at);at+=r.text.length;return end>start?[{...r,text:r.text.slice(start,end)}]:[]})}
export async function patchDocxRichPaste(bytes:Uint8Array,value:unknown):Promise<Uint8Array>{
 assertZipIdentity(bytes);const op=richPasteOperation(value,sha(bytes)),parsed=await parseDocx(bytes),zip=await loadDocxZip(bytes)
 const settings=zip.file('word/settings.xml');if(settings&&/<w:(?:documentProtection|writeProtection)\b/.test(await settings.async('string')))fail('protected')
 const selected=parsed.blocks.filter(b=>b.docxIndex!=null&&b.docxIndex>=op.start.docxIndex&&b.docxIndex<=op.end.docxIndex)
 if(!selected.length||selected[0].docxIndex!==op.start.docxIndex||selected.at(-1)!.docxIndex!==op.end.docxIndex||selected.some(b=>!pasteTargetSupported(b)))fail('target_unsupported')
 const first=selected[0],last=selected.at(-1)!,prefix=sliceRuns(first,0,op.start.offset),lastLength=(last.runs??[]).map(r=>r.text).join('').length,suffix=sliceRuns(last,op.end.offset,lastLength)
 const pictures:NonNullable<SaveOptions['newPictures']>={},defs:NonNullable<NonNullable<SaveOptions['numbering']>['newDefs']>=[]
 const existing=new Set<string>();const numberingFile=zip.file('word/numbering.xml');if(numberingFile)for(const m of (await numberingFile.async('string')).matchAll(/w:numId=["'](\d+)["']/g))existing.add(m[1]);let nextNum=1,pictureId=0
 let previousList:string|null=null,listId:string|undefined
 function runs(nodes:PasteNode[]):Run[]{return nodes.map(n=>{
  if(n.type==='docInlineImage'){
   const a=n.attrs!,match=/^data:(image\/(?:png|jpeg));base64,(.*)$/.exec(String(a.dataUrl));if(!match)fail('image')
   const data=Buffer.from(match![2],'base64'),mime=match![1] as 'image/png'|'image/jpeg',size=imageSizeFromBytes(data);if(!size||data.length>8*1024*1024||size.w>12000||size.h>12000||mime==='image/png'&&!data.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))||mime==='image/jpeg'&&(data[0]!==255||data[1]!==216))fail('image')
   const token=NEW_PICTURE_TOKEN_PREFIX+ ++pictureId;pictures[token]={base64:match![2],mime};return{text:'',image:{xml:inlinePictureDrawingXml({rId:token,docPrId:token,widthPx:Number(a.widthPx)||size.w,heightPx:Number(a.heightPx)||size.h,altText:String(a.alt??'')})}} as Run
  }
  const run:Run={text:n.type==='hardBreak'?'\n':n.text??''}
  for(const m of n.marks??[]){if(['bold','italic','underline','strike'].includes(m.type))(run as unknown as Record<string,unknown>)[m.type]=true;else if(m.type==='docTextStyle')Object.assign(run,m.attrs);else if(m.type==='link')run.link={href:String(m.attrs!.href)}}
  return run
 })}
 function paragraph(n:PasteNode):GeneratedBlock{
  const a={...n.attrs},format={...a};for(const key of ['level','kind','ilvl'])delete format[key]
  const result:GeneratedBlock={type:n.type==='docHeading'?'heading':n.type==='docListItem'?'listItem':'paragraph',runs:runs(n.content??[]),...(Object.keys(format).length?{format:format as ParaFormat}:{})}
  if(n.type==='docHeading'){result.level=Number(a.level)||1;if(!parsed.headingStyleIds.has(result.level))result.outlineOnly=true}
  if(n.type==='docListItem'){
   const kind=a.kind==='ordered'?'ordered':'bullet';let numId=listId
   if(!numId||previousList!==kind){while(existing.has(String(nextNum)))nextNum++;numId=String(nextNum++);existing.add(numId);defs.push({numId,kind});listId=numId}
   result.list={kind,numId,ilvl:Number(a.ilvl)||0};previousList=kind
  }else previousList=null
  return result
 }
 function table(n:PasteNode):TableModel{
  const rows:TableCell[][]=[],spans=new Map<number,{left:number;cell:TableCell}>();let columns=0
  for(const row of n.content??[]){const cells:TableCell[]=[];let col=0;const fill=()=>{while(spans.has(col)){const item=spans.get(col)!;cells.push({...item.cell,paras:[''],richParas:[],vMerge:'continue'});const width=item.cell.colSpan??1;if(--item.left<=0)spans.delete(col);col+=width}}
   for(const c of row.content??[]){fill();const paras=(c.content??[]).filter(pasteParagraph).map(paragraph),nested=(c.content??[]).filter(x=>x.type==='docTable').map(table),nestedTableAnchors=(c.content??[]).flatMap((child,index)=>child.type==='docTable'?[(c.content??[]).slice(0,index).filter(pasteParagraph).length]:[]),span=Number(c.attrs?.colspan)||1,rowspan=Number(c.attrs?.rowspan)||1
    const cell:TableCell={paras:paras.map(p=>p.runs.map(r=>r.text).join('')),richParas:paras.map(p=>({...p.format,runs:p.runs,...(p.list?{list:p.list}:{})})),...(span>1?{colSpan:span}:{}),...(rowspan>1?{vMerge:'restart' as const}:{}),...(nested.length?{nestedTables:nested,nestedTableAnchors}:{}),...(c.attrs?.fill?{fill:String(c.attrs.fill)}:{}),...(c.attrs?.vAlign?{vAlign:c.attrs.vAlign as 'top'|'center'|'bottom'}:{})}
    cells.push(cell);if(rowspan>1)spans.set(col,{left:rowspan-1,cell});col+=span
   }fill();columns=Math.max(columns,col);rows.push(cells)
  }
  if(!rows.length||rows.length>200||columns>100||spans.size)fail('table_geometry')
  return {rows,colWidthsPct:Array.from({length:columns},()=>100/columns),widthPct:Number(n.attrs?.widthPct)||100,autoFit:'window'}
 }
 function preservedPPr(raw:string,block:GeneratedBlock):string{
  const merged=mergePPrFormat(raw,block.format??{}),fresh=generateParagraphXml({...block,runs:[],rawPPr:undefined},{headingStyleIds:parsed.headingStyleIds,listParagraphStyleId:parsed.listParagraphStyleId,allocateHyperlinkRel:()=>fail('internal_link')})
  const inner=(xml:string)=>xml.match(/<w:pPr(?: [^>]*)?>([\s\S]*?)<\/w:pPr>/)?.[1]??'',structural=new Set(['w:pStyle','w:numPr','w:outlineLvl'])
  const children=[...splitXmlChildren(inner(merged)).filter(c=>!structural.has(c.name)),...splitXmlChildren(inner(fresh)).filter(c=>structural.has(c.name))]
  children.sort((a,b)=>PPR_CHILD_ORDER.indexOf(a.name)-PPR_CHILD_ORDER.indexOf(b.name))
  return children.length?'<w:pPr>'+children.map(c=>c.xml).join('')+'</w:pPr>':''
 }
 const inserted:SaveBlock[]=op.blocks.map(n=>pasteParagraph(n)?{kind:'generated',block:paragraph(n)}:{kind:'xml',xml:generateTableModelXml(table(n))})
 function originalBlock(b:Block,r:Run[]):GeneratedBlock{return {type:b.type as GeneratedBlock['type'],runs:r,rawPPr:b.rawPPr,rawPAttrs:b.originalXml?.match(/^<w:p(\s[^>]*)?>/)?.[1],level:b.level,list:b.list}}
 if(prefix.length){if(inserted[0].kind==='generated'){inserted[0].block.runs.unshift(...prefix);if(first.rawPPr)inserted[0].block.rawPPr=preservedPPr(first.rawPPr,inserted[0].block)}else inserted.unshift({kind:'generated',block:originalBlock(first,prefix)})}
 if(suffix.length){const end=inserted.at(-1)!;if(end.kind==='generated'){end.block.runs.push(...suffix);if(end.block.rawPPr===undefined&&last.rawPPr)end.block.rawPPr=preservedPPr(last.rawPPr,end.block)}else inserted.push({kind:'generated',block:originalBlock(last,suffix)})}
 const saved:SaveBlock[]=[];for(const b of parsed.blocks){if(b.hidden)continue;if(b.docxIndex===op.start.docxIndex)saved.push(...inserted);if(b.docxIndex!=null&&(b.docxIndex<op.start.docxIndex||b.docxIndex>op.end.docxIndex))saved.push({kind:'original',docxIndex:b.docxIndex})}
 return saveDocx(parsed,saved,{newPictures:pictures,...(defs.length?{numbering:{newDefs:defs}}:{})})
}

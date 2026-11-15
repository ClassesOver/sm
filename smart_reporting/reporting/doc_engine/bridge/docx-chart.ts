/** Fixed GenOffice f8c17004 ChartInsertModal's genuine OOXML chart path. */
import JSZip from 'jszip'
import {parseDocx} from '../packages/docx-engine/src/parse'
import {saveDocx,findChartWorkbookPath,type SaveBlock} from '../packages/docx-engine/src/patch'
import type {NewChart} from '../packages/docx-engine/src/types'
import {docxInsertionAnchor,docxInsertionHash,readDocxInsertionAnchor,validDocxInsertText} from './docx-field'
import {patchChartPartXml,parseChartPartXml,patchChartWorkbookXlsxBase64} from '../packages/docx-engine/src/chart'
import {assertZipIdentity} from './docx-comment-source'
export const isDocxChartOperation=(v:{kind?:unknown})=>v.kind==='insertChart'||v.kind==='updateChart'
export function readDocxChartOperation(v:unknown){
 const op=v as any;if(op?.kind==='updateChart'){if(Object.keys(op).some(k=>!['kind','blockId','expectedObjectSha256','expectedChartSha256','chart'].includes(k))||![op.blockId,op.expectedObjectSha256,op.expectedChartSha256].every(x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x)))throw new Error('docx_chart_operation')}else readDocxInsertionAnchor(op,['chart'],'chart');const c=op.chart
 if(!isDocxChartOperation(op)||!c||typeof c!=='object'||Object.keys(c).some(k=>!['kind','title','categories','series'].includes(k))||!['bar','line','pie'].includes(c.kind)||(c.title!==undefined&&!validDocxInsertText(c.title))||!Array.isArray(c.categories)||c.categories.length<1||c.categories.length>256||!c.categories.every((x:unknown)=>validDocxInsertText(x))||!Array.isArray(c.series)||c.series.length<1||c.series.length>64||!c.series.every((s:any)=>s&&typeof s==='object'&&Object.keys(s).every(k=>['name','values'].includes(k))&&(validDocxInsertText(s.name)||(op.kind==='updateChart'&&s.name===undefined))&&Array.isArray(s.values)&&s.values.length===c.categories.length&&s.values.every((n:unknown)=>n===null||typeof n==='number'&&Number.isFinite(n))))throw new Error('docx_chart_operation')
 return op as {kind:'insertChart'|'updateChart';expectedChartSha256?:string;blockId:string;expectedObjectSha256:string;position:'before'|'after';chart:NewChart}
}
export async function patchDocxChart(bytes:Uint8Array,value:unknown,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 const op=readDocxChartOperation(value);if(op.kind==='updateChart')return patchExistingDocxChart(bytes,op,parsed);const {parsed:doc,source,at}=await docxInsertionAnchor(bytes,op,'chart',parsed)
 // Let the fixed engine allocate collision-free chart/workbook paths, rel IDs and drawing IDs.
 const blocks:SaveBlock[]=doc.extras.elements.map((_,docxIndex)=>({kind:'original',docxIndex}));blocks.push({kind:'chart',chart:op.chart})
 const generated=await saveDocx(doc,blocks),model=await parseDocx(generated)
 const before=await JSZip.loadAsync(bytes),after=await JSZip.loadAsync(generated)
 const addedCharts=Object.keys(after.files).filter(n=>/^word\/charts\/chart\d+\.xml$/.test(n)&&!before.file(n))
 if(addedCharts.length!==1)throw new Error('docx_chart_generation')
 const fragment=model.blocks.find(b=>b.chartDisplay?.partPath===addedCharts[0])?.originalXml
 if(!fragment)throw new Error('docx_chart_generation')
 // Keep original body XML byte-for-byte; namespace declarations are local to the new drawing.
 const xml=fragment.replace('<wp:inline ','<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" ').replace('<c:chart ','<c:chart xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ')
 before.file('word/document.xml',source.xml.slice(0,at)+xml+source.xml.slice(at),{createFolders:false})
 for(const name of Object.keys(after.files))if(!after.files[name]!.dir&&(!before.file(name)||['word/_rels/document.xml.rels','[Content_Types].xml'].includes(name)))before.file(name,await after.file(name)!.async('uint8array'),{createFolders:false})
 return before.generateAsync({type:'uint8array',compression:'DEFLATE'})
}

export async function inspectDocxCharts(bytes:Uint8Array,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 parsed??=await parseDocx(bytes);const zip=await JSZip.loadAsync(bytes),source=docxInsertionHash(bytes)
 const result=[];for(const b of parsed.blocks){if(!b.chartDisplay||b.docxIndex==null||!b.originalXml||!['bar','line','pie'].includes(b.chartDisplay.kind))continue;const part=await zip.file(b.chartDisplay.partPath)?.async('string');if(!part)continue
 result.push({blockId:docxInsertionHash(source+':block:'+b.docxIndex),expectedObjectSha256:docxInsertionHash(b.originalXml),expectedChartSha256:docxInsertionHash(part),docxIndex:b.docxIndex,chart:b.chartDisplay})}
 return result
}
async function patchExistingDocxChart(bytes:Uint8Array,op:ReturnType<typeof readDocxChartOperation>,parsed?:Awaited<ReturnType<typeof parseDocx>>){
 assertZipIdentity(bytes);parsed??=await parseDocx(bytes);if(parsed.protection?.enforced)throw new Error('docx_chart_protection')
 const target=(await inspectDocxCharts(bytes,parsed)).find(b=>b.blockId===op.blockId&&b.expectedObjectSha256===op.expectedObjectSha256&&b.expectedChartSha256===op.expectedChartSha256)
 if(!target)throw new Error('docx_chart_anchor')
 const old=target.chart,c=op.chart
 if(c.kind!==old.kind||c.categories.length!==old.categories.length||c.series.length!==old.series.length||c.series.some((s,i)=>s.values.length!==old.series[i]!.values.length||s.values.some((v,j)=>(v===null)!==(old.series[i]!.values[j]===null))))throw new Error('docx_chart_edit_structure_unsupported')
 const zip=await JSZip.loadAsync(bytes),path=old.partPath,original=await zip.file(path)!.async('string')
 const patched=patchChartPartXml(original,{title:c.title,categories:c.categories,series:c.series}),display=parseChartPartXml(patched,path)
 if(!display||display.title!==(c.title??old.title)||JSON.stringify(display.categories)!==JSON.stringify(c.categories)||JSON.stringify(display.series.map(s=>({name:s.name,values:s.values})))!==JSON.stringify(c.series))throw new Error('docx_chart_edit_cache_unsupported')
 const workbookPath=await findChartWorkbookPath(bytes,path)
 if(workbookPath){const workbook=await zip.file(workbookPath)?.async('base64');if(!workbook)throw new Error('docx_chart_workbook_unsupported');const updated=await patchChartWorkbookXlsxBase64(workbook,c.categories,c.series.map((s,i)=>({name:s.name??`Series${i+1}`,values:s.values})));if(!updated)throw new Error('docx_chart_workbook_unsupported');zip.file(workbookPath,updated,{base64:true,createFolders:false})}
 zip.file(path,patched,{createFolders:false});return zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
}

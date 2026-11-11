/** Range protocol follows pinned TextEditInput.styleRuns, expressed in UTF-16 units. */
import {plannedCharStyles,type RunStyle} from '../src/main/text-edit'
import type {TextEditInput} from '../src/shared/ipc'
export interface PdfTextStyleRun{start:number;end:number;font?:'arial'|'times'|'courier';size?:number;color?:[number,number,number];bold?:boolean;italic?:boolean}
const fields=['font','size','color','bold','italic'] as const
const scalarBoundary=(text:string,index:number)=>!(index>0&&index<text.length&&/[\uD800-\uDBFF]/.test(text[index-1]!)&&/[\uDC00-\uDFFF]/.test(text[index]!))
export function validateTextStyleRuns(text:string,runs:unknown):asserts runs is PdfTextStyleRun[]|undefined{
 if(runs===undefined)return
 if(!Array.isArray(runs)||runs.length>4000)throw Error('PDF 选区样式范围无效')
 let end=0
 for(const run of runs){
  if(!run||typeof run!=='object'||Array.isArray(run)||Object.keys(run).some(key=>!['start','end',...fields].includes(key)))throw Error('PDF 选区样式字段无效')
  if(!Number.isInteger(run.start)||!Number.isInteger(run.end)||run.start<end||run.start<0||run.end<=run.start||run.end>text.length||!scalarBoundary(text,run.start)||!scalarBoundary(text,run.end))throw Error('PDF 选区须为升序不重叠的完整 UTF-16 字符范围')
  if(!fields.some(key=>run[key]!==undefined))throw Error('PDF 选区样式不得为空')
  if(run.font!==undefined&&!['arial','times','courier'].includes(run.font))throw Error('PDF 选区字体无效')
  if(run.size!==undefined&&(!Number.isFinite(run.size)||run.size<6||run.size>72))throw Error('PDF 选区字号须为6–72')
  if(run.color!==undefined&&(!Array.isArray(run.color)||run.color.length!==3||run.color.some((value:unknown)=>typeof value!=='number'||!Number.isFinite(value)||value<0||value>1)))throw Error('PDF 选区颜色无效')
  if(run.bold!==undefined&&typeof run.bold!=='boolean'||run.italic!==undefined&&typeof run.italic!=='boolean')throw Error('PDF 选区粗斜体无效')
  end=run.end
 }
}
export function nativeTextStyleRuns(runs:PdfTextStyleRun[]|undefined):TextEditInput['styleRuns']{return runs?.map(run=>({...run,...(run.color?{color:run.color.map(value=>Math.round(value*255)) as [number,number,number]}:{})}))}
/** Only reconstruct the writer's style boundaries; all glyph positioning remains native. */
export function expectedTextSegments(edit:TextEditInput){
 const styles=plannedCharStyles(edit,edit.newText),lines:{text:string;style:RunStyle|null;lineIndex:number}[][]=[]
 const key=(s:RunStyle|null)=>s?[s.color?.join(',')??'',s.font??'',s.size??'',s.bold===undefined?'':s.bold?1:0,s.italic===undefined?'':s.italic?1:0].join('|'):''
 let offset=0
 for(const [lineIndex,line]of edit.newText.split('\n').entries()){
  const segments:{text:string;style:RunStyle|null;lineIndex:number}[]=[];let at=offset
  for(const character of line){const style=styles?.[at]??null,last=segments.at(-1);if(last&&key(last.style)===key(style))last.text+=character;else segments.push({text:character,style,lineIndex});at+=character.length}
  lines.push(segments);offset+=line.length+1
 }
 return lines
}

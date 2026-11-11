import {applyCellEdits,type CellEdit} from '../../workbook_engine/packages/xlsx-engine/src/workbook-write'
import {cellRef,sanitizeText,type SheetSpec} from '../vendor/pdf2docx/src/rebuild-xlsx/workbook'

/** The original plain XLSX and its existing normalization remain authoritative.
 * Patch only unchanged mixed text; numeric and uniformly styled cells stay intact. */
export async function applyXlsxRichText(
 sourceBytes:Uint8Array,sheets:SheetSpec[],writer:typeof applyCellEdits=applyCellEdits,
):Promise<{bytes:Uint8Array;warnings:string[]}>{
 const edits:CellEdit[]=[],warnings:string[]=[]
 for(const sheet of sheets)for(const cell of sheet.cells){
  if(cell.value?.kind!=='text'||!cell.richText?.length)continue
  const rich=cell.richText
  if(new Set(rich.filter(run=>run.text!=='').map(({text,...style})=>JSON.stringify(style))).size<2)continue
  if(rich.map(run=>run.text).join('')!==cell.value.text||sanitizeText(cell.value.text)!==cell.value.text){
   warnings.push(`${sheet.name}!${cellRef(cell.row,cell.col)}: XLSX 富文本与既有正规化文字不一致，已保留受限纯文本（plain fallback）。`)
   continue
  }
  edits.push({sheetName:sheet.name,row:cell.row,column:cell.col,writeValue:true,cell:{value:cell.value.text},rich,
   // Absent run flags inherit the cell font in Office; clear only these four
   // switches through the existing copy-on-write style API before adding runs.
   style:{bold:false,italic:false,underline:false,strikethrough:false}})
 }
 if(!edits.length)return {bytes:sourceBytes,warnings}
 try{return {bytes:await writer(sourceBytes,edits),warnings}}
 catch(error){warnings.push('XLSX 富文本补写失败，已保留原始纯文本工作簿（plain bytes retained）：'+(error instanceof Error?error.message:String(error)));return {bytes:sourceBytes,warnings}}
}

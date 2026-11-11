/** 固定源 save-pdf.ts installDateActions 的精确内建脚本许可，不许可任意 JavaScript。 */
import {PDFDict,PDFName,PDFString,PDFHexString} from 'pdf-lib'
export const FORM_DATE_FORMATS=['yyyy-mm-dd','mm/dd/yyyy','dd/mm/yyyy','yyyy/mm/dd'] as const
export function inspectDesignDateActions(dict:PDFDict){try{
 const aa=dict.lookupMaybe(PDFName.of('AA'),PDFDict);if(!aa)return null
 if(aa.keys().map(String).sort().join(',')!=='/F,/K')return null
 for(const format of FORM_DATE_FORMATS){const objects:PDFDict[]=[aa];let valid=true
  for(const[key,fn]of [['F','AFDate_FormatEx'],['K','AFDate_KeystrokeEx']]){const action=aa.lookupMaybe(PDFName.of(key),PDFDict),script=action?.lookup(PDFName.of('JS'));if(!action||action.keys().map(String).sort().join(',')!=='/JS,/S'||String(action.get(PDFName.of('S')))!=='/JavaScript'||!(script instanceof PDFString||script instanceof PDFHexString)||script.decodeText()!==fn+'("'+format+'");'){valid=false;break}objects.push(action)}
  if(valid)return {format,objects}
 }return null
}catch{return null}}

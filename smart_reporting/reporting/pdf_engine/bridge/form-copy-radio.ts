/** Preserve radio option order, page offsets and a rigid translation within each source page. */
export interface RadioCopyRow {pageId:string;rect:[number,number,number,number];exportValue:string;checked?:boolean}
export function radioCopyMatches(source:RadioCopyRow[],target:RadioCopyRow[],pageId:string,rect:RadioCopyRow['rect'],pageIds:readonly string[]){
 if(source.length<2||source.length>64||source.length!==target.length||new Set(pageIds).size!==pageIds.length||source.some(row=>!row.pageId||!pageIds.includes(row.pageId)||!row.exportValue||row.rect.length!==4||!row.rect.every(Number.isFinite))||new Set(source.map(row=>row.exportValue)).size!==source.length||source.filter(row=>row.checked===true).length>1||target[0]?.pageId!==pageId||JSON.stringify(target[0]?.rect)!==JSON.stringify(rect))return false
 const start=pageIds.indexOf(pageId);if(start<0)return false
 const offset=start-pageIds.indexOf(source[0]!.pageId),translations=new Map<string,[number,number]>()
 return target.every((row,i)=>{
  const original=source[i]!,index=pageIds.indexOf(original.pageId)+offset
  if(index<0||index>=pageIds.length||row.pageId!==pageIds[index]||row.exportValue!==original.exportValue||(row.checked===true)!==(original.checked===true)||row.rect.length!==4||!row.rect.every(Number.isFinite))return false
  const delta:[number,number]=translations.get(original.pageId)??[row.rect[0]-original.rect[0],row.rect[1]-original.rect[1]];translations.set(original.pageId,delta)
  return row.rect.every((value,j)=>Math.abs(value-original.rect[j]!-(j%2===0?delta[0]:delta[1]))<=1e-7)
 })
}

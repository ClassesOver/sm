import type { DocxAnchor, DocxPmNode } from './docx-operations'
import type { NativeOperation } from './native-draft'
const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b)
const normalized=(node:DocxPmNode)=>{const copy=structuredClone(node);for(const row of copy.content??[]){row.attrs={...row.attrs};delete row.attrs.repeatHeader;delete row.attrs.repeatHeaderEdited}return copy}
export function projectTableHeaders(source:DocxPmNode,anchor:DocxAnchor,op:NativeOperation):DocxPmNode {
  const count=source.content?.length??0
  if(source.type!=='docTable'||op.kind!=='setTableRepeatHeaders'||op.blockId!==anchor.blockId||op.expectedObjectSha256!==anchor.expectedObjectSha256
    ||Object.keys(op).some(key=>!['kind','blockId','expectedObjectSha256','expectedRowCount','prefixRowCount','headers'].includes(key))
    ||!Number.isInteger(op.prefixRowCount)||Number(op.prefixRowCount)<1||Number(op.prefixRowCount)>count||op.expectedRowCount!==count||!Array.isArray(op.headers)||op.headers.length!==count||op.headers.some(value=>typeof value!=='boolean'))throw new Error('重复标题行草稿字段或来源身份无效')
  const headers=op.headers as boolean[],result=structuredClone(source)
  if(headers.some((value,index)=>index>=Number(op.prefixRowCount)&&value!==!!source.content?.[index]?.attrs?.repeatHeader))throw new Error('重复标题行前缀范围无效')
  result.content!.forEach((row,index)=>{if(index<Number(op.prefixRowCount))row.attrs={...row.attrs,repeatHeader:headers[index],repeatHeaderEdited:true}})
  return result
}
/** 只允许源命令改变重复标题标记；同表其他编辑须先保存。 */
export function tableHeaderOperation(source:DocxPmNode,edited:DocxPmNode,anchor:DocxAnchor):NativeOperation|null {
  if(!same(normalized(source),normalized(edited)))throw new Error('重复标题行不能与同表其他修改混合，请先保存')
  const headers=(edited.content??[]).map(row=>!!row.attrs?.repeatHeader)
  if(headers.every((value,index)=>value===!!source.content?.[index]?.attrs?.repeatHeader))return null
  const prefixRowCount=(edited.content??[]).reduce((end,row,index)=>row.attrs?.repeatHeaderEdited?index+1:end,0)
  return {kind:'setTableRepeatHeaders',blockId:anchor.blockId,expectedObjectSha256:anchor.expectedObjectSha256,expectedRowCount:headers.length,prefixRowCount,headers}
}

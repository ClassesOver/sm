import type {DocxPmNode} from './docx-operations'
/** Insert only in the source interval that surrounds the requested position.
 * Skipping a retained protected object would silently reorder the saved file. */
export function docxInsertionAnchor(before:readonly DocxPmNode[],after:readonly DocxPmNode[],index:number,eligible:(node:DocxPmNode)=>boolean):{target:DocxPmNode;position:'before'|'after'}|undefined{
 const id=(n:DocxPmNode)=>n.attrs?.docxIndex,retained=(n:DocxPmNode)=>id(n)!=null
 const next=after.slice(index+1).find(retained),previous=after.slice(0,index).reverse().find(retained)
 // Prefer a shared paragraph anchor across mixed image/table/rich insertions.
 for(const [target,position]of [[next,'before'],[previous,'after']]as const)if(target&&target.type!=='docTable'&&eligible(target))return{target,position}
 const start=previous?before.findIndex(n=>id(n)===id(previous)):-1,end=next?before.findIndex(n=>id(n)===id(next)):before.length
 if(start>=end||previous&&start<0||next&&end<0)return
 const deleted=before.slice(start+1,end).filter(n=>!after.some(a=>retained(a)&&id(a)===id(n)))
 const paragraph=deleted.find(n=>n.type!=='docTable'&&eligible(n))
 if(paragraph)return{target:paragraph,position:'before'}
 // Plain table-tail insertion uses the preceding table. Rich insertion shares
 // this choice whenever no paragraph anchor exists in the same interval.
 for(const [target,position]of [[previous,'after'],[next,'before']]as const)if(target&&eligible(target))return{target,position}
 const target=deleted.find(eligible)
 if(target)return{target,position:'before'}
}

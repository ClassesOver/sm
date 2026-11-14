import type {Transaction} from '@tiptap/pm/state'
import {ReplaceStep} from '@tiptap/pm/transform'
import type {DocxAnchor,DocxPmNode} from './docx-operations'

/** 仅供 Guard 校验 recorder 追加标记前的单段纯文本事务；投影不进入草稿。 */
export function docxTrackedInputProjection(transaction:Transaction,anchors:readonly DocxAnchor[]){
 if(transaction.steps.length!==1)return null
 const step=transaction.steps[0]
 if(!(step instanceof ReplaceStep)||step.toJSON().structure||step.slice.openStart||step.slice.openEnd)return null
 const from=transaction.before.resolve(step.from),to=transaction.before.resolve(step.to)
 if(from.depth!==1||!from.sameParent(to)||!['docParagraph','docHeading','docListItem'].includes(from.parent.type.name))return null
 const index=from.parent.attrs.docxIndex,matches=anchors.filter(anchor=>anchor.docxIndex===index)
 if(matches.length!==1||!matches[0].editable||matches[0].reviewTargets?.length||matches[0].revisionReadOnlyReason)return null
 const text=from.parent.textContent,boundary=(at:number)=>!(at>0&&at<text.length&&/[\uD800-\uDBFF]/.test(text[at-1])&&/[\uDC00-\uDFFF]/.test(text[at]))
 if(!boundary(from.parentOffset)||!boundary(to.parentOffset))return null
 const inherited=from.marks();let valid=true
 from.parent.forEach(child=>{if(!child.isText)valid=false})
 step.slice.content.forEach(child=>{
  if(!child.isText||!child.text?.isWellFormed()||/[\u0000-\u0008\u000B-\u001F\uFFFE\uFFFF]/.test(child.text)||child.marks.length!==inherited.length||child.marks.some(mark=>!inherited.some(source=>source.eq(mark))))valid=false
 })
 if(!valid||!step.apply(transaction.before).doc?.eq(transaction.doc))return null
 const baseline=transaction.before.toJSON() as DocxPmNode,current=transaction.doc.toJSON() as DocxPmNode
 for(const doc of [baseline,current]){
  const paragraph=doc.content?.find(node=>node.attrs?.docxIndex===index)
  if(!paragraph)return null
  for(const child of paragraph.content??[])if(child.marks){child.marks=child.marks.filter(mark=>mark.type!=='ins'&&mark.type!=='del');if(!child.marks.length)delete child.marks}
 }
 return{baseline,current}
}

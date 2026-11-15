import{it,expect}from'vitest'
import{docxInsertionAnchor}from'./docx-insertion-anchor'
import type{DocxPmNode}from'./docx-operations'
const p=(id:number|null,type='docParagraph'):DocxPmNode=>({type,attrs:{docxIndex:id}})
it('never skips a retained protected object when both adjacent anchors are unavailable',()=>{
 const a=p(0),image=p(1,'docProtected'),other=p(2,'docProtected'),tail=p(3),before=[a,image,other,tail]
 expect(docxInsertionAnchor(before,[a,image,p(null),other,tail],2,n=>n.type==='docParagraph')).toBeUndefined()
})
it('can anchor against a deleted original inside the same interval',()=>{
 const a=p(0),deleted=p(1),image=p(2,'docProtected'),before=[a,deleted,image]
 expect(docxInsertionAnchor(before,[a,p(null),image],1,n=>n.type==='docParagraph')).toEqual({target:a,position:'after'})
 expect(docxInsertionAnchor(before,[p(null),image],0,n=>n.type==='docParagraph')).toEqual({target:a,position:'before'})
})
it('uses the same paragraph anchor for mixed insertion types beside a table',()=>{
 const table=p(0,'docTable'),tail=p(1),fresh=p(null),before=[table,tail],after=[table,fresh,tail]
 const ordinary=docxInsertionAnchor(before,after,1,n=>n.type==='docParagraph')
 const rich=docxInsertionAnchor(before,after,1,n=>n.type==='docParagraph'||n.type==='docTable')
 expect(rich).toEqual(ordinary);expect(rich).toEqual({target:tail,position:'before'})
})
it('rejects deleted fallback anchors outside the insertion interval',()=>{
 const a=p(0),image=p(1,'docProtected'),other=p(2,'docProtected'),before=[a,image,other]
 expect(docxInsertionAnchor(before,[image,p(null),other],1,n=>n.type==='docParagraph')).toBeUndefined()
})

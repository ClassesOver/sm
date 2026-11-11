import assert from 'node:assert/strict'
import {test} from 'node:test'
import {mkdir,writeFile} from 'node:fs/promises'
import {PDFArray,PDFDict,PDFDocument,PDFName,PDFNumber} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt} from './operations'
async function fixture(){const doc=await PDFDocument.create();doc.addPage([300,400]);doc.addPage([300,400]);doc.getForm().createTextField('control').setText('unchanged');const b=await doc.save(),m=await inspectPdf(b),p=m.pages[0].pageId;return (await patchPdfWithReceipt(b,[{kind:'addTextAnnotation',pageId:p,localId:'a'.repeat(32),rect:[30,100,50,118],text:'root',createdMs:0},...['same','same'].map(contents=>({kind:'replyPendingNote',pageId:p,parentLocalId:'a'.repeat(32),contents,createdMs:0}))],m.sourceSha256)).bytes}
function edit(m:Awaited<ReturnType<typeof inspectPdf>>,index=1){const n=m.pages[0].notes[index];return {kind:'editNote',pageId:m.pages[0].pageId,annotationId:n.annotationId,expectedAnnotationSha256:n.expectedAnnotationSha256,contents:'edited reply ✓',modifiedAt:'2026-11-09T09:00:00Z'}}
function remove(m:Awaited<ReturnType<typeof inspectPdf>>,index=2){const {contents,modifiedAt,...op}=edit(m,index);return {...op,kind:'removeNote'}}
test('exact saved leaf edit/remove preserves parent and identical sibling and remains replyable after reopening',async()=>{
 const source=await fixture(),m=await inspectPdf(source);assert.equal(m.pages[0].notes[0].editable,false);assert.equal(m.pages[0].notes[1].editable,true);assert.equal(m.pages[0].notes[1].parentAnnotationId,m.pages[0].notes[0].annotationId)
 const edited=await patchPdfWithReceipt(source,[edit(m)],m.sourceSha256),again=await patchPdfWithReceipt(source,[edit(m)],m.sourceSha256);assert.equal(edited.sha256,again.sha256)
 const doc=await PDFDocument.load(edited.bytes),a=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray);assert.equal(a.lookup(1,PDFDict).lookup(PDFName.of('Contents')).decodeText(),'edited reply ✓');assert.equal(a.lookup(2,PDFDict).lookup(PDFName.of('Contents')).decodeText(),'same');assert.equal(String(a.lookup(1,PDFDict).get(PDFName.of('IRT'))),String(a.get(0)));assert.equal(a.lookup(1,PDFDict).lookup(PDFName.of('CreationDate')).decodeText(),'D:19700101000000Z');assert.equal(a.lookup(1,PDFDict).lookup(PDFName.of('M')).decodeText(),'D:20261109090000Z')
 const output=await patchPdfWithReceipt(source,[edit(m),remove(m)],m.sourceSha256),after=await inspectPdf(output.bytes);assert.equal(after.pages[0].notes.length,2);assert.equal(after.pages[0].notes[0].replyable,true);assert.equal(after.pages[0].notes[1].editable,true)
 const deleteLast=await patchPdfWithReceipt(output.bytes,[remove(after,1)],after.sourceSha256),last=await inspectPdf(deleteLast.bytes);assert.equal(last.pages[0].notes.length,1);assert.equal(last.pages[0].notes[0].replyable,true);assert.equal(last.pages[0].notes[0].editable,true)
 const root=after.pages[0].notes[0];const appended=await patchPdfWithReceipt(output.bytes,[{kind:'replyNote',pageId:after.pages[0].pageId,annotationId:root.annotationId,expectedAnnotationSha256:root.expectedAnnotationSha256,contents:'still works',createdMs:0}],after.sourceSha256);assert.equal((await inspectPdf(appended.bytes)).pages[0].notes.length,3)
 const dir=process.env.PDF_SAVED_REPLY_EVIDENCE_DIR;if(dir){await mkdir(dir,{recursive:true});await writeFile(`${dir}/source.pdf`,source);await writeFile(`${dir}/output.pdf`,output.bytes);await writeFile(`${dir}/deleted-last.pdf`,deleteLast.bytes)}
})
test('stale/foreign identities, duplicate leaf mutations and root writes refuse',async()=>{
 const source=await fixture(),m=await inspectPdf(source)
 for(const ops of [[{...edit(m),expectedAnnotationSha256:'0'.repeat(64)}],[{...edit(m),pageId:m.pages[1].pageId}],[edit(m),remove(m,1)],[edit(m,0)],[remove(m,0)],[edit(m),{kind:'cropPage',pageId:m.pages[0].pageId,rect:[0,0,200,300]}],[edit(m),{kind:'setPageSize',preset:'A4'}],[{...edit(m),parentAnnotationId:m.pages[0].notes[0].annotationId}]])await assert.rejects(()=>patchPdfWithReceipt(source,ops,m.sourceSha256))
})
test('linked/shared/protected/nested/cross-page/locked/rich/group replies remain readonly',async()=>{
 for(const mode of ['shared','protected','nested','cross-page','locked','rich','group','popup']){
 const doc=await PDFDocument.load(await fixture()),a=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray),child=a.lookup(1,PDFDict)
 if(mode==='shared')doc.catalog.set(PDFName.of('Other'),a.get(1));if(mode==='protected')doc.catalog.set(PDFName.of('Perms'),doc.context.obj({}));if(mode==='nested')a.lookup(2,PDFDict).set(PDFName.of('IRT'),a.get(1));if(mode==='cross-page')doc.getPage(1).node.set(PDFName.of('Annots'),doc.context.obj([a.get(1)]));if(mode==='locked')child.set(PDFName.of('F'),PDFNumber.of(128));if(mode==='rich')child.set(PDFName.of('RC'),PDFName.of('unsupported'));if(mode==='group')child.set(PDFName.of('RT'),PDFName.of('Group'));if(mode==='popup')child.set(PDFName.of('Popup'),a.get(2))
 const source=await doc.save(),m=await inspectPdf(source);assert.equal(m.pages[0].notes[1].editable,false,mode);await assert.rejects(()=>patchPdfWithReceipt(source,[edit(m)],m.sourceSha256))
 }
})
test('leaf mutations combine with new replies, rotation/reorder, form values and attachments',async()=>{
 const source=await fixture(),m=await inspectPdf(source),root=m.pages[0].notes[0],f=m.formFields[0]
 const result=await patchPdfWithReceipt(source,[edit(m),remove(m),{kind:'replyNote',pageId:m.pages[0].pageId,annotationId:root.annotationId,expectedAnnotationSha256:root.expectedAnnotationSha256,contents:'new sibling',createdMs:0},{kind:'rotatePage',pageId:m.pages[0].pageId,delta:90},{kind:'reorderPages',pageIds:m.pages.map(p=>p.pageId).reverse()},{kind:'setFormValue',fieldId:f.fieldId,expectedFieldSha256:f.expectedFieldSha256,name:f.name,fieldKind:'text',value:'changed'},{kind:'addAttachment',name:'control.bin',bytesBase64:'AP8='}],m.sourceSha256)
 const after=await inspectPdf(result.bytes);assert.equal(after.pages[1].notes.length,3);assert.equal(after.pages[1].rotation,90);assert.equal(after.pages[1].notes[0].replyable,true);assert.equal(after.formFields[0].value,'changed');assert.equal(after.attachments[0].size,2)
})
test('unlink-only leaves a stale inbound IRT; verified leaf release preserves future thread capability',async()=>{
 const source=await fixture(),m=await inspectPdf(source),doc=await PDFDocument.load(source),a=doc.getPage(0).node.lookup(PDFName.of('Annots'),PDFArray)
 doc.getPage(0).node.set(PDFName.of('Annots'),doc.context.obj(a.asArray().slice(0,2)))
 const unlinkOnly=await doc.save({useObjectStreams:false,updateFieldAppearances:false}),blocked=await inspectPdf(unlinkOnly);assert.equal(blocked.pages[0].notes[0].replyable,false)
 const fixed=await patchPdfWithReceipt(source,[remove(m)],m.sourceSha256),after=await inspectPdf(fixed.bytes);assert.equal(after.pages[0].notes[0].replyable,true);assert.equal(after.pages[0].notes[1].editable,true)
 const dir=process.env.PDF_SAVED_REPLY_EVIDENCE_DIR;if(dir)await writeFile(`${dir}/unlink-only.pdf`,unlinkOnly)
})

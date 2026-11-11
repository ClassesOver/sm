import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash } from 'node:crypto'
import { PDFDocument, PDFName, PDFString, degrees } from 'pdf-lib'
import { patchExternalPages } from './external-pages'
import { inspectNativeText } from './text-operations'
const sha = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex')
async function pdf(prefix: string, count: number) {
  const doc = await PDFDocument.create(); doc.setCreationDate(new Date('2020-01-01T00:00:00Z')); doc.setModificationDate(new Date('2020-01-02T00:00:00Z'))
  for (let index=0; index<count; index++) { const page=doc.addPage([300+index*10,400]); page.drawText(`${prefix} ${index+1}`,{x:30,y:300});page.setCropBox(10,20,250,350);page.setRotation(degrees(index%2*90)) }
  return doc.save({useObjectStreams:false})
}
function op(source:Uint8Array,external:Uint8Array,action='insert',options:Record<string,unknown>={}) { return {kind:'externalPages',action,sourceSha256:sha(source),externalSha256:sha(external),bytesBase64:Buffer.from(external).toString('base64'),...(action==='insert'?{afterPageIndex:0}:{pages:[0,2]}),...options} }
async function texts(bytes:Uint8Array) { return (await inspectNativeText(bytes,sha(bytes))).map(page=>page.map(item=>item.text).join(' ').trim()) }
test('external PDF insert and noncontiguous replacement preserve actual page content and geometry',async()=>{
  const source=await pdf('source',3),external=await pdf('external',2)
  for(const [operation,expected] of [[op(source,external),['source 1','external 1','external 2','source 2','source 3']],[op(source,external,'insert',{afterPageIndex:-1}),['external 1','external 2','source 1','source 2','source 3']],[op(source,external,'replace'),['external 1','external 2','source 2']]] as const){
    const result=await patchExternalPages(source,operation,sha(source));assert.deepEqual(await texts(result.bytes),expected)
    assert.equal(result.sourceSha256,sha(source));assert.equal(result.externalSha256,sha(external));assert.equal(result.sha256,sha(result.bytes));assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[])
    const output=await PDFDocument.load(result.bytes),a=await PDFDocument.load(source),b=await PDFDocument.load(external)
    for(const [index,label] of expected.entries()){ const original=(label.startsWith('source')?a:b).getPage(Number(label.split(' ')[1])-1),page=output.getPage(index);assert.deepEqual(page.getMediaBox(),original.getMediaBox());assert.deepEqual(page.getCropBox(),original.getCropBox());assert.equal(page.getRotation().angle,original.getRotation().angle) }
    assert.equal((await patchExternalPages(source,operation,sha(source))).previewDigest,result.previewDigest)
  }
  assert.deepEqual(await texts(source),['source 1','source 2','source 3'])
})
test('strict external page options reject wrong hashes, implicit clipping and arbitrary paths',async()=>{
  const source=await pdf('source',3),external=await pdf('external',1)
  for(const patch of [{sourceSha256:'f'.repeat(64)},{externalSha256:'f'.repeat(64)},{afterPageIndex:3},{afterPageIndex:-2},{afterPageIndex:0.5},{afterPageIndex:true},{path:'/tmp/foreign.pdf'},{bytesBase64:Buffer.from(external).toString('base64')+' '},{action:'replace',pages:[0,0],afterPageIndex:undefined},{action:'replace',pages:[3],afterPageIndex:undefined},{action:'replace',pages:[true],afterPageIndex:undefined}]) await assert.rejects(patchExternalPages(source,op(source,external,'insert',patch),sha(source)))
  await assert.rejects(patchExternalPages(source,op(source,external),'f'.repeat(64)))
})
test('either PDF with forms annotations protection or navigation is refused before writing',async()=>{
  const plain=await pdf('plain',1)
  for(const kind of ['AcroForm','Annots','Perms','Names','Outlines','OpenAction']){
    const doc=await PDFDocument.load(plain)
    if(kind==='Annots')doc.getPage(0).node.set(PDFName.of(kind),doc.context.obj([{Type:'Annot',Subtype:'Text',Rect:[0,0,10,10],Contents:PDFString.of('note')}]))
    else doc.catalog.set(PDFName.of(kind),doc.context.obj(kind==='AcroForm'?{Fields:[]}:{}))
    const unsafe=await doc.save({useObjectStreams:false})
    await assert.rejects(patchExternalPages(unsafe,op(unsafe,plain),sha(unsafe)),/暂不支持/)
    await assert.rejects(patchExternalPages(plain,op(plain,unsafe),sha(plain)),/暂不支持/)
  }
})
test('a review failure after the real writer returns retains readable actual output with an explicit warning',async()=>{
  const source=await pdf('source',2),external=await pdf('external',1),sourceHash=sha(source),externalHash=sha(external)
  const load=PDFDocument.load
  PDFDocument.load=async function(bytes,...options){
    if(bytes instanceof Uint8Array && ![sourceHash,externalHash].includes(sha(bytes)))throw Error('injected output review fault')
    return load.call(this,bytes,...options)
  } as typeof PDFDocument.load
  let result:Awaited<ReturnType<typeof patchExternalPages>>
  try{result=await patchExternalPages(source,op(source,external),sourceHash)}finally{PDFDocument.load=load}
  assert.equal(result.sha256,sha(result.bytes));assert.equal(result.size,result.bytes.length)
  assert.deepEqual(result.appliedOperationIndices,[]);assert.equal(result.skippedOperations[0]?.kind,'externalPages')
  assert.match(result.skippedOperations[0]!.reason,/复核/)
  assert.deepEqual(await texts(result.bytes),['source 1','external 1','source 2'])
})

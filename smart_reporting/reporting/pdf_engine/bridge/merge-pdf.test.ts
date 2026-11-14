import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument,PDFName,PDFString} from 'pdf-lib'
import {mergePdfBytes} from '../src/main/save-pdf'
import {mergePdf} from './merge-pdf'

test('固定源文件合并保留基文档表单目录与各页批注，不人为拒绝复杂来源',async()=>{
  const first=await PDFDocument.create(),other=await PDFDocument.create()
  first.addPage([300,400]);other.addPage([500,600])
  first.setTitle('base title')
  first.getForm().createTextField('base-field').addToPage(first.getPage(0),{x:10,y:10,width:50,height:20})
  first.catalog.set(PDFName.of('Outlines'),first.context.obj({Type:PDFName.of('Outlines'),Count:0}))
  other.getForm().createTextField('external-field').addToPage(other.getPage(0),{x:10,y:10,width:50,height:20})
  const note=other.context.register(other.context.obj({Type:'Annot',Subtype:'Text',Rect:[10,10,20,20],Contents:PDFString.of('external note')}))
  other.getPage(0).node.addAnnot(note)
  const base=await first.save(),external=await other.save(),result=await mergePdfBytes(base,[external,external])
  const output=await PDFDocument.load(result.merged)
  assert.equal(result.appended,2);assert.equal(output.getPageCount(),3);assert.equal(output.getTitle(),'base title')
  assert(output.catalog.has(PDFName.of('Outlines')))
  assert.deepEqual(output.getForm().getFields().map(field=>field.getName()),['base-field'])
  assert.equal(output.getPage(1).node.Annots()?.size(),2)
  assert.equal(output.getPage(2).node.Annots()?.size(),2)
  assert.deepEqual(output.getPages().map(page=>[page.getWidth(),page.getHeight()]),[[300,400],[500,600],[500,600]])
})

test('输出复核失败仅告警，固定源生成的实际合并字节仍返回',async()=>{
  const first=await PDFDocument.create(),other=await PDFDocument.create();first.addPage([300,400]);other.addPage([500,600])
  const a=await first.save(),b=await other.save(),load=PDFDocument.load
  const sources=[a,b].map(bytes=>Buffer.from(bytes).toString('base64'))
  PDFDocument.load=async function(bytes,...options){
    if(bytes instanceof Uint8Array&&!sources.includes(Buffer.from(bytes).toString('base64')))throw Error('injected output review failure')
    return load.call(this,bytes,...options)
  } as typeof PDFDocument.load
  let result:Awaited<ReturnType<typeof mergePdf>>
  try{result=await mergePdf(a,[b])}finally{PDFDocument.load=load}
  assert(result.bytes.length>0);assert.equal((await PDFDocument.load(result.bytes)).getPageCount(),2)
  assert(result.reviewIssues.some(issue=>issue.includes('后置页面复核未通过')))
})

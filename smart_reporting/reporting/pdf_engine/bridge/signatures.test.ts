import test from 'node:test'
import assert from 'node:assert/strict'
import {PDFDocument} from 'pdf-lib'
import {inspectPdf} from './operations'
import {inspectDigitalSignatures} from './signatures'
import {signedPdfFixture} from './fixtures/signature-fixture'

test('原生检查明确返回只读签名清单及校验范围，空字段不冒充数字签名',async()=>{
 const pdf=await PDFDocument.create();pdf.addPage()
 const bytes=await pdf.save(),before=Buffer.from(bytes)
 const result=await inspectPdf(bytes) as Awaited<ReturnType<typeof inspectPdf>>&{digitalSignatures?:unknown[];signatureVerification?:{scope:string}}
 assert.deepEqual(result.digitalSignatures,[])
 assert.equal(result.signatureVerification?.scope,'basic-integrity-only')
 assert.deepEqual(Buffer.from(bytes),before)
})

test('真实分离CMS验证摘要、证书和覆盖范围，但不冒称PKI信任',async()=>{
 const bytes=await signedPdfFixture(),before=Buffer.from(bytes)
 const result=await inspectDigitalSignatures(bytes),sig=result.digitalSignatures[0]!
 assert.equal(sig.signer?.commonName,'Signature Fixture');assert.equal(sig.status,'untrusted')
 assert.deepEqual(sig.problems,['self-signed']);assert.equal(sig.trusted,false)
 assert.equal(sig.coversWholeDocument,true);assert.equal(sig.digestAlgorithm,'SHA256');assert.equal(sig.signingTimeSigned,true)
 assert.equal(sig.pageIndex,0);assert.equal(sig.fieldName,'ReviewSignature');assert.deepEqual(bytes,before)
 const changed=Buffer.from(bytes),at=changed.indexOf('Signature fixture');assert.ok(at<0) // 正文由 PDF 字体编码。
 changed[15]=changed[15]!^1
 const altered=(await inspectDigitalSignatures(changed)).digitalSignatures[0]!
 assert.equal(altered.status,'invalid');assert.ok(altered.problems.includes('digest-mismatch'))
 assert.equal(altered.signingTimeSigned,false)
 const appended=(await inspectDigitalSignatures(Buffer.concat([bytes,Buffer.from('\n% later revision\n')]))).digitalSignatures[0]!
 assert.equal(appended.status,'warning');assert.ok(appended.problems.includes('document-changed-after-signing'))
 assert.equal(appended.coversWholeDocument,false)
})

test('空签名字段不列入；缺失ByteRange的已赋值签名明确无效',async()=>{
 assert.deepEqual((await inspectDigitalSignatures(await signedPdfFixture({empty:true}))).digitalSignatures,[])
 const result=await inspectDigitalSignatures(await signedPdfFixture({missingRange:true}))
 assert.equal(result.digitalSignatures.length,1)
 assert.equal(result.digitalSignatures[0]!.status,'invalid');assert.deepEqual(result.digitalSignatures[0]!.problems,['malformed'])
})

test('未知SubFilter和ByteRange额外排除字节不能显示核验通过',async()=>{
 const unknown=(await inspectDigitalSignatures(await signedPdfFixture({unsupported:true}))).digitalSignatures[0]!
 assert.equal(unknown.status,'warning');assert.deepEqual(unknown.problems,['unsupported-algorithm'])
 const gap=(await inspectDigitalSignatures(await signedPdfFixture({gapExtra:true}))).digitalSignatures[0]!
 assert.equal(gap.status,'invalid');assert.deepEqual(gap.problems,['malformed'])
})


test('真实literal Contents CMS明确为未支持编码，不误报签名无效或已核验',async()=>{
 const bytes=await signedPdfFixture({literalContents:true}),before=Buffer.from(bytes)
 assert.ok(bytes.includes(Buffer.from('/Contents (\\060')))
 const sig=(await inspectDigitalSignatures(bytes)).digitalSignatures[0]!
 assert.equal(sig.status,'warning');assert.deepEqual(sig.problems,['unsupported-algorithm'])
 assert.equal(sig.trusted,false);assert.equal(sig.signingTimeSigned,false);assert.equal(sig.coversWholeDocument,false)
 assert.deepEqual(bytes,before)
})

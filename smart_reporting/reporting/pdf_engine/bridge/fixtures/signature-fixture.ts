import {execFileSync} from 'node:child_process'
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {PDFDocument,PDFHexString,PDFName,PDFString} from 'pdf-lib'

/** 测试专用：OpenSSL 独立生成真实分离 CMS，不依赖被测读取器或应用签名功能。 */
export async function signedPdfFixture(options:{malformedRange?:boolean;unsupported?:boolean;empty?:boolean;gapExtra?:boolean;missingRange?:boolean;literalContents?:boolean}={}){
 const pdf=await PDFDocument.create(),page=pdf.addPage([400,300])
 page.drawText('Signature fixture',{x:40,y:230})
 const value=pdf.context.obj({Type:'Sig',Filter:'Adobe.PPKLite',SubFilter:options.unsupported?'unknown.detached':'adbe.pkcs7.detached',ByteRange:[0,1111111111,1111111111,1111111111],Contents:options.literalContents?PDFString.of('\\000'.repeat(8192)):PDFHexString.of('0'.repeat(16384)),Name:PDFString.of('Unverified PDF Name'),Reason:PDFString.of('Review fixture')})
 if(options.missingRange)value.delete(PDFName.of('ByteRange'))
 const sig=pdf.context.obj({Type:'Annot',Subtype:'Widget',FT:'Sig',T:PDFString.of('ReviewSignature'),Rect:[30,30,160,70],F:4,P:page.ref,...(!options.empty?{V:pdf.context.register(value)}:{})}),ref=pdf.context.register(sig)
 page.node.set(PDFName.of('Annots'),pdf.context.obj([ref]));pdf.catalog.set(PDFName.of('AcroForm'),pdf.context.obj({Fields:[ref]}))
 const bytes=Buffer.from(await pdf.save({useObjectStreams:false}));if(options.empty||options.missingRange)return bytes
 const text=bytes.toString('latin1'),marker=options.literalContents?'/Contents (':'/Contents <',start=text.indexOf(marker)+marker.length-1,end=start+(options.literalContents?32770:16386)
 const extra=options.gapExtra?1:0,range=[0,start,end+extra,bytes.length-end-extra]
 if(options.malformedRange)range[1]=start-1
 const old='/ByteRange [ 0 1111111111 1111111111 1111111111 ]',next=('/ByteRange [ '+range.join(' ')+' ]').padEnd(old.length,' ')
 const rangeAt=text.indexOf(old);if(rangeAt<0||start<marker.length)throw Error('fixture marker missing')
 bytes.write(next,rangeAt,'latin1')
 const dir=mkdtempSync(join(tmpdir(),'pdf-signatures-'))
 try{
  execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-keyout',join(dir,'key.pem'),'-out',join(dir,'cert.pem'),'-nodes','-subj','/CN=Signature Fixture','-days','1'],{stdio:'ignore'})
  writeFileSync(join(dir,'signed.bin'),Buffer.concat([bytes.subarray(0,range[1]),bytes.subarray(range[2],range[2]!+range[3]!)]))
  execFileSync('openssl',['cms','-sign','-binary','-in',join(dir,'signed.bin'),'-signer',join(dir,'cert.pem'),'-inkey',join(dir,'key.pem'),'-outform','DER','-out',join(dir,'signature.der'),'-md','sha256'],{stdio:'ignore'})
  const cms=readFileSync(join(dir,'signature.der'));if(cms.length>8192)throw Error('fixture CMS too large')
  if(options.literalContents)execFileSync('openssl',['cms','-verify','-binary','-inform','DER','-in',join(dir,'signature.der'),'-content',join(dir,'signed.bin'),'-noverify','-out',join(dir,'verified.bin')],{stdio:'ignore'})
  const encoded=options.literalContents?Array.from(cms,byte=>'\\'+byte.toString(8).padStart(3,'0')).join('').padEnd(32768,'\\000'):cms.toString('hex').toUpperCase().padEnd(16384,'0')
  bytes.write(encoded,start+1,'latin1')
  return bytes
 }finally{rmSync(dir,{recursive:true,force:true})}
}

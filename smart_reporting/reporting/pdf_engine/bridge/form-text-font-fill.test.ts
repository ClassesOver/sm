import assert from 'node:assert/strict'
import {test} from 'node:test'
import {readFile,mkdir,writeFile} from 'node:fs/promises'
import {spawnSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {PDFDocument,PDFDict,PDFName,PDFRawStream} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {bodySnapshot} from './form-design-create'
const directory='/tmp/pdf-next-form-fonts/fill-regression'
await mkdir(directory,{recursive:true})
async function fixture(){let bytes:Uint8Array=await readFile(new URL('./fixtures/form-design-create-reportlab.pdf',import.meta.url));for(const[name,value,y]of [['party.name','Alice',230],['party.code','C001',180]]as const){const model=await inspectPdf(bytes);bytes=(await patchPdfWithReceipt(bytes,[{kind:'createFormField',sourceSha256:sha256(bytes),pageId:model.pages[0].pageId,fieldKind:'text',fieldName:name,rect:[30,y,270,y+30],required:true,value}],sha256(bytes))).bytes}return bytes}
function appearance(document:PDFDocument,name:string){const field=document.getForm().getTextField(name),widget=field.acroField.getWidgets()[0],normal=widget.dict.lookup(PDFName.of('AP'),PDFDict).lookup(PDFName.of('N'),PDFRawStream);return {fieldRef:String(field.ref),widgetRef:String(document.context.getObjectRef(widget.dict)),widget:widget.dict.toString(),normalDict:normal.dict.toString(),normalBytes:Buffer.from(normal.contents).toString('hex')}}
for(const [fontName,fontSize]of [['Courier-BoldOblique',18],['Times-BoldItalic',16]]as const)test('setFormValue preserves proved standard '+fontName+' face and size in actual AP',async()=>{
 let bytes=await fixture();const initial=await inspectPdf(bytes),widget=initial.formDesignWidgets.find(w=>w.fieldName==='party.name')!,{fieldName,widgetId,widgetIdentity,expectedWidgetSha256}=widget
 bytes=(await patchPdfWithReceipt(bytes,[{kind:'editFormTextProperties',sourceSha256:sha256(bytes),fieldName,widgetId,widgetIdentity,expectedWidgetSha256,fontName,fontSize,textAlignment:'right'}],sha256(bytes))).bytes
 const model=await inspectPdf(bytes),field=model.formFields.find(f=>f.name==='party.name')!,before=await PDFDocument.load(bytes),sourceAppearance=appearance(before,'party.name'),unrelatedAppearance=appearance(before,'party.code'),result=await patchPdfWithReceipt(bytes,[{kind:'setFormValue',fieldId:field.fieldId,expectedFieldSha256:field.expectedFieldSha256,name:field.name,fieldKind:field.kind,value:'Alice Updated'}],sha256(bytes))
 assert.deepEqual(result.appliedOperationIndices,[0]);assert.deepEqual(result.skippedOperations,[]);assert.equal(result.sha256,sha256(result.bytes));const out=await PDFDocument.load(result.bytes),after=await inspectPdf(result.bytes),props=after.formDesignWidgets.find(w=>w.fieldName==='party.name')!.textProperties!
 assert.equal(out.getForm().getTextField('party.name').getText(),'Alice Updated');assert.equal(props.fontName,fontName);assert.equal(props.fontSize,fontSize);assert.equal(props.textAlignment,'right');assert.deepEqual(bodySnapshot(out),bodySnapshot(before));assert.equal(appearance(out,'party.name').fieldRef,sourceAppearance.fieldRef);assert.equal(appearance(out,'party.name').widgetRef,sourceAppearance.widgetRef);assert.deepEqual(appearance(out,'party.code'),unrelatedAppearance)
 const path=directory+'/'+fontName+'.pdf';await writeFile(path,result.bytes)
 const script=String.raw`import sys,re,json
from pypdf import PdfReader
r=PdfReader(sys.argv[1])
def walk(refs,prefix=''):
 for ref in refs:
  f=ref.get_object();name=prefix+str(f['/T'])
  if '/FT' not in f:yield from walk(f['/Kids'],name+'.')
  else:yield name,f
fields=dict(walk(r.trailer['/Root']['/AcroForm']['/Fields']))
f=fields['party.name'];ap=f['/Kids'][0].get_object()['/AP']['/N'];font=next(iter(ap['/Resources']['/Font'].values())).get_object()
assert f['/V']=='Alice Updated' and font['/BaseFont']=='/'+sys.argv[2]
assert re.search('/'+re.escape(sys.argv[2])+r'\s+'+sys.argv[3]+r'(?:\.0+)?\s+Tf',str(f['/DA']))
assert b'416C6963652055706461746564' in ap.get_data()
assert fields['party.code']['/V']=='C001'
print(json.dumps({'ok':True,'font':str(font['/BaseFont']),'value':str(f['/V'])}))`
 const probe=spawnSync(fileURLToPath(new URL('../../../../.venv/bin/python',import.meta.url)),['-c',script,path,fontName,String(fontSize)],{encoding:'utf8'});assert.equal(probe.status,0,probe.stderr);assert.equal(JSON.parse(probe.stdout).ok,true)
})

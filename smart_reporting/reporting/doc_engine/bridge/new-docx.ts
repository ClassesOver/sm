/** Host-created paths only. Fixed upstream blank template, not an invented OOXML shell. */
import {readFile,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {buildBlankDocx} from '../packages/docx-engine/src/blank.ts'
try {
 if(process.argv.length!==3)throw new Error('new_docx_arguments_invalid')
 const request=JSON.parse(await readFile(process.argv[2]!,'utf8'))
 if(Object.keys(request).join()!=='output'||typeof request.output!=='string'||!request.output)throw new Error('new_docx_arguments_invalid')
 // A reproducible built-in template makes retries address the same immutable bytes.
 const date=new Date('2000-01-01T00:00:00Z')
 const template=await buildBlankDocx({createdAt:date,eastAsiaFont:'宋体',paperSize:'A4'})
 const zip=await JSZip.loadAsync(template)
 // The browser host's native protection reader expects the standard settings part.
 zip.file('word/settings.xml','<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
 const documentXml=await zip.file('word/document.xml')!.async('string')
 // Native text replacement requires an explicit paragraph extent for its trusted anchor.
 zip.file('word/document.xml',documentXml.replace('<w:p/>','<w:p></w:p>'))
 const types=await zip.file('[Content_Types].xml')!.async('string')
 zip.file('[Content_Types].xml',types.replace('</Types>','<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/></Types>'))
 const rels=await zip.file('word/_rels/document.xml.rels')!.async('string')
 zip.file('word/_rels/document.xml.rels',rels.replace('</Relationships>','<Relationship Id="nativeSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/></Relationships>'))
 for(const file of Object.values(zip.files))file.date=date
 const bytes=await zip.generateAsync({type:'uint8array',compression:'DEFLATE'})
 await writeFile(request.output,bytes,{flag:'wx'})
 process.stdout.write(JSON.stringify({ok:true,size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')}))
}catch(error){process.stderr.write(error instanceof Error?error.message:String(error));process.exitCode=1}

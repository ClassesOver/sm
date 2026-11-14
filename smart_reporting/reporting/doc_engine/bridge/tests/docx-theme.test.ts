import assert from 'node:assert/strict'
import { test } from 'node:test'
import { inspectDocxTheme, validateDocxThemeOperations, assertDocxThemeWritten } from '../docx-theme.ts'
import { applyThemeFonts, applyThemeColors } from '../../packages/docx-engine/src/theme.ts'
const xml = '<a:theme><a:themeElements><a:clrScheme name="Old">'+['dk2','lt2','accent1','accent2','accent3','accent4','accent5','accent6'].map(k=>`<a:${k}><a:srgbClr val="123456"/></a:${k}>`).join('')+'</a:clrScheme><a:fontScheme name="old"><a:majorFont><a:latin typeface="Old"/><a:ea typeface="宋体"/></a:majorFont><a:minorFont><a:latin typeface="Old"/><a:ea typeface="宋体"/></a:minorFont></a:fontScheme></a:themeElements></a:theme>'
test('theme source anchors presets and independently verifies engine write', () => {
 const model=inspectDocxTheme(xml,false)
 assert.equal(model.editable,true)
 const op={kind:'setDocumentTheme',expectedThemeSha256:model.expectedThemeSha256,fontPreset:'ribbonThemeFontYahei',colorPreset:'ribbonColorBlue'}
 const options=validateDocxThemeOperations([op],model)!
 assert.equal(options.themeFonts?.major,'微软雅黑')
 const out=applyThemeColors(applyThemeFonts(xml,options.themeFonts!),options.themeColors!)
 assertDocxThemeWritten(out,options)
 assert.throws(()=>assertDocxThemeWritten(xml,options),/not_applied/)
 assert.throws(()=>validateDocxThemeOperations([{...op,xml:'<bad/>'}],model),/invalid/)
 assert.throws(()=>validateDocxThemeOperations([{...op,expectedThemeSha256:'0'.repeat(64)}],model),/anchor/)
 assert.throws(()=>validateDocxThemeOperations([op],inspectDocxTheme(xml,true)),/unsupported/)
 assert.equal(inspectDocxTheme(null,false).editable,false)
})
import JSZip from 'jszip'
import { buildDocx } from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import { parseDocx } from '../../packages/docx-engine/src/parse.ts'
import { saveDocx } from '../../packages/docx-engine/src/patch.ts'
test('native engine theme save roundtrip preserves original direct body formatting',async()=>{
 const bytes=await buildDocx({bodyXml:'<w:p><w:r><w:rPr><w:rFonts w:ascii="Arial"/><w:color w:val="FF0000"/></w:rPr><w:t>Keep direct formatting</w:t></w:r></w:p>',extraParts:[{path:'word/theme/theme1.xml',xml,contentType:'application/vnd.openxmlformats-officedocument.theme+xml'}],extraRels:'<Relationship Id="rTheme" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'})
 const parsed=await parseDocx(bytes), model=inspectDocxTheme(xml,false)
 const options=validateDocxThemeOperations([{kind:'setDocumentTheme',expectedThemeSha256:model.expectedThemeSha256,themePreset:'ribbonThemeFacet',fontPreset:'ribbonThemeFontKaiti'}],model)!
 const out=await saveDocx(parsed,parsed.blocks.filter(b=>!b.hidden).map(b=>({kind:'original' as const,docxIndex:b.docxIndex!})),options)
 const original=await JSZip.loadAsync(bytes),zip=await JSZip.loadAsync(out)
 assertDocxThemeWritten(await zip.file('word/theme/theme1.xml')!.async('string'),options)
 assert.equal(await zip.file('word/document.xml')!.async('string'),await original.file('word/document.xml')!.async('string'))
})

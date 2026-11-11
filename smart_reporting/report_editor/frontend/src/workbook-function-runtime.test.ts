import {expect,it,vi} from 'vitest'
import {Univer,LocaleType,IUniverInstanceService} from '@univerjs/core'
import {FUniver} from '@univerjs/core/lib/facade'
import {UniverSheetsPlugin} from '@univerjs/sheets'
import '@univerjs/sheets/facade'
const path='./workbook-function-runtime'
async function setup(){
 const univer=new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}});univer.registerPlugin(UniverSheetsPlugin)
 const api=FUniver.newAPI(univer),book=api.createWorkbook({id:'function-book',name:'Functions',sheetOrder:['one','two'],sheets:{one:{id:'one',name:'One',rowCount:30,columnCount:10,cellData:{0:{0:{v:3},1:{v:4}}}},two:{id:'two',name:'Other Sheet',rowCount:20,columnCount:10}}})
 univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId());book.getActiveSheet()!.getRange('D2').activate()
 let editable=true,protectedSheet=false
 const onWrite=vi.fn(),{createWorkbookFunctionHost}=await import(/* @vite-ignore */path)
 const host=createWorkbookFunctionHost({univer,univerAPI:api},{editable:()=>editable,protectedSheet:()=>protectedSheet,onWrite})
 return{univer,api,book,host,onWrite,readonly(){editable=false},protect(){protectedSheet=true}}
}
it('writes the captured cell after selection and sheet change, never the later active cell',async()=>{
 const c=await setup();try{const target=await c.host.readTarget();expect(target.label).toBe('D2');c.book.setActiveSheet(c.book.getSheetBySheetId('two')!);c.book.getActiveSheet()!.getRange('B4').activate()
 expect(c.host.write(target,'=SUM(A1:B1)')).toBeNull();expect(c.book.getSheetBySheetId('one')!.getRange('D2').getFormula()).toBe('=SUM(A1:B1)');expect(c.book.getSheetBySheetId('two')!.getRange('B4').getFormula()).toBe('');expect(c.onWrite).toHaveBeenCalledTimes(1)
 }finally{c.host.dispose();c.univer.dispose()}
})
it.each(['readonly','protect','replace','dispose'])('rejects a captured target after %s without writing or marking dirty',async fault=>{
 const c=await setup();try{const target=await c.host.readTarget();if(fault==='readonly')c.readonly();if(fault==='protect')c.protect();if(fault==='dispose')c.host.dispose();if(fault==='replace'){c.api.disposeUnit(c.book.getId());c.api.createWorkbook({id:'function-book',name:'replacement',sheetOrder:['one'],sheets:{one:{id:'one',name:'One',rowCount:20,columnCount:10}}})}
 expect(c.host.write(target,'=SUM(1,2)')).toBeTypeOf('string');expect(c.onWrite).not.toHaveBeenCalled()
 }finally{c.host.dispose();c.univer.dispose()}
})
it('does not capture a readonly or protected target',async()=>{const c=await setup();try{c.readonly();await expect(c.host.readTarget()).rejects.toThrow()}finally{c.host.dispose();c.univer.dispose()}})
it.each(['replace','dispose'])('stops a synchronous write callback before activating or recording a %s target',async fault=>{
 const c=await setup();try{
  const target=await c.host.readTarget()
  const listener=c.api.onCommandExecuted((command:any)=>{if(command.id!=='sheet.mutation.set-range-values')return;if(fault==='dispose')c.host.dispose();else{c.api.disposeUnit(c.book.getId());c.api.createWorkbook({id:'function-book',name:'replacement',sheetOrder:['one'],sheets:{one:{id:'one',name:'One',rowCount:20,columnCount:10}}})}})
  expect(c.host.write(target,'=SUM(1,2)')).toBeTypeOf('string');expect(c.onWrite).not.toHaveBeenCalled()
  listener.dispose()
 }finally{c.host.dispose();c.univer.dispose()}
})

it('lists authorized package external links without probing their source paths', async () => {
 const files:Record<string,string> = {
  'xl/workbook.xml':'<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><externalReferences><externalReference r:id="rId4"/></externalReferences></workbook>',
  'xl/_rels/workbook.xml.rels':'<Relationships><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink" Target="externalLinks/externalLink1.xml"/></Relationships>',
  'xl/externalLinks/externalLink1.xml':'<externalLink><externalBook><sheetNames><sheetName val="Data"/><sheetName val="Quarter 1"/></sheetNames></externalBook></externalLink>',
  'xl/externalLinks/_rels/externalLink1.xml.rels':'<Relationships><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath" Target="file:///reports/source.xlsx" TargetMode="External"/></Relationships>',
 }
 const {readExternalPickTargetsFromSource}=await import(/* @vite-ignore */path)
 await expect(readExternalPickTargetsFromSource({has:async (part: string)=>part in files,readText:async (part: string)=>files[part]!})).resolves.toEqual([{index:1,name:'source.xlsx',source:'file:///reports/source.xlsx',open:false,wcId:null,sheetNames:['Data','Quarter 1']}])
})

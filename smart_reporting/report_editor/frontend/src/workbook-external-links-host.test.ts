import JSZip from '../../../reporting/workbook_engine/node_modules/jszip'
import {expect,it} from 'vitest'
import {Univer,LocaleType,IUniverInstanceService} from '@univerjs/core'
import {FUniver} from '@univerjs/core/lib/facade'
import {UniverSheetsPlugin} from '@univerjs/sheets'
import {UniverFormulaEnginePlugin} from '@univerjs/engine-formula'
import {UniverSheetsFormulaPlugin} from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import {evaluateExternalFormula} from './workbook-external-links-host'
import {createBlankWorkbook} from '@sheets-web/xlsx-engine'
it('evaluates scalar range boolean and text formulas through the installed Univer engine',async()=>{
 const univer=new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}});univer.registerPlugin(UniverSheetsPlugin);univer.registerPlugin(UniverFormulaEnginePlugin);univer.registerPlugin(UniverSheetsFormulaPlugin)
 const api=FUniver.newAPI(univer),book=api.createWorkbook({id:'external',name:'external',sheetOrder:['one'],sheets:{one:{id:'one',name:'Sheet1',rowCount:30,columnCount:10}}});univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId())
 try{
  for(const [expression,expected] of [['=12*2',24],['=SUM({2,3;4,5})',14],['=FALSE',false],['="new text"','new text']] as const)expect(await evaluateExternalFormula({univer,univerAPI:api},{sheetName:'Sheet1',address:'A1',formula:'[1]Data!A1',expression})).toEqual(expected)
 }finally{univer.dispose()}
},15000)
it('retains external formula caches in the projected workbook while preserving original formula text',async()=>{
 const {withExternalFormulaCaches}=await import('./workbook-external-links-host')
 const zip=await JSZip.loadAsync(await createBlankWorkbook());zip.file('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f>[1]Data!A1*2</f><v>24</v></c></row></sheetData></worksheet>')
 const bytes=await zip.generateAsync({type:'uint8array'}),data={sheets:{'sheet-0':{name:'Sheet1',cellData:{0:{0:{f:'=[1]Data!A1*2'}}}}}}
 await withExternalFormulaCaches(bytes,data)
 expect(data.sheets['sheet-0'].cellData[0][0]).toEqual({f:'=[1]Data!A1*2',v:24,t:2})
})
it('keeps actual external cached values across automatic recalculation without changing stored formula',async()=>{
 const {withExternalFormulaCaches,installExternalFormulaCaches}=await import('./workbook-external-links-host')
 const zip=await JSZip.loadAsync(await createBlankWorkbook());zip.file('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f>[1]Data!A1*2</f><v>24</v></c></row></sheetData></worksheet>')
 const univer=new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}});univer.registerPlugin(UniverSheetsPlugin);univer.registerPlugin(UniverFormulaEnginePlugin);univer.registerPlugin(UniverSheetsFormulaPlugin)
 const api=FUniver.newAPI(univer),data:any={id:'external-cache',name:'cached',sheetOrder:['one'],sheets:{one:{id:'one',name:'Sheet1',rowCount:30,columnCount:10,cellData:{0:{0:{f:'=[1]Data!A1*2'}}}}}}
 await withExternalFormulaCaches(await zip.generateAsync({type:'uint8array'}),data)
 const handle=installExternalFormulaCaches({univer,univerAPI:api});try{const book=api.createWorkbook(data);univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId());await new Promise(resolve=>setTimeout(resolve,80));expect(book.getActiveSheet()!.getRange('A1').getValue()).toBe(24);expect(book.getActiveSheet()!.getRange('A1').getFormula()).toBe('=[1]Data!A1*2')}finally{handle.dispose();univer.dispose()}
})

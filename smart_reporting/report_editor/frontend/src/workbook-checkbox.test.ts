import { expect, it } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverSheetsDataValidationPlugin } from '@univerjs/sheets-data-validation'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import { applyWorkbookCheckbox } from './workbook-checkbox'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { workbookDataValidationOperations, withWorkbookDataValidations, type ValidationWorkbook } from './workbook-data-validation'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { NativeDraft, type NativeOperation } from './native-draft'

it('uses the official checkbox builder, undo/redo and identity-bound draft/save/reopen', async () => {
 const univer = new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}})
 univer.registerPlugin(UniverSheetsPlugin);univer.registerPlugin(UniverFormulaEnginePlugin)
 univer.registerPlugin(UniverSheetsFormulaPlugin);univer.registerPlugin(UniverSheetsDataValidationPlugin)
 const api=FUniver.newAPI(univer)
 try {
  expect(applyWorkbookCheckbox({univerAPI:api})).toBe(false)
  const book=api.createWorkbook({id:'checkbox',name:'Checkbox',sheetOrder:['data'],sheets:{data:{id:'data',name:'Sheet1',rowCount:20,columnCount:10,cellData:{0:{1:{v:'Keep'}}}}}})
  univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId())
  const sheet=book.getActiveSheet()!
  book.setActiveRange(sheet.getRange('A1:A2'))
  expect(applyWorkbookCheckbox({univerAPI:api})).toBe(true)
  expect(sheet.getDataValidations()[0]!.rule.type).toBe('checkbox')
  await api.undo();expect(sheet.getDataValidations()).toHaveLength(0)
  await api.redo();expect(sheet.getDataValidations()[0]!.rule.type).toBe('checkbox')
  const bytes=await createBlankWorkbook(),model=await readWorkbook(bytes)
  const ops=workbookDataValidationOperations(model,book as unknown as ValidationWorkbook) as NativeOperation[]
  const identity={documentId:'checkbox',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}}
  const memory=new Map<string,string>(),storage={getItem:(key:string)=>memory.get(key)??null,setItem:(key:string,value:string)=>{memory.set(key,value)},removeItem:(key:string)=>{memory.delete(key)}}
  const draft=new NativeDraft(identity,storage);draft.setOperations(ops)
  const restored=new NativeDraft(identity,storage)
  expect(restored.operations).toEqual(ops)
  expect(new NativeDraft({...identity,revision:2},storage).operations).toEqual([])
  const saved=await applyWorkbookOperations(bytes,restored.beginSave().operations)
  const reopened=await readWorkbook(saved)
  expect(reopened.sheets[0]!.dataValidations!.rules[0]!.rule.type).toBe('checkbox')
  const resource=withWorkbookDataValidations({sheets:{data:{id:'data',name:'Sheet1'}}},reopened)
  expect(JSON.parse(resource.resources[0]!.data).data[0].type).toBe('checkbox')
 } finally {univer.dispose()}
})

import { expect, it } from 'vitest'
import { Univer, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
const path = './workbook-statistics'
async function product(): Promise<any> { return import(/* @vite-ignore */ path) }

it('counts source snapshot values and formulas independently across every sheet without mutation', async () => {
  const univer = new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}}); univer.registerPlugin(UniverSheetsPlugin)
  const api = FUniver.newAPI(univer)
  try {
    const book = api.createWorkbook({id:'statistics',name:'Statistics',sheetOrder:['one','hidden'],sheets:{
      one:{id:'one',name:'One',rowCount:20,columnCount:10,cellData:{0:{0:{v:0},1:{v:false},2:{v:''},3:{v:' '},4:{v:null},5:{s:{bl:1}},6:{f:'=1'},7:{f:'',v:'text'},8:{f:'=2',v:2}},1:{0:{p:{body:{dataStream:'rich\r\n'}}}}}},
      hidden:{id:'hidden',name:'Hidden',hidden:1,rowCount:10,columnCount:10,cellData:{4:{2:{v:'hidden',f:'=3'}}}}
    }} as any)
    const before = JSON.stringify(book.getSnapshot())
    const { readWorkbookStatistics } = await product()
    expect(readWorkbookStatistics({univerAPI:api})).toEqual({sheets:2,cells:6,formulas:3,message:'工作簿统计：2 个工作表 · 6 个有数据的单元格 · 3 个公式。'})
    expect(JSON.stringify(book.getSnapshot())).toBe(before)
    book.getActiveSheet()!.getRange('A10').setValue('new')
    expect(readWorkbookStatistics({univerAPI:api})).toMatchObject({sheets:2,cells:7,formulas:3})
  } finally {univer.dispose()}
})
it('counts sparse blank snapshots and preserves source thousands formatting', async () => {
  const cells = Object.fromEntries(Array.from({length:1001},(_,i)=>[i,{v:1,f:'=1'}]))
  const {readWorkbookStatistics} = await product()
  const runtime = {univerAPI:{getActiveWorkbook:()=>({getSnapshot:()=>({sheets:{empty:{},data:{cellData:{0:cells,1:null,2:{0:null}}}}})})}}
  expect(readWorkbookStatistics(runtime)).toEqual({sheets:2,cells:1001,formulas:1001,message:`工作簿统计：2 个工作表 · ${(1001).toLocaleString()} 个有数据的单元格 · ${(1001).toLocaleString()} 个公式。`})
})
it('returns no feedback when no workbook is open', async () => {
  const {readWorkbookStatistics} = await product()
  expect(readWorkbookStatistics({univerAPI:{getActiveWorkbook:()=>null}})).toBeNull()
})

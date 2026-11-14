import {expect,it} from 'vitest'
import {projectPictureNotes} from './workbook-note-pictures-host'
import {withWorkbookNotes,workbookNoteOperations} from './workbook-notes'
it('图片批注进入官方note资源且只读文字仍禁止差分写回',()=>{
 const model:any={sheets:[{name:'表',notes:{notes:[],readOnlyReason:'图片'}}]}
 projectPictureNotes(model,{key:'k',pictures:[{sheetName:'表',row:0,column:0,text:'原文',author:'作者'}],issues:[]} as any)
 const data:any=withWorkbookNotes({sheets:{s:{id:'s',name:'表',rowCount:10,columnCount:10}}} as any,model)
 expect(JSON.parse(data.resources[0].data).s[0][0].note).toBe('原文')
 const sheet:any={getSheetName:()=> '表',getNotes:()=>[{row:0,col:0,note:'原文'}]}
 expect(workbookNoteOperations(model,{getSheets:()=>[sheet]} as any)).toEqual([])
 sheet.getNotes=()=>[{row:0,col:0,note:'变化'}]
 expect(()=>workbookNoteOperations(model,{getSheets:()=>[sheet]} as any)).toThrow('图片')
})

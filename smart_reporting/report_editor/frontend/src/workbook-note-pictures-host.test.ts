import {expect,it,vi} from 'vitest'
import {installNotePictureHover,projectPictureNotes} from './workbook-note-pictures-host'
import {SheetsNotePopupService} from '@univerjs/sheets-note-ui'
import {Subject} from 'rxjs'
it('subscribes to official popup service for temporary and pinned notes and disposes subscription',()=>{
 const activePopup$=new Subject<any>(),onCard=vi.fn(),picture={row:0,column:0,sheetName:'数据',sheetIndex:0} as any
 const get=vi.fn(token=>{expect(token).toBe(SheetsNotePopupService);return {activePopup$}})
 const host=installNotePictureHover({univer:{__getInjector:()=>({get})},univerAPI:{getActiveWorkbook:()=>({getSheetBySheetId:()=>({getSheetName:()=> '数据'})})}},()=>({key:'x',pictures:[picture]}),onCard)
 activePopup$.next({subUnitId:'sheet-0',row:0,col:0,temp:true});expect(onCard).toHaveBeenLastCalledWith(picture,'x')
 activePopup$.next({subUnitId:'sheet-0',row:0,col:0,temp:false});expect(onCard).toHaveBeenLastCalledWith(picture,'x')
 activePopup$.next(null);expect(onCard).toHaveBeenLastCalledWith(null,'x');host.dispose();onCard.mockClear();activePopup$.next({});expect(onCard).not.toHaveBeenCalled()
})
it('projects picture metadata onto the matching sheet while retaining the edit guard',()=>{
 const model:any={sheets:[{name:'数据',notes:{notes:[],readOnlyReason:'含图片'}}]}
 const picture={sheetName:'数据',row:0,column:0,text:'原文',author:'作者',sourceIdentity:'a'} as any
 projectPictureNotes(model,{key:'x',pictures:[picture],issues:[]})
 expect(model.sheets[0].notes.pictures).toEqual([picture]);expect(model.sheets[0].notes.pictureProjection).toBe(true);expect(model.sheets[0].notes.readOnlyReason).toBe('含图片');expect(model.sheets[0].notes.notes).toEqual([])
})
it('preserves ordinary notes while projecting matching pictures only',()=>{
 const model:any={sheets:[{name:'数据',notes:{notes:[{row:1,column:1,text:'普通',author:'甲'},{row:0,column:0,text:'旧缓存',author:'旧'}],sourceIdentity:'old'}}]}
 const picture={sheetName:'数据',row:0,column:0,text:'原文',author:'作者',sourceIdentity:'a'} as any
 projectPictureNotes(model,{key:'x',pictures:[picture,{...picture,sheetName:'Other'}],issues:[]})
 expect(model.sheets[0].notes.notes).toEqual([{row:1,column:1,text:'普通',author:'甲'},{row:0,column:0,text:'旧缓存',author:'旧'}])
 expect(model.sheets[0].notes.pictures).toEqual([picture])
})

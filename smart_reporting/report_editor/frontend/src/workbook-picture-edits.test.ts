import {describe,expect,it} from 'vitest'
import {captureWorkbookPictureEdits,WORKBOOK_PICTURE_EDIT_COMMANDS,WORKBOOK_PICTURE_EDIT_WRAPPERS} from './workbook-picture-edits'

const position={from:{row:2,column:3,rowOffset:4,columnOffset:5},to:{row:4,column:5,rowOffset:6,columnOffset:7}}
const transform={left:305,top:44,width:202,height:42,angle:0,flipX:false,flipY:false,skewX:0,skewY:0}
function fixture() {
  const drawing={unitId:'book',subUnitId:'sheet',drawingId:'one',drawingType:0,source:'data:image/png;base64,controlled',
    imageSourceType:1,transform:structuredClone(transform),sheetTransform:structuredClone(position),axisAlignSheetTransform:structuredClone(position)}
  const picture={sheetName:'Sheet1',drawingPart:'xl/drawings/drawing1.xml',pictureId:'7',sha256:'a'.repeat(64),
    row:0,column:0,rowOffsetPx:0,columnOffsetPx:0,widthPx:100,heightPx:100}
  const second={...structuredClone(drawing),drawingId:'two'}
  const bindings=new Map([['one',{picture,drawing:structuredClone(drawing)}],
    ['two',{picture:{...picture,pictureId:'8'},drawing:structuredClone(second)}]])
  const command={id:WORKBOOK_PICTURE_EDIT_COMMANDS[0] as string,params:{unitId:'book',drawings:[drawing,second]}}
  return {drawing,second,bindings,command}
}
const resolve=()=>({...transform})
describe('ordinary drawing command capture',()=>{
  it('translates native multi-picture movement/resize into one validated batch without touching inputs',()=>{
    const {command,bindings}=fixture(),before=structuredClone(command)
    const edits=captureWorkbookPictureEdits(command,'book',bindings,resolve)!
    expect(edits.map(edit=>edit.pictureId)).toEqual(['7','8'])
    expect(edits[0]).toMatchObject({kind:'editPicture',mediaSha256:'a'.repeat(64),
      before:{row:0,widthPx:100},geometry:{row:2,column:3,rowOffsetPx:4,columnOffsetPx:5,widthPx:202,heightPx:42}})
    expect(command).toEqual(before)
    expect(edits[0]).not.toHaveProperty('sourceIdentity')
  })
  it('captures identity-only native batch deletes and leaves wrappers to the SDK',()=>{
    const {command,bindings}=fixture()
    command.id=WORKBOOK_PICTURE_EDIT_COMMANDS[1]
    command.params.drawings=command.params.drawings.map(({unitId,subUnitId,drawingId,drawingType})=>
      ({unitId,subUnitId,drawingId,drawingType})) as typeof command.params.drawings
    expect(captureWorkbookPictureEdits(command,'book',bindings,resolve)?.map(edit=>edit.geometry)).toEqual([null,null])
    for(const id of WORKBOOK_PICTURE_EDIT_WRAPPERS)
      expect(captureWorkbookPictureEdits({id},'book',bindings,resolve)).toBeUndefined()
  })
  it('accepts the native drag controller partial drawing payload without image source fields',()=>{
    const {command,bindings}=fixture()
    command.params.drawings=command.params.drawings.map(({unitId,subUnitId,drawingId,transform,sheetTransform,axisAlignSheetTransform})=>
      ({unitId,subUnitId,drawingId,transform,sheetTransform,axisAlignSheetTransform})) as typeof command.params.drawings
    expect(captureWorkbookPictureEdits(command,'book',bindings,resolve)).toHaveLength(2)
  })
  it('rejects geometry edits with the specific source projection reason',()=>{
    const {command,bindings}=fixture()
    Object.assign(bindings.get('two')!.picture,{geometryReadOnlyReason:'源图片含旋转或裁剪，暂不支持移动或缩放'})
    expect(()=>captureWorkbookPictureEdits(command,'book',bindings,resolve)).toThrow('源图片含旋转或裁剪，暂不支持移动或缩放')
  })
  it('still permits deleting pictures whose source geometry cannot be projected',()=>{
    const {command,bindings}=fixture()
    Object.assign(bindings.get('two')!.picture,{geometryReadOnlyReason:'源图片含旋转或裁剪，暂不支持移动或缩放'})
    command.id=WORKBOOK_PICTURE_EDIT_COMMANDS[1]
    expect(captureWorkbookPictureEdits(command,'book',bindings,resolve)?.map(edit=>edit.geometry)).toEqual([null,null])
  })
  it.each(['foreign-book','foreign-sheet','unknown','duplicate','changed-source','rotation','flip','NaN','zero','negative-offset','fractional-row','axis-conflict','transform-conflict','unsupported'])(
    'rejects the entire batch when its second member has %s',issue=>{
      const {command,second,bindings}=fixture()
      if(issue==='foreign-book')second.unitId='other'
      if(issue==='foreign-sheet')second.subUnitId='other'
      if(issue==='unknown')second.drawingId='unknown'
      if(issue==='duplicate')second.drawingId='one'
      if(issue==='changed-source')second.source='https://foreign.invalid/image.png'
      if(issue==='rotation')second.transform.angle=90
      if(issue==='flip')second.transform.flipX=true
      if(issue==='NaN')second.transform.width=NaN
      if(issue==='zero')second.transform.width=0
      if(issue==='negative-offset')second.sheetTransform.from.rowOffset=-1
      if(issue==='fractional-row')second.sheetTransform.from.row=1.5
      if(issue==='axis-conflict')second.axisAlignSheetTransform.from.row=99
      if(issue==='transform-conflict')second.transform.width=200
      if(issue==='unsupported')Object.assign(second,{crop:{left:5}})
      expect(()=>captureWorkbookPictureEdits(command,'book',bindings,resolve)).toThrow(/身份/)
    })
  it('rejects unresolvable geometry and mismatched workbook envelopes',()=>{
    const {command,bindings}=fixture()
    expect(()=>captureWorkbookPictureEdits(command,'book',bindings,()=>undefined)).toThrow()
    command.params.unitId='other'
    expect(()=>captureWorkbookPictureEdits(command,'book',bindings,resolve)).toThrow()
  })
})

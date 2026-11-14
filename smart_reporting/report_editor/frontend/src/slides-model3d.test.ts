import {it,expect} from 'vitest'
import {turnModelDraft,validateModelDraft,type ModelChanges} from './slides-model3d'
import {NativeDraft} from './native-draft'
it('未保存模型旋转更新插入条目，已有来源旋转绑定GLB身份，Undo整对恢复',()=>{
 const changes:ModelChanges={modelInsertions:[{slideIndex:0,key:'new-one',name:'a.glb',bytesBase64:'Z2xi',posterBase64:'b2xk',aspect:1,rot:{ax:0,ay:0,az:0}}]}
 const source={sourceId:'native-new',sha256:'a'.repeat(64),size:3,rot:{ax:0,ay:0,az:0},bytesBase64:'Z2xi'}
 const rotated=turnModelDraft(changes,0,source,'new-one',{ax:30000,ay:60000,az:0},'bmV3')
 expect(rotated.modelInsertions?.[0]?.posterBase64).toBe('bmV3');expect(rotated.modelViews).toBeUndefined();expect(changes.modelInsertions?.[0]?.rot.ax).toBe(0)
 const existing=turnModelDraft({},0,source,undefined,{ax:30000,ay:60000,az:0},'bmV3')
 expect(existing.modelViews?.[0]?.expectedSha256).toBe(source.sha256)
 const draft=new NativeDraft({documentId:'models',revision:1,sourceSha256:'b'.repeat(64),format:'pptx'} as any,{getItem:()=>null,setItem:()=>{},removeItem:()=>{}})
 draft.setOperations([{kind:'editSlides',...changes}]);draft.setOperations([{kind:'editSlides',...rotated}]);draft.undo();expect(draft.operations[0]?.modelInsertions).toEqual(changes.modelInsertions);draft.redo();expect(draft.operations[0]?.modelInsertions).toEqual(rotated.modelInsertions)
})
it('不恢复无来源身份的模型视角',()=>{expect(()=>validateModelDraft({modelViews:[{slideIndex:0,elementId:'x',expectedSha256:'wrong',rot:{ax:0,ay:0,az:0},posterBase64:'AA=='}]},1)).toThrow()})

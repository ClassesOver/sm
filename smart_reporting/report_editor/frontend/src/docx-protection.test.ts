import { describe,it,expect } from 'vitest'
import {docxProtectionModel,withDocxProtection,docxProtectionOperations} from './docx-protection'
const model={expectedSettingsSha256:'a'.repeat(64),expectedProtectionSha256:'b'.repeat(64),protection:null,editable:true,contentLocked:false,hasPassword:false,readOnlyReason:null}
describe('document protection draft',()=>{
 it('binds enable to source and isolates protection save',()=>{const m=docxProtectionModel(model)!;const ops=withDocxProtection([],m,'enable','readOnly','');expect(docxProtectionOperations(ops,m)).toEqual(ops);expect(()=>withDocxProtection([{kind:'setPageColor'}],m,'enable','forms','')).toThrow(/单独/);expect(()=>docxProtectionOperations(ops,{...m,expectedSettingsSha256:'c'.repeat(64)})).toThrow(/来源/)})
 it('never unlocks content before save/reload and rejects malformed model',()=>{expect(docxProtectionModel({...model,expectedSettingsSha256:'bad'})).toBeNull();expect(()=>withDocxProtection([],{...model,protection:{edit:'readOnly',enforced:true},contentLocked:true},'enable','forms','')).toThrow(/解除/)})
})

import { expect, it } from 'vitest'
import { missingRequiredPdfFields } from './pdf-form-completion'

it('uses visible widget flags and draft values without counting a visual signature as a digital one', () => {
  const widget = (fieldName: string, fieldType: string, extra = {}) => ({
    id: fieldName, subtype: 'Widget', fieldName, fieldType, required: true,
    rect: [0, 0, 40, 16], fieldValue: '', ...extra,
  })
  const result = missingRequiredPdfFields([
    {pageId:'first', annotations:[
      widget('check', 'Btn', {checkBox:true,fieldValue:'Off'}),
      widget('required text', 'Tx', {fieldValue:'saved',rect:[10,20,80,40]}),
      widget('read only', 'Tx', {readOnly:true}),
      widget('choice', 'Ch', {fieldValue:['selected']}),
      widget('radio', 'Btn', {radioButton:true,fieldValue:'Off'}),
      widget('removed', 'Tx'),
    ]},
    {pageId:'second', annotations:[
      widget('radio', 'Btn', {radioButton:true,fieldValue:'Yes'}),
      widget('signature', 'Sig', {fieldValue:'unverified visual indicator'}),
      widget('hidden', 'Tx', {hidden:true}),
    ]},
  ], [
    {kind:'setFormValue', name:'check', checked:true},
    {kind:'setFormValue', name:'required text', value:'   '},
    {kind:'removeFormWidget', widgetId:'removed'},
  ])
  expect(result.map(({name,pageId})=>[name,pageId])).toEqual([
    ['required text','first'],['signature','second'],
  ])
})

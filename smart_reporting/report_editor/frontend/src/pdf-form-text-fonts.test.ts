import {afterEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {stagePdfFormTextProperties,validatePdfFormTextProperties,validateRestoredPdfFormTextProperties,bindPdfFormTextPropertiesPanel} from './pdf-form-text-properties'
afterEach(()=>document.body.replaceChildren())
const sourceSha256='a'.repeat(64),target={fieldName:'party.name',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64)},widget={...target,pageIndex:0,rect:[30,180,180,210]as[number,number,number,number],removable:false,removalReason:'hierarchy',designEditable:true,fieldKind:'text',textPropertiesEditable:true,textProperties:{multiLine:false,maxLen:null,textAlignment:'left' as const,fontSize:12,fontName:'Times-Italic',valueLength:5}},model=()=>({sourceSha256,formDesignWidgets:[widget],capabilities:{editFormTextProperties:true}})
const faces=['Helvetica','Helvetica-Bold','Helvetica-Oblique','Helvetica-BoldOblique','Times-Roman','Times-Bold','Times-Italic','Times-BoldItalic','Courier','Courier-Bold','Courier-Oblique','Courier-BoldOblique'] as const
function draft(){return new NativeDraft({documentId:'text-fonts',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:vi.fn(),removeItem:vi.fn()})}
it('stages and restores exactly the existing twelve standard Latin faces',()=>{
 for(const fontName of faces){const ops=stagePdfFormTextProperties(model(),[],target,{fontName});expect(ops).toEqual([{kind:'editFormTextProperties',sourceSha256,...target,fontName}]);expect(()=>validateRestoredPdfFormTextProperties(model(),ops)).not.toThrow()}
 for(const fontName of ['',null,'CustomFont','Symbol','ZapfDingbats'])expect(()=>validatePdfFormTextProperties([{kind:'editFormTextProperties',sourceSha256,...target,fontName}])).toThrow()
})
it('font panel keeps original face selected and stages only an explicit font change',async()=>{
 const root=document.createElement('div');document.body.append(root);const d=draft(),panel=bindPdfFormTextPropertiesPanel({root,draft:d,model,unavailable:()=>null,refresh:async()=>{}});panel.open()
 const font=root.querySelector<HTMLSelectElement>('select[aria-label="字体"]')!;expect(font).not.toBeNull();expect([...font.options].map(x=>x.value)).toEqual(faces);expect(font.value).toBe('Times-Italic')
 root.querySelector<HTMLButtonElement>('[data-pdf-form-text-properties-apply]')!.click();await Promise.resolve();expect(d.operations).toEqual([])
 const current=root.querySelector<HTMLSelectElement>('select[aria-label="字体"]')!;current.value='Courier-BoldOblique';panel.refresh();expect(root.querySelector('select[aria-label="字体"]')).toBe(current)
 root.querySelector<HTMLButtonElement>('[data-pdf-form-text-properties-apply]')!.click();await vi.waitFor(()=>expect(d.operations).toEqual([{kind:'editFormTextProperties',sourceSha256,...target,fontName:'Courier-BoldOblique'}]));panel.dispose()
})

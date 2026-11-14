import {afterEach,expect,it,vi} from 'vitest'
import {bindPdfMeasureDialog} from './pdf-measure-dialog'
const render=vi.hoisted(()=>vi.fn((_options:any)=>({dispose:vi.fn()})))
vi.mock('./pdf-measure-dialog-source',()=>({showPdfMeasureDialog:render}))
let control:ReturnType<typeof bindPdfMeasureDialog>|undefined
afterEach(()=>{control?.dispose();render.mockClear()})
async function fixture(){let identity='initial',unavailable:string|null=null;const status=vi.fn(),apply=vi.fn(async()=>{});control=bindPdfMeasureDialog({owner:document,snapshot:()=>identity,unavailable:()=>unavailable,status});await control.open(120,apply);return {args:render.mock.calls.at(-1)![0],apply,status,stale:()=>{identity='changed'},block:()=>{unavailable='当前只读'}}}
it('打开完整源对话框不提交，确认只调用既有宿主提交',async()=>{const f=await fixture();expect(f.apply).not.toHaveBeenCalled();expect(control!.incompleteReason()).toBeTruthy();await f.args.onApply({unitsPerPt:60,unit:'m'});expect(f.apply).toHaveBeenCalledExactlyOnceWith({unitsPerPt:60,unit:'m'});expect(control!.incompleteReason()).toBeNull()})
it.each(['cancel','dispose','stale','readonly'])('确认前%s阻止提交或丢弃迟到回调',async mode=>{const f=await fixture();if(mode==='cancel')f.args.onCancel();if(mode==='dispose')control!.dispose();if(mode==='stale')f.stale();if(mode==='readonly')f.block();await f.args.onApply({unitsPerPt:60,unit:'m'}).catch(()=>{});expect(f.apply).not.toHaveBeenCalled()})
it('提交失败保留对话框和错误，不误标定成功',async()=>{const f=await fixture();f.apply.mockRejectedValueOnce(Error('校验失败'));await expect(f.args.onApply({unitsPerPt:60,unit:'m'})).rejects.toThrow('校验失败');expect(control!.incompleteReason()).toBeTruthy()})
it('模块迟到加载在取消后不挂载dialog',async()=>{const status=vi.fn();control=bindPdfMeasureDialog({owner:document,snapshot:()=>'',unavailable:()=>null,status});const opening=control.open(120,vi.fn(async()=>{}));control.cancel();await opening;expect(render).not.toHaveBeenCalled();expect(control.incompleteReason()).toBeNull()})

it('取消重新标定通知宿主保留旧比例，成功确认不调用取消',async()=>{const onCancel=vi.fn(),apply=vi.fn(async()=>{});control=bindPdfMeasureDialog({owner:document,snapshot:()=>'',unavailable:()=>null,status:vi.fn()});await control.open(120,apply,onCancel);render.mock.calls.at(-1)![0].onCancel();expect(onCancel).toHaveBeenCalledOnce();expect(apply).not.toHaveBeenCalled();await control.open(120,apply,onCancel);await render.mock.calls.at(-1)![0].onApply({unitsPerPt:60,unit:'m'});expect(onCancel).toHaveBeenCalledOnce()})

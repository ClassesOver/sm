import assert from 'node:assert/strict'
import {test} from 'node:test'
import {addElement,createBlankPptx,openPptx,savePptx,type SlideElement} from '@genoffice/pptx-engine'
import {inspectBrushSource} from '../pptx-brush-source.ts'
const element=(runs:unknown[]=[])=>({type:'shape',anchor:{originalXml:'<p:sp/>'},fill:{type:'solid',color:'#123456'},text:{paragraphs:[{align:'center',runs}]}} as unknown as SlideElement)
test('所有非空runs逐字段一致才捕获，保留false且不复制删除线',()=>{
 const source=element([{text:'甲',bold:false,fontSize:18,strike:true},{text:'乙',bold:false,fontSize:24}])
 assert.deepEqual(inspectBrushSource(source),{supported:true,text:{bold:false},align:'center',shape:{fill:'#123456'}})
})
test('缺省继承字段和复杂颜色不猜默认，渐变/复杂边框不降级',()=>{
 const source=element([{text:'甲',bold:false,boldImplicit:true,color:'#11223380'}])
 Object.assign(source,{fill:{type:'gradient',stops:[]},stroke:{fill:{type:'solid',color:'#112233'},width:12700,dash:'dash'}})
 assert.deepEqual(inspectBrushSource(source),{supported:true,align:'center'})
 assert.equal(inspectBrushSource({...source,type:'picture'} as SlideElement).supported,false)
 assert.equal(inspectBrushSource({...source,anchor:{originalXml:'<p:sp><a:fld/></p:sp>'}} as SlideElement).supported,false)
})
test('边框只接收简单可写范围，缺失边框不伪造none',()=>{
 const source=element();Object.assign(source,{stroke:{fill:{type:'solid',color:'#112233'},width:25400}})
 source.anchor.originalXml='<p:sp><p:spPr><a:ln w="25400"><a:solidFill><a:srgbClr val="112233"/></a:solidFill></a:ln></p:spPr></p:sp>'
 assert.deepEqual(inspectBrushSource(source).shape,{fill:'#123456',stroke:{color:'#112233',widthPt:2}})
})
test('轮廓摘要要求显式简单RGB线条，未解析属性或继承样式不得冒充安全实线',()=>{
 const source=element();Object.assign(source,{stroke:{fill:{type:'solid',color:'#112233'},width:25400}})
 for(const line of [
  '',
  '<a:ln w="25400" algn="in"><a:solidFill><a:srgbClr val="112233"/></a:solidFill></a:ln>',
  '<a:ln w="25400"><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:ln>',
  '<a:ln w="25400"><a:solidFill><a:srgbClr val="112233"/></a:solidFill><a:custDash><a:ds d="100" sp="100"/></a:custDash></a:ln>',
  '<a:ln w="25400"><a:solidFill><a:srgbClr val="112233"/></a:solidFill><a:headEnd type="triangle"/></a:ln>',
 ]){
  source.anchor.originalXml=`<p:sp><p:spPr>${line}</p:spPr></p:sp>`
  assert.equal(inspectBrushSource(source).shape?.stroke,undefined,line)
  assert.equal(inspectBrushSource(source).shape?.fill,'#123456')
 }
})
test('显式简单无线条回填null，缺失或带未知属性的无线条仍不猜测',()=>{
 const source=element()
 source.anchor.originalXml='<p:sp><p:spPr><a:ln><a:noFill/></a:ln></p:spPr></p:sp>'
 assert.equal(inspectBrushSource(source).shape?.stroke,null)
 for(const line of ['', '<a:ln algn="in"><a:noFill/></a:ln>']){
  source.anchor.originalXml=`<p:sp><p:spPr>${line}</p:spPr></p:sp>`
  assert.equal(inspectBrushSource(source).shape?.stroke,undefined)
 }
})
test('解析缺省文字不把黑色与未设置下划线当作明确格式',()=>{
 const source=element([{text:'甲',color:'#000000',underline:false,styleSrc:{color:'default'}}])
 assert.equal(inspectBrushSource(source).text,undefined)
})
test('真实PPTX普通创建标识不误判复杂扩展且只读摘要不修改模型',async()=>{
 const opened=await openPptx(await createBlankPptx())
 addElement(opened.deck.slides[0]!,{kind:'textbox',offset:{x:100,y:100,cx:10000,cy:10000},paragraphs:[{runs:[{text:'甲',bold:false,fontSize:18,color:'#123456'}]}]})
 const source=(await openPptx(await savePptx(opened))).deck.slides[0]!.elements[0]!
 const before=JSON.stringify(source),summary=inspectBrushSource(source)
 assert.equal(summary.supported,true);assert.equal(summary.text?.bold,false);assert.equal(summary.text?.fontSizePt,18)
 assert.equal(JSON.stringify(source),before)
 const identity={...source,anchor:{...source.anchor,originalXml:source.anchor.originalXml.replace('</p:sp>','<a:extLst><a:ext uri="{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236}"><a16:creationId id="test"/></a:ext></a:extLst></p:sp>')}}
 assert.equal(inspectBrushSource(identity).supported,true)
})
test('字体槽回归：真实PPTX中文Latin-only来源不复制解析显示字体',async()=>{
 const opened=await openPptx(await createBlankPptx())
 // browser/source.pptx 的来源 A：中文正文、仅 a:latin Arial，其余字体由主题补足。
 addElement(opened.deck.slides[0]!,{kind:'textbox',offset:{x:100,y:100,cx:10000,cy:10000},paragraphs:[{runs:[{text:'来源 A',fontSize:32,latinFont:'Arial'}]}]})
 const source=(await openPptx(await savePptx(opened))).deck.slides[0]!.elements[0]!
 assert.ok(source.type==='text'||source.type==='shape')
 const run=source.text!.paragraphs[0]!.runs[0]!
 assert.equal(run.latinFont,'Arial');assert.equal(run.eaFont,undefined);assert.equal(run.csFont,undefined)
 const before=JSON.stringify(source)
 assert.equal(inspectBrushSource(source).text?.fontFamily,undefined)
 assert.equal(JSON.stringify(source),before)
})
test('字体槽回归：所有非空run三槽同名明确字体才可安全复制',async()=>{
 const opened=await openPptx(await createBlankPptx())
 addElement(opened.deck.slides[0]!,{kind:'textbox',offset:{x:100,y:100,cx:10000,cy:10000},paragraphs:[{runs:[{text:'来源 A',latinFont:'Arial',eaFont:'Arial',csFont:'Arial'},{text:'乙',latinFont:'Arial',eaFont:'Arial',csFont:'Arial'}]}]})
 const source=(await openPptx(await savePptx(opened))).deck.slides[0]!.elements[0]!
 assert.equal(inspectBrushSource(source).text?.fontFamily,'Arial')
})
test('字体槽回归：混合文字体系、主题引用和缺省继承均省略单字体',()=>{
 for(const runs of [
  [{text:'甲',fontFamily:'Calibri'}],
  [{text:'甲',fontFamily:'Arial',latinFont:'Arial',eaFont:'宋体',csFont:'Arial'}],
  [{text:'甲',fontFamily:'Arial',latinFont:'+mn-lt',eaFont:'+mn-lt',csFont:'+mn-lt'}],
  [{text:'甲',fontFamily:'Arial',latinFont:'Arial',eaFont:'Arial',csFont:'Arial',fontImplicit:true}],
  [{text:'甲',fontFamily:'Arial',latinFont:'Arial',eaFont:'Arial',csFont:'Arial'},{text:'乙',fontFamily:'Arial',latinFont:'Calibri',eaFont:'Calibri',csFont:'Calibri'}],
 ])assert.equal(inspectBrushSource(element(runs)).text?.fontFamily,undefined)
})

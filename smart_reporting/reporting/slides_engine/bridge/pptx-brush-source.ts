import {isConnectorXml,type SlideElement,type TextRun} from '@genoffice/pptx-engine'
type Text={fontSizePt?:number;fontFamily?:string;color?:string;bold?:boolean;italic?:boolean;underline?:boolean}
type Shape={fill?:string;stroke?:{color:string;widthPt:number}|null}
export type BrushSource={supported:boolean;text?:Text;align?:'left'|'center'|'right'|'justify';shape?:Shape;reason?:string}
const hex=(value:unknown):value is string=>typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value)
/** 只摘要已解析模型，所有非空正文 run 一致且明确的字段才可复制。 */
export function inspectBrushSource(element:SlideElement):BrushSource{
 const unsupported=()=>({supported:false,reason:'此来源对象暂不支持安全格式刷'})
 const plainXml=element.anchor.originalXml.replace(/<a:extLst><a:ext uri="[{]FF2B5EF4-FFF2-40B4-BE49-F238E27FC236[}]"><a16:creationId[^>]*[/]><[/]a:ext><[/]a:extLst>/g,'')
 if(!['text','shape'].includes(element.type)||isConnectorXml(element.anchor.originalXml)||/<(?:[A-Za-z_][A-Za-z0-9_.-]*:)?(?:AlternateContent|fld|extLst|hlinkClick|hlinkHover)(?=[ />])/.test(plainXml))return unsupported()
 if(element.type!=='text'&&element.type!=='shape')return unsupported()
 const paragraphs=element.text?.paragraphs??[],runs=paragraphs.flatMap(p=>p.runs).filter(run=>run.text.length>0)
 if(runs.some(run=>run.rawXml))return unsupported()
 const text:Text={},shape:Shape={}
 const uniform=(field:keyof TextRun,valid:(value:unknown,run:TextRun)=>boolean)=>{
  const value=runs[0]?.[field]
  return runs.length&&runs.every(run=>run[field]===value&&valid(run[field],run))?value:undefined
 }
 const fontSize=uniform('fontSize',(v,r)=>typeof v==='number'&&Number.isFinite(v)&&v>=1&&v<=400&&!r.fontSizeImplicit)
 if(typeof fontSize==='number')text.fontSizePt=fontSize
 // fontFamily 是解析后的显示字体；单字段回写会覆盖 latin/ea/cs，只有三槽同名明确字体才无损。
 const family=uniform('latinFont',(v,r)=>typeof v==='string'&&!!v.trim()&&v.length<=200&&!v.startsWith('+')&&!/[\x00-\x1f]/.test(v)&&!r.fontImplicit&&r.eaFont===v&&r.csFont===v)
 if(typeof family==='string')text.fontFamily=family
 const color=uniform('color',(value,run)=>hex(value)&&run.styleSrc?.color!=='default');if(typeof color==='string')text.color=color.toUpperCase()
 for(const field of ['bold','italic','underline'] as const){
  const value=uniform(field,(v,r)=>typeof v==='boolean'&&(field==='bold'?!r.boldImplicit:field==='italic'?!r.italicImplicit:v===false?r.underlineExplicitNone===true:r.underlineStyle===undefined||r.underlineStyle==='sng'))
  if(typeof value==='boolean')text[field]=value
 }
 if(!element.useBgFill&&!element.fillOverlay){
  if(element.fill?.type==='none')shape.fill='none'
  else if(element.fill?.type==='solid'&&hex(element.fill.color))shape.fill=element.fill.color.toUpperCase()
 }
 const stroke=element.stroke
 // width/color回写会重建整条线。模型未表达algn等XML属性，故只接受显式简单RGB线，
 // 不把继承主题线、未知属性或未解析子节点当作可无损复制的来源。
 const spPr=/<p:spPr\b[^>]*>([\s\S]*?)<\/p:spPr>/.exec(element.anchor.originalXml)?.[1]
 const line=spPr?.match(/<a:ln\b[^>]*>[\s\S]*?<\/a:ln>/g)
 const simpleLine=line?.length===1?/^<a:ln\s+w="(\d+)"\s*>\s*<a:solidFill>\s*<a:srgbClr\s+val="([0-9a-f]{6})"\s*\/?>\s*(?:<\/a:srgbClr>\s*)?<\/a:solidFill>\s*(?:<a:prstDash\s+val="solid"\s*\/>\s*)?<\/a:ln>$/i.exec(line[0]!):null
 if(line?.length===1&&/^<a:ln(?:\s+w="\d+")?\s*>\s*<a:noFill\s*\/>\s*<\/a:ln>$/.test(line[0]!))shape.stroke=null
 if(stroke?.fill.type==='solid'&&hex(stroke.fill.color)&&Number.isFinite(stroke.width)&&stroke.width>0&&stroke.width<=1270000
  &&simpleLine&&Number(simpleLine[1])===stroke.width&&`#${simpleLine[2]}`.toUpperCase()===stroke.fill.color.toUpperCase()
  &&(!stroke.dash||stroke.dash==='solid')&&!stroke.cap&&!stroke.join&&(!stroke.compound||stroke.compound==='sng')&&!stroke.headEnd&&!stroke.tailEnd)shape.stroke={color:stroke.fill.color.toUpperCase(),widthPt:stroke.width/12700}
 const align=paragraphs[0]?.align
 const uniformAlign=align&&['left','center','right','justify'].includes(align)&&paragraphs.every(p=>p.align===align)?align:undefined
 return {supported:true,...(Object.keys(text).length?{text}:{}),...(uniformAlign?{align:uniformAlign}:{}),...(Object.keys(shape).length?{shape}:{})}
}

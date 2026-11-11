/** Pure DA/AP inspection shared by safe field design and appearance refresh. */
import {PDFDict,PDFDocument,PDFName,PDFRawStream,PDFTextField,StandardFonts,adjustDimsForRotation,reduceRotation,layoutSinglelineText,layoutMultilineText,type PDFField} from 'pdf-lib'

export interface DesignTextProperties {multiLine:boolean;maxLen:number|null;textAlignment:'left'|'center'|'right';fontSize:number;fontName:string;valueLength:number}
export const designTextFontNames=['Helvetica','Helvetica-Bold','Helvetica-Oblique','Helvetica-BoldOblique','Times-Roman','Times-Bold','Times-Italic','Times-BoldItalic','Courier','Courier-Bold','Courier-Oblique','Courier-BoldOblique'] as const
const latinFonts=new Set<string>(designTextFontNames)
// Only standard Latin faces with a matching local DA/AP font are proven encodable here.
export function inspectDesignTextProperties(field:PDFField):{editable:boolean;reason:string|null;properties?:DesignTextProperties}{try{
 if(!(field instanceof PDFTextField))throw Error('仅支持标准文本字段')
 const widgets=field.acroField.getWidgets(),value=field.getText()??''
 if(widgets.length!==1||field.isReadOnly()||field.isPassword()||field.isRichFormatted()||field.isFileSelector()||(field.acroField.getFlags()&16777216)!==0)throw Error('仅支持未保护、非密码/富文本/组合格的独立文本控件')
 const widget=widgets[0];if(['A','AA'].some(key=>field.acroField.dict.has(PDFName.of(key))||widget.dict.has(PDFName.of(key)))||widget.dict.has(PDFName.of('DA')))throw Error('动作、日期或控件级独立DA暂不支持文本属性编辑')
 if(!/^[ -~\r\n]*$/.test(value))throw Error('现值含未验证字体覆盖的字符，当前仅支持ASCII文本')
 const da=field.acroField.getDefaultAppearance()??'',matches=[...da.matchAll(/\/([A-Za-z0-9_.-]+)\s+(\d*\.?\d+)\s+Tf\b/g)]
 if(matches.length!==1||Number(matches[0][2])<=0)throw Error('缺少可验证的字段默认字号')
 const normalObject=widget.dict.lookupMaybe(PDFName.of('AP'),PDFDict)?.lookup(PDFName.of('N')),normal=normalObject instanceof PDFRawStream?normalObject:undefined,fonts=normal?.dict.lookupMaybe(PDFName.of('Resources'),PDFDict)?.lookupMaybe(PDFName.of('Font'),PDFDict),font=fonts?.lookupMaybe(PDFName.of(matches[0][1]),PDFDict),base=font?.get(PDFName.of('BaseFont'))
 const name=base instanceof PDFName?base.decodeText():''
 if(!normal||fonts?.keys().length!==1||!font||String(font.get(PDFName.of('Subtype')))!=='/Type1'||font.has(PDFName.of('FontDescriptor'))||String(font.get(PDFName.of('Encoding')))!=='/WinAnsiEncoding'||!latinFonts.has(name))throw Error('仅支持DA/AP一致的标准Helvetica/Times/Courier字体；自定义字体闭包未验证')
 const alignment=field.getAlignment();if(![0,1,2].includes(alignment))throw Error('来源对齐属性无效')
 return {editable:true,reason:null,properties:{multiLine:field.isMultiline(),maxLen:field.getMaxLength()??null,textAlignment:(['left','center','right']as const)[alignment],fontSize:Number(matches[0][2]),fontName:name,valueLength:value.length}}
}catch(error){return {editable:false,reason:error instanceof Error?error.message:'来源文本属性暂不支持'}}}

export interface FormTextOverflowIssue {code:'pdf_form_text_overflow';fieldName:string;message:string;details:{mode:'singleline'|'multiline';fontName:string;fontSize:number;availableWidthPt:number;availableHeightPt:number;measuredWidthPt:number;measuredHeightPt:number;horizontal:boolean;vertical:boolean}}
/** Match pdf-lib's default text appearance bounds/layout without changing the inspected document. */
export async function inspectFormTextOverflow(document:PDFDocument,fieldName:string):Promise<FormTextOverflowIssue|null>{
 const field=document.getForm().getField(fieldName),support=inspectDesignTextProperties(field)
 if(!(field instanceof PDFTextField)||!support.editable||!support.properties||!(field.getText()??'').trim())return null
 const properties=support.properties,widget=field.acroField.getWidgets()[0],rectangle=widget.getRectangle(),borderWidth=widget.getBorderStyle()?.getWidth()??0,rotation=reduceRotation(widget.getAppearanceCharacteristics()?.getRotation()),dimensions=adjustDimsForRotation(rectangle,rotation),inset=borderWidth+1,bounds={x:inset,y:inset,width:dimensions.width-inset*2,height:dimensions.height-inset*2}
 if(![borderWidth,bounds.x,bounds.y,bounds.width,bounds.height].every(Number.isFinite)||borderWidth<0||bounds.width<=0||bounds.height<=0)throw Error('text appearance has no measurable positive content bounds')
 const measurement=await PDFDocument.create(),font=measurement.embedStandardFont(properties.fontName as StandardFonts),options={alignment:field.getAlignment(),fontSize:properties.fontSize,font,bounds},mode:FormTextOverflowIssue['details']['mode']=properties.multiLine?'multiline':'singleline',layout=properties.multiLine?layoutMultilineText(field.getText()??'',options):layoutSinglelineText(field.getText()??'',options),lines=('lines' in layout?layout.lines:[layout.line]).filter(line=>line.text.trim().length>0)
 if(!lines.length)return null
 const epsilon=.01,horizontal=lines.some(line=>line.x<bounds.x-epsilon||line.x+line.width>bounds.x+bounds.width+epsilon),vertical=lines.some(line=>line.y<bounds.y-epsilon||line.y+line.height>bounds.y+bounds.height+epsilon)
 if(!horizontal&&!vertical)return null
 const measuredWidthPt=Math.max(...lines.map(line=>line.x+line.width))-Math.min(...lines.map(line=>line.x)),measuredHeightPt=Math.max(...lines.map(line=>line.y+line.height))-Math.min(...lines.map(line=>line.y)),details={mode,fontName:properties.fontName,fontSize:properties.fontSize,availableWidthPt:bounds.width,availableHeightPt:bounds.height,measuredWidthPt,measuredHeightPt,horizontal,vertical}
 return {code:'pdf_form_text_overflow',fieldName,message:'字段“'+fieldName+'”的'+(properties.multiLine?'多行':'单行')+'文字排版范围超过控件可用'+(horizontal&&vertical?'宽高':horizontal?'宽度':'高度')+'，实际 PDF 可能裁切；已保留原值、字体和字号，请核对实际预览。',details}
}

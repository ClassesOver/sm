import {bindPdfTextSelectionStyles,canonicalPdfSelectionStyleRuns,validatePdfSelectionStyleRuns,type PdfSelectionStyleRun} from './pdf-text-selection'
import type {NativeOperation} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
import {validatePdfMarkup} from './pdf-markup'
export interface PdfReplacementStyle{font?:'arial'|'times'|'courier';fontSize?:number;color?:[number,number,number];bold?:boolean;italic?:boolean;align?:'left'|'center'|'right';lineLeading?:number;styleRuns?:PdfSelectionStyleRun[]}
const keys=['font','fontSize','color','bold','italic','align','lineLeading','styleRuns'] as const
export const PDF_STYLED_REPLACEMENT_ALONE_REASON='文字样式替换仅可与新增文字标注、安全矢量、PNG图像或安全链接同批；其他类型修改请分别保存'
export function isStyledPdfReplacement(operation:NativeOperation){return operation.kind==='replaceText'&&(keys.some(key=>operation[key]!==undefined)||typeof operation.newText==='string'&&operation.newText.includes('\n'))}
function validateStyle(style:PdfReplacementStyle){
 if(style.font!==undefined&&!['arial','times','courier'].includes(style.font))throw Error('替换文字字体无效')
 if(style.fontSize!==undefined&&(!Number.isFinite(style.fontSize)||style.fontSize<6||style.fontSize>72))throw Error('替换文字字号须为6–72')
 if(style.color!==undefined&&(!Array.isArray(style.color)||style.color.length!==3||style.color.some(value=>!Number.isFinite(value)||value<0||value>1)))throw Error('替换文字颜色无效')
 if(style.bold!==undefined&&typeof style.bold!=='boolean'||style.italic!==undefined&&typeof style.italic!=='boolean')throw Error('替换文字样式无效')
 if(style.align!==undefined&&!['left','center','right'].includes(style.align))throw Error('替换文字对齐无效')
 if(style.lineLeading!==undefined&&(!Number.isFinite(style.lineLeading)||style.lineLeading<=0))throw Error('替换文字行距须为正数')
}
export function validatePdfStyledReplacement(pages:PdfPageIdentity[],operations:NativeOperation[]){
 if(!operations.some(isStyledPdfReplacement))return
 if(operations.some(operation=>!['replaceText','addMarkup','highlight','addDrawing'].includes(operation.kind)))throw Error(PDF_STYLED_REPLACEMENT_ALONE_REASON)
 const used=new Set<string>();let pngPixels=0,pngBytes=0
 for(const operation of operations){
  if(operation.kind!=='replaceText'){
   const page=pages.find(item=>item.pageId===operation.pageId),box=page?.cropBox
   if(!page||page.blank||!(operation.kind==='addDrawing'?page.drawingsReadSafe:page.markupReadSafe)||operation.sourceSha256!==undefined&&(typeof operation.sourceSha256!=='string'||!page.pageId.startsWith('sha256:'+operation.sourceSha256+':page:')))throw Error('文字标注或绘图来源及页面身份已变化')
   if(operation.kind==='addDrawing'){
    const geometry=({rect:['rect'],ellipse:['rect'],arrow:['from','to'],polygon:['vertices'],ink:['paths'],image:['rect','image'],link:['rect','url','destPage'],measure:['from','to','label'],caret:['point']} as Record<string,string[]>)[String(operation.shape)]
    if(!geometry||Object.keys(operation).some(key=>!['kind','pageId','sourceSha256','shape','color','width',...geometry].includes(key))||!Array.isArray(operation.color)||operation.color.length!==3||operation.color.some(value=>typeof value!=='number'||!Number.isFinite(value)||value<0||value>1)||typeof operation.width!=='number'||!Number.isFinite(operation.width)||operation.width<.25||operation.width>24)throw Error('样式改字同批绘图参数无效')
    const point=(value:unknown):value is [number,number]=>Array.isArray(value)&&value.length===2&&value.every(value=>typeof value==='number'&&Number.isFinite(value)),inside=([x,y]:[number,number])=>x>=box!.x&&y>=box!.y&&x<=box!.x+box!.width&&y<=box!.y+box!.height
    if(operation.shape==='rect'||operation.shape==='ellipse'||operation.shape==='image'||operation.shape==='link'){
     if(!Array.isArray(operation.rect)||operation.rect.length!==4||operation.rect.some(value=>typeof value!=='number'||!Number.isFinite(value)))throw Error('绘图范围无效')
     const[x1,y1,x2,y2]=operation.rect as number[]
     if(x2!-x1!<1||y2!-y1!<1||!inside([x1!,y1!])||!inside([x2!,y2!]))throw Error('绘图范围无效')
     if(operation.shape==='link'){
      const {url,destPage}=operation
      if((url===undefined)===(destPage===undefined))throw Error('链接目标必须二选一')
      if(destPage!==undefined){const destination=pages.find(item=>item.index===Number(destPage)-1);if(typeof destPage!=='number'||!Number.isInteger(destPage)||destPage<1||!destination||destination.blank||destination.pageId!==page.pageId.slice(0,page.pageId.lastIndexOf(':page:'))+':page:'+destination.index)throw Error('链接目标页面身份无效')}
      else {
       if(typeof url!=='string'||!url||url.length>2048||!/^[\x21-\x7e]+$/.test(url))throw Error('链接网址须为可打印ASCII，其他字符请使用百分编码')
       let parsed:URL,decoded:string
       try{parsed=new URL(url);decoded=decodeURIComponent(url)}catch{throw Error('链接网址无效')}
       if(/[\p{Cc}\p{Cf}]/u.test(decoded)||parsed.username||parsed.password||/^https?:\/\/[^/?#]*@/i.test(url)||!(/^https?:\/\//i.test(url)&&['http:','https:'].includes(parsed.protocol)&&parsed.hostname||/^mailto:/i.test(url)&&parsed.protocol==='mailto:'&&parsed.pathname&&!parsed.hash))throw Error('仅支持安全 http/https/mailto 链接')
      }
     }
     if(operation.shape==='image'){
      if(typeof operation.image!=='string'||operation.image.length>6_000_000||operation.image.length%4!==0||!/^[A-Za-z0-9+/]*={0,2}$/.test(operation.image))throw Error('PNG 图像编码无效')
      const decoded=atob(operation.image);if(btoa(decoded)!==operation.image)throw Error('PNG 图像编码须为规范base64')
      const bytes=Uint8Array.from(decoded,char=>char.charCodeAt(0)),view=new DataView(bytes.buffer)
      if(bytes.length<45||Array.from(bytes.subarray(0,8)).join(',')!=='137,80,78,71,13,10,26,10'||view.getUint32(8)!==13||String.fromCharCode(...bytes.subarray(12,16))!=='IHDR')throw Error('PNG 图像头无效')
      const width=view.getUint32(16),height=view.getUint32(20)
      if(!width||!height||width>2000||height>2000||width*height>4_000_000||bytes[24]!==8||![2,6].includes(bytes[25]!)||bytes[26]!==0||bytes[27]!==0||bytes[28]!==0)throw Error('PNG 图像头或像素预算无效')
      if((pngPixels+=width*height)>8_000_000||(pngBytes+=bytes.length)>12*1024*1024)throw Error('PNG 批量像素或字节预算超限')
      if(![0,90,180,270].includes(((page.rotation%360)+360)%360))throw Error('PNG 来源页面旋转不支持')
      let data=false,endedData=false,end=false
      for(let offset=8;offset<bytes.length;){
       if(offset+12>bytes.length)throw Error('PNG 数据块截断')
       const length=view.getUint32(offset),type=String.fromCharCode(...bytes.subarray(offset+4,offset+8)),next=offset+12+length
       if(next>bytes.length)throw Error('PNG 数据块范围无效')
       if(type==='IHDR'){if(offset!==8||length!==13)throw Error('PNG 图像头重复')}
       else if(type==='IDAT'){if(endedData||!length)throw Error('PNG 图像数据无效');data=true}
       else if(type==='IEND'){if(length||!data||next!==bytes.length)throw Error('PNG 图像结尾无效');end=true}
       else {if(data)endedData=true;const lengths:Record<string,number>={sRGB:1,gAMA:4,pHYs:9,cHRM:32};if(lengths[type]!==length)throw Error('PNG 仅支持静态标准图像数据块')}
       offset=next
      }
      if(!end)throw Error('PNG 缺少图像结尾')
     }
    }else if(operation.shape==='caret'){
     if(!point(operation.point)||!inside(operation.point))throw Error('插入符号位置无效')
    }else if(operation.shape==='arrow'||operation.shape==='measure'){
     if(!point(operation.from)||!point(operation.to)||!inside(operation.from)||!inside(operation.to)||Math.hypot(operation.to[0]-operation.from[0],operation.to[1]-operation.from[1])<2)throw Error('箭头范围无效')
     if(operation.shape==='measure'&&(typeof operation.label!=='string'||!/^[\x20-\x7e]{1,64}$/.test(operation.label)||!operation.label.trim()))throw Error('测量标签须为1–64个可打印ASCII字符')
    }else if(operation.shape==='polygon'){
     if(!Array.isArray(operation.vertices)||operation.vertices.length<3||operation.vertices.length>200||!operation.vertices.every(point)||operation.vertices.some(point=>!inside(point))||Math.max(...operation.vertices.map(v=>v[0]))-Math.min(...operation.vertices.map(v=>v[0]))<1||Math.max(...operation.vertices.map(v=>v[1]))-Math.min(...operation.vertices.map(v=>v[1]))<1)throw Error('多边形顶点无效')
    }else if(operation.shape==='ink'){
     if(!Array.isArray(operation.paths)||operation.paths.length<1||operation.paths.length>20||operation.paths.some(path=>!Array.isArray(path)||path.length<4||path.length>4000||path.length%2!==0||path.some((value,index)=>typeof value!=='number'||!Number.isFinite(value)||index%2===0&&!inside([value,path[index+1]!]))))throw Error('手绘路径无效')
    }
    continue
   }
   if(operation.kind==='addMarkup')validatePdfMarkup(operation)
   else if(Object.keys(operation).some(key=>!['kind','pageId','sourceSha256','rect','color'].includes(key))||!Array.isArray(operation.rect)||operation.rect.length!==4||operation.rect.some(value=>typeof value!=='number'||!Number.isFinite(value))||operation.color!==undefined&&(!Array.isArray(operation.color)||operation.color.length!==3||operation.color.some(value=>typeof value!=='number'||!Number.isFinite(value)||value<0||value>1)))throw Error('高亮范围或颜色无效')
   const rects=operation.kind==='addMarkup'?(operation.quads as number[][]).map(q=>[q[0]!,q[5]!,q[2]!,q[1]!]):[operation.rect as number[]]
   for(const[x1,y1,x2,y2]of rects)if(x2!-x1!<.5||y2!-y1!<.5||x1!<box!.x||y1!<box!.y||x2!>box!.x+box!.width||y2!>box!.y+box!.height)throw Error('文字标注范围无效')
   continue
  }
  if(Object.keys(operation).some(key=>!['kind','sourceSha256','pageId','objectId','expectedTextSha256','newText',...keys].includes(key)))throw Error('文字样式替换参数无效')
  if(typeof operation.newText!=='string'||operation.newText.length>4000||/[\p{Cc}\p{Cf}\u2028\u2029]/u.test(operation.newText.replace(/\n/g,'')))throw Error('替换文字仅允许换行，不得含其他控制字符')
  validateStyle(operation as PdfReplacementStyle)
  validatePdfSelectionStyleRuns(operation.newText,operation.styleRuns)
  const page=pages.find(item=>item.pageId===operation.pageId)
  if(!page||page.blank||typeof operation.sourceSha256!=='string'||!/^[a-f0-9]{64}$/.test(operation.sourceSha256)||!page.pageId.startsWith('sha256:'+operation.sourceSha256+':page:'))throw Error('替换文字来源或页面身份已变化')
  if(typeof operation.objectId!=='string'||!page.textObjects?.some(item=>item.objectId===operation.objectId&&item.expectedTextSha256===operation.expectedTextSha256))throw Error('替换文字对象身份已变化')
  if(used.has(operation.objectId))throw Error('文字样式替换对象重复')
  used.add(operation.objectId)
 }
}
/** Whole-object options plus an explicit UTF-16 textarea selection toolbar. */
export function bindPdfReplacementStyle(root:HTMLElement){
 const owner=root.ownerDocument,section=owner.createElement('fieldset'),legend=owner.createElement('legend')
 section.className='pdf-replacement-style';legend.textContent='文字样式（整对象）';section.append(legend)
 const hint=owner.createElement('p');hint.textContent='支持水平文字的字体、粗斜体与手动多行。保留原字体时粗体可能使用描边合成；恢复常规体请显式选择字体。缺字替代或越界会在实际 PDF 预览中提示。';section.append(hint)
 function label(name:string,input:HTMLElement){const row=owner.createElement('label');row.textContent=name;input.setAttribute('aria-label','替换文字'+name);row.append(input);section.append(row);return input}
 const font=label('字体',owner.createElement('select')) as HTMLSelectElement
 for(const [value,name]of [['','保留原字体'],['arial','Arial / Liberation Sans'],['times','Times / Liberation Serif'],['courier','Courier / Liberation Mono']]){const option=owner.createElement('option');option.value=value!;option.textContent=name!;font.append(option)}
 const size=label('字号',owner.createElement('input')) as HTMLInputElement;size.type='number';size.min='6';size.max='72';size.step='any';size.placeholder='保留原字号'
 const bold=label('粗体',owner.createElement('input')) as HTMLInputElement;bold.type='checkbox'
 const italic=label('斜体',owner.createElement('input')) as HTMLInputElement;italic.type='checkbox'
 const applyColor=label('指定颜色',owner.createElement('input')) as HTMLInputElement;applyColor.type='checkbox'
 const color=label('颜色',owner.createElement('input')) as HTMLInputElement;color.type='color';color.value='#111111';color.disabled=true
 const align=label('对齐',owner.createElement('select')) as HTMLSelectElement
 for(const [value,name]of [['','保留基线（左对齐）'],['left','左对齐'],['center','基线居中'],['right','基线右对齐']]){const option=owner.createElement('option');option.value=value!;option.textContent=name!;align.append(option)}
 const leading=label('行距',owner.createElement('input')) as HTMLInputElement;leading.type='number';leading.min='0';leading.step='any';leading.placeholder='自动（字号 × 1.2）'
 root.append(section);const selection=bindPdfTextSelectionStyles(root);let disabled=false
 const wholeEvents=[[font,'font','change'],[size,'size','input'],[size,'size','change'],[bold,'bold','change'],[italic,'italic','change'],[applyColor,'color','change'],[color,'color','input'],[color,'color','change']] as const
 const clearWhole=(event:Event)=>{const binding=wholeEvents.find(([control,,type])=>control===event.target&&type===event.type);if(binding)selection.clearFields([binding[1]])};section.addEventListener('input',clearWhole);section.addEventListener('change',clearWhole)
 const syncColor=()=>{color.disabled=disabled||!applyColor.checked};applyColor.addEventListener('change',syncColor)
 function read():PdfReplacementStyle{
  const style:PdfReplacementStyle={}
  if(font.value)style.font=font.value as PdfReplacementStyle['font']
  if(size.value)style.fontSize=Number(size.value)
  if(applyColor.checked){const rgb=color.value.match(/^#([a-f0-9]{2})([a-f0-9]{2})([a-f0-9]{2})$/i);if(!rgb)throw Error('替换文字颜色无效');style.color=rgb.slice(1).map(value=>parseInt(value,16)/255) as [number,number,number]}
  if(bold.checked)style.bold=true
  if(italic.checked)style.italic=true
  if(align.value)style.align=align.value as PdfReplacementStyle['align']
  if(leading.value)style.lineLeading=Number(leading.value)
  const runs=selection.read();if(runs.length)style.styleRuns=runs
  validateStyle(style);return style
 }
 function canonical(operation?:NativeOperation){const value:Record<string,unknown>={};for(const key of keys)if(operation?.[key]!==undefined&&operation[key]!==false)value[key]=key==='styleRuns'?(canonicalPdfSelectionStyleRuns(String(operation?.newText??''),operation[key]).length?canonicalPdfSelectionStyleRuns(String(operation?.newText??''),operation[key]):undefined):key==='color'?(operation[key] as number[]).map(item=>Math.round(item*255)/255):operation[key];return value}
 function fill(operation?:NativeOperation){font.value=typeof operation?.font==='string'?operation.font:'';size.value=typeof operation?.fontSize==='number'?String(operation.fontSize):'';bold.checked=operation?.bold===true;italic.checked=operation?.italic===true;applyColor.checked=Array.isArray(operation?.color);if(applyColor.checked)color.value='#'+(operation!.color as number[]).map(value=>Math.round(value*255).toString(16).padStart(2,'0')).join('');align.value=typeof operation?.align==='string'?operation.align:'';leading.value=typeof operation?.lineLeading==='number'?String(operation.lineLeading):'';syncColor();selection.fill(operation)}
 return {read,fill,bindTextarea:selection.bindTextarea,changed(operation?:NativeOperation){const current=read();return keys.some(key=>JSON.stringify(current[key])!==JSON.stringify(canonical(operation)[key]))},setDisabled(value:boolean){disabled=value;selection.setDisabled(value);for(const input of section.querySelectorAll('input,select'))(input as HTMLInputElement).disabled=value;syncColor()},dispose(){section.removeEventListener('input',clearWhole);section.removeEventListener('change',clearWhole);applyColor.removeEventListener('change',syncColor);section.remove();selection.dispose()}}
}

/** Fixed GenOffice f8c17004 mail-merge/layout.ts geometry; request values are presets, never XML. */
export type MailMergeLayout = {stock:'avery5160'}|{stock:'custom';paper:'letter'|'a4';columns:number;rows:number}|{envelope:'size10'|'dl'|'c5'|'c6'}
export interface Layout {pageWidth:number;pageHeight:number;marginTop:number;marginRight:number;marginBottom:number;marginLeft:number;grid?:{columns:number;rows:number;gapX:number;gapY:number}}
const inch=(n:number)=>Math.round(n*1440),mm=(n:number)=>Math.round(n*1440/25.4)
const invalid=():never=>{throw new Error('docx_mail_merge_layout_invalid')}
export function mailMergeLayout(mode:string,value:unknown):Layout {
 if(!value||typeof value!=='object'||Array.isArray(value))return invalid()
 const v=value as Record<string,unknown>
 if(mode==='labels'){
  if(v.stock==='avery5160'&&Object.keys(v).length===1)return {pageWidth:12240,pageHeight:15840,marginTop:720,marginBottom:720,marginLeft:270,marginRight:270,grid:{columns:3,rows:10,gapX:180,gapY:0}}
  if(v.stock==='custom'&&Object.keys(v).length===4&&['a4','letter'].includes(String(v.paper))&&[v.columns,v.rows].every(n=>typeof n==='number'&&Number.isInteger(n)&&n>=1&&n<=20))return {pageWidth:v.paper==='a4'?mm(210):inch(8.5),pageHeight:v.paper==='a4'?mm(297):inch(11),marginTop:720,marginBottom:720,marginLeft:720,marginRight:720,grid:{columns:v.columns as number,rows:v.rows as number,gapX:0,gapY:0}}
 }else if(mode==='envelopes'&&Object.keys(v).length===1){
  const sizes:Record<string,[number,number]>={size10:[inch(9.5),inch(4.125)],dl:[mm(220),mm(110)],c5:[mm(229),mm(162)],c6:[mm(162),mm(114)]},size=Object.hasOwn(sizes,String(v.envelope))?sizes[String(v.envelope)]:undefined
  if(size)return {pageWidth:size[0],pageHeight:size[1],marginTop:720,marginBottom:720,marginLeft:720,marginRight:720}
 }
 return invalid()
}
export function layoutSectionXml(section:string,layout:Layout):string {
 const paper=`<w:pgSz w:w="${layout.pageWidth}" w:h="${layout.pageHeight}" w:orient="${layout.pageWidth>layout.pageHeight?'landscape':'portrait'}"/>`
 const oldMargins=/<w:pgMar\b[^>]*\/>/.exec(section)?.[0]??'',distance=(name:string)=>oldMargins.match(new RegExp(`\\bw:${name}=["'](\\d+)["']`))?.[1]??'0'
 const margins=`<w:pgMar w:top="${layout.marginTop}" w:right="${layout.marginRight}" w:bottom="${layout.marginBottom}" w:left="${layout.marginLeft}" w:header="${distance('header')}" w:footer="${distance('footer')}" w:gutter="${distance('gutter')}"/>`
 if(!section||/^<w:sectPr\b[^>]*\/>$/.test(section))return `<w:sectPr>${paper}${margins}</w:sectPr>`
 const following='paperSrc|pgBorders|lnNumType|pgNumType|cols|formProt|vAlign|noEndnote|titlePg|textDirection|bidi|rtlGutter|docGrid|printerSettings|sectPrChange'
 const upsert=(xml:string,tag:string,value:string,after:string)=>{
  const existing=new RegExp(`<w:${tag}\\b[^>]*\\/>`)
  if(existing.test(xml))return xml.replace(existing,value)
  const next=new RegExp(`<w:(?:${after})\\b`).exec(xml),at=next?.index??xml.lastIndexOf('</w:sectPr>')
  return xml.slice(0,at)+value+xml.slice(at)
 }
 return upsert(upsert(section,'pgSz',paper,'pgMar|'+following),'pgMar',margins,following)
}

export function labelSheetXml(cells:string[],layout:Layout):string {
 const g=layout.grid!,width=Math.floor((layout.pageWidth-layout.marginLeft-layout.marginRight-g.gapX*(g.columns-1))/g.columns),height=Math.floor((layout.pageHeight-layout.marginTop-layout.marginBottom-g.gapY*(g.rows-1))/g.rows)
 const borders='<w:tcBorders>'+['top','left','bottom','right'].map(side=>`<w:${side} w:val="nil"/>`).join('')+'</w:tcBorders>'
 const cell=(text:string,w:number)=>`<w:tc><w:tcPr><w:tcW w:w="${w}" w:type="dxa"/>${borders}</w:tcPr>${text||'<w:p/>'}</w:tc>`
 const widths=Array.from({length:g.columns},(_,i)=>(i&&g.gapX?[g.gapX,width]:[width])).flat()
 const rows:string[]=[]
 for(let at=0;at<cells.length;at+=g.columns){
  rows.push(`<w:tr><w:trPr><w:trHeight w:val="${height}" w:hRule="exact"/><w:cantSplit/></w:trPr>`+Array.from({length:g.columns},(_,i)=>(i&&g.gapX?cell('',g.gapX):'')+cell(cells[at+i]??'',width)).join('')+'</w:tr>')
 }
 return `<w:tbl><w:tblPr><w:tblW w:w="${layout.pageWidth-layout.marginLeft-layout.marginRight}" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>${widths.map(w=>`<w:gridCol w:w="${w}"/>`).join('')}</w:tblGrid>${rows.join('')}</w:tbl><w:p/>`
}

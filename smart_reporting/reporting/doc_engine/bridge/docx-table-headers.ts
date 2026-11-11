import { splitXmlChildren } from '../packages/docx-engine/src/generate'
function fail():never {throw new Error('docx_table_repeat_headers_invalid')}
function children(xml:string){const open=/^<[\w:.-]+\b[^>]*>/.exec(xml)?.[0];if(!open)fail();return open.endsWith('/>')?[]:splitXmlChildren(xml.slice(open.length,xml.lastIndexOf('</')))}
/** 仅替换直接子节点；复用引擎XML分段，嵌套表格不参与行坐标。 */
function replaceChild(xml:string,name:string,replacement:string,order:readonly string[]=[]):string {
  const parts=children(xml),matches=parts.filter(child=>child.name===name)
  if(matches.length>1)fail()
  if(matches.length){const old=matches[0]!.xml,at=xml.indexOf(old);return xml.slice(0,at)+replacement+xml.slice(at+old.length)}
  if(!replacement)return xml
  if(xml.endsWith('/>'))return xml.slice(0,-2)+'>'+replacement+'</'+/^<([\w:.-]+)/.exec(xml)![1]+'>'
  const rank=order.indexOf(name),next=parts.find(child=>order.indexOf(child.name)>rank),at=next?xml.indexOf(next.xml):xml.lastIndexOf('</')
  return xml.slice(0,at)+replacement+xml.slice(at)
}
export function patchTableRepeatHeaders(xml:string,expectedRowCount:unknown,headers:unknown,prefixRowCount:unknown=expectedRowCount):string {
  if(!/^<w:tbl\b/.test(xml))fail()
  const rows=children(xml).filter(child=>child.name==='w:tr')
  if(!Number.isInteger(prefixRowCount)||Number(prefixRowCount)<1||Number(prefixRowCount)>rows.length||!Number.isInteger(expectedRowCount)||expectedRowCount!==rows.length||!Array.isArray(headers)||headers.length!==rows.length||headers.some(value=>typeof value!=='boolean'))fail()
  const order=['w:cnfStyle','w:divId','w:gridBefore','w:gridAfter','w:wBefore','w:wAfter','w:cantSplit','w:trHeight','w:tblHeader','w:tblCellSpacing','w:jc','w:hidden','w:ins','w:del','w:trPrChange']
  let cursor=0,result=''
  rows.forEach((row,index)=>{
    const at=xml.indexOf(row.xml,cursor),props=children(row.xml).filter(child=>child.name==='w:trPr');if(props.length>1)fail()
    const original=props[0]?.xml??'<w:trPr/>',flags=children(original).filter(child=>child.name==='w:tblHeader');if(flags.length>1)fail()
    const active=!!flags.length&&!/\bw:val\s*=\s*["'](?:0|false|off)["']/.test(flags[0]!.xml)
    if(index>=Number(prefixRowCount)&&active!==headers[index])fail()
    const replacement=active===headers[index]?row.xml:replaceChild(row.xml,'w:trPr',replaceChild(original,'w:tblHeader',headers[index]?'<w:tblHeader/>':'',order),['w:tblPrEx','w:trPr','w:tc'])
    result+=xml.slice(cursor,at)+replacement;cursor=at+row.xml.length
  })
  return result+xml.slice(cursor)
}

export type TableAltText={title:string;description:string}
export interface TableAltTextSource extends TableAltText {rawTitle:string|null;rawDescription:string|null}
/** 固定源 trim/空值清除；标题单行255字符，说明4096字符，拒绝XML非法字符。 */
export function normalizeTableAltText(value:unknown):TableAltText{
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==2||Object.keys(value).some(k=>!['title','description'].includes(k)))throw new Error('docx_table_alt_text_invalid')
 const input=value as TableAltText
 for(const [key,limit] of [['title',255],['description',4096]] as const){
  const text=input[key]
  if(typeof text!=='string'||Array.from(text).length>limit||key==='title'&&/[\r\n\t]/.test(text))throw new Error('docx_table_alt_text_invalid')
  for(const char of text){const code=char.codePointAt(0)!;if(code<32&&![9,10,13].includes(code)||code>=0xd800&&code<=0xdfff||code===0xfffe||code===0xffff)throw new Error('docx_table_alt_text_invalid')}
 }
 return{title:input.title.trim(),description:input.description.trim()}
}
